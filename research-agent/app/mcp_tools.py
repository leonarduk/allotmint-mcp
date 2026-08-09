"""MCP client for the four read-only v0 tools.

The agent reaches `allotmint_portfolio`, `allotmint_instrument`,
`allotmint_market`, and `allotmint_health` by being an ordinary MCP client of
the same allotmint-mcp server that exposes `allotmint_research`. That is what
"reuse the four existing v0 MCP tools as-is" means concretely: the portfolio
aggregation, filtering, and instrument lookups stay in the Java implementations
and are not reimplemented here.

Two safety properties are enforced in `call_tool`, not left to the prompt:

* Only names in `Settings.tools` can be invoked. `allotmint_research` is not in
  that allowlist, so the agent cannot recurse into itself, and no write-shaped
  tool added to the server later becomes reachable through this path by default.
* Every call is recorded before its result is returned, so the citation layer
  reports what the agent actually did rather than what it says it did.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .models import ToolCallRecord

log = logging.getLogger(__name__)

MAX_EXCERPT_CHARS = 400


class ToolCallRejected(RuntimeError):
    """Raised when the agent asks for a tool outside the read-only allowlist."""


@dataclass
class ToolSession:
    """A live MCP session plus the record of what was called through it."""

    settings: Settings
    session: Any
    calls: list[ToolCallRecord] = field(default_factory=list)
    trace_logger: Any | None = None

    @property
    def call_count(self) -> int:
        return len(self.calls)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Invokes one allowlisted v0 tool and returns its response as text.

        The text form is what goes back to the model: MCP tool responses are
        already JSON-shaped text content, and re-serializing them keeps the
        model looking at exactly the bytes we recorded as the citation.
        """
        if name not in self.settings.tools:
            raise ToolCallRejected(
                f"{name!r} is not one of the read-only tools this agent may call: "
                f"{', '.join(self.settings.tools)}"
            )
        if self.call_count >= self.settings.max_tool_calls:
            return json.dumps(
                {
                    "error": "tool call budget exhausted",
                    "detail": (
                        f"already made {self.call_count} calls (limit "
                        f"{self.settings.max_tool_calls}); answer from what you have"
                    ),
                }
            )

        cleaned = {
            k: v
            for k, v in arguments.items()
            if v is not None
            and not (isinstance(v, str) and v.strip().lower() in {"null", "none"})
        }
        log.info("agent -> %s(%s)", name, cleaned)

        if self.trace_logger is not None:
            self.trace_logger.tool_call_start(name, cleaned)

        try:
            result = await self.session.call_tool(name, cleaned)
        except Exception as exc:  # noqa: BLE001 - surfaced to the model, not swallowed
            text = json.dumps({"error": f"tool call failed: {exc}"})
            self.calls.append(
                ToolCallRecord(tool=name, arguments=cleaned, result_excerpt=text[:MAX_EXCERPT_CHARS])
            )
            if self.trace_logger is not None:
                self.trace_logger.tool_call_end(name, len(text), success=False)
            return text

        text = _result_to_text(result)
        self.calls.append(
            ToolCallRecord(tool=name, arguments=cleaned, result_excerpt=text[:MAX_EXCERPT_CHARS])
        )
        if self.trace_logger is not None:
            self.trace_logger.tool_call_end(name, len(text), success=True)
        return text


def _result_to_text(result: Any) -> str:
    """Flattens an MCP `CallToolResult` into the text the model should see.

    Prefers structured content when the tool provides it (the v0 tools mostly
    do, and it is the machine-readable half), falling back to concatenated text
    content blocks otherwise. Both spellings of the field are checked: the
    Python MCP SDK renamed `structuredContent` to `structured_content`.
    """
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if structured:
        return json.dumps(structured, default=str)

    parts = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    if parts:
        return "\n".join(parts)
    return json.dumps({"error": "tool returned no content"})


def _streamable_http_client():
    """Returns the SDK's streamable-HTTP transport under whichever name it has.

    The Python MCP SDK renamed `streamablehttp_client` to
    `streamable_http_client`. Supporting both keeps this service working across
    the SDK versions a `pip install` might resolve, rather than pinning an exact
    one just to survive a rename.
    """
    import mcp.client.streamable_http as transport

    factory = getattr(transport, "streamable_http_client", None) or getattr(
        transport, "streamablehttp_client"
    )
    return factory


def _timeout_value(annotation: Any, seconds: float) -> Any:
    """Coerces a timeout to whatever the installed SDK's signature expects."""
    from datetime import timedelta

    if "timedelta" in str(annotation):
        return timedelta(seconds=seconds)
    return seconds


@asynccontextmanager
async def open_session(
    settings: Settings, trace_logger: Any | None = None
):
    """Opens an MCP session against the allotmint-mcp server for one request.

    A session per request rather than a shared long-lived one: request volume
    here is low (each one runs a whole LLM loop), and per-request sessions keep
    concurrent runs from interleaving state on a single stream.
    """
    import inspect

    from mcp import ClientSession

    factory = _streamable_http_client()
    factory_kwargs = {}
    factory_params = inspect.signature(factory).parameters
    if "timeout" in factory_params:
        factory_kwargs["timeout"] = _timeout_value(
            factory_params["timeout"].annotation, settings.mcp_timeout_seconds
        )

    session_params = inspect.signature(ClientSession.__init__).parameters
    session_kwargs = {}
    if "read_timeout_seconds" in session_params:
        session_kwargs["read_timeout_seconds"] = _timeout_value(
            session_params["read_timeout_seconds"].annotation, settings.mcp_timeout_seconds
        )

    async with factory(settings.mcp_url, **factory_kwargs) as streams:
        # Older SDKs yield (read, write, get_session_id); newer yield (read, write).
        read, write = streams[0], streams[1]
        async with ClientSession(read, write, **session_kwargs) as session:
            await session.initialize()
            yield ToolSession(
                settings=settings, session=session, trace_logger=trace_logger
            )
