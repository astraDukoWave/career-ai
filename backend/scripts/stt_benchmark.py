#!/usr/bin/env python3
"""Speech-to-text provider benchmark — C2-PLAN-01, CS-0 (spike, not app code).

Decides with data which streaming provider closes interviewer turns best:

    A   Nova-3 (language=multi) + the REQ-04 turn heuristic (the approved spec)
    A2  Nova-3 with conservative endpointing, UtteranceEnd only (informative)
    B   Flux Multilingual (flux-general-multi), model-based end of turn

Runs in GitHub Actions (needs network + DEEPGRAM_API_KEY):
1. Synthesises a 10-question interviewer script (5 EN, 5 ES) with Aura-2 TTS.
2. Builds a realistic fixture: mid-sentence pauses and fillers, a
   code-switched question, light background noise and an Opus round trip at
   ~24 kbps (the codec Meet uses), 16 kHz linear16.
3. Streams the same audio to every candidate at the same time, in real time,
   in 100 ms frames (each frame is sent when it would have been captured).
4. Scores turns closed, premature cuts, latency and technical-term accuracy,
   and writes report.md plus samples.json (raw messages for CS-4 parser
   tests; no audio is ever stored).

The pure parts (fixture timeline, turn simulation, scoring) are unit-tested in
backend/tests/test_stt_benchmark.py without network.
"""

from __future__ import annotations

import argparse
import array
import asyncio
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.parse
import wave
from dataclasses import dataclass, field
from pathlib import Path

SAMPLE_RATE = 16_000
FRAME_S = 0.1
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_S)
GAP_AFTER_QUESTION_S = 4.0
GAP_AFTER_BACKCHANNEL_S = 1.0
LEAD_SILENCE_S = 1.0
TAIL_SILENCE_S = 4.0
NOISE_SNR_DB = 25.0
OPUS_BITRATE = "24k"
VOICES = {"en": "aura-2-asteria-en", "es": "aura-2-celeste-es"}

# id, lang, [(text, pause_after_s)], is_question, technical terms
SCRIPT: list[dict] = [
    {"id": "Q1", "lang": "en", "segments": [("Tell me about a project you're proud of.", 0)]},
    {"id": "Q2", "lang": "en", "segments": [
        ("Can you walk me through,", 1.2), ("um,", 0.9),
        ("how you would design a rate limiter for a public API?", 0)], "pauses": True},
    {"id": "B1", "lang": "en", "segments": [("Okay, great.", 0)], "question": False},
    {"id": "Q3", "lang": "en", "segments": [
        ("What's the difference between useEffect and useLayoutEffect in React?", 0)],
     "terms": ["useEffect", "useLayoutEffect"]},
    {"id": "Q4", "lang": "en", "segments": [
        ("So, in your last project,", 1.0),
        ("how did you handle a production incident with PostgreSQL?", 0)],
     "terms": ["PostgreSQL"], "pauses": True},
    {"id": "Q5", "lang": "en", "segments": [
        ("How would you deploy a FastAPI service to Kubernetes with zero downtime?", 0)],
     "terms": ["FastAPI", "Kubernetes"]},
    {"id": "Q6", "lang": "es", "segments": [("Cuéntame de algún proyecto del que te sientas orgulloso.", 0)]},
    {"id": "Q7", "lang": "es", "segments": [
        ("¿Cómo manejarías,", 1.3), ("este,", 0.8),
        ("la caché con Redis en una API de alto tráfico?", 0)],
     "terms": ["Redis"], "pauses": True},
    {"id": "B2", "lang": "es", "segments": [("Perfecto, gracias.", 0)], "question": False},
    {"id": "Q8", "lang": "es", "segments": [
        ("¿Qué ventajas tiene TypeScript sobre JavaScript en un equipo grande?", 0)],
     "terms": ["TypeScript"]},
    {"id": "Q9", "lang": "es", "segments": [
        ("Háblame de tu experiencia con GitHub Actions, like how you set up the CI pipeline.", 0)],
     "terms": ["GitHub Actions"], "mixed": True},
    {"id": "Q10", "lang": "es", "segments": [("¿Por qué quieres trabajar con nosotros?", 0)]},
]

KEYTERMS = ["useEffect", "useLayoutEffect", "PostgreSQL", "FastAPI", "Kubernetes",
            "Redis", "TypeScript", "GitHub Actions", "React", "CareerAI"]


# =============================================================================
# Fixture timeline (pure)
# =============================================================================

@dataclass
class ItemSpan:
    id: str
    question: bool
    start: float   # first speech sample, seconds
    end: float     # last speech sample, seconds
    next_start: float = math.inf


def trim_silence(pcm: array.array, threshold: int = 300, pad: int = 800) -> array.array:
    """Drop leading/trailing near-silence (10 ms RMS frames), keep 50 ms pad."""
    frame = SAMPLE_RATE // 100
    loud = [
        i for i in range(0, len(pcm), frame)
        if math.sqrt(sum(s * s for s in pcm[i:i + frame]) / max(1, len(pcm[i:i + frame]))) > threshold
    ]
    if not loud:
        return array.array("h")
    first = max(0, loud[0] - pad)
    last = min(len(pcm), loud[-1] + frame + pad)
    return pcm[first:last]


def build_timeline(segment_audio: dict[tuple[str, int], array.array]) -> tuple[array.array, list[ItemSpan]]:
    """Concatenate trimmed segments with scripted pauses and gaps."""
    pcm = array.array("h", [0] * int(LEAD_SILENCE_S * SAMPLE_RATE))
    spans: list[ItemSpan] = []
    for item in SCRIPT:
        start = len(pcm) / SAMPLE_RATE
        for idx, (_, pause) in enumerate(item["segments"]):
            pcm.extend(segment_audio[(item["id"], idx)])
            if pause:
                pcm.extend([0] * int(pause * SAMPLE_RATE))
        end = len(pcm) / SAMPLE_RATE
        spans.append(ItemSpan(item["id"], item.get("question", True), start, end))
        gap = GAP_AFTER_QUESTION_S if item.get("question", True) else GAP_AFTER_BACKCHANNEL_S
        pcm.extend([0] * int(gap * SAMPLE_RATE))
    pcm.extend([0] * int((TAIL_SILENCE_S - GAP_AFTER_QUESTION_S) * SAMPLE_RATE))
    for cur, nxt in zip(spans, spans[1:]):
        cur.next_start = nxt.start
    return pcm, spans


def add_noise(pcm: array.array, snr_db: float = NOISE_SNR_DB, seed: int = 7) -> array.array:
    speech = [s for s in pcm if abs(s) > 300]
    rms = math.sqrt(sum(s * s for s in speech) / max(1, len(speech)))
    sigma = rms / (10 ** (snr_db / 20))
    rng = random.Random(seed)
    return array.array("h", (max(-32768, min(32767, int(s + rng.gauss(0, sigma)))) for s in pcm))


def opus_round_trip(pcm: array.array) -> array.array:
    """Encode to Opus (Meet-like bitrate) and decode back to 16 kHz PCM."""
    with tempfile.TemporaryDirectory() as tmp:
        src, ogg, raw = Path(tmp) / "in.wav", Path(tmp) / "x.ogg", Path(tmp) / "out.raw"
        with wave.open(str(src), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c:a", "libopus",
                        "-b:a", OPUS_BITRATE, str(ogg)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ogg), "-ar", str(SAMPLE_RATE),
                        "-ac", "1", "-f", "s16le", str(raw)], check=True)
        out = array.array("h")
        out.frombytes(raw.read_bytes())
        return out


# =============================================================================
# Turn detection (pure) — A follows REQ-04; B uses the model's EndOfTurn
# =============================================================================

_QUESTION_WORDS = re.compile(
    r"\b(what|how|why|when|where|which|who|can you|could you|would you|tell me|describe|"
    r"walk me through|explain|cuál|cual|cómo|como|qué|por qué|cuándo|dónde|quién|cuéntame|"
    r"háblame|hablame|describe|explícame|explicame)\b",
    re.IGNORECASE,
)


def is_question(text: str) -> bool:
    return "?" in text or "¿" in text or bool(_QUESTION_WORDS.search(text))


@dataclass
class Turn:
    at: float          # emission time on the audio clock (s)
    text: str
    kind: str = "end"  # "end" or "eager"


def simulate_nova_turns(events: list[dict], use_speech_final: bool,
                        join_max_s: float = 2.0, join_wait_s: float = 1.5) -> list[Turn]:
    """Replay recorded Nova-3 events through the REQ-04 turn rules.

    A turn closes on speech_final (if enabled) or UtteranceEnd. A closed turn
    without a question signal that lasted < join_max_s is held join_wait_s;
    new speech inside that window merges it with the next turn.
    """
    turns: list[Turn] = []
    buf: list[str] = []
    first_word: float | None = None
    last_word: float | None = None
    pending: dict | None = None

    def close(at: float) -> None:
        nonlocal buf, first_word, last_word, pending
        text = " ".join(buf).strip()
        if not text:
            return
        duration = (last_word or 0) - (first_word or 0)
        if is_question(text) or duration >= join_max_s:
            turns.append(Turn(at, text))
        else:
            pending = {"text": text, "first": first_word, "deadline": at + join_wait_s}
        buf, first_word, last_word = [], None, None

    for ev in events:
        at, msg = ev["t"], ev["msg"]
        if pending and at > pending["deadline"]:
            turns.append(Turn(pending["deadline"], pending["text"]))
            pending = None
        kind = msg.get("type")
        if kind == "Results":
            alt = (msg.get("channel", {}).get("alternatives") or [{}])[0]
            transcript = (alt.get("transcript") or "").strip()
            if transcript and pending:
                buf, first_word = [pending["text"]], pending["first"]
                pending = None
            if transcript and msg.get("is_final"):
                buf.append(transcript)
                words = alt.get("words") or []
                if words:
                    first_word = words[0].get("start") if first_word is None else first_word
                    last_word = words[-1].get("end")
            if use_speech_final and msg.get("speech_final"):
                close(at)
        elif kind == "UtteranceEnd":
            close(at)
    if pending:
        turns.append(Turn(pending["deadline"], pending["text"]))
    return turns


def flux_turns(events: list[dict]) -> list[Turn]:
    out = []
    for ev in events:
        msg = ev["msg"]
        if msg.get("type") == "TurnInfo" and msg.get("event") == "EndOfTurn":
            out.append(Turn(ev["t"], (msg.get("transcript") or "").strip()))
        elif msg.get("type") == "TurnInfo" and msg.get("event") == "EagerEndOfTurn":
            out.append(Turn(ev["t"], (msg.get("transcript") or "").strip(), kind="eager"))
    return out


def transcript_text(events: list[dict], provider: str) -> str:
    parts = []
    for ev in events:
        msg = ev["msg"]
        if provider.startswith("A") and msg.get("type") == "Results" and msg.get("is_final"):
            parts.append((msg.get("channel", {}).get("alternatives") or [{}])[0].get("transcript", ""))
        if provider == "B" and msg.get("type") == "TurnInfo" and msg.get("event") == "EndOfTurn":
            parts.append(msg.get("transcript", ""))
    return " ".join(p for p in parts if p)


# =============================================================================
# Scoring (pure)
# =============================================================================

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass
class Score:
    closed: int = 0
    questions: int = 0
    premature_cuts: int = 0
    questions_cut: list[str] = field(default_factory=list)
    latencies: list[float] = field(default_factory=list)
    eager_latencies: list[float] = field(default_factory=list)
    terms_ok: int = 0
    terms_total: int = 0
    per_question: dict[str, dict] = field(default_factory=dict)

    @staticmethod
    def pct(values: list[float], q: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def score(turns: list[Turn], spans: list[ItemSpan], full_text: str) -> Score:
    result = Score()
    ends = [t for t in turns if t.kind == "end"]
    eagers = [t for t in turns if t.kind == "eager"]
    for span in spans:
        if not span.question:
            continue
        result.questions += 1
        cuts = [t for t in ends if span.start + 0.3 < t.at < span.end]
        closing = next((t for t in ends if span.end <= t.at < span.next_start), None)
        eager = next((t for t in eagers if span.start + 0.3 < t.at < span.next_start), None)
        if cuts:
            result.premature_cuts += len(cuts)
            result.questions_cut.append(span.id)
        if closing:
            result.closed += 1
            result.latencies.append(closing.at - span.end)
        if eager and eager.at >= span.end:
            result.eager_latencies.append(eager.at - span.end)
        result.per_question[span.id] = {
            "closed": bool(closing),
            "latency_s": round(closing.at - span.end, 2) if closing else None,
            "cuts": len(cuts),
            "text": " / ".join(t.text for t in cuts + ([closing] if closing else [])),
        }
    norm_text = _norm(full_text)
    terms = [t for item in SCRIPT for t in item.get("terms", [])]
    result.terms_total = len(terms)
    result.terms_ok = sum(1 for t in terms if _norm(t) in norm_text)
    return result


def decide(a: Score, b: Score) -> tuple[str, list[str]]:
    """Decision rule approved in C2-PLAN-01 (conditions 1–3; cost is checked
    by hand against the public price list)."""
    reasons = []
    c1 = b.closed >= 9 and b.closed >= a.closed and b.premature_cuts <= a.premature_cuts
    reasons.append(f"1. turnos: B {b.closed}/10 vs A {a.closed}/10; cortes B {b.premature_cuts} vs A {a.premature_cuts} → {'✅' if c1 else '❌'}")
    pa, pb = Score.pct(a.latencies, 0.5), Score.pct(b.latencies, 0.5)
    c2 = pb is not None and (pa is None or pb <= pa)
    reasons.append(f"2. p50: B {fmt(pb)} vs A {fmt(pa)} → {'✅' if c2 else '❌'}")
    c3 = b.terms_ok >= a.terms_ok
    reasons.append(f"3. términos: B {b.terms_ok}/{b.terms_total} vs A {a.terms_ok}/{a.terms_total} → {'✅' if c3 else '❌'}")
    reasons.append("4. costo ≤ 2× A: se verifica a mano con la lista pública de precios")
    return ("B" if (c1 and c2 and c3) else "A"), reasons


def fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f} s"


# =============================================================================
# Network: TTS + streaming (only in CI)
# =============================================================================

def synthesize(api_key: str) -> dict[tuple[str, int], array.array]:
    from deepgram import DeepgramClient

    client = DeepgramClient(api_key=api_key)
    out = {}
    for item in SCRIPT:
        for idx, (text, _) in enumerate(item["segments"]):
            chunks = client.speak.v1.audio.generate(
                text=text, model=VOICES[item["lang"]], encoding="linear16",
                sample_rate=SAMPLE_RATE, container="none",
            )
            pcm = array.array("h")
            pcm.frombytes(b"".join(chunks))
            out[(item["id"], idx)] = trim_silence(pcm)
    return out


def _url(base: str, params: list[tuple[str, str]]) -> str:
    return base + "?" + urllib.parse.urlencode(params)


def candidate_urls(keyterms: bool) -> dict[str, str]:
    kt = [("keyterm", k) for k in KEYTERMS] if keyterms else []
    common = [("encoding", "linear16"), ("sample_rate", str(SAMPLE_RATE)), ("channels", "1")]
    nova = [("model", "nova-3"), ("language", "multi"), ("interim_results", "true"),
            ("utterance_end_ms", "1000"), ("smart_format", "true"), ("punctuate", "true"),
            ("vad_events", "true")]
    return {
        "A": _url("wss://api.deepgram.com/v1/listen",
                  common + nova + [("endpointing", "100"), ("tag", "careerai-cs0-A")] + kt),
        "A2": _url("wss://api.deepgram.com/v1/listen",
                   common + nova + [("endpointing", "300"), ("tag", "careerai-cs0-A2")] + kt),
        "B": _url("wss://api.deepgram.com/v2/listen",
                  [("model", "flux-general-multi"), ("encoding", "linear16"),
                   ("sample_rate", str(SAMPLE_RATE)), ("eager_eot_threshold", "0.5"),
                   ("language_hint", "en"), ("language_hint", "es"),
                   ("tag", "careerai-cs0-B")] + kt),
    }


async def _open(name: str, api_key: str, log: dict):
    from websockets.asyncio.client import connect

    headers = {"Authorization": f"Token {api_key}"}
    for keyterms in (True, False):
        url = candidate_urls(keyterms)[name]
        try:
            ws = await asyncio.wait_for(connect(url, additional_headers=headers, max_size=None), 10)
            log[name] = {"keyterm_accepted": keyterms}
            return ws
        except Exception as err:  # noqa: BLE001 — record and retry without keyterms
            log.setdefault("errors", []).append(f"{name} keyterm={keyterms}: {type(err).__name__}: {err}")
    return None


async def stream_all(pcm: array.array, api_key: str) -> tuple[dict[str, list[dict]], dict]:
    log: dict = {}
    sockets = {n: await _open(n, api_key, log) for n in ("A", "A2", "B")}
    sockets = {n: ws for n, ws in sockets.items() if ws is not None}
    events: dict[str, list[dict]] = {n: [] for n in sockets}
    loop = asyncio.get_running_loop()
    t0 = loop.time() + 0.5
    data = pcm.tobytes()
    frame_bytes = FRAME_SAMPLES * 2
    n_frames = math.ceil(len(data) / frame_bytes)

    async def sender(name: str, ws) -> None:
        for k in range(n_frames):
            await asyncio.sleep(max(0.0, t0 + (k + 1) * FRAME_S - loop.time()))
            await ws.send(data[k * frame_bytes:(k + 1) * frame_bytes])
        if name != "B":
            await ws.send(json.dumps({"type": "Finalize"}))
        await asyncio.sleep(3.0)
        try:
            await ws.send(json.dumps({"type": "CloseStream"}))
        except Exception as err:  # noqa: BLE001 — the server may have closed already
            log.setdefault("errors", []).append(f"{name} close: {type(err).__name__}")

    async def receiver(name: str, ws) -> None:
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                events[name].append({"t": loop.time() - t0, "msg": json.loads(raw)})
        except Exception as err:  # noqa: BLE001 — a closed socket ends the run
            log.setdefault("errors", []).append(f"{name} receive: {type(err).__name__}: {err}")

    tasks = [asyncio.create_task(receiver(n, ws)) for n, ws in sockets.items()]
    await asyncio.gather(*(sender(n, ws) for n, ws in sockets.items()), return_exceptions=True)
    await asyncio.wait(tasks, timeout=8)
    for ws in sockets.values():
        await ws.close()
    return events, log


# =============================================================================
# Report
# =============================================================================

def samples(events: dict[str, list[dict]]) -> dict:
    """Up to two raw messages per (provider, type/event) for CS-4 parser tests."""
    out: dict[str, list] = {}
    for name, evs in events.items():
        seen: dict[str, int] = {}
        for ev in evs:
            msg = ev["msg"]
            key = f"{name}:{msg.get('type')}:{msg.get('event', '')}"
            if seen.get(key, 0) >= 2:
                continue
            seen[key] = seen.get(key, 0) + 1
            trimmed = json.loads(json.dumps(msg))
            for alt in trimmed.get("channel", {}).get("alternatives", []) or []:
                alt["words"] = (alt.get("words") or [])[:3]
            if "words" in trimmed:
                trimmed["words"] = trimmed["words"][:3]
            out.setdefault(key, []).append(trimmed)
    return out


def render_report(spans, scores: dict[str, Score], log: dict, minutes: float) -> str:
    lines = ["## CS-0 · Benchmark de proveedores de STT", ""]
    lines.append(f"Audio: {minutes:.1f} min por candidato; 10 preguntas (5 EN / 5 ES), 3 con pausas "
                 f"a media frase, 1 con mezcla de idiomas, 2 muletillas cortas; Opus {OPUS_BITRATE} + "
                 f"ruido SNR {NOISE_SNR_DB:.0f} dB; frames de 100 ms en tiempo real.")
    lines += ["", "| Candidato | Turnos cerrados | Cortes prematuros | Latencia p50 | p90 | Términos | keyterm |",
              "|---|---|---|---|---|---|---|"]
    names = {"A": "A · Nova-3 multi + heurística REQ-04", "A2": "A2 · Nova-3 conservador (informativo)",
             "B": "B · Flux Multilingual"}
    for n, s in scores.items():
        kt = log.get(n, {}).get("keyterm_accepted")
        lines.append(f"| {names[n]} | {s.closed}/{s.questions} | {s.premature_cuts} "
                     f"({', '.join(s.questions_cut) or '—'}) | {fmt(Score.pct(s.latencies, .5))} | "
                     f"{fmt(Score.pct(s.latencies, .9))} | {s.terms_ok}/{s.terms_total} | "
                     f"{'sí' if kt else 'no' if kt is False else '—'} |")
    if "B" in scores and scores["B"].eager_latencies:
        lines.append(f"\nFlux EagerEndOfTurn p50: {fmt(Score.pct(scores['B'].eager_latencies, .5))} "
                     "(permite arrancar el LLM antes).")
    if "A" in scores and "B" in scores:
        winner, reasons = decide(scores["A"], scores["B"])
        lines += ["", f"### Regla de decisión (C2-PLAN-01) → **{winner}** (condiciones 1–3)", ""]
        lines += [f"- {r}" for r in reasons]
    lines += ["", "### Transcripción por pregunta (revisión humana)", "",
              "| Pregunta | " + " | ".join(scores) + " |", "|---|" + "---|" * len(scores)]
    for span in spans:
        if not span.question:
            continue
        cells = []
        for s in scores.values():
            q = s.per_question.get(span.id, {})
            mark = "✅" if q.get("closed") else "❌"
            cut = f" ✂️{q['cuts']}" if q.get("cuts") else ""
            lat = f" {q['latency_s']} s" if q.get("latency_s") is not None else ""
            cells.append(f"{mark}{cut}{lat} {q.get('text', '')}".replace("|", "/"))
        lines.append(f"| {span.id} | " + " | ".join(cells) + " |")
    if log.get("errors"):
        lines += ["", "### Errores", ""] + [f"- `{e}`" for e in log["errors"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="stt-benchmark-out")
    args = parser.parse_args()
    api_key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if not api_key:
        print("DEEPGRAM_API_KEY is not set", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    started = time.time()
    clean, spans = build_timeline(synthesize(api_key))
    pcm = opus_round_trip(add_noise(clean))
    minutes = len(pcm) / SAMPLE_RATE / 60
    print(f"fixture: {minutes:.2f} min, built in {time.time() - started:.1f} s")

    events, log = asyncio.run(stream_all(pcm, api_key))
    scores: dict[str, Score] = {}
    for name, evs in events.items():
        if name == "B":
            turns = flux_turns(evs)
        else:
            turns = simulate_nova_turns(evs, use_speech_final=(name == "A"))
        scores[name] = score(turns, spans, transcript_text(evs, name))

    report = render_report(spans, scores, log, minutes)
    sample = samples(events)
    (out / "report.md").write_text(
        report + "\n<details><summary>Mensajes reales (muestras para los tests de CS-4)</summary>\n\n"
        "```json\n" + json.dumps(sample, ensure_ascii=False, indent=1)[:60_000] + "\n```\n</details>\n"
    )
    (out / "samples.json").write_text(json.dumps(sample, ensure_ascii=False, indent=1))
    (out / "spans.json").write_text(json.dumps([s.__dict__ for s in spans], default=str, indent=1))
    print(report)
    return 0 if scores else 1


if __name__ == "__main__":
    sys.exit(main())
