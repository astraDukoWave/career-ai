"""Live interview WebSocket: /api/interview/ws/live (C2-SPEC-01).

Per the layered-architecture rule this module ONLY translates the WebSocket
protocol to `app.services.live_session`. It replaces the old pre-recorded
/ws/audio route (Cycle #2, HANDOFF §4).

Protocol:
    browser -> server
        1. text  {"type": "start", "source": "tab"|"mic", "context": {...}?}
        2. binary frames: 16 kHz mono linear16 PCM (~100 ms each)
        3. text  {"type": "stop"}   (or just close the socket)
    server -> browser (JSON text frames)
        {"type": "ready"}
        {"type": "partial"|"final", "text", "turn_id"}
        {"type": "turn", "text", "is_question", "turn_id"}  (a repeated
            turn_id means the question continued: restart its suggestion)
        {"type": "error", "code", ...}, then the server closes the socket:
            busy (1013, with "max_sessions") · time_limit (1000, with
            "limit_s") · stt_unavailable (1011) · bad_start (1008) ·
            internal (1011)

Security (NFR-04): Starlette's CORSMiddleware does not cover WebSocket
handshakes, so the Origin is checked here against CORS_ORIGINS before
accept(). A foreign origin never gets a socket: uvicorn answers the
handshake with HTTP 403 (a browser reports close code 1006) and Deepgram is
never dialled. The Deepgram key stays on the server (AC-12). A session slot
is taken only after a valid `start`, so idle sockets cannot hold one; frame
size and compression are capped in heroku.yml's uvicorn command.
"""

from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.schemas.interview import LiveStart
from app.services import live_session
from app.services.live_session import LiveSessionError, SessionLimiter
from app.services.stt_stream import SttConnector, open_deepgram_session

logger = logging.getLogger(__name__)
router = APIRouter()

START_TIMEOUT_S = 10.0
MAX_FRAME_BYTES = 64 * 1024  # 2 s of audio; real frames are ~3.2 KB

_CLOSE_CODES = {
    "busy": 1013,
    "time_limit": 1000,
    "stt_unavailable": 1011,
    "bad_start": 1008,
    "internal": 1011,
}


def get_stt_connector(settings: Settings = Depends(get_settings)) -> SttConnector:
    """Production connector (Deepgram); tests override this dependency."""

    async def connect(keyterms: list[str]):
        return await open_deepgram_session(keyterms, settings)

    return connect


@lru_cache(maxsize=1)
def _limiter(max_sessions: int) -> SessionLimiter:
    return SessionLimiter(max_sessions)


def get_session_limiter(settings: Settings = Depends(get_settings)) -> SessionLimiter:
    """One process-wide limiter (one uvicorn process per dyno)."""
    return _limiter(settings.LIVE_MAX_SESSIONS)


class _Client:
    """Adapts the socket to the service's two callables."""

    def __init__(self, websocket: WebSocket) -> None:
        self.ws = websocket
        self.gone = False
        self._warned_size = False

    async def next_audio(self) -> bytes | None:
        while not self.gone:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                self.gone = True
                return None
            data = message.get("bytes")
            if data is not None:
                if len(data) > MAX_FRAME_BYTES:
                    if not self._warned_size:
                        logger.warning("Live WS: dropping audio frames over %d bytes", MAX_FRAME_BYTES)
                        self._warned_size = True
                    continue
                if data:
                    return data
                continue
            if _message_type(message.get("text")) == "stop":
                return None
        return None

    async def send(self, payload: dict) -> None:
        if self.gone:
            return
        try:
            await self.ws.send_json(payload)
        except (WebSocketDisconnect, RuntimeError, OSError):
            self.gone = True  # the browser left; the session winds down on its own


def _message_type(text: str | None) -> str | None:
    try:
        data = json.loads(text or "")
    except ValueError:
        return None
    return data.get("type") if isinstance(data, dict) else None


async def _end(client: _Client, code: str, **details: object) -> None:
    """Tell the browser why, then close."""
    await client.send({"type": "error", "code": code, **details})
    if not client.gone:
        try:
            await client.ws.close(code=_CLOSE_CODES[code])
        except (RuntimeError, WebSocketDisconnect, OSError):
            pass  # the browser is already gone


def _client_label(websocket: WebSocket) -> str:
    """The caller's IP for log lines: Heroku's router appends the address it
    saw as the LAST X-Forwarded-For entry (earlier ones can be forged)."""
    forwarded = websocket.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[-1].strip()
    return websocket.client.host if websocket.client else "?"


async def _receive_start(websocket: WebSocket) -> LiveStart | None:
    """The first message must be a valid `start`; None if it is not."""
    try:
        message = await asyncio.wait_for(websocket.receive(), START_TIMEOUT_S)
    except TimeoutError:
        return None
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    try:
        return LiveStart.model_validate_json(message.get("text") or "")
    except ValidationError:
        return None


@router.websocket("/ws/live")
async def live_ws(
    websocket: WebSocket,
    settings: Settings = Depends(get_settings),
    connect: SttConnector = Depends(get_stt_connector),
    limiter: SessionLimiter = Depends(get_session_limiter),
) -> None:
    caller = _client_label(websocket)
    origin = websocket.headers.get("origin")
    if origin not in settings.cors_origins_list:
        logger.warning("Live WS refused: origin %r is not in CORS_ORIGINS (client=%s)", origin, caller)
        await websocket.close(code=1008)  # before accept(): uvicorn answers HTTP 403
        return

    await websocket.accept()
    client = _Client(websocket)
    try:
        start = await _receive_start(websocket)
    except WebSocketDisconnect:
        return  # the browser left before starting
    if start is None:
        await _end(client, "bad_start")
        return
    if not limiter.try_acquire():
        logger.info("Live WS refused: %d sessions already active (client=%s)", limiter.active, caller)
        await _end(client, "busy", max_sessions=limiter.max_sessions)
        return
    try:
        await live_session.run_live_session(start, client.next_audio, client.send, connect, settings, caller)
        if not client.gone:
            await websocket.close(code=1000)
    except LiveSessionError as err:
        await _end(client, err.code, **err.details)
    except WebSocketDisconnect:
        pass  # the browser left mid-session
    except Exception:  # noqa: BLE001 — log it and tell the browser, never a half-open socket
        logger.exception("Live WS failed unexpectedly")
        await _end(client, "internal")
    finally:
        limiter.release()
