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

    return len(matched) / len(keywords), matched, missing
