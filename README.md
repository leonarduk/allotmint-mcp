# allotmint-mcp

Standalone MCP server for [AllotMint](https://github.com/leonarduk/allotmint) built with Spring Boot 4.1.0, Java 25, and the [MCP Java SDK](https://github.com/modelcontextprotocol/java-sdk). Registers the same tool set on both a stdio transport (for Claude Desktop / MCP Inspector) and an HTTP/streamable transport (`/mcp`), so a single process can serve either.

## Status

Proof of concept. The MCP plumbing (stdio + HTTP transports, JSON mapping, exception handling, Actuator health/metrics) is wired up and tested. Both transports expose the same tools:

- `echo` — verifies the transport end to end.
- `allotmint_instrument` — looks up an instrument. `action` is required: `search` (query required) matches by ticker/name; `detail` (ticker required) merges price history, portfolio positions, and recent news; `prices` (ticker required) returns the latest quote; `news` (ticker required) returns recent headlines. An optional `exchange` is appended to `ticker` when `ticker` doesn't already carry a suffix (e.g. `ticker=VWRL`, `exchange=L` becomes `VWRL.L`).

More AllotMint API and local file-access tools described in the repo summary are not implemented yet.

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
