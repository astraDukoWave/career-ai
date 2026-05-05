# CareerAI — MVP scaffolding

Hackathon MVP for Milan AI Week (May 13–20, 2026). Two modules: **CV Engine**
(this sprint) and **Interview Copilot** (next sprint).

## Stack

- **Backend**: Python 3.11 + FastAPI, Gemini API, Jinja2, WeasyPrint
- **Frontend**: React 18 + TypeScript + Vite
- **Infra**: Docker Compose (backend + frontend + postgres + redis)

> Postgres and Redis are provisioned in `docker-compose.yml` but the CV Engine
> backend does **not** connect to them yet (no `psycopg2`/`redis` in
> `requirements.txt`). They are reserved for the Interview Copilot sprint.

## Quick start

```bash
# 1. Configure secrets
cp .env.example .env
# edit .env and set GEMINI_API_KEY=...

# 2. Build & start everything
docker compose up --build

# 3. Open the app
# Frontend → http://localhost:5173
# Backend  → http://localhost:8000/docs   (Swagger UI)
```

## Folder structure

```
cv-engine/
├── backend/
│   ├── app/
│   │   ├── api/cv.py             # POST /api/cv/generate, GET /api/cv/{file}/pdf
│   │   ├── services/             # cv_engine, ats_scorer, llm_client
│   │   ├── schemas/cv.py         # Pydantic request/response models
│   │   └── templates/cv_template.html
│   ├── storage/cvs/              # Generated PDFs (Docker volume)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/CVGenerator.tsx
│   │   ├── components/CVPreview.tsx
│   │   └── api/client.ts
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml
└── .env.example
```

## Architectural rules (enforced)

- **Routes** → no business logic, no DB access
- **Services** → business logic only, no FastAPI imports
- **Schemas** → Pydantic only
- **Models** → SQLAlchemy only (none yet — added when first Alembic migration lands)
- **Config** → all values from env vars, no hardcoded ports/hosts/credentials
