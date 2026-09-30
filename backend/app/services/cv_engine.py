"""CV Engine — orchestrator service.

Implements the pipeline from the architecture doc:
    1. Extract keywords from the job posting (LLM)
    2. Score the candidate profile against those keywords (ATS scorer)
    3. If score < 0.60, ask the LLM to rewrite experience bullets to embed the
       missing keywords (without inventing facts)
    4. Recompute the score after the rewrite
    5. Render the Jinja2 template -> HTML
    6. Generate the PDF with WeasyPrint
    7. Return everything the API layer needs.

Layered-architecture compliance: NO FastAPI imports here. The route layer
calls this function and shapes the HTTP response.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app.config import get_settings
from app.schemas.cv import CVResponse, ExperienceEntry, UserProfile
from app.services import ats_scorer, cv_format, llm_client

logger = logging.getLogger(__name__)

# Threshold below which we ask the LLM to rewrite bullets. Sourced from the
# architecture doc ("Score mínimo aceptable: 60% de keywords presentes").
ATS_REWRITE_THRESHOLD = 0.60

# Below this final score the CV is unlikely to land — rather than silently
# shipping a low-fit CV we surface a banner asking the user to reconsider.
MISMATCH_WARNING_THRESHOLD = 0.30

# Lightweight domain hints. Each label maps to keyword fragments we look for
# (substring) inside the top missing keywords. Intentionally NOT exhaustive —
# this is a hedged "appears to be in" hint, not a classifier.
_DOMAIN_KEYWORDS: dict[str, set[str]] = {
    "finance/business": {
        "finance",
        "financial",
        "fintech",
        "banking",
        "accounting",
        "investment",
        "treasury",
        "audit",
        "compliance",
    },
    "data science": {
        "data scientist",
        "data science",
        "machine learning",
        "deep learning",
        "nlp",
        "computer vision",
        "tensorflow",
        "pytorch",
        "statistics",
    },
    "design": {
        "figma",
        "ux",
        "ui",
        "design system",
        "wireframe",
        "prototype",
        "user research",
        "interaction",
    },
    "marketing": {
        "marketing",
        "seo",
        "sem",
        "campaign",
        "growth",
        "content",
        "brand",
        "social media",
        "advertising",
    },
    "devops/infrastructure": {
        "devops",
        "kubernetes",
        "terraform",
        "ci/cd",
        "infrastructure",
        "sre",
        "ansible",
        "helm",
    },
    "sales": {
        "sales",
        "crm",
        "salesforce",
        "pipeline",
        "quota",
        "account executive",
        "business development",
    },
    "healthcare": {
        "healthcare",
        "clinical",
        "medical",
        "patient",
        "ehr",
        "hipaa",
    },
}

# Jinja2 environment — built once at import time.
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


# =============================================================================
# Helpers
# =============================================================================


def _profile_to_text(profile: UserProfile) -> str:
    """Flatten every searchable field of the profile into one string for scoring."""
    parts: list[str] = [profile.name]
    if profile.headline:
        parts.append(profile.headline)
    # The summary is printed on the CV and real ATS index the whole document,
    # so its keywords count too.
    if profile.summary:
        parts.append(profile.summary)
    parts.extend(profile.skills)
    for exp in profile.experience:
        parts.append(exp.title)
        parts.append(exp.company)
        parts.extend(exp.bullets)
    for edu in profile.education or []:
        parts.append(edu.degree)
        parts.append(edu.institution)
    return " ".join(parts)


def _clean_profile(profile: UserProfile) -> UserProfile:
    """Normalise every rendered field before scoring and rendering.

    - Bullets: list markers and markdown stripped; empty ones dropped.
    - Summary, headline, titles, companies, education: markdown stripped.
    - Dates typed as "2026-5" become "May 2026".
    """
    experience: list[ExperienceEntry] = []
    for exp in profile.experience:
        bullets = [b for b in (cv_format.clean_bullet(raw) for raw in exp.bullets) if b]
        experience.append(
            exp.model_copy(
                update={
                    "title": cv_format.clean_inline(exp.title),
                    "company": cv_format.clean_inline(exp.company),
                    "start": cv_format.format_month(exp.start),
                    "end": cv_format.format_month(exp.end),
                    "bullets": bullets,
                }
            )
        )
    education = None
    if profile.education is not None:
        education = [
            edu.model_copy(
                update={
                    "institution": cv_format.clean_inline(edu.institution),
                    "degree": cv_format.clean_inline(edu.degree),
                    "year": cv_format.format_month(edu.year),
                }
            )
            for edu in profile.education
        ]
    return profile.model_copy(
        update={
            "summary": cv_format.clean_inline(profile.summary),
            "headline": cv_format.clean_inline(profile.headline),
            "experience": experience,
            "education": education,
        }
    )


def _printed_profile(profile: UserProfile) -> UserProfile:
    """The profile as the PDF prints it, with skills as normalised lines.

    Skill groups become "Label: a, b"; ungrouped skills become one line.
    """
    skills = cv_format.normalize_skills(profile.skills)
    lines = [f"{g.label}: {', '.join(g.items)}" for g in skills.groups]
    if skills.ungrouped:
        lines.append(", ".join(skills.ungrouped))
    return profile.model_copy(update={"skills": lines})


def _render_html(profile: UserProfile, job_title: str) -> str:
    """Render the Jinja2 template with the profile data."""
    template = _jinja_env.get_template("cv_template.html")
    skills = cv_format.normalize_skills(profile.skills)
    return template.render(
        profile=profile,
        job_title=job_title,
        skill_groups=skills.groups,
        skill_items=skills.ungrouped,
    )


def _write_pdf(html: str, output_dir: Path) -> tuple[str, Path]:
    """Persist the HTML as a PDF on disk and return (filename, full_path)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"cv-{uuid.uuid4().hex}.pdf"
    pdf_path = output_dir / filename
    HTML(string=html).write_pdf(target=str(pdf_path))
    return filename, pdf_path


def _detect_domain(missing_keywords: list[str]) -> str:
    """Pick the dominant domain from the top-3 missing keywords.

    Returns a phrase like 'finance/business domain'. Falls back to
    'another domain' when nothing in the top-3 maps to a known group.
    """
    top = [kw.lower() for kw in missing_keywords[:3]]
    if not top:
        return "another domain"

    scores: dict[str, int] = {label: 0 for label in _DOMAIN_KEYWORDS}
    for label, fragments in _DOMAIN_KEYWORDS.items():
        for fragment in fragments:
            if any(fragment in kw for kw in top):
                scores[label] += 1

    label, count = max(scores.items(), key=lambda item: item[1])
    return f"{label} domain" if count > 0 else "another domain"


def _summarise_skills(profile: UserProfile) -> str:
    """First three real skills as a comma-separated phrase."""
    skills = cv_format.normalize_skills(profile.skills).flat
    if skills:
        return ", ".join(skills[:3])
    if profile.headline:
        return profile.headline
    return "your stated experience"


def _build_mismatch_warning(
    ats_score: float,
    missing: list[str],
    profile: UserProfile,
) -> str | None:
    """Compose the low-fit warning, or None when the score clears the threshold."""
    if ats_score >= MISMATCH_WARNING_THRESHOLD:
        return None
    pct = round(ats_score * 100)
    domain = _detect_domain(missing)
    skills_summary = _summarise_skills(profile)
    return (
        f"Low match detected (score: {pct}%). This role appears to be in "
        f"{domain}. Your profile shows strength in {skills_summary}."
    )


# =============================================================================
# Public entry point
# =============================================================================


async def generate_cv(job_posting: str, user_profile: dict[str, Any]) -> CVResponse:
    """Run the full CV generation pipeline.

    Args:
        job_posting: Raw job-posting text.
        user_profile: Dict matching the UserProfile schema.

    Returns:
        CVResponse populated with HTML, PDF URL, score and keyword breakdown.
    """
    settings = get_settings()
    profile = _clean_profile(UserProfile.model_validate(user_profile))

    # 1. Extract ATS keywords from the posting via Gemini. The first line is
    #    the job title (rendered verbatim in the CV header), so we exclude it
    #    from extraction to keep it out of the "missing" list.
    posting_title, posting_body = ats_scorer.split_title_and_body(job_posting)
    keywords = await llm_client.extract_keywords(posting_body or job_posting)
    keywords = ats_scorer.filter_title_from_keywords(keywords, posting_title)

    # 2. Initial score against the candidate profile as-is.
    profile_text = _profile_to_text(profile)
    ats_score, matched, missing = ats_scorer.score(profile_text, keywords)

    # What the candidate actually wrote (cleaned). This, never an LLM rewrite,
    # is what the Interview Copilot receives as facts (C2-SPEC-01 REQ-06).
    facts_profile = profile

    rewritten = False
    # 3. Optional (CV_REWRITE_BULLETS, off by default): below the threshold,
    #    ask the LLM to weave missing keywords into the bullets. A keyword is
    #    "missing" precisely because the candidate never claimed it, so this
    #    step can turn a posting requirement into an invented claim.
    if settings.CV_REWRITE_BULLETS and ats_score < ATS_REWRITE_THRESHOLD and missing:
        new_experience: list[ExperienceEntry] = []
        for exp in profile.experience:
            if not exp.bullets:
                new_experience.append(exp)
                continue
            new_bullets = await llm_client.rewrite_bullets(exp.bullets, missing)
            if new_bullets != exp.bullets:
                rewritten = True
            new_experience.append(exp.model_copy(update={"bullets": new_bullets}))
        profile = _clean_profile(profile.model_copy(update={"experience": new_experience}))

        # 4. Recompute score after rewrite.
        profile_text = _profile_to_text(profile)
        ats_score, matched, missing = ats_scorer.score(profile_text, keywords)

    # 5. Render template. The LLM isolates the role title (2-6 words); on any
    #    failure llm_client falls back to the posting's first line, so the
    #    candidate's headline / a generic phrase only kicks in if the posting
    #    itself is empty.
    job_title = await llm_client.extract_job_title(job_posting)
    if not job_title:
        job_title = profile.headline or "Professional Profile"
    cv_html = _render_html(profile, job_title)

    # 6. Generate PDF.
    filename, pdf_path = _write_pdf(cv_html, settings.CV_OUTPUT_DIR)
    logger.info("Generated CV PDF at %s (score=%.2f)", pdf_path, ats_score)

    # 7. Build the response. The PDF URL is RELATIVE — the frontend prefixes
    #    it with VITE_API_URL on its side. The mismatch warning is None when
    #    the final score clears MISMATCH_WARNING_THRESHOLD.
    mismatch_warning = _build_mismatch_warning(ats_score, missing, profile)
    return CVResponse(
        job_title=job_title,
        final_profile=_printed_profile(facts_profile),
        cv_html=cv_html,
        cv_pdf_url=f"/api/cv/{filename}/pdf",
        ats_score=round(ats_score, 4),
        matched_keywords=matched,
        missing_keywords=missing,
        rewritten=rewritten,
        mismatch_warning=mismatch_warning,
    )
