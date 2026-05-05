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
from app.schemas.cv import CVResponse, ExperienceItem, UserProfile
from app.services import ats_scorer, llm_client

logger = logging.getLogger(__name__)

# Threshold below which we ask the LLM to rewrite bullets. Sourced from the
# architecture doc ("Score mínimo aceptable: 60% de keywords presentes").
ATS_REWRITE_THRESHOLD = 0.60

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
    parts.extend(profile.skills)
    for exp in profile.experience:
        parts.append(exp.title)
        parts.append(exp.company)
        parts.extend(exp.bullets)
    for edu in profile.education:
        parts.append(edu.degree)
        parts.append(edu.institution)
    return " ".join(parts)


def _render_html(profile: UserProfile, job_title: str) -> str:
    """Render the Jinja2 template with the profile data."""
    template = _jinja_env.get_template("cv_template.html")
    return template.render(profile=profile, job_title=job_title)


def _write_pdf(html: str, output_dir: Path) -> tuple[str, Path]:
    """Persist the HTML as a PDF on disk and return (filename, full_path)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"cv-{uuid.uuid4().hex}.pdf"
    pdf_path = output_dir / filename
    HTML(string=html).write_pdf(target=str(pdf_path))
    return filename, pdf_path


def _guess_job_title(job_posting: str, fallback: str | None) -> str:
    """Best-effort job-title extraction.

    Per the ATS rules: the CV title should match the posting's title verbatim.
    The first non-empty line of a posting is almost always the title; we use
    that and fall back to the candidate's headline or a generic phrase.
    """
    for line in job_posting.splitlines():
        candidate = line.strip()
        if candidate and len(candidate) <= 120:
            return candidate
    return fallback or "Professional Profile"


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
    profile = UserProfile.model_validate(user_profile)

    # 1. Extract ATS keywords from the posting via Gemini. The first line is
    #    the job title (rendered verbatim in the CV header), so we exclude it
    #    from extraction to keep it out of the "missing" list.
    posting_title, posting_body = ats_scorer.split_title_and_body(job_posting)
    keywords = await llm_client.extract_keywords(posting_body or job_posting)
    keywords = ats_scorer.filter_title_from_keywords(keywords, posting_title)

    # 2. Initial score against the candidate profile as-is.
    profile_text = _profile_to_text(profile)
    ats_score, matched, missing = ats_scorer.score(profile_text, keywords)

    rewritten = False
    # 3. If under threshold, ask the LLM to rewrite each experience block's
    #    bullets to weave in missing keywords (without fabricating facts).
    if ats_score < ATS_REWRITE_THRESHOLD and missing:
        new_experience: list[ExperienceItem] = []
        for exp in profile.experience:
            if not exp.bullets:
                new_experience.append(exp)
                continue
            new_bullets = await llm_client.rewrite_bullets(exp.bullets, missing)
            if new_bullets != exp.bullets:
                rewritten = True
            new_experience.append(exp.model_copy(update={"bullets": new_bullets}))
        profile = profile.model_copy(update={"experience": new_experience})

        # 4. Recompute score after rewrite.
        profile_text = _profile_to_text(profile)
        ats_score, matched, missing = ats_scorer.score(profile_text, keywords)

    # 5. Render template.
    job_title = _guess_job_title(job_posting, profile.headline)
    cv_html = _render_html(profile, job_title)

    # 6. Generate PDF.
    filename, pdf_path = _write_pdf(cv_html, settings.CV_OUTPUT_DIR)
    logger.info("Generated CV PDF at %s (score=%.2f)", pdf_path, ats_score)

    # 7. Build the response. The PDF URL is RELATIVE — the frontend prefixes
    #    it with VITE_API_URL on its side.
    return CVResponse(
        cv_html=cv_html,
        cv_pdf_url=f"/api/cv/{filename}/pdf",
        ats_score=round(ats_score, 4),
        matched_keywords=matched,
        missing_keywords=missing,
        rewritten=rewritten,
    )
