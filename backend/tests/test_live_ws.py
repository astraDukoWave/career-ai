"""Live interview WebSocket /api/interview/ws/live (C2-SPEC-01).

AC-06 (Origin), AC-07 (session and duration limits), AC-08 (provider down:
an error for the live mode while the text copilot keeps working), event
mapping, and the backend half of AC-12 (the Deepgram key never reaches the
browser). The provider is a fake injected with FastAPI dependency overrides,
so production code carries no test flags.
"""

import asyncio
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import interview as interview_api
from app.api import interview_audio
from app.config import Settings, get_settings
from app.services.live_session import SessionLimiter
from app.services.stt_stream import SttUnavailable, parse_deepgram
from real_timeline import spoken_text, window

ORIGIN = "https://career-ai.test"
URL = "/api/interview/ws/live"
FRAME = b"\x00\x01" * 1600
CONTEXT = {
    "job_title": "Backend Developer",
    "skills": ["Backend: FastAPI, PostgreSQL", "Python"],
    "experience": [{"title": "Developer", "company": "CareerAI", "bullets": ["Built the live copilot"]}],
}


class FakeSession:
    """Plays scripted SttEvents once audio arrives, like the real provider."""

    def __init__(self, events=(), fail_mid=False):
        self.script = list(events)
        self.fail_mid = fail_mid
        self.audio = bytearray()
        self.finished = False
        self.closed = False

    async def send_audio(self, chunk):
        self.audio += chunk

    async def events(self):
        while not self.audio and not self.finished:
            await asyncio.sleep(0.005)
        for event in self.script:
            yield event
        if self.fail_mid:
            raise SttUnavailable("dropped_after_reconnect")
        while not self.finished:
            await asyncio.sleep(0.005)

    async def finish(self):
        self.finished = True

    async def close(self):
        self.closed = True


class FakeConnector:
    def __init__(self, *, events=(), fail_mid=False, unavailable=False):
        self.events, self.fail_mid, self.unavailable = events, fail_mid, unavailable
        self.calls: list[list[str]] = []
        self.sessions: list[FakeSession] = []

    async def __call__(self, keyterms):
        self.calls.append(keyterms)
        if self.unavailable:
            raise SttUnavailable("http_401")
        session = FakeSession(self.events, self.fail_mid)
        self.sessions.append(session)
        return session


def make_client(connector=None, limiter=None, **overrides):
    settings = Settings(CORS_ORIGINS=f"http://localhost:5173,{ORIGIN}", DEEPGRAM_API_KEY="", **overrides)
    app = FastAPI()
    app.include_router(interview_audio.router, prefix="/api/interview")
    app.include_router(interview_api.router, prefix="/api/interview")
    app.dependency_overrides[get_settings] = lambda: settings
    if connector is not None:
        app.dependency_overrides[interview_audio.get_stt_connector] = lambda: connector
    limiter = limiter or SessionLimiter(settings.LIVE_MAX_SESSIONS)
    app.dependency_overrides[interview_audio.get_session_limiter] = lambda: limiter
    return TestClient(app), limiter


def start_message(context=CONTEXT, source="tab"):
    return json.dumps({"type": "start", "source": source, "context": context})


def until_close(ws) -> tuple[list[dict], int]:
    messages = []
    while True:
        message = ws.receive()
        if message["type"] == "websocket.close":
            return messages, message.get("code", 1000)
        messages.append(json.loads(message["text"]))


def until_turn(ws, text: str, limit: int = 50) -> list[dict]:
    """Messages up to the turn carrying `text` (never blocks past `limit`)."""
    received = []
    for _ in range(limit):
        received.append(ws.receive_json())
        if received[-1]["type"] == "turn" and received[-1]["text"] == text:
            return received
    raise AssertionError(f"no turn {text!r} in {received}")


def real_events(name):
    """Normalised events of one question from the real Deepgram session."""
    return [event for message in window([name]) for event in parse_deepgram(message)]


# --- AC-06: Origin ------------------------------------------------------------------


@pytest.mark.parametrize("headers", [{"origin": "https://evil.example"}, {}])
def test_a_foreign_or_missing_origin_is_refused_before_deepgram(headers):
    connector = FakeConnector()
    client, limiter = make_client(connector)
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(URL, headers=headers):
            pass
    assert refused.value.code == 1008
    assert connector.calls == [] and limiter.active == 0


# --- Happy path: protocol and mapping ---------------------------------------------


def test_a_session_streams_audio_and_maps_a_real_cut_question_to_one_turn():
    connector = FakeConnector(events=real_events("Q2"))
    client, limiter = make_client(connector)
    with client.websocket_connect(URL, headers={"origin": ORIGIN}) as ws:
        ws.send_text(start_message())
        assert ws.receive_json() == {"type": "ready"}
        for _ in range(3):
            ws.send_bytes(FRAME)
        received = until_turn(ws, spoken_text(["Q2"]))
        ws.send_text(json.dumps({"type": "stop"}))
        rest, code = until_close(ws)
    assert code == 1000 and rest == []
    turn_messages = [m for m in received if m["type"] == "turn"]
    assert [t["turn_id"] for t in turn_messages] == [1, 1]
    assert turn_messages[-1] == {"type": "turn", "text": spoken_text(["Q2"]), "is_question": True, "turn_id": 1}
    [session] = connector.sessions
    assert bytes(session.audio) == FRAME * 3 and session.finished and session.closed
    # REQ-03: keyterms come from the CV context.
    assert connector.calls[0][:3] == ["FastAPI", "PostgreSQL", "Python"]
    assert limiter.active == 0


def test_the_browser_leaving_mid_session_frees_the_slot():
    connector = FakeConnector()
    client, limiter = make_client(connector)
    with client.websocket_connect(URL, headers={"origin": ORIGIN}) as ws:
        ws.send_text(start_message(context=None, source="mic"))
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(FRAME)
    for _ in range(100):
        if limiter.active == 0:
            break
        time.sleep(0.02)
    assert limiter.active == 0 and connector.sessions[0].closed
    assert connector.calls == [[]]  # no context, no keyterms


def test_a_bad_first_message_is_refused():
    client, limiter = make_client(FakeConnector())
    with client.websocket_connect(URL, headers={"origin": ORIGIN}) as ws:
        ws.send_text(json.dumps({"type": "start", "source": "speaker"}))
        messages, code = until_close(ws)
    assert messages == [{"type": "error", "code": "bad_start"}] and code == 1008
    assert limiter.active == 0


# --- AC-07: limits -----------------------------------------------------------------


def test_the_third_concurrent_session_is_refused():
    connector = FakeConnector()
    client, limiter = make_client(connector, LIVE_MAX_SESSIONS=2)
    with client.websocket_connect(URL, headers={"origin": ORIGIN}) as first, \
            client.websocket_connect(URL, headers={"origin": ORIGIN}) as second:
        for ws in (first, second):
            ws.send_text(start_message())
            assert ws.receive_json() == {"type": "ready"}
        with client.websocket_connect(URL, headers={"origin": ORIGIN}) as third:
            third.send_text(start_message())
            messages, code = until_close(third)
        assert messages == [{"type": "error", "code": "busy", "max_sessions": 2}] and code == 1013
        assert limiter.active == 2 and len(connector.calls) == 2
        for ws in (first, second):
            ws.send_text(json.dumps({"type": "stop"}))
            until_close(ws)
    assert limiter.active == 0


def test_a_socket_that_never_starts_holds_no_slot(monkeypatch):
    monkeypatch.setattr(interview_audio, "START_TIMEOUT_S", 0.3)
    client, limiter = make_client(FakeConnector(), LIVE_MAX_SESSIONS=1)
    with client.websocket_connect(URL, headers={"origin": ORIGIN}) as idle, \
            client.websocket_connect(URL, headers={"origin": ORIGIN}) as real:
        real.send_text(start_message())
        assert real.receive_json() == {"type": "ready"}  # the idle socket took nothing
        assert until_close(idle) == ([{"type": "error", "code": "bad_start"}], 1008)
        real.send_text(json.dumps({"type": "stop"}))
        until_close(real)
    assert limiter.active == 0


def test_a_session_past_the_duration_limit_is_closed_with_a_notice():
    connector = FakeConnector()
    client, limiter = make_client(connector, LIVE_MAX_SESSION_S=0.3)
    with client.websocket_connect(URL, headers={"origin": ORIGIN}) as ws:
        ws.send_text(start_message())
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(FRAME)
        messages, code = until_close(ws)
    assert messages == [{"type": "error", "code": "time_limit", "limit_s": 0.3}] and code == 1000
    assert limiter.active == 0 and connector.sessions[0].closed


# --- AC-08: provider down -------------------------------------------------------------


def test_provider_down_at_start_gives_an_error_and_text_mode_still_works(monkeypatch):
    client, limiter = make_client(FakeConnector(unavailable=True))
    with client.websocket_connect(URL, headers={"origin": ORIGIN}) as ws:
        ws.send_text(start_message())
        messages, code = until_close(ws)
    assert messages == [{"type": "error", "code": "stt_unavailable"}] and code == 1011
    assert limiter.active == 0

    async def fake_generate(text, intent, language, context=None):
        yield "Use a token bucket."

    monkeypatch.setattr(interview_api.llm_client, "generate_suggestion", fake_generate)
    response = client.post("/api/interview/text", json={"text": "How would you design a rate limiter?"})
    assert response.status_code == 200 and "Use a token bucket." in response.text


def test_provider_dropping_mid_session_keeps_what_was_said_and_reports_it():
    connector = FakeConnector(events=real_events("Q1"), fail_mid=True)
    client, _ = make_client(connector)
    with client.websocket_connect(URL, headers={"origin": ORIGIN}) as ws:
        ws.send_text(start_message())
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(FRAME)
        messages, code = until_close(ws)
    assert messages[-1] == {"type": "error", "code": "stt_unavailable"} and code == 1011
    assert {"type": "turn", "text": spoken_text(["Q1"]), "is_question": True, "turn_id": 1} in messages


# --- AC-12 (backend half): the key never reaches the browser ---------------------------


def test_the_deepgram_key_never_reaches_the_browser():
    secret = "dg-test-secret-0123456789"
    settings = Settings(CORS_ORIGINS=ORIGIN, DEEPGRAM_API_KEY=secret,
                        DEEPGRAM_LIVE_URL="ws://127.0.0.1:9/v1/listen", STT_CONNECT_TIMEOUT_S=1.0)
    app = FastAPI()
    app.include_router(interview_audio.router, prefix="/api/interview")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[interview_audio.get_session_limiter] = lambda: SessionLimiter(2)
    with TestClient(app).websocket_connect(URL, headers={"origin": ORIGIN}) as ws:  # real connector
        ws.send_text(start_message())
        messages, code = until_close(ws)
    assert messages == [{"type": "error", "code": "stt_unavailable"}] and code == 1011
    assert secret not in json.dumps(messages)
