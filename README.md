# allotmint-mcp

Standalone MCP server for [AllotMint](https://github.com/leonarduk/allotmint) built with Spring Boot 4.1.0, Java 25, and the [MCP Java SDK](https://github.com/modelcontextprotocol/java-sdk). Registers the same tool set on both a stdio transport (for Claude Desktop / MCP Inspector) and an HTTP/streamable transport (`/mcp`), so a single process can serve either.

## Status

Proof of concept. The MCP plumbing (stdio + HTTP transports, JSON mapping, exception handling, Actuator health/metrics) is wired up and tested. Both transports expose the same tools:

- `echo` — verifies the transport end to end.
- `allotmint_health` — checks connectivity to the configured AllotMint backend.
- `allotmint_market` — returns the combined market overview, standalone movers, or the index portion of the overview.
- `allotmint_portfolio` — returns a per-owner summary, exposure breakdown, or flat holdings list. `owner` is required; valid slugs are available from the AllotMint backend's `GET /owners` endpoint. Optional `account_type` and `currency` arguments filter the result client-side.

Set `ALLOTMINT_API_BASE` to override the default backend URL of `http://localhost:8000`.

## Running

Stdio transport (default — how Claude Desktop and the MCP Inspector launch the process):

```
./mvnw spring-boot:run
```

HTTP transport, exposed at `/mcp`, plus Actuator `health`/`info`/`metrics` endpoints:

```
./mvnw spring-boot:run -Dspring-boot.run.profiles=http
```

The two transports register the same `McpSyncServer` tool set; HTTP is off by default because an embedded servlet container can collide with port hints an MCP client sets via environment variables for its own use (Spring Boot's relaxed env binding maps `SERVER_PORT` straight to `server.port`).

## Connecting to an authenticated AllotMint backend

Set the backend URL and a backend-issued JWT before starting the MCP server:

```bash
export ALLOTMINT_API_BASE="https://your-allotmint-backend.example.com"
export ALLOTMINT_MCP_AUTH_TOKEN="<backend-issued-jwt>"
./mvnw spring-boot:run
```

AllotMint currently has no device-flow or service-account login for a headless MCP server. To obtain the token:

1. Sign in to the AllotMint web application with Google.
2. Open the browser's Developer Tools and select the **Network** panel.
3. Trigger an authenticated API request in AllotMint, then select that request.
4. In **Request Headers**, copy only the value after `Bearer ` from the `Authorization` header.
5. Set that value as `ALLOTMINT_MCP_AUTH_TOKEN` and restart the MCP server.

This is AllotMint's own backend-issued HS256 JWT, not the Google ID token used during login. Its default lifetime is approximately **15 minutes**, so repeat the extraction and restart the MCP server when it expires. Missing and expired tokens are reported as:

```text
Auth token missing or expired. Run 'allotmint-mcp login' or set ALLOTMINT_MCP_AUTH_TOKEN.
```

The `allotmint-mcp login` command is not implemented yet; long-lived API keys and device-flow OAuth are also deferred. Until one of those mechanisms exists, copying the short-lived token from Developer Tools is the supported AWS workflow. Treat the token as a password: do not commit it, paste it into logs, or include it in bug reports.

## Build & quality gates

```
./mvnw verify
```

This runs the test suite plus the checks wired into `verify`: Spotless (Google Java Format), JaCoCo coverage reporting, and OWASP `dependency-check` (fails the build on CVSS ≥ 9 findings). CI runs the same `verify` target on every push/PR to `main` via GitHub Actions, with Dependabot keeping Maven and Actions dependencies current.

## Contributing

Code style is enforced by [Spotless](https://github.com/diffplug/spotless) (Google Java Format). Before committing, run:

```
./mvnw spotless:apply
```

`mvn verify` fails the build if the code isn't formatted.
