# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CareerAI: an AI-powered ATS resume optimizer + real-time interview copilot, built as a hackathon MVP (deadline May 19, 2026 — see `STATE.md` for current sprint status). Two independent modules share one backend/frontend:

- **CV Engine** (`/api/cv/*`): takes a job posting + candidate profile, extracts ATS keywords via Gemini, scores the profile against them, rewrites weak experience bullets to close the gap, and renders a PDF via WeasyPrint.
- **Interview Copilot** (`/api/interview/*`): classifies an interviewer's question (code / concept / behavioral) and streams a Gemini-generated suggested answer over SSE, optionally driven by live mic audio transcribed through Deepgram over a WebSocket.

## Commands

There is no root `package.json` — backend and frontend are run separately, normally via Docker Compose.

```bash
# Full stack (backend :8000, frontend :5173, postgres, redis)
cp .env.example .env   # fill in GEMINI_API_KEY at minimum
docker compose up -d
docker compose logs -f backend    # or frontend
docker compose down
```

Backend, without Docker (needs WeasyPrint's native libs — cairo/pango/gdk-pixbuf — installed locally; see `backend/Dockerfile` for the apt package list on Debian/Ubuntu):

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend, without Docker:

```bash
cd frontend
npm install
npm run dev        # Vite dev server on :5173
npm run build       # tsc typecheck + production build
npm run preview
```

There is currently **no test suite and no lint config** in either package (no pytest/ruff/eslint files present) — don't assume `npm test` or `pytest` exist. `npm run build` runs `tsc` and is the closest thing to a frontend typecheck gate.

Health check: `GET /health` → `{"status": "ok"}`.

## Architecture

### Layered backend — routes never contain logic

`backend/app` is strictly layered and every file's docstring states this rule explicitly:

- `app/main.py` — FastAPI app wiring only: CORS, router registration, startup lifespan (creates `CV_OUTPUT_DIR`). No business logic.
- `app/api/*` — HTTP/WebSocket routes. Translate HTTP ⇄ services and map service exceptions to status codes. Nothing else.
- `app/services/*` — all business logic. **Must never import FastAPI.** Raise plain exceptions; the route layer decides the HTTP status.
- `app/schemas/*` — Pydantic-only request/response models. No SQLAlchemy.

When adding backend functionality, put logic in a service and keep the route a thin translator — this is an enforced convention across the codebase, not a suggestion.

### CV Engine pipeline (`app/services/cv_engine.py`)

`generate_cv()` runs, in order:
1. Split the posting into title/body (`ats_scorer.split_title_and_body`) so the title doesn't pollute keyword extraction.
2. Extract 10–25 ATS keywords via Gemini (`llm_client.extract_keywords`).
3. Score the candidate profile against those keywords (`ats_scorer.score`) — pure substring/word-boundary matching plus a closed synonym allowlist (`SKILL_SYNONYMS`), not semantic similarity.
4. If score < `ATS_REWRITE_THRESHOLD` (0.60), ask Gemini to rewrite each experience entry's bullets to weave in missing keywords without fabricating facts (`llm_client.rewrite_bullets`), then rescore.
5. Extract just the job title (2–6 words) for the CV header, falling back to the posting's first line on any LLM failure.
6. Render `app/templates/cv_template.html` via Jinja2, then `weasyprint.HTML(...).write_pdf()` to `CV_OUTPUT_DIR`.
7. If the final score is below `MISMATCH_WARNING_THRESHOLD` (0.30), attach a human-readable low-fit warning (`_build_mismatch_warning`) with a heuristic domain guess.

PDF filenames are `cv-{uuid4hex}.pdf`; `app/api/cv.py` enforces that pattern via regex on download to block path traversal.

### Interview Copilot pipeline

- `router_agent.py` classifies intent (`tech_code` / `tech_concept` / `behavioral_star`) and language (`en`/`es`) via **keyword matching, not an LLM call** — deliberately, to stay well under a second for a live interview. Intent priority order (behavioral > code > concept) and trigger phrases live in `_INTENT_TRIGGERS`.
- `app/api/interview.py` streams the result as SSE with a fixed event sequence: `meta` (always first) → `chunk`* → `error`? → `done` (always last). Because the stream has already started by the time an LLM error can occur, errors are reported as an SSE `error` event, not an HTTP error status.
- `llm_client.generate_suggestion` picks the prompt addendum from `_SUGGESTION_INTENT_PROMPTS` (prompts originally sourced from `skill-creator-v2.md`) and streams Gemini chunks.
- Audio: `app/api/interview_audio.py` is a WebSocket (`/api/interview/ws/audio`) that receives raw `audio/webm;codecs=opus` blobs (~2s slices from the browser's `MediaRecorder`) and forwards each to `stt_client.transcribe_audio_chunk` (Deepgram Nova-3, pre-recorded API, `language="es"` hardcoded). `stt_client` **never raises** — any failure (missing key, network error, malformed response) collapses to `""` so the socket stays open.
- Note: Starlette's `CORSMiddleware` does not govern WebSocket handshakes, so the audio route currently accepts any Origin (see the comment block in `interview_audio.py` for the production fix needed before this ships past local dev).

### Config (`app/config.py`)

All configuration is env-var driven via a single `pydantic-settings` `Settings` class (`get_settings()`, `@lru_cache`d) — no hardcoded hosts/ports/credentials anywhere. `GEMINI_API_KEY` and `DEEPGRAM_API_KEY` are optional at boot; the app starts without them and fails per-request instead (503 for missing Gemini key via `LLMConfigError`, silent `""` for missing Deepgram key). `CORS_ORIGINS` is a comma-separated env string parsed into a list.

### Frontend

No router library — `App.tsx` implements a two-route path switch (`/cv`, `/interview`) by hand using `history.pushState`/`popstate`. No state library either; each page owns its own `useState`.

`frontend/src/api/client.ts` is the single point of contact with the backend: TypeScript interfaces there manually mirror the Pydantic schemas in `backend/app/schemas/*` — when a schema changes, update this file too, there's no codegen. It also hand-rolls SSE frame parsing over a `fetch` `ReadableStream` (not `EventSource`, since that's GET-only and this is a POST).

`frontend/src/hooks/useAudioCapture.ts` wraps `getUserMedia`/`MediaRecorder`; deliberately a hook rather than a service so unmount always tears down the mic stream (browser keeps the mic LED on otherwise).

`VITE_API_URL` (default `http://localhost:8000`) is the only place the backend origin is configured; `WS_URL` in `InterviewCopilot.tsx` derives the WebSocket URL from it by swapping the `http`/`https` scheme for `ws`/`wss`.

## Postgres / Redis

Both are provisioned in `docker-compose.yml` and started, but **the backend does not connect to either** in the current sprint (no DB client, no redis client in `requirements.txt`). They exist for a future Interview Copilot sprint (session persistence, SSE pub/sub). Don't assume any data is actually persisted there yet.

## Frozen / do-not-touch areas

Per `STATE.md`: Deepgram Nova-3 STT integration is frozen post-hackathon-submission — avoid changing `stt_client.py`'s transcription call shape unless specifically asked to.

---

## CareerAI — Contexto para Claude Code CLI

### Qué es este proyecto
SaaS de job seeking: CV Engine (ATS optimizer + PDF) + Interview Copilot
(real-time suggestions). Fase 0 MVP cerrado. Leer HANDOFF.md para estado completo.

### Reglas de arquitectura (no violar)
1. CORS nunca hardcoded — leer de `Settings.cors_origins_list`
2. `allow_origins=["*"]` con `allow_credentials=True` está PROHIBIDO — rompe el spec HTTP
3. GEMINI_API_KEY, DEEPGRAM_API_KEY, CORS_ORIGINS van en .env / Replit Secrets —
   NUNCA en código NI en documentación. El repo es PÚBLICO: placeholders únicamente.
4. Un commit por task. Mensaje en Conventional Commits.
5. Todo trabajo ocurre en una rama nueva y termina en `git push` de esa rama.
   Nada queda solo en el working tree.
6. El repo es público: análisis competitivo, pricing y estrategia comercial
   NO entran a ningún archivo del repo (viven en strategy.md, fuera del repo).
7. No tocar `interview_audio.py` ni `main.py` sin revisar HANDOFF.md sección 4 primero.

### Archivos que NO modificar sin aprobación explícita
- `backend/app/api/interview_audio.py` — WebSocket handler frágil
- `backend/app/services/stt_client.py` — Deepgram syntax funcionando pero frágil
- `docker-compose.yml` — solo para local dev. Producción: Replit hoy;
  migración a Heroku aprobada — ver HANDOFF.md §3 antes de asumir el host

### Cómo correr el proyecto localmente
```bash
# Backend (requiere libs nativas para WeasyPrint en Linux/Mac)
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (en otra terminal)
cd frontend && npm install && npm run dev
```

DOCKER: esta máquina (MacBook Air 2017) no puede correr Docker. Usar GitHub Codespaces para todo lo que requiera docker compose.

### Cómo deployar
PRODUCCIÓN: el deployment de Replit corre DE PRESTADO (trial vencido, suscripción cancelada) — responde 200 pero puede caer sin aviso. NO redeployar ni tocar nada en Replit. La restauración formal de producción es el ciclo SDD #1: migración a Heroku (HANDOFF.md §3). Build manual local si es necesario: `cd frontend && npm run build` (Replit sirve dist/ desde FastAPI StaticFiles).

### Variables de entorno requeridas
Ver sección 9 del HANDOFF.md (placeholders; valores reales en Replit Secrets).

### Tests antes de merge
- `curl https://career-ai-astradukowave.replit.app/health` → 200 (actualizar al dominio de Heroku tras el cutover del ciclo SDD #1)
- CV Engine: generar un CV simple y verificar ATS score visible
- Interview Copilot: `POST /api/interview/text` con texto corto → SSE response

### Skills en .claude/skills/
Próxima a crear: `harness-engineering` (ver HANDOFF.md sección 10).
