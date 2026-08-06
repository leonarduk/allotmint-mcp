"""Stops allotmint_research's dependencies (the counterpart to client.py --start-deps).

pgvector and the research-agent sidecar are stopped via `docker compose stop`
(reversible - containers and volumes stay in place for next time). Ollama and
the allotmint-mcp server are only stopped if this tool's own --start-deps
started them in a prior run (tracked via the PID files spawn_background()
writes to mcp-client/logs/); anything else running on those ports -
Ollama installed as a system service, an allotmint-mcp you started by hand -
is left alone, and reported as still up rather than silently skipped.

Usage:
    python stop_deps.py                          # stop everything
    python stop_deps.py --ollama --mcp-server     # stop just these
"""

from __future__ import annotations

import argparse
import sys

import deps


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stop allotmint_research's dependencies (pgvector, Ollama, allotmint-mcp, research-agent)."
    )
    parser.add_argument(
        "--url",
        default=deps.DEFAULT_MCP_URL,
        help=f"allotmint-mcp streamable-HTTP endpoint, to find its port (default: {deps.DEFAULT_MCP_URL})",
    )
    parser.add_argument(
        "--research-url",
        default=deps.DEFAULT_RESEARCH_URL,
        help=f"research-agent sidecar base URL (default: {deps.DEFAULT_RESEARCH_URL})",
    )
    parser.add_argument("--pgvector", action="store_true", help="Stop only pgvector")
    parser.add_argument("--ollama", action="store_true", help="Stop only Ollama")
    parser.add_argument("--mcp-server", action="store_true", help="Stop only the allotmint-mcp server")
    parser.add_argument(
        "--research-agent", action="store_true", help="Stop only the research-agent sidecar"
    )
    return parser.parse_args(argv)


def selected_dependencies(args: argparse.Namespace) -> set[str]:
    """Which dependencies to stop: the ones flagged, or everything if none were."""
    chosen = {
        name
        for name, flag in (
            ("pgvector", args.pgvector),
            ("ollama", args.ollama),
            ("mcp-server", args.mcp_server),
            ("research-agent", args.research_agent),
        )
        if flag
    }
    return chosen or set(deps.ALL_DEPENDENCIES)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    which = selected_dependencies(args)

    problems = deps.stop_running(args.url, args.research_url, which)

    if problems:
        for problem in problems:
            print(f"Warning: {problem}", file=sys.stderr)
        return 1

    print("Stopped: " + ", ".join(sorted(which)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
