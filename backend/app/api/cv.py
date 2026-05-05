"""HTTP routes for the CV Engine.

Per the layered-architecture rule: routes ONLY translate HTTP <-> services.
NO business logic and NO direct DB access live here.

Endpoints (all mounted under /api/cv via app.main):
    POST /generate           -> generate a CV
    GET  /{filename}/pdf     -> stream the generated PDF
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.config import get_settings
from app.schemas.cv import CVRequest, CVResponse
from app.services import cv_engine
from app.services.llm_client import LLMConfigError, LLMRateLimitError, LLMResponseError

logger = logging.getLogger(__name__)
router = APIRouter()

# Whitelist for the filename path param: prevents path-traversal (e.g. ../etc/passwd).
_FILENAME_RE = re.compile(r"^cv-[a-f0-9]{32}\.pdf$")


@router.post(
    "/generate",
    response_model=CVResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a tailored CV from a job posting + user profile",
)
async def generate(req: CVRequest) -> CVResponse:
    """Run the CV Engine pipeline and return HTML + PDF URL + ATS analysis."""
    try:
        return await cv_engine.generate_cv(
            job_posting=req.job_posting,
            user_profile=req.user_profile.model_dump(),
        )
    except LLMConfigError as err:
        # Missing API key is an operational error, not a bug — 503 is correct.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(err),
        ) from err
    except LLMRateLimitError as err:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(err),
            headers={"Retry-After": "60"},
        ) from err
    except LLMResponseError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM returned an unexpected response: {err}",
        ) from err
    except Exception as err:
        logger.exception("Unexpected error generating CV")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate CV.",
        ) from err


@router.get(
    "/{filename}/pdf",
    summary="Download a previously-generated CV as a PDF",
    response_class=FileResponse,
)
async def download_pdf(filename: str) -> FileResponse:
    """Serve the PDF from the configured output directory.

    Filename must match the strict pattern produced by cv_engine (UUID4 hex)
    so users can't request arbitrary files on disk.
    """
    if not _FILENAME_RE.match(filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    settings = get_settings()
    pdf_path: Path = settings.CV_OUTPUT_DIR / filename
    if not pdf_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV not found. It may have expired or never been generated.",
        )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename,
    )
