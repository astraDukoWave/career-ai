"""Speech-to-text adapter (C2-SPEC-01 REQ-02/03, NFR-02).

- The parser runs on real Nova-3 messages recorded in CS-0
  (fixtures/deepgram_cs0_samples.json).
- `DeepgramLiveSession` runs against a local fake Deepgram WebSocket server:
  parameters and auth header, audio forwarding, KeepAlive, CloseStream, one
  reconnection with the clock shifted, and the failures that end a session.
No network beyond 127.0.0.1 and no API key.
"""

import asyncio
import http
import json
import socket
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import Settings
from app.schemas.interview import InterviewContext
from app.services.stt_stream import (
    DeepgramLiveSession,
    SttEvent,
    SttUnavailable,
    build_live_url,
    derive_keyterms,
    open_deepgram_session,
    parse_deepgram,
)
from fake_deepgram import FRAME, FakeDeepgram, answer, with_fake

SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "deepgram_cs0_samples.json").read_text())["messages"]


# --- Parser on real CS-0 messages ----------------------------------------------


def test_real_interim_results_become_partials_with_word_times():
    empty, words = SAMPLES["Results"]
    assert parse_deepgram(empty) == []
    assert parse_deepgram(words) == [SttEvent("partial", "Tell me about a project", 0.96, 1.52)]


def test_real_vad_and_utterance_end_messages():
    assert parse_deepgram(SAMPLES["SpeechStarted"][0]) == [SttEvent("speech_start", start=1.1)]
    # UtteranceEnd is about the last word (7.89) and is sent utterance_end_ms later.
    assert parse_deepgram(SAMPLES["UtteranceEnd"][1], utterance_end_s=1.0) == [
        SttEvent("utterance_end", start=7.89, end=8.89)
    ]
    assert parse_deepgram(SAMPLES["Metadata"][0]) == []


def test_a_final_with_speech_final_closes_at_the_end_of_its_window():
    message = {**SAMPLES["Results"][1], "is_final": True, "speech_final": True, "duration": 2.75}
    assert parse_deepgram(message, offset=10.0) == [
        SttEvent("final", "Tell me about a project", 10.96, 11.52),
        SttEvent("turn_end", end=12.75),
    ]


def test_an_empty_endpoint_is_only_a_turn_end_and_junk_is_ignored():
    message = {"type": "Results", "start": 8.05, "duration": 1.65, "is_final": True, "speech_final": True,
               "channel": {"alternatives": [{"transcript": "", "words": []}]}}
    assert parse_deepgram(message) == [SttEvent("turn_end", end=9.7)]
    assert parse_deepgram({"type": "Results", "channel": [0, 1]}) == []
    assert parse_deepgram({"type": "Results", "channel": {"alternatives": "odd"}}) == []
    assert parse_deepgram({"type": "Results", "channel": {"alternatives": [1]}}) == []
    assert parse_deepgram({"type": "Results", "channel": {"alternatives": [{"transcript": "hi", "words": "x"}]},
                           "start": 1.0, "duration": 0.5}) == [SttEvent("partial", "hi", 1.0, 1.5)]
    assert parse_deepgram({"type": "Something new"}) == []


# --- URL and keyterms (REQ-02/03) ------------------------------------------------


def test_the_live_url_carries_req_02_parameters_and_never_the_key():
    url = build_live_url("wss://api.deepgram.com/v1/listen", ["C#", "Node.js"], endpointing_ms=100,
                         utterance_end_ms=500)
    query = parse_qs(urlsplit(url).query)
    assert query["model"] == ["nova-3"] and query["language"] == ["multi"]
    assert query["encoding"] == ["linear16"] and query["sample_rate"] == ["16000"]
    assert query["interim_results"] == ["true"] and query["smart_format"] == ["true"]
    assert query["vad_events"] == ["true"] and query["endpointing"] == ["100"]
    assert query["utterance_end_ms"] == ["1000"]  # REQ-02 floor
    assert query["keyterm"] == ["C#", "Node.js"]
    assert "token" not in url.lower()


def test_keyterms_put_the_cv_first_dedupe_and_cap_at_the_limit():
    context = InterviewContext(
        job_title="Senior React Developer",
        job_posting="We use React, TypeScript and Node.js.\n- Kubernetes and AWS (S3)\nNice to have: C#.",
        skills=["Languages: Python, TypeScript, SQL", "Backend: FastAPI (async), REST APIs"],
    )
    terms = derive_keyterms(context)
    assert terms[:5] == ["Python", "TypeScript", "SQL", "FastAPI", "REST APIs"]
    for term in ("React", "Node.js", "Kubernetes", "AWS", "S3", "C#"):
        assert term in terms
    assert len({t.casefold() for t in terms}) == len(terms)
    assert "We" not in terms and "Senior" not in terms
    assert derive_keyterms(context, limit=3) == ["Python", "TypeScript", "SQL"]
    assert derive_keyterms(None) == []


def test_a_huge_posting_stays_fast_and_bounded():
    context = InterviewContext(job_posting="Python, Docker and AWS. " * 800)
    started = time.monotonic()
    terms = derive_keyterms(context)
    assert time.monotonic() - started < 0.5
    assert terms == ["Python", "Docker", "AWS"]


# --- Against the fake Deepgram -------------------------------------------------


def session_for(base: str, keyterms=("FastAPI",), **kwargs) -> DeepgramLiveSession:
    url = build_live_url(base, list(keyterms), endpointing_ms=100, utterance_end_ms=1000)
    return DeepgramLiveSession(url, "test-key", **kwargs)


async def collect(session: DeepgramLiveSession) -> list[SttEvent]:
    return [event async for event in session.events()]


def test_a_session_forwards_audio_and_relays_events_until_close_stream():
    fake = FakeDeepgram(answer([SAMPLES["SpeechStarted"][0], SAMPLES["Results"][1]], after_frames=2))

    async def body(base):
        session = session_for(base)
        await session.open()
        events = asyncio.create_task(collect(session))
        for _ in range(3):
            await session.send_audio(FRAME)
            await asyncio.sleep(0.02)
        await session.finish()
        result = await asyncio.wait_for(events, 5)
        await session.close()
        return result, session

    events, session = asyncio.run(with_fake(fake, body))
    [conn] = fake.connections
    query = parse_qs(urlsplit(conn["path"]).query)
    assert query["model"] == ["nova-3"] and query["keyterm"] == ["FastAPI"]
    assert conn["headers"]["Authorization"] == "Token test-key"
    assert bytes(conn["audio"]) == FRAME * 3
    assert conn["texts"] == [{"type": "CloseStream"}]
    assert events == [SttEvent("speech_start", start=1.1), SttEvent("partial", "Tell me about a project", 0.96, 1.52)]
    assert session.audio_seconds == pytest.approx(0.3)


def test_keepalive_is_sent_while_no_audio_arrives():
    fake = FakeDeepgram(answer())

    async def body(base):
        session = session_for(base, keepalive_s=0.2)
        await session.open()
        events = asyncio.create_task(collect(session))
        await asyncio.sleep(0.7)
        await session.finish()
        await asyncio.wait_for(events, 5)
        await session.close()

    asyncio.run(with_fake(fake, body))
    texts = fake.connections[0]["texts"]
    assert {"type": "KeepAlive"} in texts and texts[-1] == {"type": "CloseStream"}


def test_one_reconnection_keeps_the_session_clock():
    after = [{"type": "SpeechStarted", "channel": [0, 1], "timestamp": 0.25}]
    fake = FakeDeepgram(answer(drop_after_frames=5), answer(after, after_frames=1))

    async def body(base):
        session = session_for(base)
        await session.open()
        events = asyncio.create_task(collect(session))
        for _ in range(5):
            await session.send_audio(FRAME)
        for _ in range(100):  # until the drop is seen and the new connection is up
            if session.reconnected and session._ws is not None:
                break
            await asyncio.sleep(0.02)
        for _ in range(2):
            await session.send_audio(FRAME)
            await asyncio.sleep(0.02)
        await session.finish()
        result = await asyncio.wait_for(events, 5)
        await session.close()
        return result

    events = asyncio.run(with_fake(fake, body))
    assert len(fake.connections) == 2
    # Deepgram restarts at 0 on the new connection; 0.5 s were sent before it.
    assert events == [SttEvent("speech_start", start=0.75)]


def test_a_second_drop_ends_the_session():
    fake = FakeDeepgram(answer(drop_after_frames=1), answer(drop_after_frames=1))

    async def body(base):
        session = session_for(base)
        await session.open()
        events = asyncio.create_task(collect(session))
        for _ in range(40):
            await session.send_audio(FRAME)
            await asyncio.sleep(0.02)
            if events.done():
                break
        with pytest.raises(SttUnavailable, match="dropped_after_reconnect"):
            await asyncio.wait_for(events, 5)
        await session.close()

    asyncio.run(with_fake(fake, body))
    assert len(fake.connections) == 2


def test_a_rejected_handshake_reports_the_status_only():
    fake = FakeDeepgram(reject=lambda request: http.HTTPStatus.UNAUTHORIZED)

    async def body(base):
        with pytest.raises(SttUnavailable) as caught:
            await session_for(base).open()
        return str(caught.value)

    assert asyncio.run(with_fake(fake, body)) == "http_401"


def test_an_unreachable_provider_fails_fast():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    async def body():
        started = time.monotonic()
        with pytest.raises(SttUnavailable):
            await session_for(f"ws://127.0.0.1:{port}/v1/listen", connect_timeout_s=1.0).open()
        return time.monotonic() - started

    assert asyncio.run(body()) < 2


def test_a_provider_that_never_answers_times_out():
    async def silent(reader, writer):
        await asyncio.sleep(5)

    async def body():
        server = await asyncio.start_server(silent, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        started = time.monotonic()
        try:
            with pytest.raises(SttUnavailable, match="TimeoutError"):
                await session_for(f"ws://127.0.0.1:{port}/v1/listen", connect_timeout_s=0.3).open()
        finally:
            server.close()
        return time.monotonic() - started

    assert asyncio.run(body()) < 2


def test_rejected_keyterms_fall_back_to_a_session_without_them():
    fake = FakeDeepgram(answer(), reject=lambda r: http.HTTPStatus.BAD_REQUEST if "keyterm=" in r.path else None)

    async def body(base):
        settings = Settings(DEEPGRAM_API_KEY="test-key", DEEPGRAM_LIVE_URL=base)
        session = await open_deepgram_session(["FastAPI"], settings)
        await session.finish()
        await session.close()

    asyncio.run(with_fake(fake, body))
    assert len(fake.requests) == 2
    assert "keyterm=" in fake.requests[0] and "keyterm=" not in fake.requests[1]


def test_without_a_key_nothing_is_dialed():
    with pytest.raises(SttUnavailable, match="missing_key"):
        asyncio.run(open_deepgram_session([], Settings(DEEPGRAM_API_KEY="  ")))
