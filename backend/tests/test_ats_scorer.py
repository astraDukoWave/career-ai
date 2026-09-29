"""Unit tests for app.services.ats_scorer (pure functions, no network)."""

from app.services.ats_scorer import score

# Phrasing from a real CV scored on 2026-09-29, which reported "html",
# "frontend development" and "web accessibility" as missing.
REAL_PROFILE = (
    "Frontend Developer with 3+ years building responsive, accessible (WCAG) apps. "
    "Core Frontend: React.js, TypeScript, HTML5, CSS3, Responsive Design"
)


def test_versioned_and_role_spellings_count_as_matches():
    _, matched, missing = score(
        REAL_PROFILE, ["html", "css", "frontend development", "web accessibility", "react"]
    )
    assert missing == []
    assert set(matched) == {"html", "css", "frontend development", "web accessibility", "react"}


def test_synonyms_never_invent_a_match():
    _, matched, missing = score("Backend engineer: Python, FastAPI", ["html", "web accessibility"])
    assert matched == []
    assert missing == ["html", "web accessibility"]


def test_score_is_the_matched_fraction():
    ats, _, _ = score("React, TypeScript", ["react", "typescript", "graphql", "jest"])
    assert ats == 0.5
