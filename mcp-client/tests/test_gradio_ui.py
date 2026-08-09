"""Tests for the Gradio UI (gradio_ui.py, issue #310).

No live allotmint-mcp server, sidecar, or LLM required: client.open_session
is monkeypatched to a fake async context manager wrapping the same
FakeSession pattern test_client.py/test_webui.py use, so these only cover
the ui_ask/ui_list_tools/ui_call_tool glue gradio_ui.py adds on top of
client.py's already-tested ask/list_tools/call_tool - the same functions the
Gradio buttons call directly as event handlers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import gradio as gr
import pytest

import client as client_module
import gradio_ui
from tests._helpers import FakeSession, _content, _fake_open_session, _result


# ------------------------------------------------------------------- ui_ask


@pytest.mark.asyncio
async def test_ui_ask_returns_the_answer(monkeypatch):
    session = FakeSession(
        result=_result("Technology rose from 18% to 27% [1]."),
        required_tools=client_module.REQUIRED_TOOLS,
    )
    monkeypatch.setattr(client_module, "open_session", _fake_open_session(session))

    async def healthy(research_url, timeout_seconds):
        return {"status": "ok", "model": "ollama:llama3.2", "retrieval_enabled": True}

    monkeypatch.setattr(client_module, "fetch_research_agent_health", healthy)

    answer = await gradio_ui.ui_ask(
        "how has my tech exposure changed?", "demo", None,
        client_module.DEFAULT_MCP_URL, client_module.DEFAULT_RESEARCH_URL, 180.0, False,
    )

    assert answer == "Technology rose from 18% to 27% [1]."
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


@pytest.mark.asyncio
async def test_ui_ask_requires_a_question():
    answer = await gradio_ui.ui_ask(
        "   ", "", None, client_module.DEFAULT_MCP_URL, client_module.DEFAULT_RESEARCH_URL, 180.0, False
    )

    assert answer == "Enter a question first."


@pytest.mark.asyncio
async def test_ui_ask_skips_preflight_when_requested(monkeypatch):
    session = FakeSession(result=_result("answer"), tools=[])
    monkeypatch.setattr(client_module, "open_session", _fake_open_session(session))

    async def fail_if_called(research_url, timeout_seconds):
        raise AssertionError("should not check the sidecar when preflight is skipped")

    monkeypatch.setattr(client_module, "fetch_research_agent_health", fail_if_called)

    answer = await gradio_ui.ui_ask(
        "?", "", None, client_module.DEFAULT_MCP_URL, client_module.DEFAULT_RESEARCH_URL, 180.0, True
    )

    assert answer == "answer"


@pytest.mark.asyncio
async def test_ui_ask_reports_preflight_problems(monkeypatch):
    session = FakeSession(tools=[SimpleNamespace(name="allotmint_health", description="")])
    monkeypatch.setattr(client_module, "open_session", _fake_open_session(session))

    answer = await gradio_ui.ui_ask(
        "?", "", None, client_module.DEFAULT_MCP_URL, client_module.DEFAULT_RESEARCH_URL, 180.0, False
    )

    assert "allotmint_research" in answer
    assert session.calls == []


@pytest.mark.asyncio
async def test_ui_ask_reports_connection_failures(monkeypatch):
    @asynccontextmanager
    async def broken_session(url, timeout_seconds):
        raise ConnectionRefusedError("[Errno 111] Connection refused")
        yield  # pragma: no cover - unreachable, keeps this an async generator

    monkeypatch.setattr(client_module, "open_session", broken_session)

    answer = await gradio_ui.ui_ask(
        "?", "", None, client_module.DEFAULT_MCP_URL, client_module.DEFAULT_RESEARCH_URL, 180.0, True
    )

    assert "ConnectionRefusedError" in answer


# ------------------------------------------------------------- ui_list_tools


@pytest.mark.asyncio
async def test_ui_list_tools_lists_names_and_descriptions(monkeypatch):
    session = FakeSession(
        tools=[
            SimpleNamespace(name="allotmint_health", description="Checks connectivity."),
            SimpleNamespace(name="allotmint_research", description="Answers questions."),
        ]
    )
    monkeypatch.setattr(client_module, "open_session", _fake_open_session(session))

    listing = await gradio_ui.ui_list_tools(client_module.DEFAULT_MCP_URL, 30.0)

    assert listing == (
        "allotmint_health - Checks connectivity.\nallotmint_research - Answers questions."
    )


@pytest.mark.asyncio
async def test_ui_list_tools_reports_connection_failures(monkeypatch):
    @asynccontextmanager
    async def broken_session(url, timeout_seconds):
        raise ConnectionRefusedError("[Errno 111] Connection refused")
        yield  # pragma: no cover

    monkeypatch.setattr(client_module, "open_session", broken_session)

    listing = await gradio_ui.ui_list_tools(client_module.DEFAULT_MCP_URL, 30.0)

    assert "ConnectionRefusedError" in listing


# -------------------------------------------------------------- ui_call_tool


@pytest.mark.asyncio
async def test_ui_call_tool_passes_arguments_through(monkeypatch):
    session = FakeSession(
        result=_result('{"status": "ok"}'),
        required_tools=client_module.REQUIRED_TOOLS,
    )
    monkeypatch.setattr(client_module, "open_session", _fake_open_session(session))

    output = await gradio_ui.ui_call_tool("allotmint_health", "{}", client_module.DEFAULT_MCP_URL, 180.0)

    assert output == '{"status": "ok"}'
    assert session.calls == [("allotmint_health", {})]


@pytest.mark.asyncio
async def test_ui_call_tool_requires_a_tool_name():
    output = await gradio_ui.ui_call_tool("  ", "{}", client_module.DEFAULT_MCP_URL, 180.0)

    assert output == "Enter a tool name first."


@pytest.mark.asyncio
async def test_ui_call_tool_reports_invalid_json():
    output = await gradio_ui.ui_call_tool("allotmint_health", "{not json", client_module.DEFAULT_MCP_URL, 180.0)

    assert "not valid JSON" in output


@pytest.mark.asyncio
async def test_ui_call_tool_reports_connection_failures(monkeypatch):
    @asynccontextmanager
    async def broken_session(url, timeout_seconds):
        raise ConnectionRefusedError("[Errno 111] Connection refused")
        yield  # pragma: no cover

    monkeypatch.setattr(client_module, "open_session", broken_session)

    output = await gradio_ui.ui_call_tool("allotmint_health", "{}", client_module.DEFAULT_MCP_URL, 180.0)

    assert "ConnectionRefusedError" in output


# ------------------------------------------------------------- build_app / args


def test_build_app_returns_blocks_with_the_configured_urls():
    url = "http://example.invalid:8080/mcp"
    research_url = "http://example.invalid:8100"
    demo = gradio_ui.build_app({"url": url, "research_url": research_url})

    assert isinstance(demo, gr.Blocks)

    # Verify the configured URLs landed in the right Textbox components.
    textboxes = [b for b in demo.blocks.values() if isinstance(b, gr.Textbox)]
    url_boxes = [b for b in textboxes if b.label == "allotmint-mcp URL"]
    research_boxes = [b for b in textboxes if b.label == "research-agent URL"]

    # Every "allotmint-mcp URL" field (in Ask / List tools / Call tabs)
    # should hold the configured URL.
    assert len(url_boxes) >= 1
    for box in url_boxes:
        assert box.value == url

    # The "research-agent URL" field in the Ask tab should hold the configured value.
    assert len(research_boxes) == 1
    assert research_boxes[0].value == research_url


def test_parse_args_defaults():
    args = gradio_ui.parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8601
    assert args.url == client_module.DEFAULT_MCP_URL
    assert args.research_url == client_module.DEFAULT_RESEARCH_URL
    assert args.share is False


def test_parse_args_overrides():
    args = gradio_ui.parse_args(
        ["--host", "0.0.0.0", "--port", "9000", "--url", "http://x/mcp", "--share"]
    )

    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.url == "http://x/mcp"
    assert args.share is True


def test_bootstrap_covers_the_direct_runtime_dependencies():
    assert gradio_ui.PYTHON_REQUIREMENTS == {
        "gradio": "gradio>=6.15.0,<7.0",
        "mcp": "mcp>=1.9",
    }
