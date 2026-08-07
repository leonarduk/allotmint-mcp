"""Tests for the pure argument/formatting logic in client.py.

No live allotmint-mcp server, sidecar, or LLM required: session interaction is
covered by a fake session object, and the streamable-HTTP transport itself is
the mcp SDK's own responsibility, not this client's.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import client as client_module
import deps
from client import (
    ask,
    build_research_arguments,
    call_tool,
    format_exception,
    list_tools,
    missing_required_tools,
    parse_args,
    preflight,
    requested_dependencies,
    result_display,
    result_is_error,
    result_text,
)


def _content(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text)


def _result(text: str, is_error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(content=[_content(text)], isError=is_error)


class FakeSession:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result

    async def list_tools(self):
        return self.result


def test_build_research_arguments_includes_only_provided_fields():
    assert build_research_arguments("why?", None, None) == {
        "action": "ask",
        "question": "why?",
    }
    assert build_research_arguments("why?", "demo", 30) == {
        "action": "ask",
        "question": "why?",
        "owner": "demo",
        "lookback_days": 30,
    }


def test_result_text_joins_text_content_blocks():
    result = SimpleNamespace(content=[_content("line one"), _content("line two")])
    assert result_text(result) == "line one\nline two"


def test_result_text_handles_no_content():
    assert result_text(SimpleNamespace(content=[])) == "(no content returned)"
    assert result_text(SimpleNamespace()) == "(no content returned)"


def test_result_display_prefers_structured_content_over_stub_text():
    result = SimpleNamespace(
        content=[_content("AllotMint portfolio summary for owner steve returned successfully")],
        structuredContent={"total_value_gbp": 625156.28},
    )
    assert result_display(result) == json.dumps({"total_value_gbp": 625156.28}, indent=2, default=str)


def test_result_display_falls_back_to_text_without_structured_content():
    result = SimpleNamespace(content=[_content("line one"), _content("line two")])
    assert result_display(result) == "line one\nline two"


def test_result_text_ignores_structured_content_even_when_present():
    """allotmint_research sets structuredContent alongside its rendered prose

    (AllotMintResearchTool.java) - ask/the REPL must keep showing the prose,
    not the raw JSON duplicate, unlike result_display's --call path.
    """
    result = SimpleNamespace(
        content=[_content("Your portfolio is worth £625,156.28 [1].")],
        structuredContent={"answer": "Your portfolio is worth £625,156.28 [1]."},
    )
    assert result_text(result) == "Your portfolio is worth £625,156.28 [1]."


def test_result_is_error_checks_both_field_spellings():
    assert result_is_error(SimpleNamespace(isError=True)) is True
    assert result_is_error(SimpleNamespace(is_error=True)) is True
    assert result_is_error(SimpleNamespace(isError=False)) is False
    assert result_is_error(SimpleNamespace()) is False


@pytest.mark.asyncio
async def test_ask_calls_the_research_tool_with_built_arguments():
    session = FakeSession(_result("Technology rose from 18% to 27% [1].\n\nSources:\n[1] ..."))

    answer = await ask(session, "how has my tech exposure changed?", "demo", 90)

    assert session.calls == [
        (
            "allotmint_research",
            {"action": "ask", "question": "how has my tech exposure changed?", "owner": "demo", "lookback_days": 90},
        )
    ]
    assert answer.startswith("Technology rose")


@pytest.mark.asyncio
async def test_ask_prefixes_error_results():
    session = FakeSession(_result("question is required", is_error=True))

    answer = await ask(session, "?", None, None)

    assert answer == "Error: question is required"


@pytest.mark.asyncio
async def test_call_tool_passes_arguments_through_verbatim():
    session = FakeSession(_result('{"status": "ok"}'))

    output = await call_tool(session, "allotmint_health", {})

    assert session.calls == [("allotmint_health", {})]
    assert output == '{"status": "ok"}'


@pytest.mark.asyncio
async def test_list_tools_formats_name_and_description():
    session = FakeSession(
        SimpleNamespace(
            tools=[
                SimpleNamespace(name="allotmint_health", description="Checks connectivity."),
                SimpleNamespace(name="allotmint_research", description="Answers questions."),
            ]
        )
    )

    output = await list_tools(session)

    assert output == (
        "allotmint_health - Checks connectivity.\nallotmint_research - Answers questions."
    )


@pytest.mark.asyncio
async def test_list_tools_reports_when_the_server_exposes_nothing():
    session = FakeSession(SimpleNamespace(tools=[]))

    assert await list_tools(session) == "(server exposes no tools)"


def test_parse_args_defaults():
    args = parse_args([])

    assert args.question is None
    assert args.url == client_module.DEFAULT_MCP_URL
    assert args.owner is None
    assert args.lookback_days is None
    assert args.list_tools is False
    assert args.call is None
    assert args.args == "{}"
    assert args.research_url == client_module.DEFAULT_RESEARCH_URL
    assert args.skip_preflight is False


def test_parse_args_skip_preflight_and_research_url():
    args = parse_args(["--skip-preflight", "--research-url", "http://localhost:9100"])

    assert args.skip_preflight is True
    assert args.research_url == "http://localhost:9100"


def test_parse_args_start_flags_default_off():
    args = parse_args([])

    assert args.start_deps is False
    assert args.start_pgvector is False
    assert args.start_ollama is False
    assert args.start_mcp_server is False
    assert args.start_research_agent is False
    assert args.start_timeout == deps.DEFAULT_START_TIMEOUT


def test_parse_args_individual_start_flags():
    args = parse_args(["--start-ollama", "--start-mcp-server", "--start-timeout", "30"])

    assert args.start_ollama is True
    assert args.start_mcp_server is True
    assert args.start_pgvector is False
    assert args.start_timeout == 30.0


def test_requested_dependencies_start_deps_means_everything():
    args = parse_args(["--start-deps"])

    assert requested_dependencies(args) == set(deps.ALL_DEPENDENCIES)


def test_requested_dependencies_defaults_to_nothing():
    args = parse_args([])

    assert requested_dependencies(args) == set()


def test_requested_dependencies_combines_individual_flags():
    args = parse_args(["--start-pgvector", "--start-research-agent"])

    assert requested_dependencies(args) == {"pgvector", "research-agent"}


def test_parse_args_one_shot_question_with_flags():
    args = parse_args(
        [
            "how has my tech exposure changed?",
            "--owner",
            "demo",
            "--lookback-days",
            "30",
            "--url",
            "http://localhost:9999/mcp",
        ]
    )

    assert args.question == "how has my tech exposure changed?"
    assert args.owner == "demo"
    assert args.lookback_days == 30
    assert args.url == "http://localhost:9999/mcp"


def test_parse_args_call_with_json_args():
    args = parse_args(["--call", "allotmint_health", "--args", '{"action": "check"}'])

    assert args.call == "allotmint_health"
    assert args.args == '{"action": "check"}'


def test_format_exception_includes_type_and_message():
    assert format_exception(ValueError("bad owner")) == "ValueError: bad owner"


def test_format_exception_falls_back_to_type_name_when_message_is_empty():
    assert format_exception(RuntimeError()) == "RuntimeError"


def test_format_exception_unwraps_a_taskgroup_style_exception_group():
    group = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [ConnectionRefusedError("[Errno 61] Connection refused")],
    )

    assert format_exception(group) == (
        "ConnectionRefusedError: [Errno 61] Connection refused"
    )


def test_format_exception_unwraps_nested_and_multiple_sub_exceptions():
    group = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [
            ValueError("first"),
            ExceptionGroup("nested", [TimeoutError("second")]),
        ],
    )

    assert format_exception(group) == "ValueError: first; TimeoutError: second"


def _mcp_error_class():
    """The installed SDK's JSON-RPC error class, whether it's McpError or MCPError."""
    import mcp.shared.exceptions as exceptions

    return getattr(exceptions, "MCPError", None) or getattr(exceptions, "McpError")


def _make_mcp_error(error_cls, code: int, message: str):
    """Construct an MCP error, compatible with both old and new SDK constructors.

    Newer SDK:  McpError(ErrorData(code=..., message=...))
    Older SDK:  MCPError(code=..., message=...)
    """
    try:
        from mcp.types import ErrorData

        return error_cls(ErrorData(code=code, message=message))
    except TypeError:
        return error_cls(code=code, message=message)


def test_format_exception_appends_mcp_error_data():
    error_cls = _mcp_error_class()

    # Real-world case: the server's "unknown tool" error hardcodes its message
    # to "Unknown tool: invalid_tool_name" no matter what was actually
    # requested (io.modelcontextprotocol.sdk:mcp-core McpAsyncServer bug) - the
    # real tool name only shows up in `data`.
    error = _make_mcp_error(error_cls, -32602, "Unknown tool: invalid_tool_name")
    error.error.data = "Tool not found: allotmint_research"

    assert format_exception(error) == (
        f"{error_cls.__name__}: Unknown tool: invalid_tool_name"
        " (Tool not found: allotmint_research)"
    )


def test_format_exception_skips_the_parenthetical_when_mcp_error_has_no_data():
    error_cls = _mcp_error_class()

    error = _make_mcp_error(error_cls, -32602, "Something else went wrong")

    assert format_exception(error) == f"{error_cls.__name__}: Something else went wrong"


def test_missing_required_tools_reports_only_what_is_absent():
    assert missing_required_tools(set(client_module.REQUIRED_TOOLS)) == []
    assert missing_required_tools({"allotmint_health"}) == [
        "allotmint_research",
        "allotmint_portfolio",
        "allotmint_instrument",
        "allotmint_market",
    ]


def _tools_session(names: list[str]) -> FakeSession:
    return FakeSession(SimpleNamespace(tools=[SimpleNamespace(name=n, description="") for n in names]))


@pytest.mark.asyncio
async def test_preflight_reports_missing_tools_without_checking_the_sidecar(monkeypatch):
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("should not check the sidecar when tools are missing")

    monkeypatch.setattr(client_module, "fetch_research_agent_health", fail_if_called)
    session = _tools_session(["allotmint_health"])

    problems = await preflight(session, client_module.DEFAULT_RESEARCH_URL, 5.0)

    assert len(problems) == 1
    assert "allotmint_research" in problems[0]
    assert "ALLOTMINT_MCP_RESEARCH_ENABLED" in problems[0]


@pytest.mark.asyncio
async def test_preflight_reports_an_unreachable_sidecar(monkeypatch, capsys):
    async def unreachable(research_url, timeout_seconds):
        raise ConnectionRefusedError("[Errno 111] Connection refused")

    monkeypatch.setattr(client_module, "fetch_research_agent_health", unreachable)
    session = _tools_session(list(client_module.REQUIRED_TOOLS))

    problems = await preflight(session, "http://localhost:8100", 5.0)

    assert len(problems) == 1
    assert "http://localhost:8100" in problems[0]
    assert "ConnectionRefusedError" in problems[0]
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_preflight_passes_and_prints_the_sidecar_config(monkeypatch, capsys):
    async def healthy(research_url, timeout_seconds):
        return {"status": "ok", "model": "ollama:llama3.2", "retrieval_enabled": True}

    monkeypatch.setattr(client_module, "fetch_research_agent_health", healthy)
    session = _tools_session(list(client_module.REQUIRED_TOOLS))

    problems = await preflight(session, client_module.DEFAULT_RESEARCH_URL, 5.0)

    assert problems == []
    output = capsys.readouterr().out
    assert "ollama:llama3.2" in output
    assert "retrieval_enabled=True" in output
