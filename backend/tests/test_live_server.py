"""The live WebSocket on a real uvicorn server, started with heroku.yml's flags.

What the in-process TestClient cannot show: the real Deepgram adapter against
a local fake Deepgram, a stop that lets the provider flush, a browser that
vanishes mid-session, and uvicorn's own frame cap (C2 CS-4 review of PR #17).
Only 127.0.0.1; no keys.
"""

import asyncio
import json
import shlex
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.api import interview_audio
from app.config import Settings, get_settings
from app.services.live_session import SessionLimiter
from fake_deepgram import FRAME, FakeDeepgram, answer, url_of
from real_timeline import spoken_text, window

ORIGIN = "https://career-ai.test"
HEROKU_YML = Path(__file__).resolve().parents[2] / "heroku.yml"
_FLAGS = {
    "--workers": ("workers", int),
    "--ws-max-size": ("ws_max_size", int),
    "--ws-max-queue": ("ws_max_queue", int),
    "--ws-per-message-deflate": ("ws_per_message_deflate", lambda v: v.lower() == "true"),
}


def production_flags() -> dict:
    """uvicorn.Config kwargs from heroku.yml's run.web command."""
    lines = HEROKU_YML.read_text().split("run:", 1)[1].splitlines()
    command = next(line.split("web:", 1)[1] for line in lines if line.strip().startswith("web:"))
    args = shlex.split(command)
    return {name: cast(args[args.index(flag) + 1]) for flag, (name, cast) in _FLAGS.items() if flag in args}


def test_heroku_runs_one_process_with_capped_uncompressed_frames():
    assert production_flags() == {
        "workers": 1, "ws_max_size": 1_048_576, "ws_max_queue": 8, "ws_per_message_deflate": False,
    }


async def run_stack(fake: FakeDeepgram, scenario, **settings_overrides):
    """Fake Deepgram + the live route on uvicorn, both on this event loop."""
    limiter = SessionLimiter(2)
    async with fake.serve() as dg:
        settings = Settings(CORS_ORIGINS=ORIGIN, DEEPGRAM_API_KEY="test-key", DEEPGRAM_LIVE_URL=url_of(dg),
                            **settings_overrides)
        app = FastAPI()
        app.include_router(interview_audio.router, prefix="/api/interview")
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[interview_audio.get_session_limiter] = lambda: limiter
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning",
                                               lifespan="off", **production_flags()))
        serving = asyncio.create_task(server.serve())
        try:
            for _ in range(200):
                if server.started:
                    break
                await asyncio.sleep(0.01)
            port = server.servers[0].sockets[0].getsockname()[1]
            return await scenario(f"ws://127.0.0.1:{port}/api/interview/ws/live", limiter)
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, 10)


async def wait_until(predicate, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


def start_message():
    return json.dumps({"type": "start", "source": "tab", "context": {"skills": ["FastAPI", "Python"]}})


def test_stop_lets_the_provider_flush_then_closes_cleanly():
    fake = FakeDeepgram(answer(window(["Q2"]), after_frames=1))

    async def scenario(url, limiter):
        async with connect(url, additional_headers={"Origin": ORIGIN}) as ws:
            # --ws-per-message-deflate false: compression is never negotiated.
            assert ws.response.headers.get("Sec-WebSocket-Extensions") is None
            await ws.send(start_message())
            assert json.loads(await ws.recv()) == {"type": "ready"}
            for _ in range(3):
                await ws.send(FRAME)
            received = []
            while not (received and received[-1].get("text") == spoken_text(["Q2"])):
                received.append(json.loads(await asyncio.wait_for(ws.recv(), 5)))
            await ws.send(json.dumps({"type": "stop"}))
            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(ws.recv(), 5)
            code = ws.close_code
        assert await wait_until(lambda: limiter.active == 0)
        return received, code

    received, code = asyncio.run(run_stack(fake, scenario))
    assert code == 1000
    turns = [m for m in received if m["type"] == "turn"]
    assert [t["turn_id"] for t in turns] == [1, 1]
    [conn] = fake.connections
    assert conn["texts"][-1] == {"type": "CloseStream"} and bytes(conn["audio"]) == FRAME * 3
    assert "keyterm=FastAPI" in conn["path"]


def test_a_browser_that_vanishes_still_closes_the_provider_and_frees_the_slot():
    fake = FakeDeepgram(answer())

    async def scenario(url, limiter):
        ws = await connect(url, additional_headers={"Origin": ORIGIN})
        await ws.send(start_message())
        assert json.loads(await ws.recv()) == {"type": "ready"}
        await ws.send(FRAME)
        assert limiter.active == 1
        ws.transport.abort()  # no close frame, like a closed laptop lid
        assert await wait_until(lambda: fake.connections and fake.connections[0]["closed"])
        assert await wait_until(lambda: limiter.active == 0)

    asyncio.run(run_stack(fake, scenario))
    assert fake.connections[0]["texts"] == [{"type": "CloseStream"}]


def test_an_oversized_frame_is_cut_by_uvicorn_before_the_app_buffers_it():
    """uvicorn closes with 1009 at once; it tells the app only after its 10 s
    close timeout, so the slot is freed within ~10 s (bounded, measured)."""
    fake = FakeDeepgram(answer())

    async def scenario(url, limiter):
        async with connect(url, additional_headers={"Origin": ORIGIN}, max_size=None) as ws:
            await ws.send(start_message())
            assert json.loads(await ws.recv()) == {"type": "ready"}
            await ws.send(b"\x00" * (2 * 1024 * 1024))
            with pytest.raises(ConnectionClosed):
                while True:
                    await asyncio.wait_for(ws.recv(), 5)
            code = ws.close_code
        assert await wait_until(lambda: limiter.active == 0, timeout=15)
        return code

    assert asyncio.run(run_stack(fake, scenario)) == 1009  # message too big
    assert fake.connections[0]["closed"]


def test_a_foreign_origin_gets_http_403_and_deepgram_is_never_dialled():
    fake = FakeDeepgram()

    async def scenario(url, limiter):
        with pytest.raises(Exception) as refused:
            async with connect(url, additional_headers={"Origin": "https://evil.example"}):
                pass
        return str(refused.value)

    assert "403" in asyncio.run(run_stack(fake, scenario))
    assert fake.requests == []
