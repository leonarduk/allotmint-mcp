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

Pass `--start-deps` to have the client start whichever of these aren't already running, rather than doing all four by hand — see [Auto-starting dependencies](#auto-starting-dependencies) below.

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

## Auto-starting dependencies

`--start-deps` checks each of pgvector, Ollama, the `allotmint-mcp` server, and the `research-agent` sidecar, and starts whichever isn't already reachable — so a fresh checkout can go from nothing running to a first answer in one command:

```bash
python client.py "How has my tech exposure changed this year, and why?" --owner demo --start-deps
```

What each one does, in this order (matching [`research-agent/README.md`](../research-agent/README.md#run-it)):

| Dependency | Already-running check | How it's started |
|---|---|---|
| pgvector | TCP `:5432` open | `docker compose up -d pgvector` |
| Ollama | `GET :11434/api/tags` | `ollama serve` (most installs already run this as a service, so this is usually a no-op) |
| `allotmint-mcp` server | TCP on `--url`'s host/port | `java -jar target/allotmint-mcp-server.jar --spring.profiles.active=http`, with `ALLOTMINT_MCP_RESEARCH_ENABLED=true` — **requires a prebuilt jar** (`./mvnw package`); this does not build one, since a Maven build is much slower than anything else here |
| `research-agent` sidecar | `GET <research-url>/health` | `docker compose --profile research up -d research-agent` — a first run builds the image, which can take several minutes; pass a larger `--start-timeout` if it does. Right after it comes up from cold, its pgvector sample corpus is seeded too (`docker compose exec research-agent python ingest.py --sample`) — otherwise retrieval stays unavailable on a fresh database with no obvious reason why. |

Started processes are left running in the background (not tied to this script's lifetime), with logs under `mcp-client/logs/`. Anything that's already running is left alone — every check is a plain reachability probe first, so re-running with `--start-deps` never restarts something that's already up (and doesn't re-seed the sample corpus every time either — only right after starting the sidecar from cold; `ingest.py` itself is idempotent if you do need to rerun it by hand).

Use `--start-pgvector`, `--start-ollama`, `--start-mcp-server`, or `--start-research-agent` individually instead of `--start-deps` to auto-start only some of them (e.g. you already have Ollama and the Java server running in another terminal, and only want the sidecar brought up). `--start-timeout` (default 90s) controls how long each one is given to become reachable before it's reported as a problem rather than silently ignored — auto-starting is always best-effort: any dependency that can't be confirmed ready is printed as a warning, and the client still tries to proceed, so the usual preflight/connection errors explain what's still missing.

### Logs

Every status line — from `--start-deps`, `stop_deps.py`, and the client's own preflight/errors — is timestamped and appended to `mcp-client/logs/mcp-client.log`, in addition to being printed. A confusing run (did it hang? what actually happened, in what order?) can be reconstructed from that file afterwards rather than relying on whatever scrolled past in the terminal. Each spawned process also gets its own log (`logs/allotmint-mcp.log`, `logs/ollama.log`), with a header recording exactly which command was run and when, appended across restarts rather than overwritten — so if a server "started" but never became reachable, the log almost always says why.

One specific check worth knowing about: `--start-mcp-server` warns (but doesn't refuse to start) if `target/allotmint-mcp-server.jar` is older than any file under `src/` or `pom.xml`. A stale jar starts up completely normally — it just silently lacks whatever was added since it was built, which otherwise only surfaces later as a confusing "missing required tool(s)" error from preflight. If you see that warning, rebuild first: `./mvnw package`.

### Gotcha: multiple checkouts of this repo

`docker-compose.yml` hardcodes `container_name: allotmint-mcp-pgvector` (and `allotmint-mcp-research-agent`) — a real container name, global to the Docker daemon, not scoped per checkout. If you have more than one clone of this repo and start pgvector from each, only the *first* one actually owns that name; the second's `docker compose up -d pgvector` either no-ops against the wrong checkout's container or fails with `Conflict: container name already in use`, and — the more confusing failure mode — a `research-agent` started from the second checkout can end up on a *different* Docker network than that first container, so its internal `pgvector` hostname doesn't resolve at all ("failed to resolve host 'pgvector'") even though `docker ps` shows something answering on port 5432. If you hit either symptom, check which checkout actually owns the running container (`docker inspect allotmint-mcp-pgvector --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'`) and stop it there before starting this checkout's own.

### Stopping dependencies

`stop_deps.py` is the counterpart to `--start-deps`:

```bash
python stop_deps.py                        # stop everything
python stop_deps.py --ollama --mcp-server   # stop just these
```

pgvector and the research-agent sidecar are stopped with `docker compose stop` (reversible — the containers and pgvector's data volume stay in place for next time, `docker compose up -d` brings them straight back). Ollama and the `allotmint-mcp` server are only stopped if a prior `--start-deps` run started them — tracked via the PID files `spawn_background` writes to `mcp-client/logs/`. Anything else already listening on those ports (Ollama running as a system service, an `allotmint-mcp` you started by hand in another terminal) is deliberately left alone, and reported as still running rather than silently skipped or force-killed.

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
| `--research-url` | `http://localhost:8100` | The sidecar's base URL, used for the prerequisite health check and `--start-research-agent` |
| `--skip-preflight` | | Skip the startup checks described above |
| `--start-deps` | | Start pgvector, Ollama, the `allotmint-mcp` server, and the sidecar if any aren't already running |
| `--start-pgvector` / `--start-ollama` / `--start-mcp-server` / `--start-research-agent` | | Start just one of them |
| `--start-timeout` | `90` | Seconds to wait for a started dependency to become ready |

### `Unknown tool: invalid_tool_name`

If you still see this exact message with `--skip-preflight` (or from `--call`), it almost never means the LLM asked for a bogus tool. It's a known bug in the server's underlying Java SDK (`io.modelcontextprotocol.sdk:mcp-core`'s `McpAsyncServer#toolsCallRequestHandler`): the "tool not found" error hardcodes its message to the literal string `invalid_tool_name` regardless of which tool was actually requested. This client appends the error's `data` field in parentheses, which does name the real tool — check that first. Without `--skip-preflight`, the preflight check above catches the underlying cause (a missing tool registration) before it gets this far.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

No live server needed: the MCP session is a fake object, so these only cover the argument-building and result-formatting logic that doesn't depend on the transport itself.
