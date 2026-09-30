"""Pure parts of the CS-0 STT benchmark (no network, no audio services)."""

import array

from scripts.stt_benchmark import (
    SCRIPT,
    SAMPLE_RATE,
    ItemSpan,
    Score,
    Turn,
    build_timeline,
    decide,
    flux_turns,
    is_question,
    score,
    simulate_nova_turns,
)


def _tone(seconds: float) -> array.array:
    return array.array("h", [1000] * int(seconds * SAMPLE_RATE))


def _spans():
    audio = {(item["id"], i): _tone(0.5) for item in SCRIPT for i, _ in enumerate(item["segments"])}
    return build_timeline(audio)


def test_timeline_keeps_scripted_pauses_and_chains_next_starts():
    pcm, spans = _spans()
    q2 = next(s for s in spans if s.id == "Q2")
    # three 0.5 s segments + 1.2 s + 0.9 s of mid-question pauses
    assert round(q2.end - q2.start, 2) == round(1.5 + 1.2 + 0.9, 2)
    b1 = next(s for s in spans if s.id == "B1")
    assert not b1.question and round(b1.next_start - b1.end, 2) == 1.0
    assert all(a.next_start == b.start for a, b in zip(spans, spans[1:]))
    assert sum(s.question for s in spans) == 10
    assert len(pcm) / SAMPLE_RATE > spans[-1].end


def test_question_signals_in_english_and_spanish():
    assert is_question("Can you walk me through,")
    assert is_question("Cuéntame de algún proyecto")
    assert is_question("¿Por qué quieres trabajar con nosotros?")
    assert not is_question("Okay, great.")
    assert not is_question("Perfecto, gracias.")


def _results(t, text, final=True, speech_final=False, start=0.0, end=0.5):
    words = [{"start": start, "end": end}] if text else []
    return {"t": t, "msg": {"type": "Results", "is_final": final, "speech_final": speech_final,
                            "channel": {"alternatives": [{"transcript": text, "words": words}]}}}


def test_mid_question_pause_is_a_premature_cut_for_the_heuristic():
    span = ItemSpan("Q2", True, start=1.0, end=5.0)
    events = [
        _results(2.2, "Can you walk me through,", speech_final=True, start=1.0, end=2.0),
        _results(5.2, "how you would design a rate limiter?", speech_final=True, start=4.0, end=5.0),
    ]
    turns = simulate_nova_turns(events, use_speech_final=True)
    result = score(turns, [span], "")
    assert result.premature_cuts == 1 and result.questions_cut == ["Q2"]
    assert result.closed == 1 and round(result.latencies[0], 2) == 0.2


def test_short_backchannel_merges_with_the_next_turn():
    events = [
        _results(1.2, "Okay, great.", speech_final=True, start=0.5, end=1.0),
        _results(2.0, "What is", final=False),
        _results(3.3, "What is React?", speech_final=True, start=1.9, end=3.0),
    ]
    turns = simulate_nova_turns(events, use_speech_final=True)
    assert [t.text for t in turns] == ["Okay, great. What is React?"]


def test_lone_backchannel_is_released_after_the_wait():
    turns = simulate_nova_turns([_results(1.2, "Okay, great.", speech_final=True, start=0.5, end=1.0)],
                                use_speech_final=True)
    assert [(t.at, t.text) for t in turns] == [(1.2 + 1.5, "Okay, great.")]


def test_flux_turns_and_scoring_with_eager_events():
    evs = [
        {"t": 4.8, "msg": {"type": "TurnInfo", "event": "EagerEndOfTurn", "transcript": "Q"}},
        {"t": 5.4, "msg": {"type": "TurnInfo", "event": "EndOfTurn", "transcript": "Question?"}},
    ]
    result = score(flux_turns(evs), [ItemSpan("Q1", True, 1.0, 4.5, next_start=9.0)], "useEffect")
    assert result.closed == 1 and result.premature_cuts == 0
    assert round(result.latencies[0], 2) == 0.9 and round(result.eager_latencies[0], 2) == 0.3
    assert result.terms_ok == 1  # only "useEffect" appears in the text


def test_decision_rule_needs_all_three_conditions():
    a = Score(closed=8, questions=10, premature_cuts=3, latencies=[1.2, 1.4], terms_ok=6, terms_total=8)
    b = Score(closed=10, questions=10, premature_cuts=0, latencies=[0.6, 0.8], terms_ok=7, terms_total=8)
    assert decide(a, b)[0] == "B"
    worse_terms = Score(**{**b.__dict__, "terms_ok": 5})
    assert decide(a, worse_terms)[0] == "A"
    assert Score.pct([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0 and Score.pct([], 0.5) is None
