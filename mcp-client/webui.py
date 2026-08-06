"""Locally hosted browser UI for the mcp-client (issue #302).

Deprecated (issue #310): gradio_ui.py is the successor to this module - a
proper, modern interface for the same client.py functions, instead of this
Swagger-like hand-rolled HTML form. This module is left in place because it
still works and some tests/workflows may depend on it, but new usage should
prefer `python gradio_ui.py`.

Wraps the same functions client.py's CLI uses - open_session, ask,
list_tools, call_tool, preflight, format_exception - behind a small FastAPI
app instead of argparse/stdin, so asking allotmint_research a question, or
exercising the v0 tools, works from a browser instead of a terminal. Nothing
in client.py or deps.py is duplicated here; this is a second entrypoint onto
the same logic, not a second implementation of it. The CLI (`python
client.py ...`) is untouched and keeps working exactly as before.

Usage:
    pip install -r requirements.txt
    python webui.py
    python webui.py --port 8600 --url http://localhost:8080/mcp
    python webui.py --start-deps
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import client
import deps

app = FastAPI(
    title="AllotMint MCP client (web UI)",
    description="Browser front end for the mcp-client CLI (issue #302). Read-only.",
)

# Populated from CLI flags in main() before the server starts; only used to
# prefill the form's default values, exactly like client.py's own --url and
# --research-url defaults.
DEFAULTS = {"url": client.DEFAULT_MCP_URL, "research_url": client.DEFAULT_RESEARCH_URL}


class AskRequest(BaseModel):
    question: str
    owner: str | None = None
    lookback_days: int | None = None
    url: str = client.DEFAULT_MCP_URL
    research_url: str = client.DEFAULT_RESEARCH_URL
    timeout: float = 180.0
    skip_preflight: bool = False


class ToolsRequest(BaseModel):
    url: str = client.DEFAULT_MCP_URL
    timeout: float = 30.0


class CallRequest(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)
    url: str = client.DEFAULT_MCP_URL
    timeout: float = 180.0


@app.post("/api/ask")
async def api_ask(payload: AskRequest) -> dict:
    """Same path as the CLI's one-shot/REPL question: preflight, then ask."""
    try:
        async with client.open_session(payload.url, payload.timeout) as session:
            if not payload.skip_preflight:
                problems = await client.preflight(session, payload.research_url, payload.timeout)
                if problems:
                    raise HTTPException(status_code=409, detail="\n".join(problems))
            answer = await client.ask(session, payload.question, payload.owner, payload.lookback_days)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - reported to the caller, not swallowed
        raise HTTPException(status_code=502, detail=client.format_exception(exc)) from exc
    return {"answer": answer}


@app.post("/api/tools")
async def api_tools(payload: ToolsRequest) -> dict:
    """Same path as the CLI's --list-tools."""
    try:
        async with client.open_session(payload.url, payload.timeout) as session:
            listing = await client.list_tools(session)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=client.format_exception(exc)) from exc
    return {"tools": listing}


@app.post("/api/call")
async def api_call(payload: CallRequest) -> dict:
    """Same path as the CLI's --call/--args, for exercising a v0 tool directly."""
    try:
        async with client.open_session(payload.url, payload.timeout) as session:
            output = await client.call_tool(session, payload.tool, payload.args)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=client.format_exception(exc)) from exc
    return {"output": output}


def render_index() -> str:
    """Renders the single-page UI, prefilled with this run's --url/--research-url.

    Plain token substitution rather than str.format(): the template is mostly
    CSS/JS, whose braces would otherwise all need doubling.  URL values are
    escaped for HTML attributes (via html.escape) and injected into JS via
    json.dumps so that special characters in URLs never break the script.
    """
    defaults_json = json.dumps(
        {"url": DEFAULTS["url"], "researchUrl": DEFAULTS["research_url"]}
    ).replace("</", "<\\/")  # defend against literal </script> in URL strings
    return (
        _INDEX_TEMPLATE.replace("__URL__", escape(DEFAULTS["url"]))
        .replace("__RESEARCH_URL__", escape(DEFAULTS["research_url"]))
        .replace("__DEFAULTS_JSON__", defaults_json)
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return render_index()


_INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AllotMint MCP client</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: system-ui, sans-serif; max-width: 46rem; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
  h1 { font-size: 1.3rem; }
  fieldset { border: 1px solid #ccc; border-radius: 6px; margin-bottom: 1.5rem; }
  label { display: block; margin-top: 0.6rem; font-size: 0.9rem; }
  input[type=text], input[type=number], input[type=url], textarea {
    width: 100%; box-sizing: border-box; padding: 0.4rem; margin-top: 0.2rem;
    font-family: inherit; font-size: 0.95rem;
  }
  textarea { min-height: 4rem; font-family: monospace; }
  button { margin-top: 0.8rem; padding: 0.5rem 1.2rem; cursor: pointer; }
  pre { background: #f4f4f4; padding: 0.8rem; white-space: pre-wrap; word-break: break-word; border-radius: 4px; }
  .error { background: #fdecea; color: #7a1f14; }
  details summary { cursor: pointer; margin-top: 0.6rem; }
  .row { display: flex; gap: 1rem; }
  .row > div { flex: 1; }
</style>
</head>
<body>
<h1>AllotMint MCP client</h1>
<p>Browser UI for the <code>mcp-client</code> CLI. The command-line tool (<code>python client.py</code>) still works unchanged.</p>

<fieldset>
<legend>Ask allotmint_research</legend>
<form id="ask-form">
  <label>Question
    <textarea name="question" required placeholder="How has my tech exposure changed this year, and why?"></textarea>
  </label>
  <div class="row">
    <div><label>Owner <input type="text" name="owner" placeholder="demo"></label></div>
    <div><label>Lookback days <input type="number" name="lookback_days" min="1" max="3650"></label></div>
  </div>
  <details>
    <summary>Advanced</summary>
    <label>allotmint-mcp URL <input type="text" name="url" value="__URL__"></label>
    <label>research-agent URL <input type="text" name="research_url" value="__RESEARCH_URL__"></label>
    <label>Timeout (seconds) <input type="number" name="timeout" value="180"></label>
    <label><input type="checkbox" name="skip_preflight" style="width:auto;display:inline"> Skip preflight checks</label>
  </details>
  <button type="submit">Ask</button>
</form>
<pre id="ask-result" hidden></pre>
</fieldset>

<fieldset>
<legend>List tools</legend>
<form id="tools-form">
  <label>allotmint-mcp URL <input type="text" name="url" value="__URL__"></label>
  <label>Timeout (seconds) <input type="number" name="timeout" value="30"></label>
  <button type="submit">List tools</button>
</form>
<pre id="tools-result" hidden></pre>
</fieldset>

<fieldset>
<legend>Call a tool directly</legend>
<form id="call-form">
  <label>Tool name <input type="text" name="tool" required placeholder="allotmint_health"></label>
  <label>Arguments (JSON) <textarea name="args">{}</textarea></label>
  <label>allotmint-mcp URL <input type="text" name="url" value="__URL__"></label>
  <label>Timeout (seconds) <input type="number" name="timeout" value="180"></label>
  <button type="submit">Call</button>
</form>
<pre id="call-result" hidden></pre>
</fieldset>

<script>
/* Injected by render_index() via json.dumps — safe for any URL chars */
const DEFAULTS = __DEFAULTS_JSON__;

async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
  const data = await response.json();
  return {ok: response.ok, data};
}

function showResult(el, ok, text) {
  el.hidden = false;
  el.textContent = text;
  el.classList.toggle("error", !ok);
}

document.getElementById("ask-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const lookback = form.get("lookback_days");
  const timeout = form.get("timeout");
  const body = {
    question: form.get("question"),
    owner: form.get("owner") || null,
    lookback_days: lookback ? parseInt(lookback, 10) : null,
    url: form.get("url") || DEFAULTS.url,
    research_url: form.get("research_url") || DEFAULTS.researchUrl,
    timeout: timeout ? parseFloat(timeout) : 180.0,
    skip_preflight: form.get("skip_preflight") === "on",
  };
  const el = document.getElementById("ask-result");
  showResult(el, true, "Asking...");
  const {ok, data} = await postJSON("/api/ask", body);
  showResult(el, ok && !data.detail, data.detail || data.answer);
});

document.getElementById("tools-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const timeout = form.get("timeout");
  const body = {
    url: form.get("url") || DEFAULTS.url,
    timeout: timeout ? parseFloat(timeout) : 30.0,
  };
  const el = document.getElementById("tools-result");
  showResult(el, true, "Loading...");
  const {ok, data} = await postJSON("/api/tools", body);
  showResult(el, ok && !data.detail, data.detail || data.tools);
});

document.getElementById("call-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const el = document.getElementById("call-result");
  const timeout = form.get("timeout");
  let args;
  try {
    args = JSON.parse(form.get("args") || "{}");
  } catch (err) {
    showResult(el, false, "Arguments is not valid JSON: " + err.message);
    return;
  }
  showResult(el, true, "Calling...");
  const body = {
    tool: form.get("tool"),
    args: args,
    url: form.get("url") || DEFAULTS.url,
    timeout: timeout ? parseFloat(timeout) : 180.0,
  };
  const {ok, data} = await postJSON("/api/call", body);
  showResult(el, ok && !data.detail, data.detail || data.output);
});
</script>
</body>
</html>
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Locally hosted browser UI for the mcp-client (issue #302)."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8600, help="Port to listen on (default: 8600)")
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
    client.add_start_deps_args(parser)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    args = parse_args(argv)
    DEFAULTS["url"] = args.url
    DEFAULTS["research_url"] = args.research_url

    which = client.requested_dependencies(args)
    if which:
        deps.ensure_running(args.url, args.research_url, args.start_timeout, which)

    deps.log("webui.py is deprecated; prefer gradio_ui.py (issue #310)", level="WARNING")

    deps.log(f"web UI: serving on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
