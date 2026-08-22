# 0001. Java MCP server with a Python research-agent sidecar over local HTTP

## Status

Accepted

## Context

`allotmint-mcp` is a Java/Spring Boot MCP server (see `README.md`) exposing four
deterministic, dependency-free REST-wrapper tools (`allotmint_health`,
`allotmint_instrument`, `allotmint_market`, `allotmint_portfolio`, plus the
later `allotmint_reconcile`/`allotmint_data_quality` tools) against the
AllotMint backend.

The `allotmint_research` tool (issue design in
[leonarduk/allotmint#4915](https://github.com/leonarduk/allotmint/discussions/4915))
needed an agentic RAG loop: an LLM deciding which of the existing tools to
call, retrieving embedded context from a vector store, and synthesizing a
cited answer. The Java MCP ecosystem has comparatively little of the
tooling this needs (agent orchestration, local embeddings, LLM provider
abstraction), while Python has mature libraries for exactly this
(Pydantic AI, sentence-transformers, pgvector clients). Rewriting the
existing four v0 tools in Python, or reimplementing an agent loop in Java,
were both rejected as unnecessary duplication of already-working code.

The interop boundary was settled in spike #12 (see the module docstring in
`research-agent/app/main.py`): the Java server calls the Python service over
plain local HTTP with Spring's `RestClient`, exactly as it already calls the
AllotMint backend — no new transport or serialization mechanism to learn.

## Decision

We will implement `allotmint_research` as a separate Python (FastAPI +
Pydantic AI) sidecar process — `research-agent/` — rather than inside the
Java server.

- The Java server (`allotmint-mcp`) calls the sidecar's `POST /research/ask`
  over local HTTP (`ALLOTMINT_RESEARCH_BASE_URL`, default
  `http://localhost:8100`) when the `allotmint_research` tool is invoked.
- The sidecar reaches the four existing v0 tools by being an ordinary MCP
  client of the same Java server's own `/mcp` HTTP-streamable endpoint
  (`research-agent/app/mcp_tools.py`), reusing the Java implementations
  instead of reimplementing portfolio/instrument/market logic in Python.
- The sidecar allowlists exactly those four tool names, so it cannot recurse
  into `allotmint_research` itself and no write-shaped tool is reachable
  through it.
- Both processes are independently deployable: the Java server runs fine
  with `allotmint_research` disabled and no sidecar present at all
  (`ALLOTMINT_MCP_RESEARCH_ENABLED=false`, the default).

## Consequences

- Two runtimes, two dependency ecosystems (Maven/JVM and pip/Python), and
  two processes to start for the full research feature — see the
  Prerequisites list in `research-agent/README.md` and `mcp-client/README.md`
  for the resulting run sequence (pgvector, an LLM, the sidecar, then the
  Java server with HTTP transport and the research tool enabled).
- The HTTP transport must be enabled on the Java server
  (`--spring.profiles.active=http`) for the sidecar to reach it, even though
  stdio remains the default for Claude Desktop — both transports can run at
  once.
- Local HTTP between trusted local processes is simple and needs no auth of
  its own, but it does mean the sidecar and the Java server must agree on
  ports/URLs via configuration (`ALLOTMINT_RESEARCH_BASE_URL`,
  `ALLOTMINT_RESEARCH_MCP_URL`) rather than being able to assume a single
  in-process call.
- We get to use the best-fit language and library ecosystem for each side
  (Java/Spring for a stable, typed MCP server; Python for agent/RAG tooling)
  instead of forcing one language to do both jobs.
