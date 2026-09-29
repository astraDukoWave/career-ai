"""Rendering tests for the single-column CV template (no LLM calls)."""

import shutil
import subprocess

import pytest

from app.schemas.cv import UserProfile
from app.services.cv_engine import _clean_profile, _render_html, _write_pdf

PROFILE = UserProfile.model_validate(
    {
        "name": "Ada Example",
        "email": "ada@example.com",
        "location": "Mexico (Remote)",
        "linkedin": "linkedin.com/in/ada-example",
        "github": "https://github.com/ada-example",
        "summary": "Frontend engineer who ships **AI features** in React and TypeScript.",
        "skills": [
            "Frontend: React, TypeScript, Component Libraries (ShadcnUI, Material UI)",
            "CI/CD & Testing: GitHub Actions, Vitest",
        ],
        "experience": [
            {
                "title": "Frontend Engineer",
                "company": "Example Co",
                "start": "2025-01",
                "end": "Present",
                "bullets": ["* Built an AI chat panel used by 2,000 users", "- Cut bundle size 35%"],
            }
        ],
        "education": [
            {"institution": "Example University", "degree": "B.Sc. Computer Science", "year": "2024"}
        ],
    }
)


def _html() -> str:
    return _render_html(_clean_profile(PROFILE), "Frontend Engineer")


def test_template_is_single_column_with_standard_section_order():
    html = _html()
    assert "<table" not in html
    positions = [html.index(h) for h in (">Summary<", ">Skills<", ">Experience<", ">Education<")]
    assert positions == sorted(positions)


def test_bullets_render_without_duplicate_markers():
    html = _html()
    assert "<li>Built an AI chat panel used by 2,000 users</li>" in html
    assert "<li>* " not in html
    assert "<li>- " not in html


def test_skill_groups_render_intact():
    html = _html()
    assert "Component Libraries (ShadcnUI, Material UI)" in html
    assert "CI/CD &amp; Testing:" in html  # label kept whole; "&" autoescaped


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext (poppler) not installed")
def test_pdf_text_reads_top_to_bottom(tmp_path):
    _, pdf_path = _write_pdf(_html(), tmp_path)
    text = subprocess.run(
        ["pdftotext", str(pdf_path), "-"], capture_output=True, text=True, check=True
    ).stdout
    flat = " ".join(text.split())

    # The old two-column layout interleaved contact lines into the summary.
    assert "Frontend engineer who ships AI features in React and TypeScript." in flat
    assert flat.index("ada@example.com") < flat.index("SUMMARY")
    assert flat.index("Material UI)") < flat.index("EXPERIENCE")


def test_summary_markdown_and_iso_dates_are_cleaned_before_rendering():
    html = _html()
    assert "**" not in html
    assert "Frontend engineer who ships AI features in React and TypeScript." in html
    assert "Jan 2025 – Present" in html
