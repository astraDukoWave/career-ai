"""HTTP routes for the Interview Copilot.

Per the layered-architecture rule: routes ONLY translate HTTP <-> services.
NO business logic and NO direct DB access live here.

Endpoints (mounted under /api/interview via app.main):
    POST /text   -> SSE stream of suggestion chunks
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.interview import InterviewTextRequest
from app.services import llm_client, router_agent
from app.services.llm_client import (
    LLMConfigError,
    LLMRateLimitError,
    LLMResponseError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _sse(event: str, data: dict) -> str:
    """Encode a JSON payload as a single Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_suggestion(text: str) -> AsyncGenerator[str, None]:
    """Drive the router → LLM pipeline and serialise it as SSE.

    Once a StreamingResponse opens we can no longer change the status code,
    so any LLM error mid-stream is reported as an `error` event right before
    the final `done`. Pre-stream validation errors (e.g. empty text) still
    surface as a 422 from FastAPI before the stream starts.
    """
    intent = router_agent.classify_intent(text)
    language = router_agent.detect_language(text)
    yield _sse("meta", {"intent": intent, "language": language})

    try:
        async for chunk in llm_client.generate_suggestion(text, intent, language):
            yield _sse("chunk", {"content": chunk})
    except LLMConfigError as err:
        yield _sse("error", {"code": "config_error", "detail": str(err)})
    except LLMRateLimitError as err:
        yield _sse("error", {"code": "rate_limit", "detail": str(err)})
    except LLMResponseError as err:
        yield _sse("error", {"code": "llm_response", "detail": str(err)})
    except Exception as err:  # noqa: BLE001 — surface as SSE so the client can react.
        logger.exception("Streaming suggestion failed: %s", err)
        yield _sse(
            "error",
            {"code": "internal", "detail": "Internal error generating suggestion."},
        )

    yield _sse("done", {})


@router.post(
    "/text",
    summary="Stream an interview suggestion as Server-Sent Events",
)
async def interview_text(req: InterviewTextRequest) -> StreamingResponse:
    """Classify the prompt, detect language, then stream Gemini chunks.

    The response is `text/event-stream`. Event sequence:
        meta  -> {"intent": "...", "language": "..."}    (always first)
        chunk -> {"content": "..."}                       (zero or more)
        error -> {"code": "...", "detail": "..."}         (only on failure)
        done  -> {}                                       (always last)
    """
    return StreamingResponse(
        _stream_suggestion(req.text),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Disables proxy buffering on nginx / Render / Railway so chunks
            # are delivered as they arrive instead of in a final flush.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
