"""One live interview session: audio in, transcript and turns out.

C2-SPEC-01 REQ-02 to REQ-04, NFR-02 and NFR-05. Service layer, so no
FastAPI: the WebSocket route hands over two plain callables (the next audio
frame, or None when the browser stops or leaves; and a function that sends
one JSON-able dict), which keeps the whole session testable without a socket.

Flow: derive keyterms from the context → open the provider session (5 s
timeout) → send `{"type": "ready"}` → forward audio while the turn detector
turns provider events into `partial` / `final` / `turn` messages → on stop,
let the provider flush its last results (bounded) and close.

Failures surface as `LiveSessionError(code)`: the route sends
`{"type": "error", "code": …}` and closes. The text copilot does not depend
on any of this (NFR-06), so it keeps working when the live mode fails.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from app.config import Settings
from app.schemas.interview import LiveStart
from app.services.stt_stream import SttConnector, SttUnavailable, derive_keyterms
from app.services.turn_detector import TurnDetector

logger = logging.getLogger(__name__)

# After the browser stops, how long the provider may take to flush.
DRAIN_TIMEOUT_S = 3.0

NextAudio = Callable[[], Awaitable[bytes | None]]
Send = Callable[[dict], Awaitable[None]]


class LiveSessionError(Exception):
    """The session ended for a reason the browser must show.

    Codes: `stt_unavailable` (EDGE-05), `time_limit` (EDGE-09).
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SessionLimiter:
    """At most `max_sessions` live sessions at a time (NFR-05, EDGE-09).

    Production runs one uvicorn process on one dyno, so an in-memory count is
    exact. Everything runs on one event loop, so no lock is needed.
    """

    def __init__(self, max_sessions: int) -> None:
        self.max_sessions = max_sessions
        self.active = 0

    def try_acquire(self) -> bool:
        if self.active >= self.max_sessions:
            return False
        self.active += 1
        return True

    def release(self) -> None:
        self.active = max(0, self.active - 1)


async def run_live_session(
    start: LiveStart,
    next_audio: NextAudio,
    send: Send,
    connect: SttConnector,
    settings: Settings,
) -> None:
    """Run one session until the browser stops, the provider fails or time runs out."""
    keyterms = derive_keyterms(start.context, settings.STT_MAX_KEYTERMS)
    started = time.monotonic()
    try:
        stt = await connect(keyterms)
    except SttUnavailable as err:
        logger.warning("Live session: speech-to-text unavailable at start (%s)", err)
        raise LiveSessionError("stt_unavailable") from err

    detector = TurnDetector(settings.TURN_CONTINUATION_S, settings.TURN_FILLER_S)
    reason = "stopped"
    logger.info("Live session started: source=%s keyterms=%d", start.source, len(keyterms))
    try:
        await send({"type": "ready"})
        try:
            async with asyncio.timeout(settings.LIVE_MAX_SESSION_S):
                await _pump(stt, detector, next_audio, send)
        except TimeoutError as err:
            reason = "time_limit"
            raise LiveSessionError("time_limit") from err
        except SttUnavailable as err:
            reason = f"stt_unavailable ({err})"
            logger.warning("Live session: speech-to-text dropped (%s)", err)
            raise LiveSessionError("stt_unavailable") from err
        except BaseException:
            reason = "error"
            raise
    finally:
        await stt.close()
        logger.info(
            "Live session ended: reason=%s duration=%.0fs turns=%d questions=%d",
            reason, time.monotonic() - started, detector.turns, detector.questions,
        )


async def _pump(stt, detector: TurnDetector, next_audio: NextAudio, send: Send) -> None:
    async def uplink() -> None:
        while (chunk := await next_audio()) is not None:
            await stt.send_audio(chunk)
        await stt.finish()

    async def downlink() -> None:
        async for event in stt.events():
            for message in detector.feed(event):
                await send(message)

    up = asyncio.create_task(uplink())
    down = asyncio.create_task(downlink())
    try:
        done, _ = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
        if down in done:
            down.result()  # the provider failed for good (SttUnavailable)
            if not up.done():
                # The provider ended without being asked to: same as a drop.
                raise SttUnavailable("ended")
        up.result()  # unexpected errors in the browser side surface here
        # The browser stopped: let the provider flush its last results.
        try:
            await asyncio.wait_for(asyncio.shield(down), DRAIN_TIMEOUT_S)
        except (TimeoutError, SttUnavailable) as err:
            down.cancel()  # nothing may feed the detector while it flushes
            logger.info("Live session: provider flush cut short (%s)", type(err).__name__)
        for message in detector.flush():
            await send(message)
    finally:
        for task in (up, down):
            task.cancel()
        await asyncio.gather(up, down, return_exceptions=True)
