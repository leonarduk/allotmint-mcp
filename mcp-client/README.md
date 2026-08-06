# AllotMint MCP client (research agent testing)

A minimal MCP client for testing `allotmint_research` ([issue #256](https://github.com/leonarduk/allotmint-mcp/issues/256)) without standing up Claude Desktop or the MCP Inspector.

It speaks the same streamable-HTTP MCP transport the research-agent sidecar itself uses to reach the four v0 tools ([`research-agent/app/mcp_tools.py`](../research-agent/app/mcp_tools.py)), connects to a running `allotmint-mcp` server, and calls `allotmint_research` the way any real MCP client would: one question in, one grounded, cited answer out.

```
client.py ──▶ allotmint-mcp (Java, --spring.profiles.active=http)
                 │  allotmint_research
                 ▼
              research-agent sidecar
                 │  ├── pgvector: retrieve context
                 │  ├── LLM (Ollama or DeepSeek): decide + synthesize
                 │  └── MCP client back into allotmint-mcp's v0 tools
```

This client is transport-only — it doesn't run or configure an LLM itself. Whether the research agent answers using a free local model (the default) or DeepSeek is entirely the sidecar's own configuration (see [`research-agent/README.md`](../research-agent/README.md#configuration)); this client works unmodified against either, because MCP is the interop boundary between them.

## Prerequisites

Everything `allotmint_research` itself needs, running first — see [`research-agent/README.md`](../research-agent/README.md#run-it) for the full sequence:

1. pgvector (`docker compose up -d pgvector`), ingested with at least the sample corpus.
2. A model — the free local default (`ollama pull llama3.2`) or DeepSeek (`ALLOTMINT_RESEARCH_LLM_PROVIDER=deepseek`, see the sidecar's README for the other env vars).
3. The `research-agent` sidecar (`uvicorn app.main:app --port 8100`).
4. The `allotmint-mcp` server, with both the HTTP transport and the research tool on:
   ```bash
   ALLOTMINT_MCP_RESEARCH_ENABLED=true java -jar target/allotmint-mcp-server.jar --spring.profiles.active=http
   ```

## Install

```bash
cd mcp-client
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
```

## Prerequisite checks

Before asking anything (a one-shot question or the REPL — not `--list-tools` or `--call`, which are themselves diagnostic), the client checks that what `allotmint_research` needs is actually in place:

1. **The tool is registered** — `allotmint_research` and the four v0 tools it chains all appear in the connected server's `list_tools()`. Catches a server started without `ALLOTMINT_MCP_RESEARCH_ENABLED=true`, or one built from a jar that predates the tool.
2. **The sidecar is reachable** — `GET <research-url>/health` succeeds. Catches the `research-agent` process not running, or listening on a different port than `--research-url` expects.

Either failure is reported with a specific, actionable cause and the client exits before making a call — no more generic errors from three layers down. On success it prints what it found, e.g.:

```
research-agent ready: model=ollama:llama3.2, retrieval_enabled=True
```

Pass `--skip-preflight` to bypass both checks (e.g. if `--research-url` isn't reachable from where this client runs but the server can still reach it itself).

## Use

One-shot question:

```bash
python client.py "How has my tech exposure changed this year, and why?" --owner demo
```

Interactive REPL — one question per line, blank line or Ctrl-D to quit:

```bash
python client.py --owner demo
```

Sanity-check the server is up and has the expected tools, without asking a question:

```bash
python client.py --list-tools
```

Call a v0 tool directly, e.g. to check the AllotMint backend connection the research agent itself depends on:

```bash
python client.py --call allotmint_health --args "{}"
```

### Flags

| Flag | Default | Purpose |
|---|---|---|
| `--url` | `http://localhost:8080/mcp` | The allotmint-mcp server's streamable-HTTP endpoint |
| `--owner` | *(none)* | Owner slug scoping portfolio lookups |
| `--lookback-days` | *(server default: 365)* | How far back retrieval considers dated documents |
| `--timeout` | `180` | Read timeout in seconds — matches the sidecar's own budget for a full agent loop |
| `--list-tools` | | List the tools the server exposes, then exit |
| `--call TOOL` | | Call an arbitrary tool instead of `allotmint_research` |
| `--args JSON` | `{}` | Arguments for `--call` |
| `--research-url` | `http://localhost:8100` | The sidecar's base URL, used only for the prerequisite health check |
| `--skip-preflight` | | Skip the startup checks described above |

### `Unknown tool: invalid_tool_name`

If you still see this exact message with `--skip-preflight` (or from `--call`), it almost never means the LLM asked for a bogus tool. It's a known bug in the server's underlying Java SDK (`io.modelcontextprotocol.sdk:mcp-core`'s `McpAsyncServer#toolsCallRequestHandler`): the "tool not found" error hardcodes its message to the literal string `invalid_tool_name` regardless of which tool was actually requested. This client appends the error's `data` field in parentheses, which does name the real tool — check that first. Without `--skip-preflight`, the preflight check above catches the underlying cause (a missing tool registration) before it gets this far.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

No live server needed: the MCP session is a fake object, so these only cover the argument-building and result-formatting logic that doesn't depend on the transport itself.
