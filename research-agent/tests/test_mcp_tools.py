"""Tests for the MCP tool proxy: the read-only boundary and the call record."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.mcp_tools import MAX_TOOL_RESULT_CHARS, ToolCallRejected, ToolSession


@dataclass
class _Content:
    text: str


class _FakeSession:
    """Stands in for an `mcp.ClientSession`, recording what it was asked for."""

    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.received: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments):
        self.received.append((name, arguments))
        if self.error is not None:
            raise self.error
        return self.result


class _Result:
    def __init__(self, structured=None, content=None):
        self.structuredContent = structured
        self.content = content or []


@pytest.mark.asyncio
async def test_calls_an_allowlisted_tool_and_records_it(settings):
    fake = _FakeSession(_Result(structured={"action": "exposure", "sectors": []}))
    session = ToolSession(settings=settings, session=fake)

    text = await session.call_tool("allotmint_portfolio", {"action": "exposure", "owner": "demo"})

    assert json.loads(text)["action"] == "exposure"
    assert fake.received == [("allotmint_portfolio", {"action": "exposure", "owner": "demo"})]
    assert session.calls[0].tool == "allotmint_portfolio"
    assert session.calls[0].arguments == {"action": "exposure", "owner": "demo"}


@pytest.mark.asyncio
async def test_none_valued_arguments_are_dropped(settings):
    # The typed wrappers default optional arguments to None; forwarding those
    # would trip the v0 tools' additionalProperties/minLength constraints.
    fake = _FakeSession(_Result(structured={"ok": True}))
    session = ToolSession(settings=settings, session=fake)

    await session.call_tool(
        "allotmint_instrument", {"action": "news", "ticker": "NVDA", "query": None}
    )

    assert fake.received == [("allotmint_instrument", {"action": "news", "ticker": "NVDA"})]


@pytest.mark.asyncio
async def test_null_and_none_string_arguments_are_dropped(settings):
    fake = _FakeSession(_Result(structured={"ok": True}))
    session = ToolSession(settings=settings, session=fake)

    await session.call_tool(
        "allotmint_portfolio",
        {
            "action": "summary",
            "owner": "demo",
            "account_type": "NULL",
            "currency": " none ",
            "label": "null-value",
        },
    )

    assert fake.received == [
        (
            "allotmint_portfolio",
            {"action": "summary", "owner": "demo", "label": "null-value"},
        )
    ]


@pytest.mark.asyncio
async def test_a_tool_outside_the_allowlist_is_refused(settings):
    session = ToolSession(settings=settings, session=_FakeSession(_Result(structured={})))

    with pytest.raises(ToolCallRejected):
        await session.call_tool("allotmint_files", {"action": "read", "path": "x"})


@pytest.mark.asyncio
async def test_the_agent_cannot_recurse_into_itself(settings):
    # allotmint_research is deliberately absent from the allowlist.
    session = ToolSession(settings=settings, session=_FakeSession(_Result(structured={})))

    with pytest.raises(ToolCallRejected):
        await session.call_tool("allotmint_research", {"action": "ask", "question": "why?"})


@pytest.mark.asyncio
async def test_the_call_budget_is_enforced(settings):
    fake = _FakeSession(_Result(structured={"ok": True}))
    session = ToolSession(settings=settings, session=fake)

    for _ in range(settings.max_tool_calls):
        await session.call_tool("allotmint_market", {"action": "overview"})

    text = await session.call_tool("allotmint_market", {"action": "movers"})

    assert "budget exhausted" in text
    # The refused call never reached the server, and never became a citation.
    assert len(fake.received) == settings.max_tool_calls
    assert len(session.calls) == settings.max_tool_calls


@pytest.mark.asyncio
async def test_a_failing_tool_call_is_reported_not_swallowed(settings):
    fake = _FakeSession(error=RuntimeError("connection reset"))
    session = ToolSession(settings=settings, session=fake)

    text = await session.call_tool("allotmint_health", {})

    assert "connection reset" in text
    # Recorded too: the model saw the failure, so the failure is citable.
    assert session.calls[0].tool == "allotmint_health"


@pytest.mark.asyncio
async def test_text_content_is_used_when_there_is_no_structured_content(settings):
    fake = _FakeSession(_Result(content=[_Content("AllotMint backend reachable")]))
    session = ToolSession(settings=settings, session=fake)

    assert await session.call_tool("allotmint_health", {}) == "AllotMint backend reachable"


class _FakeTraceLogger:
    """Records the arguments `tool_call_end` was invoked with."""

    def __init__(self):
        self.tool_call_end_calls: list[dict] = []

    def tool_call_start(self, tool, arguments):
        pass

    def tool_call_end(self, tool, result_length, success, truncated=False):
        self.tool_call_end_calls.append(
            {
                "tool": tool,
                "result_length": result_length,
                "success": success,
                "truncated": truncated,
            }
        )


@pytest.mark.asyncio
async def test_an_oversized_structured_result_is_truncated_with_a_marker(settings):
    # A long performance.history array is exactly the shape called out in the
    # issue: a payload dominated by one big array alongside small scalars.
    oversized = {
        "action": "summary",
        "total_value_gbp": 123456.78,
        "performance": {
            "history": [
                {"date": f"2024-{(day % 12) + 1:02d}-{(day % 28) + 1:02d}", "value": 1000.0 + day, "note": "daily snapshot"}
                for day in range(1, 400)
            ]
        },
    }
    trace_logger = _FakeTraceLogger()
    fake = _FakeSession(_Result(structured=oversized))
    session = ToolSession(settings=settings, session=fake, trace_logger=trace_logger)

    text = await session.call_tool("allotmint_portfolio", {"action": "summary", "owner": "demo"})

    assert len(text) <= MAX_TOOL_RESULT_CHARS + 100  # marker adds a little overhead
    assert "truncated" in text
    # The result must still be valid, parseable JSON -- the whole point of
    # eliding arrays instead of cutting mid-token.
    parsed = json.loads(text)
    assert parsed["total_value_gbp"] == 123456.78
    assert parsed["action"] == "summary"
    history = parsed["performance"]["history"]
    assert len(history) == 4  # 3 kept items + one elision marker
    assert "truncated" in history[-1]

    # Observable via tracing: truncated=True is recorded, not silent.
    assert trace_logger.tool_call_end_calls[-1]["truncated"] is True
    assert trace_logger.tool_call_end_calls[-1]["result_length"] == len(text)


@pytest.mark.asyncio
async def test_a_huge_scalar_field_falls_back_to_a_json_safe_envelope(settings):
    # Array elision alone can't help here: the oversized content is one huge
    # scalar string, not a long array. This is exactly the fallback path
    # DeepSeek's review flagged -- `_cap_text`'s old blind slice-plus-marker
    # would cut this JSON text mid-token and append a non-JSON suffix,
    # producing a string the model could no longer parse (issue #546).
    oversized = {
        "action": "news",
        "ticker": "NVDA",
        "summary": "x" * (MAX_TOOL_RESULT_CHARS * 3),
    }
    trace_logger = _FakeTraceLogger()
    fake = _FakeSession(_Result(structured=oversized))
    session = ToolSession(settings=settings, session=fake, trace_logger=trace_logger)

    text = await session.call_tool("allotmint_instrument", {"action": "news", "ticker": "NVDA"})

    # Within budget including whatever marker/envelope overhead was added.
    assert len(text) <= MAX_TOOL_RESULT_CHARS + 100
    # Must still be valid, parseable JSON -- the whole point of the fix.
    parsed = json.loads(text)
    assert parsed["_truncated"] is True
    assert parsed["original_length"] > MAX_TOOL_RESULT_CHARS
    assert isinstance(parsed["preview"], str)

    assert trace_logger.tool_call_end_calls[-1]["truncated"] is True


@pytest.mark.asyncio
async def test_a_small_structured_result_is_not_truncated(settings):
    trace_logger = _FakeTraceLogger()
    fake = _FakeSession(_Result(structured={"action": "exposure", "sectors": []}))
    session = ToolSession(settings=settings, session=fake, trace_logger=trace_logger)

    text = await session.call_tool("allotmint_portfolio", {"action": "exposure", "owner": "demo"})

    assert "truncated" not in text
    assert trace_logger.tool_call_end_calls[-1]["truncated"] is False
