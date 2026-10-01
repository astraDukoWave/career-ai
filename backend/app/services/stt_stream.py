"""Live speech-to-text through a provider adapter (C2-SPEC-01 REQ-02/03).

Per the layered-architecture rule this is a service: it never imports
FastAPI. The live WebSocket route reaches it through
`app.services.live_session`.

- `SttEvent`: what the rest of the app consumes, whatever the provider:
  `speech_start`, `partial`, `final` and `turn_end`, with times in seconds of
  session audio.
- `parse_deepgram()`: Deepgram v1 live messages to `SttEvent`s. Its tests
  replay real Nova-3 messages recorded in the CS-0 benchmark (PR #11).
- `DeepgramLiveSession`: one live Nova-3 `multi` connection (the CS-0
  winner) with NFR-02's resilience: 5 s connect timeout, KeepAlive while no
  audio arrives and ONE automatic reconnection, after which it raises
  `SttUnavailable`.
- `derive_keyterms()`: up to 50 terms from the CV skills and the posting
  (REQ-03), so technical words are transcribed as written.

The Deepgram key travels only in the Authorization header of the server's
own connection. It is never logged and never sent to the browser (AC-12).
Keyterms come from the user's CV, so they are not logged either.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Protocol

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from app.config import Settings
from app.schemas.interview import InterviewContext
from app.services.cv_format import normalize_skills

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
_BYTES_PER_SECOND = SAMPLE_RATE * 2  # linear16 mono


class SttUnavailable(Exception):
    """The provider could not be reached, or dropped twice (EDGE-05).

    The message is a short reason for logs (an exception name or an HTTP
    status), never a URL, a key or user text.
    """


EventKind = Literal["speech_start", "partial", "final", "turn_end"]


@dataclass(frozen=True)
class SttEvent:
    """A provider-neutral speech-to-text event (times: seconds of session audio).

    - speech_start: voice activity began at `start` (fillers like "um"
      produce this even when they are not transcribed).
    - partial: unstable text; `start`/`end` are its first/last word.
    - final: stable text of one segment; `start`/`end` as above.
    - turn_end: the provider detected the end of speech at `end`.
    """

    kind: EventKind
    text: str = ""
    start: float | None = None
    end: float | None = None


class SttSession(Protocol):
    """What `live_session` needs from a provider session."""

    async def send_audio(self, chunk: bytes) -> None: ...

    def events(self) -> AsyncIterator[SttEvent]: ...

    async def finish(self) -> None: ...

    async def close(self) -> None: ...


# Opens a session with these keyterms (raises SttUnavailable).
SttConnector = Callable[[list[str]], Awaitable[SttSession]]


# =============================================================================
# Deepgram v1 live messages -> SttEvent
# =============================================================================


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _shift(value: float | None, offset: float) -> float | None:
    return None if value is None else round(value + offset, 3)


def parse_deepgram(message: dict, *, offset: float = 0.0, utterance_end_s: float = 1.0) -> list[SttEvent]:
    """Normalise one Deepgram live message.

    `offset` moves the connection's clock onto the session clock (after a
    reconnection Deepgram counts from zero again). A turn closed by
    UtteranceEnd ends `utterance_end_s` after the last word: that is when
    Deepgram sends it.
    """
    kind = message.get("type")
    if kind == "Results":
        channel = message.get("channel")
        alternatives = channel.get("alternatives") if isinstance(channel, dict) else None
        best = alternatives[0] if alternatives else {}
        text = str(best.get("transcript") or "").strip()
        words = [w for w in best.get("words") or [] if isinstance(w, dict)]
        start, duration = _num(message.get("start")), _num(message.get("duration"))
        window_end = start + duration if start is not None and duration is not None else None
        events: list[SttEvent] = []
        if text:
            first = _num(words[0].get("start")) if words else start
            last = _num(words[-1].get("end")) if words else window_end
            events.append(
                SttEvent("final" if message.get("is_final") else "partial", text,
                         _shift(first, offset), _shift(last, offset))
            )
        if message.get("is_final") and message.get("speech_final"):
            events.append(SttEvent("turn_end", end=_shift(window_end, offset)))
        return events
    if kind == "UtteranceEnd":
        last_word_end = _num(message.get("last_word_end"))
        end = last_word_end + utterance_end_s if last_word_end is not None else None
        return [SttEvent("turn_end", end=_shift(end, offset))]
    if kind == "SpeechStarted":
        return [SttEvent("speech_start", start=_shift(_num(message.get("timestamp")), offset))]
    return []  # Metadata and anything new


# =============================================================================
# Keyterms (REQ-03)
# =============================================================================

_PARENS = re.compile(r"\s*[(\[{].*?[)\]}]")
_TOKEN = re.compile(r"[A-Za-zÀ-ÿ0-9.#+/_-]+")
_BREAK = re.compile(r"[.!?:;\n•·*–—|]| - ")
_ACRONYM_STOP = {"OK", "CV", "HR", "USA", "MX", "EN", "ES", "LLC", "INC", "SA", "PM", "AM", "TBD", "ASAP"}
# Capitalised words that are grammar, not names (EN/ES posting boilerplate).
_TITLE_STOP = {
    "The", "This", "That", "These", "Our", "We", "You", "Your", "They", "It", "In", "On", "At", "For", "With",
    "And", "Or", "If", "As", "To", "Of", "By", "From", "An", "Be", "Is", "Are", "Will", "Can", "Must",
    "Remote", "Hybrid", "Full", "Part", "Time", "Senior", "Junior", "Mid", "Lead", "Strong", "Good",
    "El", "La", "Los", "Las", "Un", "Una", "En", "Con", "Para", "Por", "De", "Del", "Que", "Se", "Al",
    "Somos", "Buscamos", "Ofrecemos", "Requisitos", "Responsabilidades", "Beneficios", "Requirements",
    "Responsibilities", "Benefits", "About", "Nice", "Plus", "Bonus", "Experience", "Experiencia",
}
# Stack names that are plain capitalised words, so they are kept even at the
# start of a bullet ("- React", "• Python").
_KNOWN_TECH = {
    name.casefold() for name in (
        "React", "Angular", "Vue", "Svelte", "Next", "Nuxt", "Node", "Express", "Nest", "Deno", "Bun",
        "Python", "Django", "Flask", "FastAPI", "Java", "Spring", "Kotlin", "Swift", "Flutter", "Dart",
        "Go", "Golang", "Rust", "Ruby", "Rails", "Elixir", "Scala", "Haskell", "Clojure", "Laravel",
        "Docker", "Kubernetes", "Terraform", "Ansible", "Jenkins", "Linux", "Git", "Redis", "Kafka",
        "Postgres", "Postgresql", "MySQL", "MongoDB", "Supabase", "Firebase", "Azure", "Heroku", "Vercel",
        "Figma", "Jira", "Tailwind", "Redux", "Zustand", "Vite", "Webpack", "Jest", "Vitest", "Playwright",
        "Cypress", "Selenium", "Pandas", "Spark", "Airflow", "Snowflake", "Tableau", "Excel", "Salesforce",
        "Gemini", "OpenAI", "Claude", "LangChain", "Pytorch", "Tensorflow", "Unity", "Unreal", "Shopify",
    )
}


def _is_technical(token: str) -> bool:
    """CamelCase, digits, tech punctuation (Node.js, C#, CI/CD) or an acronym."""
    core = token.strip(".-_/")
    if len(core) < 2 or not re.search(r"[A-Za-z]", core):
        return False
    if any(c.isupper() for c in core[1:]) and any(c.islower() for c in core):
        return True  # TypeScript, PostgreSQL, useEffect, GitHub
    if re.search(r"[A-Za-z]\d|\d[A-Za-z]", core):
        return True  # S3, EC2, K8s, Vue3
    if re.search(r"[A-Za-z0-9][.#+/][A-Za-z0-9#+]|[#+]{1,2}$", core):
        return True  # Node.js, C#, C++, CI/CD
    return core.isupper() and 2 <= len(core) <= 6 and core not in _ACRONYM_STOP


def _posting_terms(text: str) -> list[str]:
    """Technical-looking words and names from the posting, most frequent first.

    A plain capitalised word counts only mid-sentence (at the start it is
    capitalised for grammar) unless it is a known stack name. Adjacent kept
    words form one term ("GitHub Actions", "Google Cloud Platform").
    """
    found: list[str] = []
    phrase: list[str] = []
    last_end, prev_raw = 0, ""
    for match in _TOKEN.finditer(text):
        raw = match.group()
        token = raw.strip(".,")
        gap = text[last_end:match.start()]
        sentence_start = not prev_raw or prev_raw.endswith((".", "!", "?", ":")) or bool(_BREAK.search(gap))
        keep = bool(token) and (
            _is_technical(token)
            or token.casefold() in _KNOWN_TECH
            or (token[:1].isupper() and token[1:].islower() and len(token) > 2
                and token not in _TITLE_STOP and not sentence_start)
        )
        joinable = (bool(phrase) and not gap.strip() and len(phrase) < 3
                    and not prev_raw.endswith((".", ",", ":", ";")))
        if keep and joinable:
            phrase.append(token)
        else:
            if phrase:
                found.append(" ".join(phrase))
            phrase = [token] if keep else []
        last_end, prev_raw = match.end(), raw
    if phrase:
        found.append(" ".join(phrase))
    counts = Counter(term.casefold() for term in found)
    first: dict[str, str] = {}
    for term in found:
        first.setdefault(term.casefold(), term)
    order = {key: index for index, key in enumerate(first)}
    return [first[key] for key in sorted(first, key=lambda k: (-counts[k], order[k]))]


def _clean_term(term: str) -> str | None:
    term = _PARENS.sub("", term).strip(" .,;:-–—*•")
    term = re.sub(r"\s+", " ", term)
    if not (2 <= len(term) <= 40) or len(term.split()) > 4 or not re.search(r"[A-Za-zÀ-ÿ]", term):
        return None
    if ":" in term or "//" in term or "@" in term:
        return None
    return term


def derive_keyterms(context: InterviewContext | None, limit: int = 50) -> list[str]:
    """Up to `limit` distinct terms: the CV's skills first, then the posting's.

    The CV comes first because the interviewer asks about the candidate's own
    stack; the posting adds the company's vocabulary.
    """
    if context is None or limit <= 0:
        return []
    terms: list[str] = []
    seen: set[str] = set()
    candidates = normalize_skills(list(context.skills)).flat + _posting_terms(
        f"{context.job_title}\n{context.job_posting}"
    )
    for raw in candidates:
        term = _clean_term(raw)
        if term and term.casefold() not in seen:
            seen.add(term.casefold())
            terms.append(term)
            if len(terms) == limit:
                break
    return terms


# =============================================================================
# Deepgram live session
# =============================================================================


def build_live_url(base: str, keyterms: list[str], *, endpointing_ms: int, utterance_end_ms: int) -> str:
    """Nova-3 `multi` with REQ-02's parameters (candidate A of the CS-0 benchmark)."""
    params = [
        ("model", "nova-3"),
        ("language", "multi"),
        ("encoding", "linear16"),
        ("sample_rate", str(SAMPLE_RATE)),
        ("channels", "1"),
        ("interim_results", "true"),
        ("utterance_end_ms", str(max(1000, utterance_end_ms))),
        ("endpointing", str(endpointing_ms)),
        ("smart_format", "true"),
        ("punctuate", "true"),
        ("vad_events", "true"),
        ("tag", "careerai-live"),
    ] + [("keyterm", term) for term in keyterms]
    return base + "?" + urllib.parse.urlencode(params)


class DeepgramLiveSession:
    """One live transcription session, with at most one reconnection."""

    def __init__(
        self,
        url: str,
        api_key: str,
        *,
        connect_timeout_s: float = 5.0,
        keepalive_s: float = 4.0,
        utterance_end_s: float = 1.0,
    ) -> None:
        self._url = url
        self._headers = {"Authorization": f"Token {api_key}"}
        self._connect_timeout_s = connect_timeout_s
        self._keepalive_s = keepalive_s
        self._utterance_end_s = utterance_end_s
        self._ws: Any = None
        self._lock: asyncio.Lock | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._received = 0  # audio bytes received from the browser
        self._offset_bytes = 0  # ... before the current connection's first frame
        self._last_send = 0.0
        self._finishing = False
        self._reconnected = False

    @property
    def audio_seconds(self) -> float:
        return self._received / _BYTES_PER_SECOND

    @property
    def reconnected(self) -> bool:
        return self._reconnected

    async def open(self) -> None:
        self._lock = asyncio.Lock()
        self._ws = await self._connect()
        self._last_send = time.monotonic()
        self._keepalive_task = asyncio.create_task(self._keepalive())

    async def _connect(self) -> Any:
        try:
            return await ws_connect(
                self._url,
                additional_headers=self._headers,
                open_timeout=self._connect_timeout_s,
                max_size=2**20,
            )
        except InvalidStatus as err:
            raise SttUnavailable(f"http_{err.response.status_code}") from err
        except (OSError, TimeoutError, WebSocketException) as err:
            raise SttUnavailable(type(err).__name__) from err

    async def send_audio(self, chunk: bytes) -> None:
        """Forward one PCM frame. Frames that arrive while reconnecting are
        dropped but still counted, so the session clock stays true."""
        if not chunk or self._finishing:
            return
        ws = self._ws
        if ws is not None and self._lock is not None:
            try:
                async with self._lock:
                    await ws.send(chunk)
                self._last_send = time.monotonic()
            except ConnectionClosed:
                pass  # events() sees the drop and reconnects
        self._received += len(chunk)

    async def events(self) -> AsyncIterator[SttEvent]:
        while True:
            ws = self._ws
            try:
                async for raw in ws:
                    if isinstance(raw, (bytes, bytearray)):
                        continue
                    try:
                        message = json.loads(raw)
                    except ValueError:
                        continue
                    if not isinstance(message, dict):
                        continue
                    offset = self._offset_bytes / _BYTES_PER_SECOND
                    for event in parse_deepgram(message, offset=offset, utterance_end_s=self._utterance_end_s):
                        yield event
            except ConnectionClosed:
                pass
            if self._finishing:
                return
            # The provider closed on its own (EDGE-05): one reconnection.
            logger.warning("Deepgram live connection dropped (code=%s reason=%s)",
                           getattr(ws, "close_code", None), getattr(ws, "close_reason", None))
            if self._reconnected:
                raise SttUnavailable("dropped_after_reconnect")
            self._reconnected = True
            self._ws = None
            new_ws = await self._connect()
            # Deepgram restarts its clock at the first frame of the new connection.
            self._offset_bytes = self._received
            self._ws = new_ws
            logger.info("Deepgram live connection re-established")

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(self._keepalive_s / 2)
            ws = self._ws
            if ws is None or self._finishing or self._lock is None:
                continue
            if time.monotonic() - self._last_send >= self._keepalive_s:
                try:
                    async with self._lock:
                        await ws.send(json.dumps({"type": "KeepAlive"}))
                    self._last_send = time.monotonic()
                except ConnectionClosed:
                    pass

    async def finish(self) -> None:
        """No more audio: Deepgram flushes the last results, then closes."""
        self._finishing = True
        ws = self._ws
        if ws is not None and self._lock is not None:
            try:
                async with self._lock:
                    await ws.send(json.dumps({"type": "CloseStream"}))
            except ConnectionClosed:
                pass

    async def close(self) -> None:
        self._finishing = True
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001 — closing is best effort
                pass


async def open_deepgram_session(keyterms: list[str], settings: Settings) -> DeepgramLiveSession:
    """Connect to Deepgram for one live session (raises SttUnavailable).

    If Deepgram rejects the request (HTTP 400) and keyterms were sent, it
    retries once without them: a session without keyterms beats no session.
    """
    api_key = settings.DEEPGRAM_API_KEY.strip()
    if not api_key:
        raise SttUnavailable("missing_key")

    async def attempt(terms: list[str]) -> DeepgramLiveSession:
        session = DeepgramLiveSession(
            build_live_url(settings.DEEPGRAM_LIVE_URL, terms,
                           endpointing_ms=settings.STT_ENDPOINTING_MS,
                           utterance_end_ms=settings.STT_UTTERANCE_END_MS),
            api_key,
            connect_timeout_s=settings.STT_CONNECT_TIMEOUT_S,
            keepalive_s=settings.STT_KEEPALIVE_S,
            utterance_end_s=max(1000, settings.STT_UTTERANCE_END_MS) / 1000,
        )
        await session.open()
        return session

    try:
        return await attempt(keyterms)
    except SttUnavailable as err:
        if keyterms and str(err) == "http_400":
            logger.warning("Deepgram rejected the keyterms (http_400); retrying without them")
            return await attempt([])
        raise
