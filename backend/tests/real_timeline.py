"""Helpers over fixtures/deepgram_turns_real.json: a real Deepgram Nova-3
session of the CS-0 interviewer script (provenance inside the file)."""

import json
from pathlib import Path

REAL = json.loads((Path(__file__).parent / "fixtures" / "deepgram_turns_real.json").read_text(encoding="utf-8"))
SPANS = {span["id"]: span for span in REAL["spans"]}
ORDER = [span["id"] for span in REAL["spans"]]
# What the interviewer says, grouped as REQ-04 v1.1 must join it: each
# backchannel ("Okay, great.") is followed within 1 s by the next question.
GROUPS = [["Q1"], ["Q2"], ["B1", "Q3"], ["Q4"], ["Q5"], ["Q6"], ["Q7"], ["B2", "Q8"], ["Q9"], ["Q10"]]
MARGIN_S = 0.5


def window(ids: list[str]) -> list[dict]:
    """The provider messages that arrived while these spans were spoken,
    up to just before the next span starts."""
    first, last = SPANS[ids[0]], SPANS[ids[-1]]
    nxt = ORDER.index(ids[-1]) + 1
    until = SPANS[ORDER[nxt]]["start"] - MARGIN_S if nxt < len(ORDER) else float("inf")
    return [e["msg"] for e in REAL["events"] if first["start"] - MARGIN_S <= e["t"] < until]


def spoken_text(ids: list[str]) -> str:
    """Everything Deepgram finalised for these spans, straight from the raw
    messages (independent of the turn detector)."""
    first, last = SPANS[ids[0]], SPANS[ids[-1]]
    parts = []
    for event in REAL["events"]:
        msg = event["msg"]
        if msg.get("type") != "Results" or not msg.get("is_final"):
            continue
        alt = msg["channel"]["alternatives"][0]
        words = alt.get("words") or []
        if alt.get("transcript") and words and first["start"] - MARGIN_S <= words[0]["start"] <= last["end"] + MARGIN_S:
            parts.append(alt["transcript"].strip())
    return " ".join(parts)


def all_messages() -> list[dict]:
    return [e["msg"] for e in REAL["events"]]
