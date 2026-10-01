"""Turn and question detection (C2-SPEC-01 REQ-04 + v1.1, AC-13).

The CS-0 timelines replay Deepgram Nova-3 messages for the benchmark script
(fixtures/deepgram_cs0_turns.json, provenance inside) through the real
parser and the detector, exactly as a live session does.
"""

import json
from pathlib import Path

import pytest

from app.services.stt_stream import SttEvent, parse_deepgram
from app.services.turn_detector import TurnDetector, is_question

FIXTURES = Path(__file__).parent / "fixtures"
CS0 = json.loads((FIXTURES / "deepgram_cs0_turns.json").read_text(encoding="utf-8"))


def replay(messages: list[dict], detector: TurnDetector | None = None) -> tuple[list[dict], TurnDetector]:
    detector = detector or TurnDetector()
    out: list[dict] = []
    for message in messages:
        for event in parse_deepgram(message):
            out.extend(detector.feed(event))
    return out, detector


def turns(out: list[dict]) -> list[dict]:
    return [m for m in out if m["type"] == "turn"]


# --- is_question --------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Tell me about a project you're proud of.",
        "Can you walk me through",
        "So in your last project, how did you handle a production incident with PostgreSQL",
        "Walk me through your resume.",
        "Describe a time you disagreed with your manager.",
        "Okay. Great. What's the difference between useEffect and useLayoutEffect and React?",
        "Cuéntame un proyecto del que te sientas orgulloso.",
        "¿Cómo manejarías?",
        "Háblame de tu experiencia con GitHub Actions, like how you set up the site pipeline.",
        "Platícame de tu último trabajo.",
        "como manejarias la cache en redis",
        "Explícame qué es un closure.",
        "I'd like to know more about your experience with React.",
        "Me gustaría saber más de tu experiencia con Python.",
        "Dime un ejemplo de un bug difícil.",
    ],
)
def test_questions_and_interview_prompts_are_detected(text):
    assert is_question(text)


@pytest.mark.parametrize(
    "text",
    ["Okay. Great.", "Perfecto, gracias.", "Trabajé como desarrollador en Puebla.", "That makes sense.",
     "Great, thanks for sharing.", "Muy bien, que bueno.", ""],
)
def test_backchannels_and_statements_are_not_questions(text):
    assert not is_question(text)


# --- AC-13: real CS-0 cuts end in one turn with the whole question -------------


@pytest.mark.parametrize("name", ["Q2", "Q7"])
def test_a_question_cut_mid_sentence_ends_as_one_turn_with_the_full_text(name):
    out, detector = replay(CS0["timelines"][name])
    sent = turns(out)
    # The cut closed a turn first (the suggestion may start on it)...
    assert len(sent) == 2 and sent[0]["is_question"]
    # ...then the rest of the question continued it: same id, full text, so
    # the browser replaces that suggestion instead of showing a second one.
    assert {t["turn_id"] for t in sent} == {1}
    assert sent[-1]["text"] == CS0["expected"][name]
    assert sent[-1]["is_question"]
    assert (detector.turns, detector.questions) == (1, 1)


def test_the_filler_is_what_bridges_q2():
    """Q2's rest starts 2.5 s after the cut; only the untranscribed "um"
    (SpeechStarted) inside the window makes it a continuation."""
    without_filler = [m for m in CS0["timelines"]["Q2"]
                      if not (m["type"] == "SpeechStarted" and m["timestamp"] == 9.19)]
    sent = turns(replay(without_filler)[0])
    assert [t["turn_id"] for t in sent] == [1, 2]


def test_a_backchannel_joins_the_question_that_follows():
    sent = turns(replay(CS0["timelines"]["B1+Q3"])[0])
    assert [(t["turn_id"], t["is_question"]) for t in sent] == [(1, False), (1, True)]
    assert sent[-1]["text"] == CS0["expected"]["B1+Q3"]


def test_the_whole_script_keeps_separate_questions_apart():
    messages = [m for name in ("Q1", "Q2", "B1+Q3", "Q7") for m in CS0["timelines"][name]]
    out, detector = replay(messages)
    last_by_id: dict[int, dict] = {}
    for turn in turns(out):
        last_by_id[turn["turn_id"]] = turn
    assert [t["text"] for t in last_by_id.values()] == [
        CS0["expected"][name] for name in ("Q1", "Q2", "B1+Q3", "Q7")
    ]
    assert all(t["is_question"] for t in last_by_id.values())
    assert (detector.turns, detector.questions) == (4, 4)


def test_partial_and_final_text_carry_the_turn_id():
    out, _ = replay(CS0["timelines"]["Q2"])
    assert out[0] == {"type": "partial", "text": "Can you walk", "turn_id": 1}
    assert {"type": "final", "text": "Can you walk me through", "turn_id": 1} in out
    # The continuation's text belongs to the same turn on screen.
    assert {"type": "partial", "text": "how you", "turn_id": 1} in out
    # The filler's empty endpoint produced nothing.
    assert all(m["text"] for m in out if m["type"] != "partial")


# --- Synthetic edges ------------------------------------------------------------


def ev(kind, text="", start=None, end=None):
    return SttEvent(kind, text, start, end)


def say(detector, text, start, end, close=True):
    out = detector.feed(ev("partial", text, start, end))
    out += detector.feed(ev("final", text, start, end))
    if close:
        out += detector.feed(ev("turn_end", end=end + 0.1))
    return out


def test_a_new_question_after_a_long_pause_is_a_new_turn():
    detector = TurnDetector()
    first = turns(say(detector, "What is a closure?", 0.0, 1.5))
    second = turns(say(detector, "How do you test React hooks?", 5.6, 7.5))
    assert [first[0]["turn_id"], second[0]["turn_id"]] == [1, 2]


def test_noise_right_after_a_question_does_not_glue_the_next_one():
    detector = TurnDetector()
    say(detector, "What is a closure?", 0.0, 1.5)
    detector.feed(ev("speech_start", start=2.0))  # a cough inside the window
    later = turns(say(detector, "Next question: why React?", 30.0, 32.0))
    assert later[0]["turn_id"] == 2


def test_a_filler_followed_too_late_does_not_continue():
    detector = TurnDetector(continuation_s=1.5, filler_s=1.0)
    say(detector, "Can you walk me through", 0.0, 1.0)  # closes at 1.1
    detector.feed(ev("speech_start", start=2.0))
    late = turns(say(detector, "how you would design it?", 4.6, 6.0))  # 2.6 s after the filler
    assert late[0]["turn_id"] == 2


def test_a_chain_of_cuts_is_one_question():
    detector = TurnDetector()
    out = say(detector, "¿Cómo manejarías?", 0.0, 1.0)
    out += say(detector, "Este,", 2.3, 2.6)
    out += say(detector, "la caché con Redis en una API de alto tráfico?", 3.5, 6.0)
    sent = turns(out)
    assert {t["turn_id"] for t in sent} == {1}
    assert sent[-1]["text"] == "¿Cómo manejarías? Este, la caché con Redis en una API de alto tráfico?"
    assert (detector.turns, detector.questions) == (1, 1)


def test_unstable_text_that_never_became_final_is_cleared_and_forgotten():
    detector = TurnDetector()
    say(detector, "What is a closure?", 0.0, 1.5)
    assert detector.feed(ev("partial", "uh", 2.0, 2.2)) == [{"type": "partial", "text": "uh", "turn_id": 1}]
    assert detector.feed(ev("turn_end", end=2.4)) == [{"type": "partial", "text": "", "turn_id": 1}]
    later = turns(say(detector, "How do you test hooks?", 20.0, 21.5))
    assert later[0]["turn_id"] == 2 and later[0]["text"] == "How do you test hooks?"


def test_utterance_end_closes_a_turn_when_speech_final_never_came():
    detector = TurnDetector()
    detector.feed(ev("final", "Describe your last project.", 0.0, 1.8))
    [turn] = detector.feed(ev("turn_end", end=2.8))
    assert turn["is_question"] and turn["text"] == "Describe your last project."
    assert detector.feed(ev("turn_end", end=2.9)) == []  # a second end signal is a no-op


def test_flush_closes_the_turn_still_open_when_the_session_stops():
    detector = TurnDetector()
    detector.feed(ev("final", "Why do you want this job?", 0.0, 1.5))
    assert detector.flush() == [
        {"type": "turn", "text": "Why do you want this job?", "is_question": True, "turn_id": 1}
    ]
    assert detector.flush() == []


def test_a_runaway_continuation_keeps_only_the_latest_text():
    detector = TurnDetector(max_chars=40)
    say(detector, "Our company builds payment software for banks.", 0.0, 3.0)
    [turn] = turns(say(detector, "How would you scale it?", 3.5, 5.0))
    assert len(turn["text"]) <= 40 and turn["text"].endswith("How would you scale it?")
