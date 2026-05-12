"""Gemini API wrapper.

Why a dedicated wrapper:
- Centralises the model name, prompts and JSON parsing.
- Lets cv_engine.py stay focused on orchestration.
- Single place to mock when we add tests later.

Per the layered-architecture rule: this file is a SERVICE, so no FastAPI
imports. It raises plain exceptions; the route layer translates them to HTTP.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncGenerator

from google.api_core import exceptions as google_exceptions
import google.generativeai as genai

from app.config import get_settings

logger = logging.getLogger(__name__)

_MODEL_ALIASES = {}


class LLMConfigError(RuntimeError):
    """Raised when the Gemini API key is missing — the API can't function."""


class LLMResponseError(RuntimeError):
    """Raised when Gemini returns an unparseable response."""


class LLMRateLimitError(RuntimeError):
    """Raised when Gemini rejects the request due to quota/rate limits."""


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

# =============================================================================
# Interview Copilot prompts (sourced verbatim from skill-creator-v2.md)
# =============================================================================
# Base prompt prepended to every suggestion regardless of intent. Establishes
# the "respond in the input language", "max ~3 sentences" and "never reveal
# you're an AI" rules. Intent-specific prompts append on top.
_SUGGESTION_BASE_PROMPT = """Eres un copiloto de comunicación profesional en tiempo real.
Tu función: sugerir respuestas claras, concisas y naturales para entrevistas técnicas.

REGLAS CRÍTICAS:
- Respuestas de máximo 3 oraciones para que el usuario pueda leerlas mientras habla
- NUNCA menciones que eres una IA ayudando en una entrevista
- Detecta el idioma del input y responde en el MISMO idioma
- Si detectas cambio de idioma, adapta inmediatamente sin confirmación
- Prioriza claridad sobre profundidad técnica excesiva"""

# Three intent-specific addenda. Keys must match the literals returned by
# `router_agent.classify_intent` so they can be looked up directly.
_SUGGESTION_INTENT_PROMPTS: dict[str, str] = {
    "tech_code": """El entrevistador pide una implementación de código.

ESTRUCTURA DE RESPUESTA (3 partes):
1. [10 palabras] Reconfirmar entendimiento del problema en voz alta
2. [20 palabras] El enfoque/algoritmo que vas a usar y por qué
3. [Código] La solución con comentarios inline en el idioma del entrevistador

FORMATO DE THINKING OUT LOUD:
"Ok, entonces necesito [X]. Mi enfoque sería [Y] porque [Z en una razón]. Voy a empezar por...\"""",
    "tech_concept": """El entrevistador pregunta sobre un concepto técnico.

ESTRUCTURA ELI5 (Explain Like I'm 5, but Senior):
1. Definición en 1 oración sin jerga
2. Analogía del mundo real
3. Cuándo usarlo en producción

Máximo 4 oraciones totales.""",
    "behavioral_star": """El entrevistador hace una pregunta behavioral (STAR).

ESTRUCTURA STAR COMPRIMIDA:
- Situación: 1 oración de contexto
- Tarea: 1 oración de responsabilidad
- Acción: 2 oraciones de qué hiciste específicamente (verbos activos + métricas)
- Resultado: 1 oración con número o impacto medible

VERSIÓN CORTA (30 seg): solo Acción + Resultado
VERSIÓN LARGA (2 min): STAR completo

Detectar si el entrevistador quiere profundidad por el tono de la pregunta.""",
}

# Extracts the job role title only — used to render the CV header verbatim.
# The first line of a posting is often the *full* posting heading
# ("Naranja X | We're hiring..."), so we ask the LLM to isolate the role.
_JOB_TITLE_PROMPT = """Read this job posting and extract ONLY the job role title.
Return 2-6 words maximum. Return ONLY the title, no punctuation,
no company name, no slogan. Examples: 'Frontend Engineer',
'Data Analyst Intern', 'Full Stack Developer'.

Job posting:
\"\"\"
{job_posting}
\"\"\"
"""

# Rewrites bullets to embed missing keywords AND attach a measurable impact
# (real metric when the candidate provided one, bracketed placeholder otherwise).
_REWRITE_PROMPT = """You are a senior CV writer optimising a candidate's experience
bullets for ATS keyword matching AND measurable impact. Always reply in the
same language as the input.

NON-NEGOTIABLE CONSTRAINTS:
- DO NOT fabricate companies, technologies, or concrete numbers the candidate
  did not mention.
- Preserve the candidate's real achievements, verbs and any metric they
  already stated.
- Naturally weave in as many of the MISSING_KEYWORDS as plausible — only when
  the bullet's context allows it.
- Keep each bullet under 25 words. Active verbs. Past tense.
- Output ONLY a JSON array of strings, same length as the input. No prose, no
  markdown fences.

METRICS RULE (mandatory — a bullet without a measurable outcome is a weak bullet):
- If the original already states a real metric, keep it verbatim.
- Otherwise, every rewritten bullet MUST end with a quantified impact using
  ONLY a bracketed placeholder so the candidate can fill it in later. Pick
  the placeholder that fits the bullet's context, translating the noun into
  the bullet's language (e.g. "users" → "usuarios", "hours" → "horas"):
    [X%]         percentages (savings, growth, reductions)
    [N users]    audience / user counts
    [Z ms]       latency / performance
    [Y hours]    time saved
- NEVER invent a concrete fake number; brackets are mandatory when the metric
  is unknown.

EXAMPLE (single bullet):
  Original: "Desarrollé una API para gestión de usuarios"
  Rewrite:  "Arquitecté una API RESTful para gestión de usuarios, reduciendo el tiempo de respuesta en [Z ms] mediante optimización de consultas"

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
    model_name = _MODEL_ALIASES.get(settings.GEMINI_MODEL, settings.GEMINI_MODEL)
    if model_name != settings.GEMINI_MODEL:
        logger.warning(
            "Gemini model %s is unavailable; using %s instead.",
            settings.GEMINI_MODEL,
            model_name,
        )
    return genai.GenerativeModel(model_name)


def _generate_content(model: genai.GenerativeModel, prompt: str):
    try:
        return model.generate_content(prompt)
    except google_exceptions.ResourceExhausted as err:
        raise LLMRateLimitError(
            "Gemini quota/rate limit exceeded. Retry later or use a key with more quota."
        ) from err


# =============================================================================
# Public API
# =============================================================================


def _first_nonempty_line(text: str) -> str:
    """First non-empty line of a posting, capped at 120 chars to skip junk headers."""
    for line in text.splitlines():
        candidate = line.strip()
        if candidate and len(candidate) <= 120:
            return candidate
    return ""


async def extract_job_title(job_posting: str) -> str:
    """Extract the job role title from a posting via Gemini.

    Returns the role title (2-6 words). Whenever the LLM is unavailable, errors,
    or returns something longer than 8 words (likely the model ignored the
    instruction and re-emitted the heading), we fall back to the first non-empty
    line of the posting — preserving the old heuristic behaviour.

    LLMConfigError is intentionally not caught here so the route layer can map
    a missing API key to HTTP 503; everything else degrades gracefully.
    """
    fallback = _first_nonempty_line(job_posting)
    model = _get_model()

    try:
        response = _generate_content(
            model, _JOB_TITLE_PROMPT.format(job_posting=job_posting)
        )
        raw = (response.text or "").strip()
    except LLMRateLimitError as err:
        logger.warning(
            "Job title extraction hit rate limit (%s); using first-line fallback.",
            err,
        )
        return fallback
    except Exception as err:  # noqa: BLE001 — any LLM hiccup → fallback, never crash the request.
        logger.warning(
            "Job title extraction failed (%s); using first-line fallback.", err
        )
        return fallback

    cleaned = _strip_code_fences(raw)
    first_line = next(
        (line.strip() for line in cleaned.splitlines() if line.strip()), ""
    )
    title = first_line.strip("\"'`*").strip().rstrip(".,;:")

    if not title or len(title.split()) > 8:
        logger.info(
            "Job title LLM response rejected (%r); using first-line fallback.", raw
        )
        return fallback

    return title


async def extract_keywords(job_posting: str) -> list[str]:
    """Ask Gemini for the ATS-relevant keywords of a job posting."""
    model = _get_model()
    prompt = _KEYWORDS_PROMPT.format(job_posting=job_posting)

    # generate_content is synchronous in the current SDK; that's fine, FastAPI
    # will run it in a threadpool because the route is `async def`.
    response = _generate_content(model, prompt)
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
        response = _generate_content(model, prompt)
        raw = _strip_code_fences(response.text or "")
        rewritten = json.loads(raw)
    except LLMRateLimitError:
        logger.warning("Bullet rewrite skipped because Gemini quota/rate limit was exceeded.")
        return bullets
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


async def generate_suggestion(
    text: str,
    intent: str,
    language: str,
) -> AsyncGenerator[str, None]:
    """Stream an interview suggestion via Gemini.

    Args:
        text: The interviewer's prompt (already transcribed if originally audio).
        intent: One of "tech_code", "tech_concept", "behavioral_star". Unknown
            values fall back to "tech_concept" — same default as router_agent.
        language: "en" or "es"; the response is produced in this language.

    Yields:
        Plain text chunks as Gemini emits them.

    Raises:
        LLMConfigError: missing API key (route layer maps to 503).
        LLMRateLimitError: quota/rate limit exceeded (route layer maps to 429).
    """
    model = _get_model()

    intent_prompt = _SUGGESTION_INTENT_PROMPTS.get(
        intent, _SUGGESTION_INTENT_PROMPTS["tech_concept"]
    )
    language_label = "Spanish" if language == "es" else "English"
    full_prompt = (
        f"{_SUGGESTION_BASE_PROMPT}\n\n"
        f"{intent_prompt}\n\n"
        f"Respond in {language_label}. Output ONLY the suggested answer text — "
        f"no preamble, no markdown fences, no role labels.\n\n"
        f'INTERVIEWER PROMPT:\n"""\n{text}\n"""\n'
    )

    try:
        response = await asyncio.to_thread(
            model.generate_content, full_prompt, stream=True
        )
    except google_exceptions.ResourceExhausted as err:
        raise LLMRateLimitError(
            "Gemini quota/rate limit exceeded. Retry later or use a key with more quota."
        ) from err

    for chunk in response:
        try:
            piece = chunk.text
        except Exception as err:  # noqa: BLE001 — Gemini error types vary across SDK versions.
            logger.debug("Skipping non-text chunk: %s", err)
            continue
        if piece:
            yield piece
