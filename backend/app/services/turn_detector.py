"""Turns and questions for the live interview copilot (C2-SPEC-01 REQ-04, v1.1).

Pure: no I/O and no clock. It consumes the provider-neutral events of
`app.services.stt_stream` (times in seconds of session audio) and returns
the messages the live WebSocket sends to the browser:

    {"type": "partial", "text", "turn_id"}                 unstable text
    {"type": "final",   "text", "turn_id"}                 one stable segment
    {"type": "turn",    "text", "is_question", "turn_id"}  a closed turn

Rules:
- A turn closes on the first end-of-speech signal (speech_final or
  UtteranceEnd) once it has stable text.
- Continuation (v1.1): speech that starts within `continuation_s` after a
  turn closes joins that turn. The joined turn is sent again with the SAME
  `turn_id` and the full text, so the browser cancels the suggestion in
  flight and restarts it with the whole question: one card, never two.
- This also covers REQ-04's join rule (a short turn without a question
  signal, followed within 1.5 s by more speech, joins the next one). Such a
  turn starts no suggestion, so it can be sent at once and joined later.
- Speech without words counts as speech. A filler such as "um" is usually
  not transcribed, but the provider reports when it starts and ends. If it
  starts within `continuation_s` of the close, it joins the turn and the
  window restarts where it ends: the chained reading of v1.1 ("Can you walk
  me through, um, how you would design…"). A cough far from the next
  question cannot glue two questions, because every gap in the chain must
  stay within `continuation_s`.
- `is_question` reads English and Spanish signals: question marks,
  interrogative words and interview imperatives ("tell me about",
  "cuéntame", "walk me through"…).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --- Question signals (REQ-04) -------------------------------------------------

_EN_WH = r"what|how|why|when|where|which|who|whom|whose"
_EN_AUX = (
    r"(?:can|could|would|will|do|did|does|have|has|are|is|were|was|should)"
    r"\s+(?:you|we|i|they|there|it)"
)
_EN_ASK = (
    r"tell me|tell us|walk me through|walk us through|talk me through|take me through|"
    r"describe|explain|give me an example|share an example|what about|how about|"
    r"(?:like|love) to (?:know|hear)|curious (?:about|to know)|interested in hearing"
)
_ES_WH = (
    r"qué|cómo|cuál|cuáles|cuándo|dónde|quién|quiénes|por qué|para qué|"
    r"cuánto|cuántos|cuánta|cuántas"
)
_ES_ASK = (
    r"cuéntame|cuéntanos|cuentame|cuentanos|háblame|háblanos|hablame|hablanos|"
    r"platícame|platícanos|platicame|platicanos|descríbeme|descríbenos|describe|"
    r"explícame|explícanos|explicame|explica|dame un ejemplo|danos un ejemplo|menciona|"
    r"dime|compárteme|compártenos|me gustaría saber|quisiera saber|me interesa saber"
)
# Without accents these are everyday words ("trabajé como…"), so they count
# only when they open a sentence.
_ES_PLAIN = r"que|como|cual|cuales|cuando|donde|quien|por que"

_SIGNAL = re.compile(
    rf"\b(?:{_EN_WH}|{_EN_ASK}|{_ES_WH}|{_ES_ASK})\b|\b{_EN_AUX}\b", re.IGNORECASE
)
_PLAIN_OPENER = re.compile(rf"^(?:{_ES_PLAIN})\b", re.IGNORECASE)
_SENTENCES = re.compile(r"[.!;:]\s*")


def is_question(text: str) -> bool:
    """True when the turn reads as a question or an interview prompt."""
    text = text.strip()
    if not text:
        return False
    if "?" in text or "¿" in text or _SIGNAL.search(text):
        return True
    return any(
        _PLAIN_OPENER.match(sentence.strip(" ,¡\"'-–—")) for sentence in _SENTENCES.split(text)
    )


# --- Turns ---------------------------------------------------------------------


@dataclass
class _Turn:
    turn_id: int
    first_start: float | None  # first word of THIS segment of speech
    prefix: str = ""  # text of the turn this one continues
    finals: list[str] = field(default_factory=list)


def _tail(text: str, limit: int) -> str:
    """Keep the last `limit` characters (the question is usually at the end)."""
    if len(text) <= limit:
        return text
    cut = text[-limit:]
    return cut.split(" ", 1)[1] if " " in cut else cut


class TurnDetector:
    """Stateful, deterministic turn detector for one live session."""

    def __init__(self, continuation_s: float = 1.5, max_chars: int = 4000) -> None:
        self.continuation_s = continuation_s
        self.max_chars = max_chars  # /api/interview/text accepts up to 4000
        self.turns = 0  # closed turns (a continuation counts once)
        self.questions = 0
        self._next_id = 1
        self._open: _Turn | None = None
        self._last: dict[str, Any] | None = None  # turn_id, text, is_question
        # Latest speech activity of the last turn's chain (its close, then any
        # word-less burst that started within the window), and whether such a
        # burst is still going on.
        self._anchor: float | None = None
        self._bridging = False

    def feed(self, event: Any) -> list[dict]:
        """Process one SttEvent; return the messages for the browser."""
        if event.kind == "speech_start":
            self._speech_started(event.start)
            return []
        if event.kind in ("partial", "final"):
            if not event.text:
                return []
            if self._open is None:
                self._open = self._begin(event.start)
            turn = self._open
            if event.kind == "final":
                turn.finals.append(event.text)
            return [{"type": event.kind, "text": event.text, "turn_id": turn.turn_id}]
        if event.kind == "turn_end":
            if self._open is None:
                self._speech_ended(event.end)
                return []
            return self._close(event.end)
        return []

    def flush(self) -> list[dict]:
        """End of session: close whatever is still open."""
        return self._close(None)

    def _within_window(self, at: float | None) -> bool:
        return at is not None and self._anchor is not None and at - self._anchor <= self.continuation_s

    def _speech_started(self, at: float | None) -> None:
        if self._open is not None or self._last is None or at is None:
            return
        if self._within_window(at):
            self._anchor = max(self._anchor, at)  # type: ignore[arg-type]
            self._bridging = True
        else:
            self._bridging = False  # the pause was long enough: the chain is over

    def _speech_ended(self, at: float | None) -> None:
        """A burst without words ended (e.g. after "um"): the window restarts here."""
        if self._bridging and at is not None and self._anchor is not None and at >= self._anchor:
            self._anchor = at
            self._bridging = False

    def _begin(self, word_start: float | None) -> _Turn:
        self._bridging = False
        last = self._last
        if last is not None and self._within_window(word_start):
            return _Turn(turn_id=last["turn_id"], first_start=word_start, prefix=last["text"])
        turn = _Turn(turn_id=self._next_id, first_start=word_start)
        self._next_id += 1
        return turn

    def _close(self, at: float | None) -> list[dict]:
        turn = self._open
        if turn is None:
            return []
        if at is not None and turn.first_start is not None and at < turn.first_start:
            return []  # a late end signal about earlier speech: this turn stays open
        self._open = None
        self._bridging = False
        if not turn.finals:
            # Only unstable text that never became final (noise revised away):
            # clear it on screen. If it was inside the window it still counts
            # as speech, like a filler.
            if turn.prefix and at is not None and self._anchor is not None:
                self._anchor = max(self._anchor, at)
            return [{"type": "partial", "text": "", "turn_id": turn.turn_id}]
        new_text = " ".join(turn.finals)
        text = _tail(f"{turn.prefix} {new_text}" if turn.prefix else new_text, self.max_chars)
        question = is_question(text)
        continued = bool(turn.prefix)
        if not continued:
            self.turns += 1
        if question and not (continued and self._last and self._last["is_question"]):
            self.questions += 1
        self._last = {"turn_id": turn.turn_id, "text": text, "is_question": question}
        self._anchor = at
        return [{"type": "turn", "text": text, "is_question": question, "turn_id": turn.turn_id}]
