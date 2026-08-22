# 0003. File-only logging for the stdio MCP transport

## Status

Accepted

## Context

`allotmint-mcp`'s default profile runs the MCP protocol over stdio
(`StdioMcpServerConfig`), which Claude Desktop and the MCP Inspector both
use to launch and talk to the server. The stdio MCP transport reads and
writes newline-delimited JSON-RPC directly on the process's own stdin and
stdout.

Any ordinary log line written to stdout — the default destination for most
logging setups — would be interleaved with that JSON-RPC stream and corrupt
it, silently breaking the client's ability to parse subsequent messages.
This is documented directly in `src/main/resources/logback-spring.xml`'s
header comment.

A second constraint compounds this: an MCP client such as Claude Desktop
launches the server process with its own working directory, not the
project's, so a relative log file path would fail to create its parent
directory and crash the process before the stdio transport ever opens.

## Decision

We will send all application logging to a file only, never to the console,
and resolve that file with an absolute default path.

`src/main/resources/logback-spring.xml` defines a single `FILE` appender
(`ch.qos.logback.core.FileAppender`) as the only appender attached to the
root logger, writing to `${LOG_FILE:-${user.home}/.allotmint-mcp/logs/allotmint-mcp.log}`
— an absolute path by default (under the user's home directory), overridable
via the `LOG_FILE` environment/system property, but never console output.
No console/`ConsoleAppender` is configured for the default (stdio) profile.

## Consequences

- Diagnosing a stdio-launched server (e.g. from Claude Desktop, which
  doesn't surface the child process's console) means reading the log file
  at `~/.allotmint-mcp/logs/allotmint-mcp.log` (or `$LOG_FILE`) rather than
  watching terminal output — see the [operational runbook](../runbook.md)
  for log locations and first-response checks.
- Any new logging statement or dependency that might write to stdout (a
  library defaulting to console logging, a stray `System.out.println`, a
  debug print) is a protocol-corruption risk under the stdio profile and
  must be caught in review, not just under the optional HTTP profile where
  the constraint doesn't apply.
- The absolute default path avoids a startup crash under MCP clients that
  launch the process from an arbitrary working directory, at the cost of
  logs living outside the project directory by default — operators who want
  project-local logs must set `LOG_FILE` explicitly.
