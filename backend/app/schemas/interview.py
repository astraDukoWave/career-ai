"""Pydantic schemas for the Interview Copilot.

Per the layered-architecture rule: this module is Pydantic-ONLY. No SQLAlchemy
imports here. These models describe the shape of HTTP request bodies for
/api/interview/* — the SSE response is plain text/event-stream so it has no
matching Pydantic schema.
"""

from typing import Annotated

from pydantic import BaseModel, Field

# Hard caps reject absurd payloads with a 422. The real budget (8 KB,
# REQ-05) is enforced afterwards by deterministic truncation in
# app.services.interview_context, so a long but sane context never fails.
_Line = Annotated[str, Field(max_length=600)]


class ContextExperience(BaseModel):
    """One role from the candidate's last generated CV."""

    title: str = Field(default="", max_length=300)
    company: str = Field(default="", max_length=300)
    bullets: list[_Line] = Field(default_factory=list, max_length=12)


class InterviewContext(BaseModel):
    """What the copilot may state about the candidate (C2-SPEC-01, REQ-05).

    Filled by the browser from the last CV the user generated. It is the ONLY
    source of facts about the candidate the suggestion prompt may use
    (REQ-06).
    """

    job_title: str = Field(default="", max_length=300)
    job_posting: str = Field(default="", max_length=20_000)
    summary: str = Field(default="", max_length=4_000)
    skills: list[_Line] = Field(default_factory=list, max_length=60)
    experience: list[ContextExperience] = Field(default_factory=list, max_length=6)


class InterviewTextRequest(BaseModel):
    """POST /api/interview/text body.

    `text` is whatever the interviewer just said, already in textual form.
    `context` is optional: without it the copilot still answers, but every
    personal story or number comes back as a `[tu ejemplo real: …]` marker.
    """

    text: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The interviewer's prompt as plain text.",
    )
    context: InterviewContext | None = Field(
        default=None,
        description="Candidate context from the last generated CV (optional).",
    )
