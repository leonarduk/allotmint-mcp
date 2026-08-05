# allotmint-mcp

Standalone MCP server for [AllotMint](https://github.com/leonarduk/allotmint) built with Spring Boot 4.1.0, Java 25, and the [MCP Java SDK](https://github.com/modelcontextprotocol/java-sdk). Registers the same tool set on both a stdio transport (for Claude Desktop / MCP Inspector) and an HTTP/streamable transport (`/mcp`), so a single process can serve either.

## Status

Proof of concept. The MCP plumbing (stdio + HTTP transports, JSON mapping, exception handling, Actuator health/metrics) is wired up and tested. The server currently exposes:

- `echo` — proves the transport works end to end
- `allotmint_health` — checks connectivity to the configured AllotMint backend
- `allotmint_market` — returns the combined market overview, standalone movers, or the index portion of the overview

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
