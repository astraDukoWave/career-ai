"""Pydantic schemas for the Interview Copilot.

Per the layered-architecture rule: this module is Pydantic-ONLY. No SQLAlchemy
imports here. These models describe the shape of HTTP request bodies for
/api/interview/* — the SSE response is plain text/event-stream so it has no
matching Pydantic schema.
"""

from pydantic import BaseModel, Field


class InterviewTextRequest(BaseModel):
    """POST /api/interview/text body.

    `text` is whatever the interviewer just said, already in textual form
    (audio / WebSocket support is Phase 2 of this sprint).
    """

    text: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The interviewer's prompt as plain text.",
    )
