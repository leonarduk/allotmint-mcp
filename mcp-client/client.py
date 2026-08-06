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
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from contextlib import asynccontextmanager
from typing import Any

DEFAULT_MCP_URL = "http://localhost:8080/mcp"
RESEARCH_TOOL = "allotmint_research"


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
    return parser.parse_args(argv)


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


def result_is_error(result: Any) -> bool:
    return bool(getattr(result, "isError", False) or getattr(result, "is_error", False))


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


async def ask(session, question: str, owner: str | None, lookback_days: int | None) -> str:
    arguments = build_research_arguments(question, owner, lookback_days)
    result = await session.call_tool(RESEARCH_TOOL, arguments)
    text = result_text(result)
    return f"Error: {text}" if result_is_error(result) else text


async def call_tool(session, name: str, arguments: dict[str, Any]) -> str:
    result = await session.call_tool(name, arguments)
    text = result_text(result)
    return f"Error: {text}" if result_is_error(result) else text


async def repl(session, owner: str | None, lookback_days: int | None) -> None:
    print("Connected. Type a question for allotmint_research (blank line or Ctrl-D to quit).")
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
            print(f"Error: {exc}")
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

        if args.question:
            print(await ask(session, args.question, args.owner, args.lookback_days))
            return 0

        await repl(session, args.owner, args.lookback_days)
        return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
