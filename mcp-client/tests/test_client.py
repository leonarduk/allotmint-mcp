"""Tests for the pure argument/formatting logic in client.py.

No live allotmint-mcp server, sidecar, or LLM required: session interaction is
covered by a fake session object, and the streamable-HTTP transport itself is
the mcp SDK's own responsibility, not this client's.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import client as client_module
from client import (
    ask,
    build_research_arguments,
    call_tool,
    list_tools,
    parse_args,
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
