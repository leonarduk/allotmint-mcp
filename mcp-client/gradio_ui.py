"""Locally hosted Gradio UI for the mcp-client (issue #310).

Wraps the same functions client.py's CLI uses - open_session, ask,
list_tools, call_tool, preflight, format_exception - behind a Gradio
Blocks app, replacing webui.py's hand-rolled HTML form with a proper,
modern interface. Nothing in client.py or deps.py is duplicated here;
this is a second entrypoint onto the same logic, not a second
implementation of it. The CLI (`python client.py ...`) is untouched and
keeps working exactly as before, and so does webui.py - this supersedes
it but doesn't remove it.

Usage:
    python gradio_ui.py
    python gradio_ui.py --port 8601 --url http://localhost:8080/mcp
    python gradio_ui.py --start-deps
"""

from __future__ import annotations

import argparse
import json
import sys

import deps

# Self-healing (issue #437): install the UI and MCP client packages before
# importing them.  deps.py is deliberately stdlib-only, so this bootstrap also
# works in a fresh or partially installed virtual environment.
PYTHON_REQUIREMENTS = {
    "gradio": "gradio>=6.15.0,<7.0",
    "mcp": "mcp>=1.9",
}
deps.ensure_python_packages(PYTHON_REQUIREMENTS)

import gradio as gr

import client

# Populated from CLI flags in main() before the server starts; only used to
# prefill the form's default values, exactly like client.py's own --url and
# --research-url defaults.
DEFAULTS = {"url": client.DEFAULT_MCP_URL, "research_url": client.DEFAULT_RESEARCH_URL}


async def ui_ask(
    question: str,
    owner: str,
    lookback_days: float | None,
    url: str,
    research_url: str,
    timeout: float,
    skip_preflight: bool,
) -> str:
    """Same path as the CLI's one-shot/REPL question: preflight, then ask."""
    if not question or not question.strip():
        return "Enter a question first."
    try:
        async with client.open_session(url.strip() or DEFAULTS["url"], timeout) as session:
            if not skip_preflight:
                problems = await client.preflight(
                    session, research_url.strip() or DEFAULTS["research_url"], timeout
                )
                if problems:
                    return "\n".join(problems)
            return await client.ask(
                session,
                question,
                owner.strip() or None,
                int(lookback_days) if lookback_days else None,
            )
    except Exception as exc:  # noqa: BLE001 - reported to the caller, not swallowed
        return client.format_exception(exc)


async def ui_list_tools(url: str, timeout: float) -> str:
    """Same path as the CLI's --list-tools."""
    try:
        async with client.open_session(url.strip() or DEFAULTS["url"], timeout) as session:
            return await client.list_tools(session)
    except Exception as exc:  # noqa: BLE001
        return client.format_exception(exc)


async def ui_call_tool(tool: str, args_json: str, url: str, timeout: float) -> str:
    """Same path as the CLI's --call/--args, for exercising a v0 tool directly."""
    if not tool or not tool.strip():
        return "Enter a tool name first."
    try:
        args = json.loads(args_json or "{}")
    except json.JSONDecodeError as exc:
        return f"Arguments is not valid JSON: {exc}"
    try:
        async with client.open_session(url.strip() or DEFAULTS["url"], timeout) as session:
            return await client.call_tool(session, tool.strip(), args)
    except Exception as exc:  # noqa: BLE001
        return client.format_exception(exc)


def build_app(defaults: dict[str, str] | None = None) -> gr.Blocks:
    """Builds the Gradio Blocks app, prefilled with *defaults* (or module DEFAULTS)."""
    defaults = defaults or DEFAULTS

    with gr.Blocks(title="AllotMint MCP client") as demo:
        gr.Markdown("# AllotMint MCP client")

        with gr.Tab("Ask allotmint_research"):
            question = gr.Textbox(
                label="Question",
                lines=3,
                placeholder="How has my tech exposure changed this year, and why?",
            )
            with gr.Row():
                owner = gr.Textbox(label="Owner", placeholder="demo")
                lookback_days = gr.Number(label="Lookback days", precision=0)
            with gr.Accordion("Advanced", open=False):
                ask_url = gr.Textbox(label="allotmint-mcp URL", value=defaults["url"])
                ask_research_url = gr.Textbox(
                    label="research-agent URL", value=defaults["research_url"]
                )
                ask_timeout = gr.Number(label="Timeout (seconds)", value=180.0)
                skip_preflight = gr.Checkbox(label="Skip preflight checks", value=False)
            ask_button = gr.Button("Ask", variant="primary")
            ask_result = gr.Textbox(label="Answer", lines=10, interactive=False)
            ask_button.click(
                ui_ask,
                inputs=[question, owner, lookback_days, ask_url, ask_research_url, ask_timeout, skip_preflight],
                outputs=ask_result,
            )
            question.submit(
                ui_ask,
                inputs=[question, owner, lookback_days, ask_url, ask_research_url, ask_timeout, skip_preflight],
                outputs=ask_result,
            )

        with gr.Tab("List tools"):
            tools_url = gr.Textbox(label="allotmint-mcp URL", value=defaults["url"])
            tools_timeout = gr.Number(label="Timeout (seconds)", value=30.0)
            tools_button = gr.Button("List tools", variant="primary")
            tools_result = gr.Textbox(label="Tools", lines=10, interactive=False)
            tools_button.click(ui_list_tools, inputs=[tools_url, tools_timeout], outputs=tools_result)

        with gr.Tab("Call a tool directly"):
            tool_name = gr.Textbox(label="Tool name", placeholder="allotmint_health")
            tool_args = gr.Textbox(label="Arguments (JSON)", value="{}", lines=4)
            call_url = gr.Textbox(label="allotmint-mcp URL", value=defaults["url"])
            call_timeout = gr.Number(label="Timeout (seconds)", value=180.0)
            call_button = gr.Button("Call", variant="primary")
            call_result = gr.Textbox(label="Output", lines=10, interactive=False)
            call_button.click(
                ui_call_tool,
                inputs=[tool_name, tool_args, call_url, call_timeout],
                outputs=call_result,
            )

    return demo


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Locally hosted Gradio UI for the mcp-client (issue #310)."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8601, help="Port to listen on (default: 8601)")
    parser.add_argument(
        "--url",
        default=client.DEFAULT_MCP_URL,
        help=f"allotmint-mcp endpoint prefilled in the UI (default: {client.DEFAULT_MCP_URL})",
    )
    parser.add_argument(
        "--research-url",
        default=client.DEFAULT_RESEARCH_URL,
        help=f"research-agent sidecar URL prefilled in the UI (default: {client.DEFAULT_RESEARCH_URL})",
    )
    parser.add_argument(
        "--share",
        action="store_true",
        help="Create a public Gradio share link, tunneled through Gradio's own servers (off by default)",
    )
    client.add_start_deps_args(parser)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    DEFAULTS["url"] = args.url
    DEFAULTS["research_url"] = args.research_url

    which = client.requested_dependencies(args)
    if which:
        deps.ensure_running(args.url, args.research_url, args.start_timeout, which)

    demo = build_app()
    deps.log(f"gradio UI: serving on http://{args.host}:{args.port}")
    demo.launch(server_name=args.host, server_port=args.port, share=args.share)
    return 0


if __name__ == "__main__":
    sys.exit(main())
