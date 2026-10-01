"""Tests for the CareerAI MCP server (LB03-SPEC-01, AC-01 to AC-04).

No network and no API keys: every HTTP call goes to an httpx.MockTransport
injected with set_transport(), and the profile is a temp copy of
profile.example.json pointed to by CAREERAI_PROFILE.

The request bodies are also validated against the real Pydantic schemas in
backend/app/schemas (REQ-03): if the API contract changes, these tests fail
before a user's Claude does.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.server.mcpserver.exceptions import ToolError

from careerai_mcp import server as srv

MCP_DIR = Path(__file__).resolve().parents[1]
REPO = MCP_DIR.parent
EXAMPLE = MCP_DIR / "profile.example.json"
API = "https://careerai.test"
POSTING = "Backend Developer\nWe need Python, FastAPI and Docker for a remote team."
PDF_PATH = "/api/cv/cv-" + "a" * 32 + ".pdf/pdf"


def _load_schema(name: str):
    """Import backend/app/schemas/<name>.py by path (it only needs pydantic)."""
    spec = importlib.util.spec_from_file_location(f"careerai_schema_{name}", REPO / "backend/app/schemas" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(name: str, args: dict | None = None) -> dict:
    result = asyncio.run(srv.server.call_tool(name, args or {}))
    assert not result.is_error
    return result.structured_content


def sse(*events: tuple[str, dict]) -> str:
    return "".join(f"event: {event}\ndata: {json.dumps(data)}\n\n" for event, data in events)


@pytest.fixture
def profile(tmp_path, monkeypatch) -> dict:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    path = tmp_path / "careerai-profile.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CAREERAI_PROFILE", str(path))
    monkeypatch.setenv("CAREERAI_API_URL", API + "/")  # the trailing slash is trimmed
    return data


class FakeAPI:
    """Records every request and answers with `reply(request)`."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.reply = lambda request: httpx.Response(500)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.reply(request)


@pytest.fixture
def api():
    fake = FakeAPI()
    srv.set_transport(httpx.MockTransport(fake))
    yield fake
    srv.set_transport(None)


# ---------------------------------------------------------------------------
# AC-01 · generate_cv
# ---------------------------------------------------------------------------


def test_generate_cv_sends_the_profile_unchanged_and_returns_an_absolute_pdf_url(profile, api):
    api.reply = lambda request: httpx.Response(
        200,
        json={
            "cv_html": "<html>…</html>",
            "cv_pdf_url": PDF_PATH,
            "ats_score": 0.624,
            "matched_keywords": ["Python", "FastAPI"],
            "missing_keywords": ["Kubernetes"],
            "rewritten": False,
            "mismatch_warning": None,
            "job_title": "Backend Developer",
            "final_profile": profile,
        },
    )

    result = call("generate_cv", {"job_posting": POSTING})

    assert result == {
        "job_title": "Backend Developer",
        "ats_score_percent": 62,
        "matched_keywords": ["Python", "FastAPI"],
        "missing_keywords": ["Kubernetes"],
        "pdf_url": API + PDF_PATH,
        "mismatch_warning": None,
    }
    [request] = api.requests
    assert request.method == "POST"
    assert str(request.url) == API + "/api/cv/generate"
    body = json.loads(request.content)
    assert body == {"job_posting": POSTING, "user_profile": profile}  # REQ-02: unchanged
    _load_schema("cv").CVRequest.model_validate(body)  # REQ-03: the API accepts it
    assert request.extensions["timeout"]["read"] == srv.CV_TIMEOUT_S == 60.0  # NFR-01


def test_generate_cv_keeps_the_mismatch_warning(profile, api):
    api.reply = lambda request: httpx.Response(
        200,
        json={"cv_pdf_url": PDF_PATH, "ats_score": 0.12, "matched_keywords": [], "missing_keywords": ["SAP"],
              "mismatch_warning": "Low fit: this looks like an ERP role.", "job_title": "SAP Consultant"},
    )
    result = call("generate_cv", {"job_posting": POSTING})
    assert result["ats_score_percent"] == 12
    assert result["mismatch_warning"] == "Low fit: this looks like an ERP role."


# ---------------------------------------------------------------------------
# AC-02 · interview_suggestion
# ---------------------------------------------------------------------------


def test_interview_suggestion_joins_the_chunks_and_sends_the_profile_as_context(profile, api):
    api.reply = lambda request: httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=sse(
            ("meta", {"intent": "behavioral_star", "language": "en"}),
            ("chunk", {"content": "Situation: at Example Labs "}),
            ("chunk", {"content": "[your real example: a deadline you met]"}),
            ("done", {}),
        ),
    )

    result = call("interview_suggestion", {"question": "Tell me about a time you met a tight deadline."})

    assert result == {
        "intent": "behavioral_star",
        "language": "en",
        "suggestion": "Situation: at Example Labs [your real example: a deadline you met]",
    }
    [request] = api.requests
    assert str(request.url) == API + "/api/interview/text"
    body = json.loads(request.content)
    assert body["text"] == "Tell me about a time you met a tight deadline."
    context = body["context"]
    assert context["job_title"] == "" and context["job_posting"] == ""
    assert context["summary"] == profile["summary"]
    assert context["skills"] == profile["skills"]
    assert context["experience"][0] == {
        "title": "Backend Developer",
        "company": "Example Labs",
        "bullets": profile["experience"][0]["bullets"],
    }
    schema = _load_schema("interview")
    schema.InterviewTextRequest.model_validate(body)  # REQ-03
    assert set(context) <= set(schema.InterviewContext.model_fields)
    assert request.extensions["timeout"]["read"] == srv.SUGGESTION_TIMEOUT_S == 40.0  # NFR-01


def test_an_sse_error_event_becomes_a_tool_error_with_its_code(profile, api):
    api.reply = lambda request: httpx.Response(
        200,
        text=sse(
            ("meta", {"intent": "tech_concept", "language": "en"}),
            ("chunk", {"content": "partial"}),
            ("error", {"code": "rate_limit", "detail": "Gemini rate limit reached"}),
            ("done", {}),
        ),
    )
    with pytest.raises(ToolError, match=r"Suggestion failed \(rate_limit\): Gemini rate limit reached"):
        call("interview_suggestion", {"question": "What is a race condition?"})


def test_parse_sse_skips_malformed_frames_and_stops_at_done():
    body = (
        sse(("meta", {"intent": "tech_code", "language": "es"}), ("chunk", {"content": "uno "}))
        + "event: chunk\ndata: {not json}\n\n"
        + sse(("chunk", {"content": "dos"}), ("done", {}), ("chunk", {"content": " after done"}))
    )
    assert srv.parse_sse(body) == ({"intent": "tech_code", "language": "es"}, "uno dos")


def test_the_context_always_fits_the_api_caps():
    huge = {
        "name": "X",
        "summary": "s" * 9000,
        "skills": [f"skill {i} " + "k" * 700 for i in range(80)],
        "experience": [
            {"title": "t" * 400, "company": "c", "bullets": ["b" * 900] * 20 + ["", "   "]}
            for _ in range(8)
        ],
    }
    context = srv.build_context(huge)
    _load_schema("interview").InterviewContext.model_validate(context)  # would 422 otherwise
    assert len(context["skills"]) == 60 and len(context["experience"]) == 6
    assert all(len(role["bullets"]) == 12 for role in context["experience"])


# ---------------------------------------------------------------------------
# AC-03 · actionable errors
# ---------------------------------------------------------------------------


def test_missing_profile_variable(monkeypatch):
    monkeypatch.delenv("CAREERAI_PROFILE", raising=False)
    with pytest.raises(ToolError, match="CAREERAI_PROFILE is not set"):
        call("get_profile")


def test_profile_file_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREERAI_PROFILE", str(tmp_path / "nope.json"))
    with pytest.raises(ToolError, match=r"Profile file not found: .*nope\.json.*profile\.example\.json"):
        call("generate_cv", {"job_posting": POSTING})


def test_profile_with_invalid_json(tmp_path, monkeypatch):
    path = tmp_path / "broken.json"
    path.write_text("{name: oops", encoding="utf-8")
    monkeypatch.setenv("CAREERAI_PROFILE", str(path))
    with pytest.raises(ToolError, match="not valid JSON"):
        call("interview_suggestion", {"question": "Why us?"})


def test_profile_without_a_name(tmp_path, monkeypatch):
    path = tmp_path / "anon.json"
    path.write_text(json.dumps({"skills": ["Python"]}), encoding="utf-8")
    monkeypatch.setenv("CAREERAI_PROFILE", str(path))
    with pytest.raises(ToolError, match="at least a 'name'"):
        call("get_profile")


def test_a_422_lists_the_invalid_fields_without_echoing_profile_content(profile, api):
    api.reply = lambda request: httpx.Response(
        422,
        json={"detail": [{
            "type": "missing",
            "loc": ["body", "user_profile", "experience", 0, "start"],
            "msg": "Field required",
            "input": {"title": "PRIVATE-BULLET-TEXT"},
        }]},
    )
    with pytest.raises(ToolError) as caught:
        call("generate_cv", {"job_posting": POSTING})
    message = str(caught.value)
    assert "422" in message and "body.user_profile.experience.0.start: Field required" in message
    assert "profile.example.json" in message
    assert "PRIVATE-BULLET-TEXT" not in message  # tool errors reach the client's logs


@pytest.mark.parametrize("tool,args", [("generate_cv", {"job_posting": POSTING}),
                                       ("interview_suggestion", {"question": "Why us?"})])
def test_a_5xx_names_the_status_and_suggests_a_retry_without_retrying(profile, api, tool, args):
    api.reply = lambda request: httpx.Response(503, html="<html><body>Application error</body></html>")
    with pytest.raises(ToolError) as caught:
        call(tool, args)
    message = str(caught.value)
    assert "503" in message and "retry in a minute" in message and "<html" not in message
    assert len(api.requests) == 1  # NFR-01: no automatic retries


def test_a_timeout_is_explained(profile, api):
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    api.reply = slow
    with pytest.raises(ToolError, match="did not answer within 60 s"):
        call("generate_cv", {"job_posting": POSTING})


def test_an_unreachable_api_names_the_url(profile, api):
    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    api.reply = down
    with pytest.raises(ToolError, match="Could not reach CareerAI at https://careerai.test"):
        call("interview_suggestion", {"question": "Why us?"})


# ---------------------------------------------------------------------------
# AC-04 · tools, schemas and the stdio transport
# ---------------------------------------------------------------------------


def test_the_server_exposes_three_tools_with_their_schemas():
    tools = {tool.name: tool for tool in asyncio.run(srv.server.list_tools())}
    assert set(tools) == {"generate_cv", "interview_suggestion", "get_profile"}
    assert tools["generate_cv"].input_schema["required"] == ["job_posting"]
    assert tools["interview_suggestion"].input_schema["required"] == ["question"]
    assert tools["get_profile"].input_schema["properties"] == {}
    assert all(tool.description for tool in tools.values())
    assert "never present them as claims" in tools["generate_cv"].description


def test_get_profile_returns_the_file_verbatim(profile):
    assert call("get_profile") == profile


def test_a_real_stdio_session_initializes_lists_and_calls_tools(profile):
    async def session() -> tuple:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "careerai_mcp"], env=dict(os.environ), cwd=str(MCP_DIR)
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                init = await client.initialize()
                tools = await client.list_tools()
                result = await client.call_tool("get_profile", {})
                return init, tools, result

    init, tools, result = asyncio.run(asyncio.wait_for(session(), timeout=60))
    assert init.server_info.name == "careerai"
    assert "only source of facts" in init.instructions  # REQ-02
    assert sorted(tool.name for tool in tools.tools) == ["generate_cv", "get_profile", "interview_suggestion"]
    assert not result.is_error and result.structured_content == profile


def test_the_check_flag_lists_the_tools_and_exits_zero():
    done = subprocess.run(
        [sys.executable, "-m", "careerai_mcp", "--check"], capture_output=True, text=True, timeout=60, cwd=MCP_DIR
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "careerai-mcp tools: generate_cv, interview_suggestion, get_profile"
