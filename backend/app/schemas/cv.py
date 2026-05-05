"""Pydantic schemas for the CV Engine.

Per the layered-architecture rule: this module is Pydantic-ONLY. No SQLAlchemy
imports here, ever. These models describe the shape of HTTP request/response
bodies for /api/cv/*.
"""

from pydantic import BaseModel, Field


# =============================================================================
# Sub-models — building blocks for the user profile
# =============================================================================


class ExperienceItem(BaseModel):
    """One work experience entry. `bullets` are short achievement statements
    that the LLM may rewrite to better match the job posting keywords."""

    title: str = Field(..., description="Job title, e.g. 'Senior Backend Engineer'")
    company: str
    start_date: str = Field(..., description="Free-text date, e.g. '2022-01' or 'Jan 2022'")
    end_date: str = Field(default="Present")
    bullets: list[str] = Field(
        default_factory=list,
        description="Achievement bullets. Verb + metric encouraged.",
    )


class EducationItem(BaseModel):
    degree: str
    institution: str
    year: str


# =============================================================================
# User profile (input half of the request)
# =============================================================================


class UserProfile(BaseModel):
    """Everything the CV needs about the candidate."""

    name: str
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    headline: str | None = Field(
        default=None,
        description="Optional one-line tagline. If empty, the job title is used.",
    )
    experience: list[ExperienceItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)


# =============================================================================
# Request / response envelopes
# =============================================================================


class CVRequest(BaseModel):
    """POST /api/cv/generate body."""

    job_posting: str = Field(
        ...,
        min_length=20,
        description="Raw text of the job posting (paste from LinkedIn/etc).",
    )
    user_profile: UserProfile


class CVResponse(BaseModel):
    """Full output of a CV generation run."""

    cv_html: str = Field(..., description="Rendered HTML used to produce the PDF")
    cv_pdf_url: str = Field(
        ...,
        description="Relative URL to download the PDF, e.g. /api/cv/{filename}/pdf",
    )
    ats_score: float = Field(..., ge=0.0, le=1.0)
    matched_keywords: list[str]
    missing_keywords: list[str]
    rewritten: bool = Field(
        ...,
        description="True if bullets were rewritten by the LLM to lift the ATS score.",
    )
