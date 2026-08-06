"""Tests for stop_deps.py's argument handling.

The actual stopping is deps.stop_running, already covered by test_deps.py;
these only check that stop_deps.py's CLI wires flags to the right set of
dependency names.
"""

from __future__ import annotations

import deps
from stop_deps import parse_args, selected_dependencies


def test_parse_args_defaults():
    args = parse_args([])

    assert args.url == deps.DEFAULT_MCP_URL
    assert args.research_url == deps.DEFAULT_RESEARCH_URL
    assert args.pgvector is False
    assert args.ollama is False
    assert args.mcp_server is False
    assert args.research_agent is False


def test_selected_dependencies_defaults_to_everything():
    args = parse_args([])

    assert selected_dependencies(args) == set(deps.ALL_DEPENDENCIES)


def test_selected_dependencies_narrows_to_flagged_ones():
    args = parse_args(["--ollama", "--mcp-server"])

    assert selected_dependencies(args) == {"ollama", "mcp-server"}


def test_parse_args_accepts_custom_urls():
    args = parse_args(["--url", "http://localhost:9999/mcp", "--research-url", "http://localhost:9100"])

    assert args.url == "http://localhost:9999/mcp"
    assert args.research_url == "http://localhost:9100"
