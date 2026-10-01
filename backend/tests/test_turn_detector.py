"""Turn and question detection (C2-SPEC-01 REQ-04 + v1.1, AC-13).

AC-13 runs on a REAL Deepgram Nova-3 session of the CS-0 interviewer script
(fixtures/deepgram_turns_real.json, captured on 30 Sep 2026 in PR #18),
replayed through the real parser and the detector exactly as a live session
does. The expected text of each question comes straight from Deepgram's own
final transcripts, not from the detector.
"""

import pytest

from app.services.stt_stream import SttEvent, parse_deepgram
from app.services.turn_detector import TurnDetector, is_question
from real_timeline import GROUPS, all_messages, spoken_text, window


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


# --- AC-13 on real Deepgram events -------------------------------------------------


@pytest.mark.parametrize("name", ["Q2", "Q4", "Q7"])
def test_a_question_cut_mid_sentence_ends_as_one_turn_with_the_full_text(name):
    out, detector = replay(window([name]))
    sent = turns(out)
    # Nova-3 really cut it: a turn closed before the question was over...
    assert len(sent) >= 2 and sent[0]["text"] != sent[-1]["text"]
    # ...and every piece continued it under ONE id, so the browser restarts a
    # single suggestion with the whole question (never two cards).
    assert {t["turn_id"] for t in sent} == {1}
    assert sent[-1]["text"] == spoken_text([name])
    assert sent[-1]["is_question"]
    assert (detector.turns, detector.questions) == (1, 1)


def test_the_real_session_yields_one_turn_per_question_with_all_its_words():
    out, detector = replay(all_messages())
    last_by_id: dict[int, dict] = {}
    for turn in turns(out):
        last_by_id[turn["turn_id"]] = turn
    assert [t["text"] for t in last_by_id.values()] == [spoken_text(group) for group in GROUPS]
    assert all(t["is_question"] for t in last_by_id.values())
    assert (detector.turns, detector.questions) == (10, 10)


def test_the_filler_is_what_bridges_q2():
    """Q2's rest starts 1.7 s after the cut. Deepgram reports the "um" it does
    not transcribe (SpeechStarted 8.84, empty endpoint at 9.19); that speech
    is what keeps the question in one piece."""
    def is_filler(message):
        if message["type"] == "SpeechStarted":
            return message["timestamp"] == 8.84
        return message["type"] == "Results" and message["start"] == 7.79 and message.get("speech_final") \
            and not message["channel"]["alternatives"][0]["transcript"]

    messages = window(["Q2"])
    assert sum(map(is_filler, messages)) == 2
    sent = turns(replay([m for m in messages if not is_filler(m)])[0])
    assert [t["turn_id"] for t in sent] == [1, 2]


def test_a_backchannel_joins_the_question_that_follows():
    sent = turns(replay(window(["B1", "Q3"]))[0])
    assert [(t["turn_id"], t["is_question"]) for t in sent] == [(1, False), (1, True)]
    assert sent[-1]["text"] == spoken_text(["B1", "Q3"])


def test_partial_and_final_text_carry_the_turn_id():
    out, _ = replay(window(["Q2"]))
    assert {"type": "final", "text": "Can you walk me through", "turn_id": 1} in out
    # The continuation's text belongs to the same turn on screen.
    assert {"type": "partial", "text": "how you would", "turn_id": 1} in out
    assert all(m["turn_id"] == 1 for m in out)
    # Empty endpoints and silence produce nothing.
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
    detector = TurnDetector(continuation_s=1.5)
    say(detector, "Can you walk me through", 0.0, 1.0)  # closes at 1.1
    detector.feed(ev("speech_start", start=2.0))
    late = turns(say(detector, "how you would design it?", 4.6, 6.0))  # 2.6 s after the filler
    assert late[0]["turn_id"] == 2


def test_a_cough_inside_the_window_cannot_reach_a_question_seconds_later():
    """Review of PR #17: the window must not stretch to 4 s after a close."""
    detector = TurnDetector(continuation_s=1.5)
    say(detector, "What is a closure?", 8.0, 9.9)  # closes at 10.0
    detector.feed(ev("speech_start", start=11.5))  # a cough, right at the edge
    sent = turns(say(detector, "Next question: how do you test React hooks?", 13.99, 16.0))
    assert sent[0]["turn_id"] == 2


def test_a_filler_chain_restarts_the_window_where_the_filler_ends():
    detector = TurnDetector(continuation_s=1.5)
    say(detector, "Can you walk me through", 6.85, 7.95)  # closes at 8.05
    detector.feed(ev("speech_start", start=9.19))  # "um" starts 1.14 s later
    detector.feed(ev("turn_end", end=9.70))  # ...and ends: no words
    detector.feed(ev("speech_start", start=10.5))  # 0.8 s after the filler
    sent = turns(say(detector, "how you would design a rate limiter?", 10.54, 13.3))
    assert sent[0]["turn_id"] == 1
    assert sent[0]["text"] == "Can you walk me through how you would design a rate limiter?"


def test_a_late_end_signal_does_not_cut_the_continuation():
    """Review of PR #17: an end about earlier speech must not close newer words."""
    detector = TurnDetector()
    say(detector, "¿Cómo manejarías?", 50.05, 51.0)  # closes at 51.1
    detector.feed(ev("final", "Este, la caché con Redis", 52.4, 54.6))
    assert detector.feed(ev("utterance_end", start=51.0, end=52.0)) == []  # about "manejarías?"
    assert detector.feed(ev("turn_end", end=52.0)) == []  # an endpoint before these words
    detector.feed(ev("final", "en una API de alto tráfico?", 54.6, 56.25))
    [turn] = detector.feed(ev("turn_end", end=56.4))
    assert turn["turn_id"] == 1
    assert turn["text"] == "¿Cómo manejarías? Este, la caché con Redis en una API de alto tráfico?"


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
    [turn] = detector.feed(ev("utterance_end", start=1.8, end=2.8))
    assert turn["is_question"] and turn["text"] == "Describe your last project."
    assert detector.feed(ev("turn_end", end=2.9)) == []  # a second end signal is a no-op


def test_an_utterance_end_never_ends_a_filler():
    """Re-review N1(a): UtteranceEnd about the cut's last word arrives while
    the "um" is still going on; the um's own endpoint must still count."""
    detector = TurnDetector()
    say(detector, "Can you walk me through", 6.38, 7.42)  # closes at 7.52
    detector.feed(ev("speech_start", start=8.10))  # "um"
    detector.feed(ev("utterance_end", start=7.42, end=8.42))  # about "through"
    detector.feed(ev("turn_end", end=8.90))  # the um's empty endpoint
    sent = turns(say(detector, "how you would design it?", 10.10, 11.5))
    assert sent[0]["turn_id"] == 1


def test_a_late_speech_start_about_earlier_speech_is_ignored():
    """Re-review N1(b): a SpeechStarted dated before the close (Deepgram sent
    one 1.96 s late in the real Q3) must not move the window."""
    detector = TurnDetector()
    say(detector, "What's the difference between useEffect and useLayoutEffect?", 17.75, 22.22)  # 22.32
    detector.feed(ev("speech_start", start=20.26))  # arrives after the close
    detector.feed(ev("utterance_end", start=22.22, end=23.22))
    # Words 1.2 s after the close still continue the turn...
    sent = turns(say(detector, "in React?", 23.5, 24.0))
    assert sent[0]["turn_id"] == 1
    # ...and a new question after a real pause is still a new turn.
    later = turns(say(detector, "So in your last project, how did you handle it?", 27.4, 30.0))
    assert later[0]["turn_id"] == 2


def test_two_noises_cannot_carry_a_new_question_into_the_old_turn():
    """Re-review N2: only one word-less burst may bridge a pause."""
    detector = TurnDetector()
    say(detector, "What is a closure?", 8.0, 9.9)  # closes at 10.0
    detector.feed(ev("speech_start", start=11.0))
    detector.feed(ev("turn_end", end=11.3))
    detector.feed(ev("speech_start", start=12.6))
    detector.feed(ev("turn_end", end=12.9))
    sent = turns(say(detector, "How do you test React hooks?", 14.4, 16.0))
    assert sent[0]["turn_id"] == 2


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
