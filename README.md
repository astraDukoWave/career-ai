# CareerAI

**ATS Optimizer + Real-Time Interview Copilot** — an AI-native job-seeking SaaS.

🔗 **Live demo:** https://career-ai-astradukowave.replit.app

## What it does

1. Paste a job posting + your profile → get a **tailored, ATS-scored CV**
   (keyword extraction via Gemini, match scoring, optional bullet rewriting,
   HTML preview → native Print-to-PDF).
2. Open the **Interview Copilot** → speak or type → intent routing
   (behavioral / technical concept / coding) → real-time streamed suggestions
   over SSE, with automatic ES/EN language detection.

## Stack

FastAPI · Gemini 2.5 Flash · Deepgram Nova-3 (STT) · React + Vite +
TypeScript · WeasyPrint · single-service Docker deploy (FastAPI
serves the built frontend).

## How it's built (the interesting part)

This repo is developed with a **spec-driven, multi-agent AI workflow**:

- **Strategic layer** (Claude App skills): `brainstorm → design-spec →
  design-plan → verify`, with mandatory human approval gates.
- **Execution layer** (Claude Code CLI): implements approved plans task by
  task, one commit per task, always on a pushed feature branch.
- **Independent verification**: every "done" report is re-audited against
  the real repo (codeload tarball diff) before merge.

`HANDOFF.md` is the single source of truth between phases. Specs and plans
live in `docs/specs/` and `docs/plans/`.

## Status & roadmap

MVP live in production. Next: hosting migration to Heroku (student
credits), then **Phase 1A — Context Bridge** (the copilot
inherits the job context from the CV you generated), then **Practice Mode**
(an AI-recruiter interview simulator with seniority-calibrated, chained
questions and rubric-based scoring).

## Run locally

```bash
# Backend (WeasyPrint needs native libs: pango, cairo, gdk-pixbuf)
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

Copy `.env.example` → `.env` and fill in your keys. Never commit `.env`.
