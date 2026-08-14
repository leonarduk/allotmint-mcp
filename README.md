# allotmint-mcp

Standalone MCP server for [AllotMint](https://github.com/leonarduk/allotmint), built with Spring Boot 4.1.0, Java 25, and the [MCP Java SDK](https://github.com/modelcontextprotocol/java-sdk). It exposes the same tools over stdio (for Claude Desktop and MCP Inspector) and HTTP streamable transport (`/mcp`).

## Prerequisites

- Java 25 or later on `PATH` (`java -version` should report 25+)
- A running AllotMint backend; the default URL is `http://localhost:8000`
- Claude Desktop if you want to use the stdio MCP integration

Maven does not need to be installed: the repository includes the Maven wrapper.

## Build

From a fresh clone:

```bash
git clone https://github.com/leonarduk/allotmint-mcp.git
cd allotmint-mcp
./mvnw clean package
```

On Windows PowerShell, run `./mvnw.cmd clean package` instead. The build produces one executable fat JAR:

```text
target/allotmint-mcp-server.jar
```

## Run

The default profile uses stdio, so the process waits silently for MCP messages on standard input:

```bash
java -jar target/allotmint-mcp-server.jar
```

Set `ALLOTMINT_API_BASE` to use a backend other than `http://localhost:8000`.

### Local environment configuration

For local development, copy the committed template and edit the values you need:

```bash
cp .env.example .env
java -jar target/allotmint-mcp-server.jar
```

The Java server loads `.env` from its current working directory automatically. The file uses
`KEY=value` syntax, and the available settings and defaults are listed in `.env.example`. Values
from the real process environment or JVM system properties take precedence over `.env`, so the
same JAR can safely use deployment-provided environment variables in testing and production.
Spring's normal defaults apply when a key is absent everywhere.

The template also includes Spring's `SPRING_PROFILES_ACTIVE` setting and the optional MCP feature
flags, so local stdio, HTTP, files-tool, and research-tool configuration can be kept in the same
place. Leave `SPRING_PROFILES_ACTIVE` empty for stdio or set it to `http` for HTTP transport.

The `.env` file is ignored by Git and must not be committed because it may contain the short-lived
authentication token. Commit only non-secret additions to `.env.example`. To disable `.env`
loading entirely, set `SPRINGDOTENV_ENABLED=false` in the process environment.

To run the optional HTTP transport at `/mcp`, with Actuator health, info, and metrics endpoints:

```bash
java -jar target/allotmint-mcp-server.jar --spring.profiles.active=http
```

## Configure Claude Desktop

Build the JAR, then add the following entry to Claude Desktop's configuration. Replace the JAR path with its absolute path; do not use a relative path because Claude Desktop does not launch servers from the repository directory.

```json
{
  "mcpServers": {
    "allotmint": {
      "command": "java",
      "args": [
        "-jar",
        "/absolute/path/to/allotmint-mcp/target/allotmint-mcp-server.jar"
      ],
      "env": {
        "ALLOTMINT_API_BASE": "http://localhost:8000"
      }
    }
  }
}
```

On Windows, use an escaped absolute path, for example:

```json
{
  "mcpServers": {
    "allotmint": {
      "command": "java",
      "args": [
        "-jar",
        "C:\\path\\to\\allotmint-mcp\\target\\allotmint-mcp-server.jar"
      ],
      "env": {
        "ALLOTMINT_API_BASE": "http://localhost:8000"
      }
    }
  }
}
```

Restart Claude Desktop after saving the configuration. The `echo` tool is available as a transport smoke test; the AllotMint tools are documented below, including the opt-in write and research tools.

## Authentication

### Local backend

Start the AllotMint backend with `DISABLE_AUTH=true`. The MCP server does not need an auth token in this mode:

```bash
export ALLOTMINT_API_BASE="http://localhost:8000"
java -jar target/allotmint-mcp-server.jar
```

`DISABLE_AUTH` is an AllotMint backend setting, not an allotmint-mcp setting.

### AWS backend

Set the backend URL and an AllotMint backend-issued JWT before starting the MCP server:

```bash
export ALLOTMINT_API_BASE="https://your-allotmint-backend.example.com"
export ALLOTMINT_MCP_AUTH_TOKEN="<backend-issued-jwt>"
java -jar target/allotmint-mcp-server.jar
```

To obtain the token:

1. Sign in to the AllotMint web application with Google.
2. Open the browser's Developer Tools and select the **Network** panel.
3. Trigger an authenticated AllotMint API request and select it.
4. Copy only the value after `Bearer ` in the request's `Authorization` header.
5. Set that value as `ALLOTMINT_MCP_AUTH_TOKEN`, then restart the MCP server.

This is AllotMint's backend-issued HS256 JWT, not the Google ID token. Its default lifetime is approximately **15 minutes**, so repeat the extraction and restart the MCP server after it expires. Do not commit the token, include it in logs, or paste it into bug reports.

Claude Desktop can pass the AWS settings in the server's `env` object:

```json
"env": {
  "ALLOTMINT_API_BASE": "https://your-allotmint-backend.example.com",
  "ALLOTMINT_MCP_AUTH_TOKEN": "<backend-issued-jwt>"
}
```

AllotMint does not yet provide device-flow or service-account login for this headless server. The error message may mention `allotmint-mcp login`, but that command is not implemented; copying the short-lived token is currently the supported AWS workflow.

## Tool reference

All schemas use JSON objects. Except for `allotmint_health`, unknown properties are rejected.

### `allotmint_health`

Checks connectivity to the configured AllotMint backend and reports its version.

```json
{
  "type": "object",
  "properties": {}
}
```

### `allotmint_instrument`

Looks up instruments by ticker or name.

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": ["search", "detail", "prices", "news"]
    },
    "query": {
      "type": "string",
      "minLength": 1
    },
    "ticker": {
      "type": "string",
      "minLength": 1
    },
    "exchange": {
      "type": "string",
      "minLength": 1
    }
  },
  "required": ["action"],
  "additionalProperties": false
}
```

`query` is required when `action` is `search`. `ticker` is required for `detail`, `prices`, and `news`. `exchange` is an optional suffix appended when `ticker` has no suffix: `ticker=VWRL` plus `exchange=L` becomes `VWRL.L`.

### `allotmint_market`

Returns the combined market overview, standalone movers, or index data.

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": ["overview", "movers", "indices"]
    }
  },
  "required": ["action"],
  "additionalProperties": false
}
```

### `allotmint_portfolio`

Returns one owner's summary, exposure breakdown, or flat holdings list.

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": ["summary", "exposure", "holdings"]
    },
    "owner": {
      "type": "string",
      "minLength": 1
    },
    "account_type": {
      "type": "string",
      "minLength": 1
    },
    "currency": {
      "type": "string",
      "minLength": 1
    }
  },
  "required": ["action", "owner"],
  "additionalProperties": false
}
```

Get valid `owner` slugs from the AllotMint backend's `GET /owners` endpoint. `account_type` and `currency` are optional case-insensitive client-side filters.

### `allotmint_reconcile`

Produces a read-only structured diff between one account's stored holdings and an uploaded broker
CSV. Broker parsing and ticker/currency normalization happen in the AllotMint backend.

```json
{
  "type": "object",
  "properties": {
    "owner": { "type": "string", "minLength": 1 },
    "account_type": { "type": "string", "minLength": 1 },
    "csv_content": { "type": "string", "minLength": 1 }
  },
  "required": ["owner", "account_type", "csv_content"],
  "additionalProperties": false
}
```

The response includes added, removed, quantity/value-changed holdings, the cash delta, and an
opaque `reconciliation_id`. Show the complete diff to the user before offering to apply it. This
tool never writes, including when write support is enabled.

### `allotmint_apply_reconciliation` (opt-in write)

Applies exactly the previously returned diff identified by `reconciliation_id`. It does not accept
replacement holdings or CSV content, so a client cannot change the reviewed payload during apply.

```json
{
  "type": "object",
  "properties": {
    "reconciliation_id": { "type": "string", "minLength": 1 }
  },
  "required": ["reconciliation_id"],
  "additionalProperties": false
}
```

The write tool is not registered by default. Enable it only on a backend where portfolio mutation
is intended:

```bash
export ALLOTMINT_MCP_WRITE_ENABLED=true
java -jar target/allotmint-mcp-server.jar
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALLOTMINT_MCP_WRITE_ENABLED` | `false` | Registers the explicit reconciliation apply tool |

Enabling the flag does not replace approval: an AI client must first call `allotmint_reconcile`,
display its diff, obtain human approval, and only then call the apply tool with its ID. See the
[reconciliation design](docs/reconciliation-design.md) for the trust boundary and backend
requirements.

### `allotmint_data_quality`

Answers and acts on data-quality questions — e.g. "which instruments have no data?" — without an
owner slug. The backend aggregates holdings across all owners server-side.

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": ["issues", "series", "preview", "fix", "dedupe", "audit", "undo"]
    },
    "type": { "type": "string", "minLength": 1 },
    "severity": { "type": "string", "minLength": 1 },
    "owner": { "type": "string", "minLength": 1 },
    "account": { "type": "string", "minLength": 1 },
    "ticker": { "type": "string", "minLength": 1 },
    "issue_id": { "type": "string", "minLength": 1 },
    "exchange": { "type": "string", "minLength": 1 },
    "audit_id": { "type": "string", "minLength": 1 },
    "confirm": { "type": "boolean", "default": false }
  },
  "required": ["action"],
  "additionalProperties": false
}
```

Read actions (never trigger backend live fetches):

- `issues` — aggregated issue list across all owners; optional `type`, `severity`, `owner`,
  `account`, `ticker` filters. No owner argument is required.
- `series` — per-series quality metrics (`GET /data-quality/timeseries`).
- `preview` — review one issue's suggested fix (requires `issue_id`); always call this before `fix`.
- `audit` — append-only fix history.

Write actions (`fix`, `dedupe`, `undo`) are rejected unless `confirm=true`, and they additionally
require the server's write capability (`ALLOTMINT_MCP_WRITE_ENABLED=true`, same gate as
`allotmint_apply_reconciliation`):

```bash
export ALLOTMINT_MCP_WRITE_ENABLED=true
java -jar target/allotmint-mcp-server.jar
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALLOTMINT_MCP_DATA_QUALITY_ENABLED` | `true` | Registers the data-quality tool (read actions)
| `ALLOTMINT_MCP_WRITE_ENABLED` | `false` | Also permits the `fix`/`dedupe`/`undo` write actions |

The backend enforces no-clobber, `.bak` backups, and atomic audit records on every fix. The data-quality
admin endpoints are tracked in [leonarduk/allotmint#6724](https://github.com/leonarduk/allotmint/issues/6724).

### `allotmint_research` (opt-in)

> **What's different from v0:** The four core query tools are deterministic REST wrappers with no external dependencies beyond the AllotMint backend. Enabling `allotmint_research` introduces the server's first LLM dependency, a pgvector retrieval store, and optional Langfuse observability — each with its own configuration, dependency, and egress path. The defaults stay local and free (Ollama + local embeddings), but switching to a hosted LLM or enabling Langfuse requires outbound internet access. See [Design: allotmint_research agentic/RAG MCP tool + LLM observability (Langfuse)](https://github.com/leonarduk/allotmint/discussions/4915) for the full rationale.

Answers a compound natural-language question by retrieving relevant embedded context and chaining the four core read-only query tools as the question requires, returning a grounded answer whose `[n]` markers cite the retrieved documents and tool calls behind it.

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": ["ask"]
    },
    "question": {
      "type": "string",
      "minLength": 1
    },
    "owner": {
      "type": "string",
      "minLength": 1
    },
    "lookback_days": {
      "type": "integer",
      "minimum": 1,
      "maximum": 3650,
      "default": 365
    }
  },
  "required": ["action", "question"],
  "additionalProperties": false
}
```

Unlike the tools above, this one is **off by default** and needs two things running alongside the server:

- the [research agent sidecar](research-agent/README.md), which runs the agent loop (Python, Pydantic AI);
- the HTTP transport, because the agent reaches the four core query tools as an MCP client of this server's own `/mcp` endpoint. Both transports can run at once, so a stdio client still works.

```bash
export ALLOTMINT_MCP_RESEARCH_ENABLED=true
java -jar target/allotmint-mcp-server.jar --spring.profiles.active=http
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `ALLOTMINT_MCP_RESEARCH_ENABLED` | `false` | Registers the tool |
| `ALLOTMINT_RESEARCH_BASE_URL` | `http://localhost:8100` | The sidecar |
| `ALLOTMINT_RESEARCH_CONNECT_TIMEOUT_SECONDS` | `5` | |
| `ALLOTMINT_RESEARCH_READ_TIMEOUT_SECONDS` | `180` | One call is a whole agent loop, often against a local model |

The sidecar's own configuration — which LLM, which retrieval store — is documented in [research-agent/README.md](research-agent/README.md). Its defaults run at no cost: a local Ollama model and locally-computed embeddings, no API key. Enabling this tool is what introduces the server's first LLM dependency, which is why it is opt-in.

The tool stays read-only: the sidecar allowlists exactly the four v0 tool names, so no write path is reachable through it, and `allotmint_research` is excluded from that allowlist so the agent cannot recurse into itself. An answer with no retrieved context and no tool calls behind it is returned as an error, not as prose.

To exercise this tool without Claude Desktop or the MCP Inspector, use the [mcp-client](mcp-client/README.md) — a minimal CLI that connects over MCP and asks it questions directly, plus an optional [locally hosted browser UI](mcp-client/README.md#web-ui) (`python webui.py`) on the same client.

### Multiple checkouts of this repo

When more than one clone of this repo runs on the same machine, `docker-compose.yml` no longer sets hardcoded `container_name` values — Compose derives per-project names automatically (`${COMPOSE_PROJECT_NAME}-pgvector-1`, etc.), so two checkouts can run their own pgvector and research-agent containers without colliding. Use `docker compose ps` to find the actual container names in your checkout. If you have old containers from before this change, remove them first: `docker rm -f allotmint-mcp-pgvector allotmint-mcp-research-agent`.

## Build and quality gates

```bash
./mvnw verify
```

This runs the test suite, Spotless (Google Java Format), JaCoCo reporting, and OWASP dependency-check. GitHub Actions runs the same target for pushes and pull requests to `main` and caches Maven dependencies and the dependency-check database.

Before committing Java changes, run:

```bash
./mvnw spotless:apply
```

## Developer tooling

The issue/PR/review automation CLI (`sync-issues`, `work-on-issue`, `local-review`,
`commit-and-push`, `run-ci-checks`, ...) is no longer vendored under
`scripts/developer_tools/` — it's the shared
[cicaid-devtools](https://github.com/leonarduk/cicaid) package now, installed with:

```bash
pip install -r scripts/requirements-dev.txt
```

See [cicaid's README](https://github.com/leonarduk/cicaid#readme) for the full
command list, e.g. `commit-and-push` and `publish-pr`. `run-ci-checks` reads its
check list from [`.cicaid-checks.toml`](.cicaid-checks.toml) in this repo (Maven
build + research-agent/mcp-client pytest, mirroring `.github/workflows/build.yml`).
`scripts/g_run_tests.ps1` remains as a PowerShell wrapper around `./mvnw verify`.
