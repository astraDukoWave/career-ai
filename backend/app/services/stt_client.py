"""Speech-to-Text client (Deepgram).

Per the layered-architecture rule this module lives in `app.services` and
contains business logic only. It MUST NOT import FastAPI: the WebSocket
route in `app.api.interview_audio` is the only HTTP-aware caller.

The public coroutine signature is fixed by that route and MUST stay:

    async def transcribe_audio_chunk(audio_data: bytes) -> str

Failure policy: this module never raises into the WebSocket handler. A
missing API key, a network error, or a malformed Deepgram response all
collapse to `""` so the socket stays open and the frontend can keep
streaming chunks.

Deepgram docs: https://developers.deepgram.com/docs/pre-recorded-audio
"""

from __future__ import annotations

import logging
from functools import lru_cache

from deepgram import AsyncDeepgramClient, PrerecordedOptions
from deepgram.core.api_error import ApiError

from app.config import get_settings

logger = logging.getLogger(__name__)

# Deepgram's current general-purpose speech model. Handles webm/opus
# (what MediaRecorder emits in the browser) without extra parameters.
_MODEL = "nova-3"


@lru_cache(maxsize=1)
def _get_client() -> AsyncDeepgramClient | None:
    """Build (and cache) the async Deepgram client, or None if no key."""
    api_key = get_settings().DEEPGRAM_API_KEY.strip()
    if not api_key:
        logger.warning(
            "DEEPGRAM_API_KEY is not set — STT is disabled, "
            "transcribe_audio_chunk() will return empty strings."
        )
        return None
    return AsyncDeepgramClient(api_key=api_key)


async def transcribe_audio_chunk(audio_data: bytes) -> str:
    """Transcribe a single audio chunk via Deepgram's pre-recorded API.

    Args:
        audio_data: Raw bytes from the browser's MediaRecorder (typically
            `audio/webm;codecs=opus`). Sent to Deepgram as-is; the server
            detects the container/codec from the audio header.

    Returns:
        The recognised transcript, or `""` for silent/empty input, a
        missing API key, or any upstream failure. Never raises.
    """
    if not audio_data:
        return ""

    client = _get_client()
    if client is None:
        return ""

    try:
        payload = {"buffer": audio_data}
        options = PrerecordedOptions(
            model=_MODEL,
            language="es",
            detect_language=True,
            smart_format=True,
        )
        response = await client.listen.asyncprerecorded.v("1").transcribe_file(
            payload, options
        )
        transcript = response.results.channels[0].alternatives[0].transcript
        return (transcript or "").strip()
    except ApiError as exc:
        # IMPORTANTE: Mantener exc.status_code y exc.body como estaban originalmente
        logger.warning("Deepgram API error (status=%s): %s", exc.status_code, exc.body)
        return ""
    except (AttributeError, IndexError, TypeError):
        logger.warning("Unexpected Deepgram response shape")
        return ""
    except Exception:
        logger.exception("Deepgram transcription failed")
        return ""
