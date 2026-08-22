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

# Bounds the text that actually enters the agent's context on every
# subsequent turn (as opposed to MAX_EXCERPT_CHARS, which only bounds the
# citation copy). Mirrors the MAX_DOC_CHARS convention used for retrieved
# RAG documents in agent.py -- tool results get a larger budget because they
# are often structured JSON rather than prose, but the principle is the same:
# a bounded amount of content per source, regardless of how large the
# underlying payload is.
MAX_TOOL_RESULT_CHARS = 4000

# Arrays longer than this are elided (kept-head + a marker) before falling
# back to a character cut, so a long list like performance.history doesn't
# eat the whole budget and, more importantly, doesn't get cut mid-element
# into invalid JSON.
MAX_ARRAY_ITEMS = 3


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
            text, truncated = _json_safe_cap(json.dumps({"error": f"tool call failed: {exc}"}))
            self.calls.append(
                ToolCallRecord(tool=name, arguments=cleaned, result_excerpt=text[:MAX_EXCERPT_CHARS])
            )
            if self.trace_logger is not None:
                self.trace_logger.tool_call_end(name, len(text), success=False, truncated=truncated)
            return text

        text, truncated = _result_to_text(result)
        self.calls.append(
            ToolCallRecord(tool=name, arguments=cleaned, result_excerpt=text[:MAX_EXCERPT_CHARS])
        )
        if self.trace_logger is not None:
            self.trace_logger.tool_call_end(name, len(text), success=True, truncated=truncated)
        return text


def _cap_text(text: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> tuple[str, bool]:
    """Blind character-cap fallback with a visible marker, never a silent cut.

    Only safe to use on plain (non-JSON) text: the marker is appended as raw
    text after the cut, so the result is not guaranteed to be valid JSON. For
    text that must remain parseable JSON, use `_json_safe_cap` instead.

    The marker itself counts against `max_chars` -- the returned string
    (preview + marker) never exceeds `max_chars`, so the caller's budget is
    honoured even after the marker is appended.
    """
    if len(text) <= max_chars:
        return text, False
    # The marker's length depends on `omitted`, which depends on how much of
    # the preview we keep, which depends on the marker's length -- resolve
    # that circularity with a couple of fixed-point passes (the digit count
    # of `omitted` only ever shrinks by one or two chars as the preview
    # shrinks, so this converges immediately in practice).
    preview_len = max_chars
    for _ in range(3):
        omitted = len(text) - preview_len
        marker = f"... [truncated, {omitted} chars omitted]"
        new_preview_len = max(0, max_chars - len(marker))
        if new_preview_len == preview_len:
            break
        preview_len = new_preview_len
    return text[:preview_len] + marker, True


def _json_safe_cap(text: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> tuple[str, bool]:
    """Fallback for text that must remain valid JSON (e.g. the serialized
    structured-content payload, after array elision still doesn't fit).

    `_cap_text` slices raw text and appends a plain-text marker, which is
    exactly wrong here: slicing JSON text mid-token and appending a non-JSON
    suffix produces a string that no longer parses as JSON, breaking the
    model's ability to parse the result (issue #546's acceptance criterion).
    Instead, this wraps a truncated preview of `text` as a *string value*
    inside a small JSON envelope, so the envelope itself always parses.
    """
    if len(text) <= max_chars:
        return text, False
    preview_len = max_chars
    while True:
        envelope = json.dumps(
            {
                "_truncated": True,
                "original_length": len(text),
                "preview": text[:preview_len],
            },
            default=str,
        )
        if len(envelope) <= max_chars or preview_len <= 0:
            return envelope, True
        # Shrink the preview by (at least) the overshoot and retry -- JSON
        # string escaping means shrinking the preview by N chars doesn't
        # always shrink the envelope by exactly N, so this can take a few
        # iterations, but each iteration strictly reduces preview_len.
        preview_len = max(0, preview_len - (len(envelope) - max_chars))


def _elide_long_arrays(value: Any) -> tuple[Any, bool]:
    """Recursively replaces arrays longer than MAX_ARRAY_ITEMS with a head
    slice plus a "[truncated, N item(s) omitted]" marker.

    This is the structure-aware half of the truncation strategy: eliding a
    long array (e.g. `performance.history`) keeps the rest of the payload's
    JSON valid, unlike a blind character cut that can slice mid-element.
    """
    truncated = False
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            elided, item_truncated = _elide_long_arrays(item)
            result[key] = elided
            truncated = truncated or item_truncated
        return result, truncated
    if isinstance(value, list):
        if len(value) > MAX_ARRAY_ITEMS:
            omitted = len(value) - MAX_ARRAY_ITEMS
            head = [_elide_long_arrays(item)[0] for item in value[:MAX_ARRAY_ITEMS]]
            return head + [f"[truncated, {omitted} item(s) omitted]"], True
        result_list = []
        for item in value:
            elided, item_truncated = _elide_long_arrays(item)
            result_list.append(elided)
            truncated = truncated or item_truncated
        return result_list, truncated
    return value, False


def _result_to_text(result: Any) -> tuple[str, bool]:
    """Flattens an MCP `CallToolResult` into the text the model should see,
    bounded to `MAX_TOOL_RESULT_CHARS` so a single oversized tool response
    cannot consume an unbounded share of the agent's context.

    Prefers structured content when the tool provides it (the v0 tools mostly
    do, and it is the machine-readable half), falling back to concatenated text
    content blocks otherwise. Both spellings of the field are checked: the
    Python MCP SDK renamed `structuredContent` to `structured_content`.

    Returns `(text, truncated)`: `truncated` is True whenever the returned
    text differs from the full untruncated serialization, whether that came
    from eliding long arrays, a fallback character cut, or both.
    """
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if structured:
        full = json.dumps(structured, default=str)
        if len(full) <= MAX_TOOL_RESULT_CHARS:
            return full, False
        # Structure-aware pass first: elide long arrays (e.g.
        # performance.history) so the result stays valid, parseable JSON
        # rather than being cut mid-token.
        elided, array_truncated = _elide_long_arrays(structured)
        text = json.dumps(elided, default=str)
        if len(text) <= MAX_TOOL_RESULT_CHARS:
            return text, array_truncated
        # Still too large (e.g. a single huge scalar field) -- a blind
        # character cut here would slice the JSON text itself and append a
        # non-JSON marker, producing a string that no longer parses. Wrap a
        # truncated preview in a small JSON envelope instead, so the result
        # is always valid JSON.
        text, _ = _json_safe_cap(text)
        return text, True

    parts = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    if parts:
        return _cap_text("\n".join(parts))
    return json.dumps({"error": "tool returned no content"}), False


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
