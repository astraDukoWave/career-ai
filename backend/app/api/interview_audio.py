"""WebSocket route for live audio capture.

Per the layered-architecture rule this module ONLY translates the
WebSocket protocol to the STT service. No business logic, no DB access.

# ---------------------------------------------------------------------
# CORS / Origin note (intentional non-action):
# Starlette's CORSMiddleware is HTTP-only — it does NOT govern the
# WebSocket handshake. By default Starlette accepts any Origin on a WS
# route, which is what we want during local + Codespaces development.
# When this endpoint goes to production, validate `websocket.headers
# .get("origin")` against `Settings.cors_origins_list` here in the
# handler before calling `accept()`.
# ---------------------------------------------------------------------

Mounted under `/api/interview` in app.main, so the live URL is:
    /api/interview/ws/audio
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import stt_client

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/audio")
async def audio_ws(websocket: WebSocket) -> None:
    """Receive one recorded audio blob from the browser and stream back its transcript.

    Wire format:
        client -> server : one binary frame per recording — the complete
                           `audio/webm;codecs=opus` blob captured by
                           MediaRecorder from start() to Stop (not
                           incremental slices), sent to Deepgram's
                           pre-recorded transcription API
        server -> client : JSON `{"type": "transcript", "text": "..."}`

    A single connection can carry multiple start/stop recordings; each
    Stop produces one blob and one transcript. Empty transcripts (silence,
    or a swallowed STT failure) are skipped to avoid UI flicker.
    Disconnects are expected — they happen every time the user navigates
    away — and are handled quietly.
    """
    await websocket.accept()
    logger.info("Audio WS opened from %s", websocket.client)

    try:
        while True:
            audio_bytes = await websocket.receive_bytes()
            transcript = await stt_client.transcribe_audio_chunk(audio_bytes)
            if not transcript:
                continue
            await websocket.send_json({"type": "transcript", "text": transcript})
    except WebSocketDisconnect:
        logger.info("Audio WS closed by client %s", websocket.client)
    except Exception:  # noqa: BLE001 — close cleanly so the socket isn't left half-open.
        logger.exception("Audio WS failed unexpectedly")
        # 1011 = "internal error" per RFC 6455; gives the frontend a
        # signal to surface a generic error instead of silently retrying.
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            # Already closed (e.g. client vanished mid-handler) — nothing
            # we can do; the disconnect is the desired terminal state.
            pass
