"""Simple MCP client for testing the allotmint_research tool (issue #256).

Connects to a running allotmint-mcp server over the streamable-HTTP transport
- the same transport the research-agent sidecar itself uses to reach the four
v0 tools - and calls allotmint_research the way any real MCP client would.
This exists so testing the research agent doesn't require standing up Claude
Desktop or the MCP Inspector: one question in, one grounded answer out.

The LLM the research agent runs against (local Ollama or DeepSeek) is entirely
the sidecar's own configuration (see research-agent/README.md's Configuration
table); this client is transport-only and works unmodified against either.

Usage:
    pip install -r requirements.txt

    # one-shot
    python client.py "How has my tech exposure changed this year?" --owner demo

    # interactive REPL
    python client.py --owner demo

    # sanity-check the server without asking a question
    python client.py --list-tools

    # exercise a v0 tool directly
    python client.py --call allotmint_health --args "{}"

    # exercise a v0 tool with arguments (no owner needed for data quality)
    python client.py --call allotmint_data_quality --args '{"action": "issues"}'

    # start whatever isn't already running (pgvector, Ollama, the Java
    # server, the research-agent sidecar), then ask a question
    python client.py "..." --owner demo --start-deps
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from contextlib import asynccontextmanager
from typing import Any

import deps

DEFAULT_MCP_URL = deps.DEFAULT_MCP_URL
DEFAULT_RESEARCH_URL = deps.DEFAULT_RESEARCH_URL
RESEARCH_TOOL = "allotmint_research"
V0_TOOLS = (
    "allotmint_portfolio",
    "allotmint_instrument",
    "allotmint_market",
    "allotmint_health",
    "allotmint_data_quality",
)
REQUIRED_TOOLS = (RESEARCH_TOOL,) + V0_TOOLS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Minimal MCP client for testing the allotmint_research tool, and the "
            "underlying v0 tools, against a running allotmint-mcp server."
        )
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="Question to ask allotmint_research. Omit to start an interactive REPL.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_MCP_URL,
        help=f"allotmint-mcp streamable-HTTP endpoint (default: {DEFAULT_MCP_URL})",
    )
    parser.add_argument("--owner", help="Owner slug scoping portfolio lookups")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help="How far back retrieval considers dated documents (server default: 365)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Read timeout in seconds (default: 180, matching the sidecar's own agent-loop budget)",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List the tools the server exposes, then exit",
    )
    parser.add_argument(
        "--call",
        metavar="TOOL",
        help="Call an arbitrary tool instead of allotmint_research, e.g. to test a v0 tool directly",
    )
    parser.add_argument(
        "--args",
        metavar="JSON",
        default="{}",
        help="JSON object of arguments for --call (default: {})",
    )
    parser.add_argument(
        "--research-url",
        default=DEFAULT_RESEARCH_URL,
        help=(
            "research-agent sidecar base URL, used only for the startup prerequisite "
            f"check (default: {DEFAULT_RESEARCH_URL})"
        ),
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip the startup checks that verify the server and sidecar are ready before asking anything",
    )
    add_start_deps_args(parser)
    return parser.parse_args(argv)


def add_start_deps_args(parser: argparse.ArgumentParser) -> None:
    """Adds the --start-deps family of arguments to *parser*, for reuse across entrypoints.

    Both client.py and webui.py call this so the flags stay in one place; each
    entrypoint's own parse_args() still adds its own entrypoint-specific args.
    """
    parser.add_argument(
        "--start-deps",
        action="store_true",
        help="Best-effort start pgvector, Ollama, the allotmint-mcp server, and the research-agent "
        "sidecar if any aren't already running",
    )
    parser.add_argument(
        "--start-pgvector", action="store_true", help="Start pgvector alone if it isn't already running"
    )
    parser.add_argument(
        "--start-ollama", action="store_true", help="Start a local Ollama server if it isn't already running"
    )
    parser.add_argument(
        "--start-mcp-server",
        action="store_true",
        help="Start the allotmint-mcp server if it isn't already running (requires a prebuilt jar)",
    )
    parser.add_argument(
        "--start-research-agent",
        action="store_true",
        help="Start the research-agent sidecar if it isn't already running",
    )
    parser.add_argument(
        "--start-timeout",
        type=float,
        default=deps.DEFAULT_START_TIMEOUT,
        help=(
            "Seconds to wait for a started dependency to become ready "
            f"(default: {deps.DEFAULT_START_TIMEOUT}; a first-time research-agent image build may need more)"
        ),
    )


def requested_dependencies(args: argparse.Namespace) -> set[str]:
    """Which of deps.ALL_DEPENDENCIES the given flags ask to start, if not already running."""
    if args.start_deps:
        return set(deps.ALL_DEPENDENCIES)
    requested = set()
    if args.start_pgvector:
        requested.add("pgvector")
    if args.start_ollama:
        requested.add("ollama")
    if args.start_mcp_server:
        requested.add("mcp-server")
    if args.start_research_agent:
        requested.add("research-agent")
    return requested


def build_research_arguments(
    question: str, owner: str | None, lookback_days: int | None
) -> dict[str, Any]:
    """Builds the allotmint_research 'ask' arguments the server's schema expects."""
    arguments: dict[str, Any] = {"action": "ask", "question": question}
    if owner:
        arguments["owner"] = owner
    if lookback_days is not None:
        arguments["lookback_days"] = lookback_days
    return arguments


def result_text(result: Any) -> str:
    """Flattens an MCP CallToolResult's text content blocks into one string.

    The Java tool layer already renders allotmint_research's answer plus a
    numbered Sources list as text content (see AllotMintResearchTool.render),
    so there is deliberately no client-side re-formatting here - printing this
    verbatim is the whole job.
    """
    parts = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else "(no content returned)"


def result_display(result: Any) -> str:
    """Renders an MCP CallToolResult for `--call`'s diagnostic output.

    Unlike allotmint_research (see result_text), the four v0 tools' text
    content is just a one-line confirmation ("AllotMint portfolio summary for
    owner steve returned successfully") - the real data, the numbers a user
    would actually want to see, lives in structuredContent instead. Preferring
    structured content when present (mirrors research-agent/app/mcp_tools.py's
    _result_to_text) is what makes `--call` useful for looking at what a v0
    tool actually returns, rather than just its stub confirmation text.

    Not used for `ask`/the REPL: allotmint_research also sets structuredContent
    (duplicating the same data for machine consumers per
    AllotMintResearchTool.java's javadoc), so unconditionally preferring it
    there would replace the rendered prose answer with a raw JSON dump.
    """
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if structured:
        return json.dumps(structured, indent=2, default=str)
    return result_text(result)


def result_is_error(result: Any) -> bool:
    return bool(getattr(result, "isError", False) or getattr(result, "is_error", False))


try:
    _EXCEPTION_GROUP: type | tuple[type, ...] = BaseExceptionGroup  # type: ignore[name-defined]
except NameError:  # pragma: no cover - only reachable before Python 3.11
    _EXCEPTION_GROUP = ()


def _mcp_error_types() -> tuple[type, ...]:
    """The MCP SDK's JSON-RPC error exception, under whichever name it has.

    Renamed McpError -> MCPError at some point; both are checked rather than
    pinning to whichever one a given pip install resolves.
    """
    import mcp.shared.exceptions as exceptions

    return tuple(
        cls
        for cls in (getattr(exceptions, "MCPError", None), getattr(exceptions, "McpError", None))
        if cls is not None
    )


def format_exception(exc: BaseException) -> str:
    """Renders an exception for display, unwrapping anyio TaskGroup noise.

    The MCP SDK's streamable-HTTP transport runs its read/write loops in an
    anyio TaskGroup, so a connection failure (server not running, wrong port,
    ...) surfaces as an ExceptionGroup whose own message is just "unhandled
    errors in a TaskGroup (1 sub-exception)" - true but useless. The actual
    cause is one level inside it.

    A server-side JSON-RPC error for an unrecognized tool name is a second,
    unrelated trap: the allotmint-mcp server's underlying Java SDK
    (io.modelcontextprotocol.sdk:mcp-core, McpAsyncServer#toolsCallRequestHandler)
    has a bug where that error's message is always the literal string "Unknown
    tool: invalid_tool_name" regardless of which tool was actually requested -
    the real name only appears in the error's `data` field ("Tool not found:
    <name>"). Appending `data` when present is what makes this message
    actionable instead of actively misleading.
    """
    if isinstance(exc, _EXCEPTION_GROUP):
        leaves = [format_exception(sub) for sub in exc.exceptions]  # type: ignore[attr-defined]
        return "; ".join(leaves) if leaves else str(exc)

    base = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    if isinstance(exc, _mcp_error_types()):
        # Newer SDK: McpError wraps ErrorData; data lives on error.data
        # Older SDK: data was a direct attribute on the exception
        error_obj = getattr(exc, "error", None)
        if error_obj is not None:
            data = getattr(error_obj, "data", None)
        else:
            data = getattr(exc, "data", None)
        if data:
            return f"{base} ({data})"
    return base


def _streamable_http_client():
    """Returns the SDK's streamable-HTTP transport under whichever name it has.

    Mirrors research-agent/app/mcp_tools.py: the Python MCP SDK renamed
    streamablehttp_client to streamable_http_client, so both are supported
    rather than pinning to whichever one a given pip install resolves.
    """
    import mcp.client.streamable_http as transport

    return getattr(transport, "streamable_http_client", None) or getattr(
        transport, "streamablehttp_client"
    )


def _timeout_value(annotation: Any, seconds: float) -> Any:
    from datetime import timedelta

    if "timedelta" in str(annotation):
        return timedelta(seconds=seconds)
    return seconds


@asynccontextmanager
async def open_session(url: str, timeout_seconds: float):
    """Opens an MCP session against the allotmint-mcp server for this run."""
    from mcp import ClientSession

    factory = _streamable_http_client()
    factory_kwargs = {}
    factory_params = inspect.signature(factory).parameters
    if "timeout" in factory_params:
        factory_kwargs["timeout"] = _timeout_value(
            factory_params["timeout"].annotation, timeout_seconds
        )

    session_params = inspect.signature(ClientSession.__init__).parameters
    session_kwargs = {}
    if "read_timeout_seconds" in session_params:
        session_kwargs["read_timeout_seconds"] = _timeout_value(
            session_params["read_timeout_seconds"].annotation, timeout_seconds
        )

    async with factory(url, **factory_kwargs) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write, **session_kwargs) as session:
            await session.initialize()
            yield session


async def list_tools(session) -> str:
    response = await session.list_tools()
    lines = [f"{tool.name} - {tool.description}" for tool in response.tools]
    return "\n".join(lines) if lines else "(server exposes no tools)"


def missing_required_tools(tool_names: set[str]) -> list[str]:
    return [name for name in REQUIRED_TOOLS if name not in tool_names]


async def fetch_research_agent_health(research_url: str, timeout_seconds: float) -> dict:
    """Fetches the research-agent sidecar's own GET /health.

    Plain stdlib HTTP, not MCP: the sidecar isn't reachable through the
    allotmint-mcp server's tool surface, so this is the only way this client
    can tell it's up at all, or see which LLM it's actually configured to use.
    Mirrors the sidecar's own /health philosophy (research-agent/app/main.py):
    it reports configuration, it doesn't probe the LLM/database itself, so a
    200 here doesn't guarantee an `ask` will succeed - only that the process
    answering for allotmint_research is alive and reachable.
    """
    import urllib.request

    def _get() -> dict:
        url = f"{research_url.rstrip('/')}/health"
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
            return json.loads(response.read())

    return await asyncio.to_thread(_get)


async def preflight(session, research_url: str, timeout_seconds: float) -> list[str]:
    """Checks what allotmint_research needs before asking it anything.

    Two independent prerequisites can each be silently missing: the
    allotmint-mcp server may not have allotmint_research (or the v0 tools it
    chains) registered at all (ALLOTMINT_MCP_RESEARCH_ENABLED unset, or a
    server built before the tool existed), and even when it is registered,
    the research-agent sidecar behind it can be down or misconfigured. Either
    one otherwise only surfaces as a confusing error from inside a real
    question - see the "Unknown tool: invalid_tool_name" case in the README.
    Returns a list of human-readable problems; empty means everything checked
    out.
    """
    response = await session.list_tools()
    tool_names = {tool.name for tool in response.tools}
    missing = missing_required_tools(tool_names)
    if missing:
        return [
            "allotmint-mcp server is missing required tool(s): "
            + ", ".join(missing)
            + ". Check that ALLOTMINT_MCP_RESEARCH_ENABLED=true was set and that the "
            "server was built from a version that includes allotmint_research "
            "(issue #13, merged in #249) - run --list-tools to see what it actually exposes."
        ]

    try:
        health = await fetch_research_agent_health(research_url, timeout_seconds)
    except Exception as exc:  # noqa: BLE001 - reported to the user, not swallowed
        return [
            f"research-agent sidecar unreachable at {research_url}: {format_exception(exc)}. "
            "Is it running (cd research-agent && uvicorn app.main:app --port 8100)?"
        ]

    deps.log(
        "preflight: research-agent ready: model={model}, retrieval_enabled={retrieval_enabled}".format(
            model=health.get("model", "?"), retrieval_enabled=health.get("retrieval_enabled", "?")
        )
    )
    return []


async def ask(session, question: str, owner: str | None, lookback_days: int | None) -> str:
    arguments = build_research_arguments(question, owner, lookback_days)
    result = await session.call_tool(RESEARCH_TOOL, arguments)
    text = result_text(result)
    return f"Error: {text}" if result_is_error(result) else text


async def call_tool(session, name: str, arguments: dict[str, Any]) -> str:
    result = await session.call_tool(name, arguments)
    text = result_display(result)
    return f"Error: {text}" if result_is_error(result) else text


async def repl(session, owner: str | None, lookback_days: int | None) -> None:
    print("Type a question for allotmint_research (blank line or Ctrl-D to quit).")
    while True:
        try:
            question = input("> ").strip()
        except EOFError:
            print()
            return
        if not question:
            return
        try:
            print(await ask(session, question, owner, lookback_days))
        except Exception as exc:  # noqa: BLE001 - a REPL should survive one bad turn
            deps.log(f"ask failed: {format_exception(exc)}", level="ERROR")
        print()


async def run(args: argparse.Namespace) -> int:
    try:
        args_json = json.loads(args.args)
    except json.JSONDecodeError as exc:
        print(f"--args is not valid JSON: {exc}", file=sys.stderr)
        return 2

    async with open_session(args.url, args.timeout) as session:
        if args.list_tools:
            print(await list_tools(session))
            return 0

        if args.call:
            print(await call_tool(session, args.call, args_json))
            return 0

        # Only the ask/REPL paths need the full stack (research tool + sidecar);
        # --list-tools and --call are themselves diagnostic, so they run unchecked.
        if not args.skip_preflight:
            problems = await preflight(session, args.research_url, args.timeout)
            if problems:
                for problem in problems:
                    deps.log(f"preflight: {problem}", level="ERROR")
                return 1

        if args.question:
            print(await ask(session, args.question, args.owner, args.lookback_days))
            return 0

        await repl(session, args.owner, args.lookback_days)
        return 0


def _fix_console_encoding() -> None:
    """Forces stdout/stderr to UTF-8 so non-ASCII answer text prints correctly.

    Answers routinely contain currency symbols (£) and typographic punctuation
    from the LLM's own prose. Python's default stdout encoding on Windows
    comes from locale.getpreferredencoding() (cp1252 here - the same mismatch
    deps.py's _TEXT_KWARGS works around for subprocess output) rather than the
    terminal's actual codepage, so those bytes land wrong even though every
    character reaching this point is valid Unicode. reconfigure() is a no-op
    when stdout is already UTF-8, and the attribute is absent when a test
    harness has swapped in something other than a real TextIOWrapper - both
    cases are safe to skip.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _fix_console_encoding()
    args = parse_args(argv)

    which = requested_dependencies(args)
    if which:
        deps.ensure_running(args.url, args.research_url, args.start_timeout, which)

    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        deps.log(f"fatal: {format_exception(exc)}", level="ERROR")
        return 1


if __name__ == "__main__":
    sys.exit(main())
