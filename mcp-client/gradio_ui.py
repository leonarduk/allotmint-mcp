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
#
# Only runs when this file is executed directly (`python gradio_ui.py`), not
# on a bare `import gradio_ui` - so importing this module (as the test suite
# does) still fails with a normal ModuleNotFoundError if gradio/mcp are
# missing, rather than triggering a pip install as an import-time side
# effect.
PYTHON_REQUIREMENTS = {
    "gradio": "gradio>=6.15.0,<7.0",
    "mcp": "mcp>=1.9",
}
if __name__ == "__main__":
    deps.ensure_python_packages(PYTHON_REQUIREMENTS)

import gradio as gr

import client

# Populated from CLI flags in main() before the server starts; only used to
# prefill the form's default values, exactly like client.py's own --url and
# --research-url defaults.
DEFAULTS = {"url": client.DEFAULT_MCP_URL, "research_url": client.DEFAULT_RESEARCH_URL}


async def ui_ask(
    question: str,
    owner: str | None,
    lookback_days: float | None,
    url: str,
    research_url: str,
    timeout: float,
    skip_preflight: bool,
    llm_provider: str | None = None,
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
                owner.strip() if owner else None,
                int(lookback_days) if lookback_days else None,
                llm_provider,
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


async def ui_load_llm_providers(research_url: str, timeout: float):
    """Populate the provider dropdown from the running sidecar's health data."""
    try:
        health = await client.fetch_research_agent_health(
            research_url.strip() or DEFAULTS["research_url"], timeout
        )
        choices = health.get("available_llm_providers") or []
        current = health.get("llm_provider")
        if not choices and current:
            choices = [current]
        if not choices:
            # Backward compatibility with a sidecar predating issue #554.
            model = health.get("model", "")
            choices = [model.split(":", 1)[0]] if ":" in model else []
        return gr.Dropdown(choices=choices, value=current or (choices[0] if choices else None))
    except Exception:  # noqa: BLE001 - an unavailable sidecar is reported by preflight on Ask
        return gr.Dropdown(choices=[], value=None)


async def ui_account_owners(url: str, timeout: float):
    """Loads valid account-owner choices when the chat UI opens.

    Returns a (dropdown_update, error_update) pair: the dropdown always
    renders (empty on failure, so the rest of the UI stays usable), and the
    error banner is shown only when discovery fails, so the reason is
    visible instead of a silently empty dropdown.
    """
    try:
        async with client.open_session(url.strip() or DEFAULTS["url"], timeout) as session:
            owners = await client.list_account_owners(session)
        return (
            gr.update(choices=owners, value=owners[0] if owners else None),
            gr.update(value="", visible=False),
        )
    except Exception as exc:  # noqa: BLE001 - reported via the error banner, not swallowed
        return (
            gr.update(choices=[], value=None),
            gr.update(value=f"Failed to load account owners: {client.format_exception(exc)}", visible=True),
        )


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
            llm_provider = gr.Dropdown(
                label="LLM provider",
                choices=[],
                value=None,
                info="Available choices are loaded from the research agent.",
            )
            question = gr.Textbox(
                label="Question",
                lines=3,
                placeholder="How has my tech exposure changed this year, and why?",
            )
            with gr.Row():
                owner = gr.Dropdown(label="Account Owner", choices=[], allow_custom_value=False)
                lookback_days = gr.Number(label="Lookback days", precision=0)
            owner_error = gr.Markdown(value="", visible=False)
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
                inputs=[
                    question,
                    owner,
                    lookback_days,
                    ask_url,
                    ask_research_url,
                    ask_timeout,
                    skip_preflight,
                    llm_provider,
                ],
                outputs=ask_result,
            )
            question.submit(
                ui_ask,
                inputs=[
                    question,
                    owner,
                    lookback_days,
                    ask_url,
                    ask_research_url,
                    ask_timeout,
                    skip_preflight,
                    llm_provider,
                ],
                outputs=ask_result,
            )
            demo.load(
                ui_load_llm_providers,
                inputs=[ask_research_url, ask_timeout],
                outputs=llm_provider,
            )
            ask_research_url.change(
                ui_load_llm_providers,
                inputs=[ask_research_url, ask_timeout],
                outputs=llm_provider,
            )
            demo.load(
                ui_account_owners,
                inputs=[ask_url, ask_timeout],
                outputs=[owner, owner_error],
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
        problems = deps.ensure_running(args.url, args.research_url, args.start_timeout, which)
        if problems:
            deps.log(
                f"not starting the UI: {len(problems)} requested dependency(ies) failed to start - "
                "fix the problems above and re-run, or run without --start-deps to open the UI anyway",
                level="ERROR",
            )
            return 1

    demo = build_app()
    deps.log(f"gradio UI: serving on http://{args.host}:{args.port}")
    demo.launch(server_name=args.host, server_port=args.port, share=args.share)
    return 0


if __name__ == "__main__":
    sys.exit(main())
