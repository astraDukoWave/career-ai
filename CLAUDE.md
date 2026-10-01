# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CareerAI: an AI-powered ATS resume optimizer + real-time interview copilot, started as a hackathon MVP in May 2026 (see `STATE.md` for the active cycle). Two independent modules share one backend/frontend:

- **CV Engine** (`/api/cv/*`): takes a job posting + candidate profile, extracts ATS keywords via Gemini, scores the profile against them, rewrites weak experience bullets to close the gap, and renders a PDF via WeasyPrint.
- **Interview Copilot** (`/api/interview/*`): classifies an interviewer's question (code / concept / behavioral) and streams a Gemini-generated suggested answer over SSE. Its live mode streams the meeting tab (or mic) over a WebSocket to Deepgram Nova-3, detects the interviewer's questions and suggests without clicks.

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

The backend has a small pytest suite (no network, no API keys needed):

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

The MCP server (`mcp/`) has its own suite, also offline:

```bash
cd mcp
pip install -e ".[test]"
python -m pytest
```

Frontend unit tests (Vitest, pure functions in `src/lib`): `cd frontend && npm test`. The live-mode E2E (Playwright + Chromium with a fake microphone, a fake Deepgram replaying a real recorded session, a fake LLM) lives in `e2e/`:

```bash
pip install -r e2e/requirements.txt && python -m playwright install chromium
cd frontend && VITE_API_URL=http://127.0.0.1:8123 npm run build && cd ..
python -m pytest e2e
```

There is **no lint config**. `npm run build` runs `tsc` and is the frontend typecheck gate.

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
- Live mode (Cycle #2, C2-SPEC-01): `app/api/interview_audio.py` is the WebSocket `/api/interview/ws/live` (protocol in its docstring: `start` JSON, then 16 kHz mono linear16 PCM frames, then `stop`; out: `ready`/`partial`/`final`/`turn`/`error`). The route only translates; `services/live_session.py` runs the session (limits: `LIVE_MAX_SESSIONS`, `LIVE_MAX_SESSION_S`), `services/stt_stream.py` talks to Deepgram Nova-3 `language=multi` over its raw WebSocket API (no SDK; 5 s connect timeout, KeepAlive, one reconnection, keyterms from the CV/posting) and `services/turn_detector.py` (pure) closes turns and applies the v1.1 continuation: speech within `TURN_CONTINUATION_S` of a close, an untranscribed filler included, continues the turn under the **same `turn_id`**, and the browser restarts that suggestion with the full text.
- Starlette's `CORSMiddleware` does not govern WebSocket handshakes, so the live route checks `Origin` against `CORS_ORIGINS` itself before `accept()` (a foreign origin gets HTTP 403). Frame size and compression are capped by the uvicorn flags in `heroku.yml` (CI boots the image with that exact command).
- Turn-detector tests replay a **real** Nova-3 session (`backend/tests/fixtures/deepgram_turns_real.json`, provenance inside); keep using recorded provider events, not hand-made ones, when changing turn rules.

### Config (`app/config.py`)

All configuration is env-var driven via a single `pydantic-settings` `Settings` class (`get_settings()`, `@lru_cache`d) — no hardcoded hosts/ports/credentials anywhere. `GEMINI_API_KEY` and `DEEPGRAM_API_KEY` are optional at boot; the app starts without them and fails per-request instead (503 for missing Gemini key via `LLMConfigError`; the live WebSocket answers `stt_unavailable` without a Deepgram key). `CORS_ORIGINS` is a comma-separated env string parsed into a list.

### Frontend

No router library — `App.tsx` implements a two-route path switch (`/cv`, `/interview`) by hand using `history.pushState`/`popstate`. No state library either; each page owns its own `useState`.

`frontend/src/api/client.ts` is the single point of contact with the backend: TypeScript interfaces there manually mirror the Pydantic schemas in `backend/app/schemas/*` — when a schema changes, update this file too, there's no codegen. It also hand-rolls SSE frame parsing over a `fetch` `ReadableStream` (not `EventSource`, since that's GET-only and this is a POST).

`frontend/src/hooks/useLiveAudio.ts` captures the meeting tab (`getDisplayMedia`, video dropped) or the mic, converts it in an AudioWorklet (`src/audio/pcm-worklet.js`, kept a hashed file by `vite.config.ts`) and owns the live socket; deliberately a hook so unmount always releases the tab/mic, even mid start-up. `components/LiveInterview.tsx` is the live UI (one suggestion card, restarted in place on a repeated `turn_id`), `lib/liveTranscript.ts` and `lib/sessionSummary.ts` are pure and tested with Vitest.

`VITE_API_URL` (default `http://localhost:8000`) is the only place the backend origin is configured; `liveSocketUrl()` in `client.ts` derives the WebSocket URL from it by swapping `http`/`https` for `ws`/`wss`.

### MCP server (`mcp/`)

`careerai-mcp` lets Claude Code / Claude Desktop call CareerAI (spec LB03-SPEC-01). It is a **thin client of the public API** over stdio: three tools (`generate_cv`, `interview_suggestion`, `get_profile`), no business logic, no secrets, configured only by `CAREERAI_API_URL` and `CAREERAI_PROFILE` (a local JSON profile that never enters the repo). **Contract rule:** its request bodies mirror `backend/app/schemas/*` exactly like `client.ts` does — when a schema changes, update `mcp/careerai_mcp/server.py` too. `mcp/tests` validates every body against those Pydantic schemas, so CI (`mcp · pytest`) fails on drift. Install guide: `mcp/README.md`.

## Postgres / Redis

Both are provisioned in `docker-compose.yml` and started, but **the backend does not connect to either** in the current sprint (no DB client, no redis client in `requirements.txt`). They exist for a future Interview Copilot sprint (session persistence, SSE pub/sub). Don't assume any data is actually persisted there yet.

## Frozen / do-not-touch areas

The live audio path (`interview_audio.py`, `live_session.py`, `stt_stream.py`, `turn_detector.py`) was rebuilt in Cycle #2 (C2-SPEC-01) and closed on 2026-10-01. It calls a paid API: changes need a spec or an explicit OK, keep the Origin check and the session limits, and get a `cto-review` before deploy. The old pre-recorded `stt_client.py` and `/ws/audio` are gone.

---

## CareerAI — Contexto para Claude Code CLI

### Qué es este proyecto
SaaS de job seeking: CV Engine (ATS optimizer + PDF) + Interview Copilot
(real-time suggestions). Ciclo #1 (Heroku) cerrado; Ciclo #2 (copiloto en
tiempo real) en curso. Leer HANDOFF.md para estado completo.

### Reglas de arquitectura (no violar)
1. CORS nunca hardcoded — leer de `Settings.cors_origins_list`
2. `allow_origins=["*"]` con `allow_credentials=True` está PROHIBIDO — rompe el spec HTTP
3. GEMINI_API_KEY, DEEPGRAM_API_KEY, CORS_ORIGINS van en .env / Heroku Config Vars —
   NUNCA en código NI en documentación. El repo es PÚBLICO: placeholders únicamente.
4. Un commit por task. Mensaje en Conventional Commits.
5. Todo trabajo ocurre en una rama nueva y termina en `git push` de esa rama.
   Nada queda solo en el working tree.
6. El repo es público: análisis competitivo, pricing y estrategia comercial
   NO entran a ningún archivo del repo (viven en strategy.md, fuera del repo).
7. No tocar `interview_audio.py` ni `main.py` sin revisar HANDOFF.md sección 4 primero.

### Archivos que NO modificar sin aprobación explícita
- `backend/app/api/interview_audio.py`, `backend/app/services/live_session.py` y `stt_stream.py` — copiloto en vivo (API de pago; cambios con spec u OK explícito y `cto-review` antes del deploy)
- `heroku.yml` — el comando de arranque lleva los límites de WebSocket de uvicorn; la CI arranca la imagen con él
- `docker-compose.yml` — solo para local dev. Producción: Heroku (HANDOFF.md §3)

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
PRODUCCIÓN: Heroku, app `career-ai` (container stack; `Dockerfile` + `heroku.yml` en la raíz). Tras cada merge a `main`, Jonathan despliega con `git push heroku main:main` (el build corre en Heroku; no hace falta Docker local). Rollback: `heroku rollback -a career-ai`. Logs: `heroku logs --tail -a career-ai`. Replit está retirado.

### Variables de entorno requeridas
Ver sección 9 del HANDOFF.md (placeholders; valores reales en Heroku Config Vars).

### Tests antes de merge
- `cd backend && python -m pytest` → verde
- `cd frontend && npm test && npm run build` → verde (Vitest + tsc)
- E2E del modo en vivo (`e2e/`) → verde en la CI (job `e2e · live mode (fake audio)`)
- `cd mcp && python -m pytest` → verde (si el cambio toca `mcp/` o `backend/app/schemas/`)
- Tras el deploy: `curl https://career-ai-95daf7c9a813.herokuapp.com/health` → 200
- CV Engine: generar un CV simple y verificar el ATS score visible
- Interview Copilot: `POST /api/interview/text` con texto corto → respuesta SSE
- Modo en vivo: `heroku logs` muestra `Live session started/ended` sin tracebacks (observabilidad en `docs/reviews/c2-d2-cto-review.md`)

### Skills
Las skills del flujo SDD viven en la cuenta de Claude (workflow-router, brainstorm, design-spec, system-design-spec, design-plan, verify, cto-review); no hay skills locales en el repo.
