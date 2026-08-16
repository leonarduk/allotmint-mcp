# AllotMint MCP operational runbook

This runbook is for the person operating a local or deployed AllotMint MCP stack. Commands assume
the repository root as the working directory unless noted otherwise. The stack can contain the Java
MCP server, the optional Python `mcp-client`, and the optional `research-agent` with pgvector and an
LLM. Only restart components that are enabled in the affected environment.

## First response

1. Record the failing request, timestamp, transport (stdio or HTTP), and whether the failure affects
   core tools or only `allotmint_research`. Do not copy authentication tokens into an incident note.
2. Check process/container state and the two HTTP health endpoints:

   ```bash
   docker compose --profile research ps
   curl --fail --silent --show-error http://localhost:8080/actuator/health
   curl --fail --silent --show-error http://localhost:8100/health
   ```

   The Java health endpoint exists only with the `http` Spring profile. A stdio-only server should
   instead be checked through its client (for example, call `echo` or `allotmint_health`). The
   research-agent health response confirms that its process and configuration load; it deliberately
   does not probe pgvector, the LLM, or the MCP server.
3. Inspect the relevant logs below before restarting. Preserve the error and preceding context.
4. Verify dependencies in request order: client -> MCP server -> AllotMint backend; for research
   calls also check MCP server -> research-agent -> pgvector/LLM -> MCP server.

The default ports are MCP HTTP `8080`, research-agent `8100`, pgvector `5432`, Ollama `11434`,
Gradio `8601`, and the deprecated client web UI `8600`. Configuration may override these values.

## Logs

| Component / launch method | Log location or command | Notes |
| --- | --- | --- |
| MCP server (all modes) | `${LOG_FILE}`, default `~/.allotmint-mcp/logs/allotmint-mcp.log` | File-only logging protects the stdio JSON-RPC stream. `LOG_FILE` should be an absolute writable path. |
| MCP server started by `mcp-client --start-deps` | `mcp-client/logs/allotmint-mcp.log` | Startup wrapper output is appended here in addition to the server's normal log. Its PID is in `mcp-client/logs/allotmint-mcp.pid`. |
| `mcp-client` and dependency manager | `mcp-client/logs/mcp-client.log` | Timestamped preflight, startup, shutdown, and error messages. |
| Ollama started by `mcp-client --start-deps` | `mcp-client/logs/ollama.log` | Ollama installed as a system service uses the platform service manager instead. |
| research-agent in Compose | `docker compose --profile research logs --tail=200 research-agent` | Add `--follow` to stream. Uvicorn application errors and research-run exceptions go to stdout/stderr. |
| pgvector in Compose | `docker compose logs --tail=200 pgvector` | Includes PostgreSQL startup, readiness, and query errors. |
| research-agent run manually | The terminal or the process supervisor's captured stdout/stderr | Redirect or configure the supervisor to retain these logs in production. |
| Structured research traces (optional) | `ALLOTMINT_RESEARCH_TRACE_FILE` | JSON Lines file. With a trace ID, query `GET /research/trace/{trace_id}`. Empty by default, so this is not a general service log. |
| Gradio / deprecated web UI | The launching terminal plus `mcp-client/logs/mcp-client.log` | UI and dependency-start status are emitted at startup. |

For a service-manager or orchestrated deployment, the manager's journal/container log is the source
for launcher and crash output, while the Java application still writes to `LOG_FILE`. Confirm the
actual environment and working directory rather than assuming local defaults.

## Restart procedures

Restarting reloads `.env` and process environment configuration. Confirm that
`ALLOTMINT_MCP_AUTH_TOKEN` is current before restarting against an authenticated backend; never put
its value on a command line or in a log.

### MCP server

**Manually launched HTTP server**

1. Stop it with `Ctrl-C` (or have its process supervisor send `SIGTERM`).
2. Check that port 8080 has been released and start it with the required flags:

   ```bash
   ALLOTMINT_MCP_RESEARCH_ENABLED=true \
     java -jar target/allotmint-mcp-server.jar --spring.profiles.active=http
   curl --fail --silent --show-error http://localhost:8080/actuator/health
   ```

   Omit `ALLOTMINT_MCP_RESEARCH_ENABLED=true` when the research tool is not intended. If the JAR is
   older than `src/` or `pom.xml`, rebuild it first with `./mvnw package`.

**Manually launched stdio server / Claude Desktop**

The stdio server is owned by its MCP client. Restart Claude Desktop (or the relevant MCP client),
which terminates and relaunches the configured Java command. Then call `echo` followed by
`allotmint_health`. Do not launch a second copy in a terminal as a substitute: it will use that
terminal's stdin/stdout rather than the client's MCP connection.

**Started by `mcp-client --start-deps`**

```bash
cd mcp-client
python stop_deps.py --mcp-server
python client.py --list-tools --start-mcp-server
```

The stop helper only terminates the PID it previously started. If it reports that an externally
managed process is still listening, restart that process through its actual owner instead.

### mcp-client

The CLI is not a daemon: cancel a stuck invocation with `Ctrl-C`, review
`mcp-client/logs/mcp-client.log`, and rerun the same command. For the Gradio UI, stop the foreground
process with `Ctrl-C` and restart it from the client virtual environment:

```bash
cd mcp-client
python gradio_ui.py --start-deps
```

If dependencies were auto-started and need a clean restart as well, run `python stop_deps.py` first.
That command preserves the pgvector volume and does not stop externally managed Ollama or Java
processes.

### research-agent

**Compose-managed (recommended with this repository)**

```bash
docker compose --profile research restart research-agent
curl --fail --silent --show-error http://localhost:8100/health
docker compose --profile research logs --tail=50 research-agent
```

If configuration, dependencies, or the image changed, recreate instead of merely restarting:

```bash
docker compose --profile research up -d --build --force-recreate research-agent
```

**Manually launched**

Stop Uvicorn with `Ctrl-C` (or `SIGTERM`) and restart from `research-agent`:

```bash
./.venv/bin/python -m uvicorn app.main:app --port 8100
```

On Windows use `.venv/Scripts/python`. After either restart, check `/health`, then make a small
research request through the MCP client. A healthy endpoint alone does not validate the database,
model, or callback into MCP.

### Supporting research services

Restart pgvector without deleting its persistent volume:

```bash
docker compose restart pgvector
docker compose ps pgvector
```

Wait for it to report `healthy` before testing research. Use `docker compose down -v` only when an
intentional, destructive database reset has been approved; reseed afterwards with `ingest.py`.
Restart Ollama through the operating-system service manager when installed as a service. If the
client started it, use `python mcp-client/stop_deps.py --ollama` and then a client command with
`--start-ollama`.

## Common failure signatures and first checks

| Signature | First checks |
| --- | --- |
| MCP client times out, connection is refused, or `/mcp` returns no response | Confirm the Java process and port 8080. Check `/actuator/health` and the Java log. Confirm the `http` profile is active for HTTP clients and that no other process owns the port. |
| Stdio client reports invalid JSON / protocol framing | Inspect the MCP server log and client configuration. The server must log to a file, not stdout; check `LOG_FILE` is writable and that no wrapper prints to stdout. Restart through the owning client. |
| `Unknown tool` or `missing required tool(s): allotmint_research` | Confirm `ALLOTMINT_MCP_RESEARCH_ENABLED=true`, use `--list-tools`, and check that the JAR is not stale. Rebuild and restart the Java server. |
| `allotmint_health` reports the backend unavailable, or tools return connection errors | Check `ALLOTMINT_API_BASE`, then query the AllotMint backend directly. Verify DNS/TLS/network access from the Java host, not only from a workstation. |
| HTTP 401/403 from AllotMint | The backend JWT is commonly expired or is the wrong token type. Obtain a fresh backend-issued JWT, set `ALLOTMINT_MCP_AUTH_TOKEN` without logging it, and restart the MCP server. |
| `allotmint_research` reports sidecar connection refused / unavailable | Check `curl http://localhost:8100/health`, research-agent logs, and `ALLOTMINT_RESEARCH_BASE_URL`. In containers, verify host/container addressing rather than assuming `localhost`. |
| research-agent `/health` is OK but a research request returns 502 | Read the `Research run failed` traceback. Check pgvector readiness and DSN, LLM provider/model/key/base URL, and reachability of the configured MCP callback URL. `/health` does not probe those dependencies. |
| Retrieval unavailable, no documents, or an ungrounded-answer error | Check pgvector is healthy and `ALLOTMINT_RESEARCH_DB_DSN` is correct. Confirm the corpus was ingested; seed a new local database with `cd research-agent && .venv/bin/python ingest.py --sample`. |
| LLM connection error, model not found, or authentication error | Verify `ALLOTMINT_RESEARCH_LLM_PROVIDER`, model, base URL, and API key. For Ollama run `curl http://localhost:11434/api/tags` and confirm the configured model is present. |
| Research request loops back with MCP connection errors | The research-agent must reach the Java server's HTTP transport. Check `ALLOTMINT_RESEARCH_MCP_URL` (Compose defaults to `host.docker.internal:8080/mcp`), the Java `http` profile, and the research container's network path. |
| pgvector container is unhealthy | Run `docker compose logs pgvector`, check disk space and port conflicts, and verify the configured database/user. Do not delete the volume as a first response. |
| `--start-deps` says Docker daemon is not reachable or a dependency never became ready | Start Docker, inspect `mcp-client/logs/mcp-client.log` and the component log, then retry with a larger `--start-timeout` only if startup is genuinely slow. |
| Address already in use | Use `docker compose --profile research ps` and the platform's port/process tools to identify the owner. Stop it through its supervisor; do not kill an unrelated process merely to free a default port. |

## Recovery verification

After corrective action:

1. Recheck process/container state and applicable health endpoints.
2. Run `cd mcp-client && python client.py --list-tools` to validate MCP negotiation.
3. Call `echo`, then `allotmint_health`; if research is enabled, make one small known-good research
   request and verify it includes sources.
4. Watch logs during the check and confirm that errors have stopped rather than only that a process
   restarted.
5. Record the cause, configuration or version changed, commands run, and any follow-up. Redact JWTs,
   API keys, portfolio data, and sensitive prompt or tool output.
