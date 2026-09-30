"""generate_cv returns what the copilot needs as context (LLM calls faked)."""

import asyncio
from types import SimpleNamespace

from app.services import cv_engine

POSTING = "Frontend Developer\nBuild React and TypeScript interfaces for a health platform."
PROFILE = {
    "name": "Ada Example",
    "summary": "Builds **AI features** in React.",
    "skills": ["Frontend: React, TypeScript, react", "Git, Docker"],
    "experience": [
        {"title": "Frontend Engineer", "company": "Example Co", "start": "2025-1",
         "bullets": ["* Shipped a React chat panel"]}
    ],
}


def test_response_carries_the_printed_profile_and_job_title(monkeypatch, tmp_path):
    async def keywords(_posting):
        return ["react", "typescript"]

    async def job_title(_posting):
        return "Frontend Developer"

    async def rewrite(bullets, _missing):
        return bullets

    monkeypatch.setattr(cv_engine.llm_client, "extract_keywords", keywords)
    monkeypatch.setattr(cv_engine.llm_client, "extract_job_title", job_title)
    monkeypatch.setattr(cv_engine.llm_client, "rewrite_bullets", rewrite)
    monkeypatch.setattr(
        cv_engine,
        "get_settings",
        lambda: SimpleNamespace(CV_OUTPUT_DIR=tmp_path, CV_REWRITE_BULLETS=False),
    )

    res = asyncio.run(cv_engine.generate_cv(POSTING, PROFILE))

    assert res.job_title == "Frontend Developer"
    printed = res.final_profile
    assert printed is not None
    assert printed.summary == "Builds AI features in React."
    assert printed.skills == ["Frontend: React, TypeScript", "Git, Docker"]
    assert printed.experience[0].bullets == ["Shipped a React chat panel"]
    assert printed.experience[0].start == "Jan 2025"


def _fake_llm(monkeypatch, tmp_path, rewrite_enabled, calls):
    async def keywords(_posting):
        # "machine learning" and "static analysis" are absent from the profile:
        # the score stays below the rewrite threshold.
        return ["react", "machine learning", "static analysis"]

    async def job_title(_posting):
        return "Generalist Software Engineer"

    async def rewrite(bullets, missing):
        calls.append(missing)
        return [f"{b} using machine learning and static analysis" for b in bullets]

    monkeypatch.setattr(cv_engine.llm_client, "extract_keywords", keywords)
    monkeypatch.setattr(cv_engine.llm_client, "extract_job_title", job_title)
    monkeypatch.setattr(cv_engine.llm_client, "rewrite_bullets", rewrite)
    monkeypatch.setattr(
        cv_engine,
        "get_settings",
        lambda: SimpleNamespace(CV_OUTPUT_DIR=tmp_path, CV_REWRITE_BULLETS=rewrite_enabled),
    )


def test_rewrite_is_off_by_default_so_no_keyword_becomes_a_claim(monkeypatch, tmp_path):
    calls: list = []
    _fake_llm(monkeypatch, tmp_path, rewrite_enabled=False, calls=calls)

    res = asyncio.run(cv_engine.generate_cv(POSTING, PROFILE))

    assert calls == []
    assert res.rewritten is False
    assert res.missing_keywords == ["machine learning", "static analysis"]
    assert "machine learning" not in res.cv_html


def test_even_with_rewrite_on_the_copilot_gets_only_the_candidates_words(monkeypatch, tmp_path):
    calls: list = []
    _fake_llm(monkeypatch, tmp_path, rewrite_enabled=True, calls=calls)

    res = asyncio.run(cv_engine.generate_cv(POSTING, PROFILE))

    assert res.rewritten is True
    assert "machine learning" in res.cv_html  # the old behaviour, opt-in only
    assert res.final_profile.experience[0].bullets == ["Shipped a React chat panel"]
