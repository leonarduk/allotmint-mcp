"""Tests for the browser UI (webui.py, issue #302).

No live allotmint-mcp server, sidecar, or LLM required: client.open_session
is monkeypatched to a fake async context manager wrapping the same
FakeSession pattern test_client.py uses, so these only cover the HTTP layer
webui.py adds on top of client.py's already-tested ask/list_tools/call_tool.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import client as client_module
import webui
from tests._helpers import FakeSession, _content, _fake_open_session, _result


@pytest.fixture
def test_client():
    return TestClient(webui.app)


# ------------------------------------------------------------------ GET /


def test_index_serves_the_form(test_client):
    response = test_client.get("/")

    assert response.status_code == 200
    assert "Ask allotmint_research" in response.text
    assert "List tools" in response.text


# -------------------------------------------------------------- POST /api/ask


def test_api_ask_returns_the_answer(monkeypatch, test_client):
    session = FakeSession(
        result=_result("Technology rose from 18% to 27% [1]."),
        required_tools=client_module.REQUIRED_TOOLS,
    )
    monkeypatch.setattr(client_module, "open_session", _fake_open_session(session))

    async def healthy(research_url, timeout_seconds):
        return {"status": "ok", "model": "ollama:llama3.2", "retrieval_enabled": True}

    monkeypatch.setattr(client_module, "fetch_research_agent_health", healthy)

    response = test_client.post(
        "/api/ask",
        json={"question": "how has my tech exposure changed?", "owner": "demo"},
    )

    assert response.status_code == 200
    assert response.json() == {"answer": "Technology rose from 18% to 27% [1]."}
    assert session.calls == [
        (
            "allotmint_research",
            {
                "action": "ask",
                "question": "how has my tech exposure changed?",
                "owner": "demo",
            },
        )
    ]


def test_api_ask_skips_preflight_when_requested(monkeypatch, test_client):
    session = FakeSession(result=_result("answer"), tools=[])
    monkeypatch.setattr(client_module, "open_session", _fake_open_session(session))

    async def fail_if_called(research_url, timeout_seconds):
        raise AssertionError("should not check the sidecar when preflight is skipped")

    monkeypatch.setattr(client_module, "fetch_research_agent_health", fail_if_called)

    response = test_client.post(
        "/api/ask", json={"question": "?", "skip_preflight": True}
    )

    assert response.status_code == 200
    assert response.json() == {"answer": "answer"}


def test_api_ask_reports_preflight_problems(monkeypatch, test_client):
    session = FakeSession(
        tools=[SimpleNamespace(name="allotmint_health", description="")]
    )
    monkeypatch.setattr(client_module, "open_session", _fake_open_session(session))

    response = test_client.post("/api/ask", json={"question": "?"})

    assert response.status_code == 409
    assert "allotmint_research" in response.json()["detail"]
    assert session.calls == []


def test_api_ask_reports_connection_failures(monkeypatch, test_client):
    @asynccontextmanager
    async def broken_session(url, timeout_seconds):
        raise ConnectionRefusedError("[Errno 111] Connection refused")
        yield  # pragma: no cover - unreachable, keeps this an async generator

    monkeypatch.setattr(client_module, "open_session", broken_session)

    response = test_client.post(
        "/api/ask", json={"question": "?", "skip_preflight": True}
    )

    assert response.status_code == 502
    assert "ConnectionRefusedError" in response.json()["detail"]


# ------------------------------------------------------------ POST /api/tools


def test_api_tools_lists_names_and_descriptions(monkeypatch, test_client):
    session = FakeSession(
        tools=[
            SimpleNamespace(name="allotmint_health", description="Checks connectivity."),
            SimpleNamespace(name="allotmint_research", description="Answers questions."),
        ]
    )
    monkeypatch.setattr(client_module, "open_session", _fake_open_session(session))

    response = test_client.post("/api/tools", json={})

    assert response.status_code == 200
    assert response.json() == {
        "tools": "allotmint_health - Checks connectivity.\nallotmint_research - Answers questions."
    }


def test_api_tools_reports_connection_failures(monkeypatch, test_client):
    @asynccontextmanager
    async def broken_session(url, timeout_seconds):
        raise ConnectionRefusedError("[Errno 111] Connection refused")
        yield  # pragma: no cover

    monkeypatch.setattr(client_module, "open_session", broken_session)

    response = test_client.post("/api/tools", json={})

    assert response.status_code == 502
    assert "ConnectionRefusedError" in response.json()["detail"]


# ------------------------------------------------------------ POST /api/call


def test_api_call_passes_arguments_through(monkeypatch, test_client):
    session = FakeSession(
        result=_result('{"status": "ok"}'),
        required_tools=client_module.REQUIRED_TOOLS,
    )
    monkeypatch.setattr(client_module, "open_session", _fake_open_session(session))

    response = test_client.post(
        "/api/call", json={"tool": "allotmint_health", "args": {}}
    )

    assert response.status_code == 200
    assert response.json() == {"output": '{"status": "ok"}'}
    assert session.calls == [("allotmint_health", {})]


def test_api_call_reports_connection_failures(monkeypatch, test_client):
    @asynccontextmanager
    async def broken_session(url, timeout_seconds):
        raise ConnectionRefusedError("[Errno 111] Connection refused")
        yield  # pragma: no cover

    monkeypatch.setattr(client_module, "open_session", broken_session)

    response = test_client.post(
        "/api/call", json={"tool": "allotmint_health", "args": {}}
    )

    assert response.status_code == 502
    assert "ConnectionRefusedError" in response.json()["detail"]


# ------------------------------------------------------------- render / args


def test_render_index_prefills_the_configured_urls():
    original = dict(webui.DEFAULTS)
    try:
        webui.DEFAULTS["url"] = "http://example.invalid:8080/mcp"
        html = webui.render_index()
        assert "http://example.invalid:8080/mcp" in html
    finally:
        webui.DEFAULTS.update(original)


def test_parse_args_defaults():
    args = webui.parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8600
    assert args.url == client_module.DEFAULT_MCP_URL
    assert args.research_url == client_module.DEFAULT_RESEARCH_URL


def test_parse_args_overrides():
    args = webui.parse_args(
        ["--host", "0.0.0.0", "--port", "9000", "--url", "http://x/mcp"]
    )

    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.url == "http://x/mcp"
