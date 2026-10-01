"""E2E stack for the live interview mode (C2-PLAN-01 CS-8, AC-09/AC-10).

One process runs, on one background event loop:
- the real app (app.main: API + the built frontend from frontend/dist),
- a fake Deepgram that replays a REAL recorded Nova-3 session
  (backend/tests/fixtures/deepgram_turns_real.json) once audio arrives, and
the LLM is replaced by a fake generator for the duration of the run.

Production code has no test flags: the app reaches the fake Deepgram through
its normal DEEPGRAM_LIVE_URL setting, and the LLM is swapped by patching the
module function the route calls (the same injection the unit tests use).

Chromium gets a fake microphone fed from a generated WAV (no audio is
committed). Build the frontend first with VITE_API_URL=http://127.0.0.1:8123.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import sys
import threading
import time
import urllib.request
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PORT, DG_PORT = 8123, 8124
ORIGIN = f"http://127.0.0.1:{PORT}"
SPEED = 4.0  # replay the recorded timeline 4x faster than real time

# Settings are read once (lru_cache), so the environment goes first.
os.environ.update(
    CORS_ORIGINS=ORIGIN,
    DEEPGRAM_API_KEY="e2e-fake-key",
    DEEPGRAM_LIVE_URL=f"ws://127.0.0.1:{DG_PORT}/v1/listen",
    GEMINI_API_KEY="",
    CV_OUTPUT_DIR=str(ROOT / "e2e" / ".cvs"),
)
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend" / "tests")]

import uvicorn  # noqa: E402
from websockets.asyncio.server import serve  # noqa: E402

from app.main import app  # noqa: E402
from app.services import llm_client  # noqa: E402
from real_timeline import REAL, SPANS  # noqa: E402

# Q1 and Q2 (Q2 is cut mid-sentence by Nova-3 and continued: REQ-04 v1.1).
REPLAY = [e for e in REAL["events"] if e["t"] < SPANS["B1"]["start"] - 0.5]


class FakeDeepgram:
    def __init__(self) -> None:
        self.down = False
        self.connections = 0
        self.close_streams = 0

    def process_request(self, connection, request):
        if self.down:
            return connection.respond(503, "unavailable\n")
        return None

    async def handler(self, ws) -> None:
        self.connections += 1
        audio = asyncio.Event()

        async def replay() -> None:
            await audio.wait()
            last = REPLAY[0]["t"]
            for event in REPLAY:
                await asyncio.sleep(max(0.0, (event["t"] - last) / SPEED))
                last = event["t"]
                await ws.send(json.dumps(event["msg"]))

        task = asyncio.create_task(replay())
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    audio.set()
                elif json.loads(message).get("type") == "CloseStream":
                    self.close_streams += 1
                    await ws.close(1000)
                    return
        finally:
            task.cancel()


async def fake_generate(text, intent, language, context=None):
    for word in f"Suggested answer to: {text}".split(" "):
        yield word + " "
        await asyncio.sleep(0.02)


def _make_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(
            struct.pack("<h", int(3000 * math.sin(2 * math.pi * 220 * i / 16000))) for i in range(16000 * 30)
        ))


@pytest.fixture(scope="session")
def stack():
    dist = ROOT / "frontend" / "dist" / "index.html"
    assert dist.exists(), "build the frontend first: VITE_API_URL=http://127.0.0.1:8123 npm run build"
    llm_client.generate_suggestion = fake_generate
    fake = FakeDeepgram()
    loop = asyncio.new_event_loop()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning",
                                           ws_max_size=1_048_576, ws_max_queue=8, ws_per_message_deflate=False))

    async def main() -> None:
        async with serve(fake.handler, "127.0.0.1", DG_PORT, process_request=fake.process_request):
            await server.serve()

    thread = threading.Thread(target=lambda: loop.run_until_complete(main()), daemon=True)
    thread.start()
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"{ORIGIN}/health", timeout=1) as res:
                if res.status == 200:
                    break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("the app did not start")
    yield fake
    server.should_exit = True
    thread.join(10)


@pytest.fixture(scope="session")
def fake_mic(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("audio") / "interviewer.wav"
    _make_wav(path)
    return path


@pytest.fixture
def page(stack, fake_mic):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("E2E_CHROMIUM") or None,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={fake_mic}",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        context = browser.new_context(viewport={"width": 480, "height": 1000})
        context.grant_permissions(["microphone", "clipboard-read", "clipboard-write"], origin=ORIGIN)
        page = context.new_page()
        page.requests = []  # type: ignore[attr-defined]
        page.on("request", lambda r: page.requests.append(r.url))  # type: ignore[attr-defined]
        yield page
        browser.close()
