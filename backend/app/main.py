"""FastAPI application entry point.

Responsibilities (and ONLY these):
- Build the FastAPI app instance
- Configure CORS so the Vite frontend can talk to it
- Register routers from app.api.*
- Ensure the CV output directory exists at startup

NO business logic lives here — that belongs in app.services.*.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import cv as cv_router
from app.api import interview as interview_router
from app.api import interview_audio as interview_audio_router
from app.config import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run once on startup: make sure the CV output directory is writable."""
    settings = get_settings()
    settings.CV_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="CareerAI API",
    description="CV Engine + (later) Interview Copilot",
    version="0.1.0",
    lifespan=lifespan,
)

_settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(cv_router.router, prefix="/api/cv", tags=["cv"])
app.include_router(interview_router.router, prefix="/api/interview", tags=["interview"])
app.include_router(
    interview_audio_router.router,
    prefix="/api/interview",
    tags=["interview-audio"],
)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe — used by Docker / Railway to know the app is up."""
    return {"status": "ok"}


import os
from pathlib import Path
from fastapi.staticfiles import StaticFiles

_dist_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(_dist_dir), html=True), name="static")
