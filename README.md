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

Restart Claude Desktop after saving the configuration. The `echo` tool is available as a transport smoke test; the four AllotMint tools are documented below.

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

## Build and quality gates

```bash
./mvnw verify
```

This runs the test suite, Spotless (Google Java Format), JaCoCo reporting, and OWASP dependency-check. GitHub Actions runs the same target for pushes and pull requests to `main` and caches Maven dependencies and the dependency-check database.

Before committing Java changes, run:

```bash
./mvnw spotless:apply
```
