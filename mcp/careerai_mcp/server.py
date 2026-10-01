"""CareerAI MCP server — use CareerAI from Claude Code or Claude Desktop.

LB03-SPEC-01. A thin client of the public CareerAI API (REQ-01): every piece of
logic (ATS score, PDF, interview suggestion) stays in the API. This module only
translates between MCP tools and HTTP, and reads the user's verifiable profile
from a local JSON file (REQ-02). It holds no secrets (NFR-02).

Configuration (environment variables only):
    CAREERAI_API_URL   API base URL (defaults to production).
    CAREERAI_PROFILE   Path to the profile JSON (same shape as
                       profile.example.json and the API's UserProfile).

The request bodies mirror backend/app/schemas/cv.py and interview.py (REQ-03):
a schema change there must be mirrored here, like frontend/src/api/client.ts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

DEFAULT_API_URL = "https://career-ai-95daf7c9a813.herokuapp.com"

# NFR-01: the CV Engine makes several Gemini calls and renders a PDF (and
# Heroku's router cuts any request at 30 s with a 503). Suggestions are capped
# by the API at 30 s. No retries: a suggestion is not idempotent for the user.
CV_TIMEOUT_S = 60.0
SUGGESTION_TIMEOUT_S = 40.0

# Caps of backend/app/schemas/interview.py (InterviewContext), so the
# suggestion context built from the profile never triggers a 422.
_MAX_LINE = 600
_MAX_SKILLS = 60
_MAX_BULLETS = 12
_MAX_ROLES = 6

INSTRUCTIONS = """CareerAI tailors CVs and suggests interview answers from the user's verifiable profile.
- The profile (get_profile) is the only source of facts about the user. Never add experience, companies, metrics or skills that are not in it.
- generate_cv returns missing keywords: present them as gaps the user may confirm, never as claims.
- interview_suggestion follows the same rule: placeholders such as [your real example: ...] mean the profile has no matching story."""

server = MCPServer("careerai", instructions=INSTRUCTIONS)

# Tests inject an httpx.MockTransport here; production uses the default.
_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the HTTP transport (tests only)."""
    global _transport
    _transport = transport


def api_url() -> str:
    return os.environ.get("CAREERAI_API_URL", DEFAULT_API_URL).rstrip("/")


def load_profile() -> dict[str, Any]:
    """Read the profile JSON pointed to by CAREERAI_PROFILE (EDGE-01)."""
    raw_path = os.environ.get("CAREERAI_PROFILE", "").strip()
    if not raw_path:
        raise ToolError(
            "CAREERAI_PROFILE is not set. Point it to your profile JSON "
            "(copy mcp/profile.example.json and fill in your real data)."
        )
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise ToolError(
            f"Profile file not found: {path}. Create it from mcp/profile.example.json."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ToolError(f"Profile file is not valid JSON ({path}): {err}") from err
    if not isinstance(data, dict) or not str(data.get("name", "")).strip():
        raise ToolError(
            "The profile must be a JSON object with at least a 'name' "
            "(same shape as mcp/profile.example.json)."
        )
    return data


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=api_url(), timeout=timeout, transport=_transport)


def _detail(response: httpx.Response) -> Any:
    """The API's JSON `detail`, or "" (Heroku error pages are HTML noise)."""
    try:
        body = response.json()
    except ValueError:
        return ""
    return body.get("detail", "") if isinstance(body, dict) else ""


def _validation_summary(detail: Any) -> str:
    """`body.user_profile.name: Field required; ...` from a FastAPI 422.

    Only the location and the message: FastAPI also echoes the offending
    `input`, which can be profile content, and tool errors end up in the
    client's logs (spec: the server never logs the profile).
    """
    if not isinstance(detail, list):
        return str(detail)[:300]
    parts = []
    for item in detail[:5]:
        if isinstance(item, dict):
            loc = ".".join(str(p) for p in item.get("loc", []))
            parts.append(f"{loc}: {item.get('msg', '')}".strip(": "))
    return "; ".join(parts)


def _http_error(response: httpx.Response) -> ToolError:
    """Turn a non-200 API response into an actionable tool error (EDGE-02/03)."""
    status = response.status_code
    if status == 422:
        return ToolError(
            f"CareerAI rejected the request (422): {_validation_summary(_detail(response))}. "
            "Check your profile against mcp/profile.example.json."
        )
    detail = _detail(response)
    if status >= 500:
        return ToolError(
            f"CareerAI API returned {status}: {detail or 'server error'}. "
            "If CareerAI was restarting or busy, retry in a minute."
        )
    return ToolError(f"CareerAI API returned {status}: {detail or response.reason_phrase}")


def _clip(value: Any, limit: int = _MAX_LINE) -> str:
    return str(value or "").strip()[:limit]


def build_context(profile: dict[str, Any]) -> dict[str, Any]:
    """Interview context from the profile, inside the API's hard caps."""
    experience = []
    for role in (profile.get("experience") or [])[:_MAX_ROLES]:
        experience.append(
            {
                "title": _clip(role.get("title"), 300),
                "company": _clip(role.get("company"), 300),
                "bullets": [_clip(b) for b in (role.get("bullets") or []) if str(b).strip()][:_MAX_BULLETS],
            }
        )
    return {
        "job_title": "",
        "job_posting": "",
        "summary": _clip(profile.get("summary"), 4000),
        "skills": [_clip(s) for s in (profile.get("skills") or []) if str(s).strip()][:_MAX_SKILLS],
        "experience": experience,
    }


def parse_sse(body: str) -> tuple[dict[str, Any], str]:
    """Parse the copilot stream: meta -> chunk* -> error? -> done (REQ-04)."""
    meta: dict[str, Any] = {}
    parts: list[str] = []
    for frame in body.split("\n\n"):
        event, data_lines = "message", []
        for line in frame.splitlines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data_lines.append(line[6:])
        if not data_lines and event == "message":
            continue
        try:
            data = json.loads("\n".join(data_lines)) if data_lines else {}
        except json.JSONDecodeError:
            continue
        if event == "meta":
            meta = data
        elif event == "chunk" and isinstance(data.get("content"), str):
            parts.append(data["content"])
        elif event == "error":
            raise ToolError(f"Suggestion failed ({data.get('code', 'unknown')}): {data.get('detail', '')}")
        elif event == "done":
            break
    return meta, "".join(parts)


@server.tool()
async def generate_cv(job_posting: str) -> dict[str, Any]:
    """Tailor the user's CV to a job posting with CareerAI.

    Sends the user's verifiable profile unchanged together with the posting.
    Returns the role title, the ATS score, matched and missing keywords and
    the PDF URL. Missing keywords are gaps: never present them as claims.
    """
    profile = load_profile()
    async with _client(CV_TIMEOUT_S) as client:
        try:
            response = await client.post(
                "/api/cv/generate", json={"job_posting": job_posting, "user_profile": profile}
            )
        except httpx.TimeoutException as err:
            raise ToolError(
                f"CareerAI did not answer within {CV_TIMEOUT_S:.0f} s. Retry in a minute."
            ) from err
        except httpx.HTTPError as err:
            raise ToolError(f"Could not reach CareerAI at {api_url()}: {err}") from err
    if response.status_code != 200:
        raise _http_error(response)
    try:
        data = response.json()
    except ValueError as err:
        raise ToolError("CareerAI returned a response that is not JSON. Retry in a minute.") from err
    pdf_path = data.get("cv_pdf_url") or ""
    return {
        "job_title": data.get("job_title", ""),
        "ats_score_percent": round(float(data.get("ats_score", 0)) * 100),
        "matched_keywords": data.get("matched_keywords", []),
        "missing_keywords": data.get("missing_keywords", []),
        # The API returns a relative path; Claude needs a link it can open.
        "pdf_url": api_url() + pdf_path if pdf_path else None,
        "mismatch_warning": data.get("mismatch_warning"),
    }


@server.tool()
async def interview_suggestion(question: str) -> dict[str, Any]:
    """Suggest an answer to an interview question, grounded in the user's profile.

    Uses CareerAI's interview copilot with the same anti-invention rules:
    personal stories come only from the profile, otherwise as placeholders.
    Returns the detected intent and language, and the suggestion text.
    """
    profile = load_profile()
    body = {"text": question, "context": build_context(profile)}
    async with _client(SUGGESTION_TIMEOUT_S) as client:
        try:
            response = await client.post("/api/interview/text", json=body)
        except httpx.TimeoutException as err:
            raise ToolError(f"No suggestion within {SUGGESTION_TIMEOUT_S:.0f} s. Please retry.") from err
        except httpx.HTTPError as err:
            raise ToolError(f"Could not reach CareerAI at {api_url()}: {err}") from err
    if response.status_code != 200:
        raise _http_error(response)
    meta, text = parse_sse(response.text)
    return {
        "intent": meta.get("intent", ""),
        "language": meta.get("language", ""),
        "suggestion": text,
    }


@server.tool()
async def get_profile() -> dict[str, Any]:
    """Return the user's verifiable profile exactly as stored in CAREERAI_PROFILE."""
    return load_profile()
