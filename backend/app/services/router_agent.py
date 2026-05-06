"""Router agent — keyword-based intent + language classification.

Why keywords (not LangChain): in a real interview the copilot must respond
in well under a second. Round-tripping to an LLM just to decide "which prompt
should I use?" adds 500-1500ms for no gain. A small allowlist of trigger
phrases already covers >95% of common interview prompts.

Per the layered-architecture rule this is a SERVICE — no FastAPI imports.
The route layer in app.api.interview translates these results into HTTP.
"""

from __future__ import annotations

import re
from typing import Literal

Intent = Literal["tech_code", "tech_concept", "behavioral_star"]
Language = Literal["en", "es"]


# =============================================================================
# Intent triggers
# =============================================================================
# Order of *intents* in this dict encodes priority when an input triggers more
# than one category — behavioral wins over tech because "tell me about a time
# you wrote a function" is behavioral first, with "function" being incidental.
_INTENT_TRIGGERS: dict[Intent, tuple[str, ...]] = {
    "behavioral_star": (
        "tell me about",
        "experience where",
        "situation where",
        "situation",
        "cuéntame",
        "experiencia donde",
        "vez que",
    ),
    "tech_code": (
        "implement",
        "write",
        "code",
        "function",
        "algorithm",
        "implementa",
        "escribe",
        "código",
        "función",
        "algoritmo",
    ),
    "tech_concept": (
        "explain",
        "what is",
        "how does",
        "difference between",
        "explica",
        "qué es",
        "cómo funciona",
        "diferencia entre",
    ),
}

# Default when nothing matches. tech_concept is safer than tech_code:
# producing a code dump for an ambiguous prompt is much more jarring than
# producing a short conceptual answer.
_DEFAULT_INTENT: Intent = "tech_concept"


# =============================================================================
# Language indicators (heuristic, not a real classifier)
# =============================================================================
# We compare counts of Spanish vs English markers. Ties go to English because
# the project's interface defaults to English.
_SPANISH_INDICATORS = re.compile(
    r"\b(?:el|la|los|las|de|que|qué|cómo|por|para|con|una|sin|sobre|también|"
    r"mientras|hasta|cuándo|dónde|porque|sí|así|pero|este|esta|esto)\b|"
    r"[áéíóúñ¿¡]",
    flags=re.IGNORECASE,
)
_ENGLISH_INDICATORS = re.compile(
    r"\b(?:the|and|of|to|in|that|is|it|for|with|on|as|are|was|be|but|by|"
    r"this|from|or|an|have|has|do|does)\b",
    flags=re.IGNORECASE,
)


# =============================================================================
# Internals
# =============================================================================


def _phrase_present(phrase: str, haystack: str) -> bool:
    """Word-boundary substring match. Multi-word phrases stay contiguous."""
    return re.search(r"\b" + re.escape(phrase) + r"\b", haystack) is not None


# =============================================================================
# Public API
# =============================================================================


def classify_intent(text: str) -> Intent:
    """Classify an interviewer prompt into one of three intents.

    Priority is encoded by the iteration order of `_INTENT_TRIGGERS`: the first
    intent whose triggers appear in the input wins. Falls back to
    `_DEFAULT_INTENT` (tech_concept) when nothing matches.
    """
    haystack = re.sub(r"\s+", " ", text.lower())
    for intent, triggers in _INTENT_TRIGGERS.items():
        if any(_phrase_present(t, haystack) for t in triggers):
            return intent
    return _DEFAULT_INTENT


def detect_language(text: str) -> Language:
    """Pick 'es' or 'en' from stopword / accent frequency. Defaults to 'en'."""
    es_hits = len(_SPANISH_INDICATORS.findall(text))
    en_hits = len(_ENGLISH_INDICATORS.findall(text))
    return "es" if es_hits > en_hits else "en"
