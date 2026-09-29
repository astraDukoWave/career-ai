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

from starlette.exceptions import HTTPException as StarletteHTTPException


class SPAStaticFiles(StaticFiles):
    """StaticFiles that serves index.html for client-side routes.

    The frontend routes by hand (/cv, /interview), so reloading one of them
    used to return 404 in production. Missing files (a path whose last
    segment has an extension) and anything under the backend's own
    prefixes (/api, /health) still return 404.
    """

    _BACKEND_PREFIXES = frozenset({"api", "health"})

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            first_segment = path.split("/", 1)[0]
            last_segment = path.rsplit("/", 1)[-1]
            if (
                exc.status_code == 404
                and first_segment not in self._BACKEND_PREFIXES
                and "." not in last_segment
            ):
                return await super().get_response("index.html", scope)
            raise


_dist_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist_dir.exists():
    app.mount("/", SPAStaticFiles(directory=str(_dist_dir), html=True), name="static")
