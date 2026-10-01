# CareerAI

[![CI](https://github.com/astraDukoWave/career-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/astraDukoWave/career-ai/actions/workflows/ci.yml)

**Tailored CVs + an interview copilot**, an AI-native job-seeking app.

🔗 **Live demo:** https://career-ai-95daf7c9a813.herokuapp.com

## What it does

1. **CV Engine.** Paste a job posting and your profile. You get a tailored,
   single-column, ATS-friendly CV:
   - Keywords are extracted from the posting with Gemini.
   - Your profile is scored against them, and weak bullets can be rewritten
     without inventing facts.
   - Output is an HTML preview plus PDF (download or print).
2. **Interview Copilot.** Type the interviewer's question and get a streamed
   suggestion (behavioral STAR, technical concept, or coding approach), with
   automatic English/Spanish detection.
   - **Live mode:** listens to the meeting tab (or the microphone), detects
     when a question ends, and grounds every suggestion in your own CV and the
     job posting.

3. **From Claude.** A local MCP server lets you tailor your CV or practice an
   answer from Claude Code or Claude Desktop, grounded in your own profile
   file. See [`mcp/README.md`](mcp/README.md).

## Stack

FastAPI · Gemini (`google-genai`) · Deepgram Nova-3 (speech-to-text) ·
React + Vite + TypeScript · WeasyPrint · one Docker image on Heroku, with
FastAPI serving the built frontend.

## How it's built

This repo is built with **Claude as the AI tech lead**: Claude Code does the
implementation, and custom Claude Skills (brainstorm, design-spec, design-plan,
verify, cto-review, …) drive each phase. The workflow is spec-driven, with
human approval gates:

- Every change goes `brainstorm → design-spec → design-plan → implementation
  → verify`. Specs and plans live in `docs/specs/` and `docs/plans/`.
- The product owner approves specs, plans, and merges. Every change reaches
  `main` through a pull request.
- "Done" means executable evidence: tests, builds, and checks against the
  live URL. A report alone doesn't count.
- `HANDOFF.md` is the single source of truth between phases.
- High-risk changes also get an independent review by a fresh-context agent
  before merge.

## Status & roadmap

- ✅ **Cycle #1:** migration to Heroku (container stack) and to the current
  Gemini SDK.
- ✅ **CV output fix:** single-column PDF, skill groups kept intact, clean
  bullets.
- 🚧 **Cycle #2:** real-time interview copilot. Spec:
  [`docs/specs/copiloto-tiempo-real.md`](docs/specs/copiloto-tiempo-real.md).
  - ✅ CI on every PR, including a boot test of the production image.
  - ✅ Suggestions grounded in the user's own CV, with anti-hallucination
    rules.
  - ✅ Speech-to-text vendor chosen with a real-time benchmark
    ([PR #11](https://github.com/astraDukoWave/career-ai/pull/11)).
  - ✅ Live mode: listens to the meeting tab or the microphone, detects the
    interviewer's questions and suggests without clicks, with a session
    summary. Tested end to end in CI with fake audio and real recorded
    speech-to-text events.
  - 🚧 First real interviews with it, to calibrate turn detection.
- ✅ **MCP server:** use CareerAI from Claude Code or Claude Desktop
  ([`mcp/`](mcp/README.md)).
- ⏭️ **Next:**
  - A verifiable profile with GitHub as the source of truth. Every CV line
    is backed by evidence or by your own confirmation, and tailored CVs
    never invent experience.
  - Then a practice mode that simulates AI-led recruiter interviews.

## Run locally

```bash
# Backend (WeasyPrint needs native libs: pango, cairo, gdk-pixbuf)
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev

# Backend tests (no API keys needed)
cd backend && pip install -r requirements-dev.txt && python -m pytest

# MCP server tests (no network needed)
cd mcp && pip install -e ".[test]" && python -m pytest
```

Copy `.env.example` to `.env` and fill in your keys. Never commit `.env`.
