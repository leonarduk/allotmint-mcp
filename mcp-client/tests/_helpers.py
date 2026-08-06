"""Shared test helpers for the mcp-client test suite.

FakeSession, _content, _result, and _fake_open_session are used by both
test_gradio_ui.py and test_webui.py to monkeypatch client.open_session
without requiring a live allotmint-mcp server or sidecar.

test_client.py has its own, simpler FakeSession with a different API and is
deliberately not refactored into this module — its session needs are
different (list_tools returns the result directly rather than wrapping it in
a SimpleNamespace).

Do not import client here: callers pass in the REQUIRED_TOOLS they need so
this module stays free of any dependency on the module-under-test.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace


def _content(text: str) -> SimpleNamespace:
    """Returns a SimpleNamespace mimicking a single MCP TextContent block."""
    return SimpleNamespace(text=text)


def _result(text: str, is_error: bool = False) -> SimpleNamespace:
    """Returns a SimpleNamespace mimicking an MCP CallToolResult."""
    return SimpleNamespace(content=[_content(text)], isError=is_error)


class FakeSession:
    """Async mock of an MCP ClientSession that records calls and returns canned results."""

    def __init__(self, result=None, tools=None, required_tools=()):
        self.result = result
        self.tools = tools if tools is not None else [
            SimpleNamespace(name=n, description="") for n in required_tools
        ]
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result

    async def list_tools(self):
        return SimpleNamespace(tools=self.tools)


def _fake_open_session(session: FakeSession):
    """Returns an async context manager that yields *session* in place of client.open_session."""

    @asynccontextmanager
    async def open_session(url, timeout_seconds):
        yield session

    return open_session
