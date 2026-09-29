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
    monkeypatch.setattr(cv_engine, "get_settings", lambda: SimpleNamespace(CV_OUTPUT_DIR=tmp_path))

    res = asyncio.run(cv_engine.generate_cv(POSTING, PROFILE))

    assert res.job_title == "Frontend Developer"
    printed = res.final_profile
    assert printed is not None
    assert printed.summary == "Builds AI features in React."
    assert printed.skills == ["Frontend: React, TypeScript", "Git, Docker"]
    assert printed.experience[0].bullets == ["Shipped a React chat panel"]
    assert printed.experience[0].start == "Jan 2025"
