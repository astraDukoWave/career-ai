"""Speech-to-Text client.

Per the layered-architecture rule this module lives in `app.services` and
contains business logic only. It MUST NOT import FastAPI: the WebSocket
route in `app.api.interview_audio` is the only HTTP-aware caller.

Sprint scope: ship an audio pipeline end-to-end with a deterministic mock
so the frontend, the WebSocket plumbing, and the UI states can be wired up
without depending on a third-party API contract that may still shift.

# =====================================================================
# MOCK STT — Replace with Deepgram API in next sprint
# See: https://developers.deepgram.com/docs/getting-started-with-live-streaming-audio
# =====================================================================
"""

from __future__ import annotations

import asyncio


# Latency the real Deepgram streaming endpoint roughly hits for a 2s audio
# chunk. Picked so the frontend's "Connecting…" → "Recording…" → transcript
# arrival cadence already feels representative under the mock.
_MOCK_LATENCY_SECONDS = 0.3


async def transcribe_audio_chunk(audio_data: bytes) -> str:
    """Pretend to transcribe a single audio chunk.

    Args:
        audio_data: Raw bytes from the browser's MediaRecorder (typically
            `audio/webm;codecs=opus`). The mock does not decode them — it
            only uses the length to vary the simulated transcript so the
            UI doesn't show the same string for every chunk.

    Returns:
        A simulated transcript. Empty input yields an empty string so the
        WebSocket route can skip sending a frame for silence/keep-alives.
    """
    if not audio_data:
        return ""

    await asyncio.sleep(_MOCK_LATENCY_SECONDS)

    # Deterministic-but-varying placeholder. Real Deepgram output will be
    # the actual recognised text and the size suffix goes away.
    size_kb = len(audio_data) // 1024
    return f"(mock transcript for ~{size_kb}KB chunk)"
