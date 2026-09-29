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
   - **In progress (Cycle #2):** a real-time mode that listens to the meeting
     tab, detects when a question ends, and grounds every suggestion in your
     own CV and the job posting.

## Stack

FastAPI · Gemini (`google-genai`) · Deepgram Nova-3 (speech-to-text) ·
React + Vite + TypeScript · WeasyPrint · one Docker image on Heroku, with
FastAPI serving the built frontend.

## How it's built

This repo is developed with a **spec-driven workflow run by an AI tech lead**,
with human approval gates:

- Every change goes `brainstorm → design-spec → design-plan → implementation
  → verify`. Specs and plans live in `docs/specs/` and `docs/plans/`.
- The product owner approves specs, plans, and merges. Every change reaches
  `main` through a pull request.
- "Done" means executable evidence: tests, builds, and checks against the
  live URL. A report alone doesn't count.
- `HANDOFF.md` is the single source of truth between phases.

## Status & roadmap

- ✅ **Cycle #1:** migration to Heroku (container stack) and to the current
  Gemini SDK.
- ✅ **CV output fix:** single-column PDF, skill groups kept intact, clean
  bullets.
- 🚧 **Cycle #2:** real-time interview copilot. Spec:
  [`docs/specs/copiloto-tiempo-real.md`](docs/specs/copiloto-tiempo-real.md).
- ⏭️ **Next:**
  - A structured CV builder: import your CV, edit without formatting, and
    confirm your experience before adding keywords.
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
```

Copy `.env.example` to `.env` and fill in your keys. Never commit `.env`.
