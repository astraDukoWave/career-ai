"""Gemini API wrapper.

Why a dedicated wrapper:
- Centralises the model name, prompts and JSON parsing.
- Lets cv_engine.py stay focused on orchestration.
- Single place to mock when we add tests later.

Per the layered-architecture rule: this file is a SERVICE, so no FastAPI
imports. It raises plain exceptions; the route layer translates them to HTTP.
"""

from __future__ import annotations

import json
import logging
import re

import google.generativeai as genai

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMConfigError(RuntimeError):
    """Raised when the Gemini API key is missing — the API can't function."""


class LLMResponseError(RuntimeError):
    """Raised when Gemini returns an unparseable response."""


# =============================================================================
# Prompt templates
# =============================================================================

# Returns ATS-relevant keywords as a JSON list of lowercase strings.
_KEYWORDS_PROMPT = """You are an expert ATS (Applicant Tracking System) parser.

Extract the most important keywords and skills from the following job posting.
Focus on:
- Technical skills (languages, frameworks, tools)
- Methodologies (agile, scrum, etc.)
- Domain terms specific to the role
- Required certifications or qualifications

Rules:
- Return between 10 and 25 keywords.
- Lowercase, no duplicates, no generic words like "team" or "communication".
- Multi-word keywords stay as single strings (e.g. "machine learning").
- Output ONLY a JSON array of strings. No prose, no markdown fences.

Job posting:
\"\"\"
{job_posting}
\"\"\"
"""

# Rewrites bullets to embed missing keywords naturally without inventing facts.
_REWRITE_PROMPT = """You are a senior CV writer optimising a candidate's experience
bullets for ATS keyword matching.

CONSTRAINTS (non-negotiable):
- DO NOT invent achievements, companies, numbers, or technologies the candidate
  did not mention.
- Preserve the candidate's verbs and metrics.
- Naturally weave in as many of the MISSING_KEYWORDS as plausible — only when
  the bullet's context allows it.
- Keep each bullet under 25 words. Active verbs. Past tense.
- Output ONLY a JSON array of strings, same length as the input. No prose, no
  markdown fences.

ORIGINAL_BULLETS:
{bullets_json}

MISSING_KEYWORDS:
{missing_keywords_json}
"""


def _strip_code_fences(text: str) -> str:
    """Gemini occasionally wraps JSON in ```json ... ``` despite instructions."""
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    return fence.group(1).strip() if fence else cleaned


def _get_model() -> genai.GenerativeModel:
    """Lazily configure the SDK and return a model instance.

    Raises LLMConfigError if GEMINI_API_KEY is not set, so the caller can map
    that to an HTTP 503 instead of a 500.
    """
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise LLMConfigError(
            "GEMINI_API_KEY is not configured. Set it in .env and restart the backend."
        )
    genai.configure(api_key=settings.GEMINI_API_KEY)
    return genai.GenerativeModel(settings.GEMINI_MODEL)


# =============================================================================
# Public API
# =============================================================================


async def extract_keywords(job_posting: str) -> list[str]:
    """Ask Gemini for the ATS-relevant keywords of a job posting."""
    model = _get_model()
    prompt = _KEYWORDS_PROMPT.format(job_posting=job_posting)

    # generate_content is synchronous in the current SDK; that's fine, FastAPI
    # will run it in a threadpool because the route is `async def`.
    response = model.generate_content(prompt)
    raw = _strip_code_fences(response.text or "")

    try:
        keywords = json.loads(raw)
    except json.JSONDecodeError as err:
        logger.warning("Gemini keyword response was not valid JSON: %r", raw)
        raise LLMResponseError("Gemini returned malformed keyword JSON") from err

    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        raise LLMResponseError("Gemini keyword response is not a JSON array of strings")

    # De-duplicate while preserving order, lowercase everything.
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        norm = kw.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            unique.append(norm)
    return unique


async def rewrite_bullets(
    bullets: list[str],
    missing_keywords: list[str],
) -> list[str]:
    """Ask Gemini to rewrite the bullets to embed missing keywords.

    On any LLM failure we return the original bullets unchanged — the caller
    treats that as 'no rewrite happened' rather than crashing the request.
    """
    if not bullets or not missing_keywords:
        return bullets

    model = _get_model()
    prompt = _REWRITE_PROMPT.format(
        bullets_json=json.dumps(bullets, ensure_ascii=False),
        missing_keywords_json=json.dumps(missing_keywords, ensure_ascii=False),
    )

    try:
        response = model.generate_content(prompt)
        raw = _strip_code_fences(response.text or "")
        rewritten = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as err:
        logger.warning("Bullet rewrite failed, falling back to originals: %s", err)
        return bullets

    if (
        not isinstance(rewritten, list)
        or len(rewritten) != len(bullets)
        or not all(isinstance(b, str) for b in rewritten)
    ):
        logger.warning("Bullet rewrite shape mismatch, falling back to originals.")
        return bullets

    return [b.strip() for b in rewritten]
