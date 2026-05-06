"""Naive but effective ATS keyword scorer.

Most real ATS use simple substring/token matching, not semantic similarity.
We mirror that: a keyword is "matched" if it appears as a (case-insensitive,
word-boundary aware) substring in the candidate's CV text.

This file is intentionally pure Python with zero external dependencies — it
must be cheap to run and trivial to unit-test later.
"""

from __future__ import annotations

import re


def _normalise(text: str) -> str:
    """Lowercase and collapse whitespace for stable matching."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _keyword_present(keyword: str, haystack: str) -> bool:
    """Word-boundary substring match.

    For multi-word keywords like "machine learning" we still want to match,
    so we escape the keyword and wrap with \b boundaries on the outer edges.
    """
    pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
    return re.search(pattern, haystack) is not None


# =============================================================================
# Synonym groups (closed allowlist)
# =============================================================================
# A missing keyword is only promoted to matched when it appears AS A KEY in
# this map AND at least one of its synonyms is present verbatim in the
# candidate's text. The map is intentionally closed: keywords with no entry
# (e.g. "fintech", "financial transformation") stay missing even when the
# candidate has loosely-related experience — synonyms cannot invent matches.
SKILL_SYNONYMS: dict[str, list[str]] = {
    "ai": [
        "langchain",
        "gemini",
        "openai",
        "llm",
        "machine learning",
        "ai tools",
        "artificial intelligence",
        "ai first",
        "ai platforms",
    ],
    "analytics": ["kpi", "data-driven", "metrics", "data analysis", "reporting"],
    "agile": ["scrum", "kanban", "sprint", "agile methodology"],
    "cloud": ["aws", "gcp", "azure", "docker", "kubernetes", "containers"],
    "api": ["rest api", "restful", "graphql", "fastapi", "express", "endpoints"],
}


def split_title_and_body(job_posting: str) -> tuple[str, str]:
    """Split a raw job posting into ``(title, body)``.

    The title is the first non-empty line; the body is everything after it.
    The job title is rendered verbatim in the CV header, so feeding it back
    into keyword extraction would inflate the ``missing`` list whenever the
    candidate's headline phrasing differs from the posting's.
    """
    lines = job_posting.splitlines()
    for i, line in enumerate(lines):
        title = line.strip()
        if title:
            body = "\n".join(lines[i + 1 :]).strip()
            return title, body
    return "", job_posting.strip()


def filter_title_from_keywords(keywords: list[str], title: str) -> list[str]:
    """Drop any keyword that exactly matches the job title.

    Defensive companion to :func:`split_title_and_body`: even when the LLM
    only sees the body, postings often repeat the title verbatim
    ("We're hiring a Frontend Engineer..."), so the title can leak in.
    """
    if not title:
        return keywords
    title_norm = _normalise(title)
    return [kw for kw in keywords if _normalise(kw) != title_norm]


def score(profile_text: str, keywords: list[str]) -> tuple[float, list[str], list[str]]:
    """Compute the ATS score for a profile against a keyword list.

    Args:
        profile_text: A single concatenated string of every searchable field
            (skills + experience bullets + headline). The caller is responsible
            for assembling it.
        keywords: The ATS keywords extracted from the job posting.

    Returns:
        (ats_score, matched, missing) where:
            ats_score = len(matched) / len(keywords)  in [0.0, 1.0]
            matched   = keywords found in the profile (preserves input order)
            missing   = keywords NOT found in the profile
    """
    if not keywords:
        return 0.0, [], []

    haystack = _normalise(profile_text)
    matched: list[str] = []
    missing: list[str] = []
    for kw in keywords:
        if _keyword_present(kw, haystack):
            matched.append(kw)
        else:
            missing.append(kw)

    # Second pass: a missing keyword that has an entry in SKILL_SYNONYMS gets
    # promoted to matched only when at least one synonym appears verbatim in
    # the candidate text. Existing matches and their order are preserved;
    # promoted keys are appended after the organic matches so the UI keeps
    # showing the candidate's real matches first.
    still_missing: list[str] = []
    for kw in missing:
        synonyms = SKILL_SYNONYMS.get(kw.lower())
        if synonyms and any(_keyword_present(s, haystack) for s in synonyms):
            matched.append(kw)
        else:
            still_missing.append(kw)

    return len(matched) / len(keywords), matched, still_missing
