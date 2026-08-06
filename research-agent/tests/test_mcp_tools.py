"""Tests for the MCP tool proxy: the read-only boundary and the call record."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.mcp_tools import ToolCallRejected, ToolSession


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
