# AllotMint research agent

The agentic RAG loop behind the `allotmint_research` MCP tool ([issue #13](https://github.com/leonarduk/allotmint-mcp/issues/13)).

A small FastAPI service. The Java MCP server calls it over local HTTP; it retrieves relevant context from pgvector, runs a [Pydantic AI](https://ai.pydantic.dev/) agent that chains the four read-only v0 MCP tools, and returns a grounded answer with citations.

## Multi-agent orchestration

The service uses a **sequential supervisor/worker** pattern. The research
worker in `app/agent.py` retrieves context, calls MCP tools, and synthesizes an
answer. It then hands the answer and the assembled (not model-invented)
evidence to a distinct, tool-free verifier in `app/orchestration.py`. The
verifier may approve the answer or request review; it cannot alter the answer
or call tools.

Approval is fail-closed: the existing deterministic guardrail and the verifier
must both approve. A disagreement between them, a verifier timeout, a malformed
verdict, or a verifier/provider exception returns the answer with
`needs_review=true` and an actionable entry in `review_reasons`. This preserves
the grounded result for inspection without silently treating an unreviewed
answer as safe. `tests/test_orchestration.py` exercises each hand-off failure
mode without an external model.
For intended use, limitations, risk classification, EU AI Act considerations,
and NIST AI RMF alignment, see [Responsible AI and governance](../docs/governance.md).

```
Claude/Inspector ──▶ allotmint-mcp (Java)
                        │  allotmint_research
                        ▼
                     research-agent (this service)
                        │  ├── pgvector: retrieve context
                        │  ├── LLM (Ollama by default): decide + synthesize
                        │  └── MCP client ─┐
                        │                  │ allotmint_portfolio / _instrument
                        └──────────────────┘ / _market / _health
                             back into allotmint-mcp's own /mcp endpoint
```

The agent reaching the v0 tools *as an MCP client of the same server* is the point: the portfolio maths, filters, and instrument lookups stay in the Java implementations and are not reimplemented here.

## Why these pieces

Both choices were settled by spikes before this was built:

| Decision | Choice | Where |
|---|---|---|
| Retrieval store | Postgres + `pgvector`, embedded locally with `sentence-transformers` (`all-MiniLM-L6-v2`) | [#11](https://github.com/leonarduk/allotmint-mcp/issues/11), `scripts/spikes/pgvector_research/` |
| Agent framework | Pydantic AI (LangGraph's prebuilt ReAct agent didn't reliably chain the second tool call, and fabricated content when it skipped it) | [#12](https://github.com/leonarduk/allotmint-mcp/issues/12), `scripts/spikes/agent_framework_comparison/` |
| JVM/Python interop | A local HTTP service called with Spring's `RestClient` — the pattern `AllotMintClient` already uses | [#12](https://github.com/leonarduk/allotmint-mcp/issues/12) |

## Grounding and citations

Citations are built from what actually happened during a run — the documents retrieval returned, and the tool calls the agent really made — never from the model's own claims. Concretely:

- Retrieved documents are numbered `[1]..[n]` in the prompt; the model cites them by number.
- Tool results are cited by name (`[tool:allotmint_portfolio]`), because the model can't know their numbers while writing. Those markers are rewritten to numbers afterwards, from the recorded calls.
- A marker pointing at something that doesn't exist — a tool that was never called, or `[9]` when there are four sources — becomes a warning, not a citation.
- `grounded` is `false` when a run produced neither a retrieved document nor a tool call. The Java tool turns that into an MCP error rather than passing the prose along.

The read-only boundary is enforced in code, not in the prompt: `app/mcp_tools.py` refuses to invoke anything outside the four-tool allowlist. `allotmint_research` is deliberately absent from it, so the agent cannot recurse into itself.

## Run it

Four processes, in this order.

**1. Retrieval store**

```bash
docker compose up -d pgvector
```

**2. A model.** The default is free and local:

```bash
ollama pull llama3.2
```

Not every local model can actually call tools — the #12 spike found `qwen2.5-coder` and vanilla `deepseek-r1:8b` print tool calls as plain text, and `gemma3` rejects tool binding outright. `llama3.2` and a locally-imported DeepSeek-Qwen3-8B both worked. Verify tool calling before switching.

**3. This service**

```bash
cd research-agent
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
./.venv/Scripts/python ingest.py --sample         # or --input ./your-corpus
./.venv/Scripts/python -m uvicorn app.main:app --port 8100
```

**4. The MCP server**, with the HTTP transport on so the agent can call the v0 tools back:

```bash
ALLOTMINT_MCP_RESEARCH_ENABLED=true \
  java -jar target/allotmint-mcp-server.jar --spring.profiles.active=http
```

Then, through any MCP client:

```json
{"action": "ask", "question": "how has my tech exposure changed this year, and why?", "owner": "demo"}
```

## Verified run

Ran 2026-08-05 against local Ollama (`llama3.2`), pgvector seeded with `ingest.py --sample`, and the Java server on `--spring.profiles.active=http`, calling `allotmint_research` through MCP exactly as a client would:

```
{"action": "ask", "question": "How has my tech exposure changed this year, and why?", "owner": "demo"}
```

```
The tech exposure in the portfolio has increased by 9 percentage points over the
past year, from 18% to 27%, making it the largest single-sector shift. This
increase is attributed to price appreciation in existing semiconductor and cloud
holdings.

The technology sector weight increased 9 percentage points year-over-year, driven
by the growth of Microsoft Azure, which reported revenue growth of 31% ahead of
estimates due to enterprise adoption of Copilot and AI-related cloud services [3].
Additionally, ASML's order backlog grew as chipmakers invested in next-gen
lithography equipment [4].

Sources:
[1]  document: key_findings.md (cosine distance 0.3869)
[2]  document: report:portfolio.sectors (cosine distance 0.6171)
[3]  document: news:MSFT:2026-04-28 (cosine distance 0.7079)
[4]  document: news:ASML:2026-06-02 (cosine distance 0.7172)
[5]  document: news:NVDA:2026-05-14 (cosine distance 0.7598)
[6]  tool_call: allotmint_instrument (action='news', ticker='ASML')
[7]  tool_call: allotmint_instrument (action='news', ticker='NVDA')
[8]  tool_call: allotmint_market (action='movers')
[9]  tool_call: allotmint_instrument (action='news', ticker='MSFT')
[10] tool_call: allotmint_portfolio (action='exposure', owner='demo')
```

Three distinct v0 tools chained in one run, chosen by the agent rather than prescribed, and every number and headline in the answer traces to a listed source.

One rough edge worth knowing: `llama3.2` sometimes copies a citation marker into an unused tool argument (`query='[4]'` alongside `ticker='ASML'`). The v0 tools ignore `query` for `action=news`, so it changes nothing but the citation detail line. A larger model doesn't do it.

## Configuration

Every setting has a working local default; the default configuration costs nothing to run.

> **What's different from v0:** The four v0 tools (`allotmint_health`, `allotmint_instrument`, `allotmint_market`, `allotmint_portfolio`) are deterministic REST wrappers with no external dependencies beyond the AllotMint backend. The research agent adds an LLM, a vector store, and optional observability — each with its own configuration, dependency, and egress path. See [Design: allotmint_research agentic/RAG MCP tool + LLM observability (Langfuse)](https://github.com/leonarduk/allotmint/discussions/4915) for the full rationale behind these choices.

| Variable | Default | Purpose |
|---|---|---|
| `ALLOTMINT_RESEARCH_LLM_PROVIDER` | `ollama` | `ollama`, `deepseek`, or `openai-compatible` |
| `ALLOTMINT_RESEARCH_LLM_MODEL` | `llama3.2` | Model name for that provider |
| `ALLOTMINT_RESEARCH_LLM_BASE_URL` | `http://localhost:11434/v1` | For `ollama` and `openai-compatible` |
| `ALLOTMINT_RESEARCH_LLM_API_KEY` | *(empty)* | Required only for `deepseek` |
| `ALLOTMINT_RESEARCH_AVAILABLE_LLM_PROVIDERS` | current provider | Comma-separated providers offered for per-question selection in clients |
| `ALLOTMINT_RESEARCH_<PROVIDER>_MODEL` | provider default | Model for an alternative selectable provider (for example `DEEPSEEK`) |
| `ALLOTMINT_RESEARCH_<PROVIDER>_BASE_URL` | provider default | Base URL for an alternative selectable provider |
| `ALLOTMINT_RESEARCH_<PROVIDER>_API_KEY` | generic API key | Credential for an alternative selectable provider |
| `ALLOTMINT_RESEARCH_LLM_TEMPERATURE` | `0.0` | Determinism over variety, for a tool quoting real numbers |
| `ALLOTMINT_RESEARCH_MCP_URL` | `http://localhost:8080/mcp` | The allotmint-mcp server's HTTP transport |
| `ALLOTMINT_RESEARCH_MCP_TIMEOUT_SECONDS` | `30` | Per-tool-call timeout |
| `ALLOTMINT_RESEARCH_MAX_TOOL_CALLS` | `6` | Bounds a runaway agent loop |
| `ALLOTMINT_RESEARCH_VERIFIER_TIMEOUT_SECONDS` | `10` | Maximum time allowed for the second-agent evidence review |
| `ALLOTMINT_RESEARCH_DB_DSN` | `postgresql://allotmint:allotmint@localhost:5432/allotmint_research` | Retrieval store |
| `ALLOTMINT_RESEARCH_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Local sentence-transformer model |
| `ALLOTMINT_RESEARCH_EMBEDDING_DIM` | `384` | Must match the model's output dimension |
| `ALLOTMINT_RESEARCH_TOP_K` | `5` | Documents retrieved per question |
| `ALLOTMINT_RESEARCH_MAX_DISTANCE` | `0.85` | Cosine distance above which a document is dropped |
| `ALLOTMINT_RESEARCH_RETRIEVAL_ENABLED` | `true` | Set false to run on tool calls alone |
| `ALLOTMINT_RESEARCH_TRACE_FILE` | *(empty)* | File path for structured JSON trace log; empty disables |
| `LANGFUSE_PUBLIC_KEY` | *(empty)* | Langfuse public key for LLM observability |
| `LANGFUSE_SECRET_KEY` | *(empty)* | Langfuse secret key |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse instance URL (cloud or self-hosted) |

### LLM provider

Switching to the low-cost hosted option is configuration only:

```bash
export ALLOTMINT_RESEARCH_LLM_PROVIDER=deepseek
export ALLOTMINT_RESEARCH_LLM_MODEL=deepseek-chat
export ALLOTMINT_RESEARCH_LLM_API_KEY=sk-...
```

To keep Ollama as the default while allowing each Gradio UI question to choose
DeepSeek, advertise both and configure DeepSeek independently:

```bash
export ALLOTMINT_RESEARCH_AVAILABLE_LLM_PROVIDERS=ollama,deepseek
export ALLOTMINT_RESEARCH_DEEPSEEK_API_KEY=sk-...
```

### Tracing

Set `ALLOTMINT_RESEARCH_TRACE_FILE` to a file path to enable structured JSON trace logging. Every step of a research invocation — retrieval, agent start/end, each tool call — emits one JSON event line with a shared `trace_id`. Traces are written immediately (append + flush), so they survive a process crash and are queryable via `GET /research/trace/{trace_id}` before the request completes.

This is the lightweight MVP tier: no tracing SDK, no new infrastructure. The same file is both the write target and the query source.

### Langfuse observability

Set both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to send each `allotmint_research` invocation to Langfuse as a trace with distinct spans for retrieval, each tool call, and synthesis. The same `trace_id` is used for both the file log and Langfuse, so the two can be correlated.

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://cloud.langfuse.com   # or your self-hosted instance
```

Langfuse is best-effort: failures to reach it are logged as warnings but never cause the research request to fail. Leaving both keys empty (the default) disables it entirely.

### Network egress

The four v0 tools need only the AllotMint backend (default `localhost:8000`). The research agent adds these outbound connections:

| Target | Default | When required |
|---|---|---|
| AllotMint backend | `localhost:8000` | Always (the v0 tools) |
| allotmint-mcp `/mcp` | `localhost:8080` | Always (the agent is an MCP client of the v0 tools) |
| pgvector | `localhost:5432` | When `ALLOTMINT_RESEARCH_RETRIEVAL_ENABLED` is `true` (the default) |
| LLM provider | `localhost:11434` (Ollama) | Always — `ollama` is local; `deepseek` and `openai-compatible` reach out to the configured `ALLOTMINT_RESEARCH_LLM_BASE_URL` |
| Langfuse | `cloud.langfuse.com:443` | Only when both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set |

With the default configuration everything stays on `localhost`. Switching to a hosted LLM or enabling Langfuse is what introduces outbound internet egress — make sure your firewall allows it.

## Ingestion

`ingest.py` embeds documents and upserts them into `research_docs`, keyed on `source` so re-running is idempotent.

```bash
python ingest.py --sample              # the #11 spike's fixtures, for a smoke test
python ingest.py --input ./corpus      # a directory of your own documents
```

A corpus directory holds JSON files (an object or list of objects with `source` and `content`, optionally `owner`, `doc_type`, `published`) and/or `.md`/`.txt` files ingested whole. `owner` scopes a document to one portfolio owner; `published` is what `lookback_days` filters on.

## API

`POST /research/ask` → `{question, owner?, lookback_days?}`; returns `{answer, citations, tool_calls, retrieved_documents, grounded, warnings, model}`. These field names are the contract with `ResearchAnswer.java` — changing one changes both.

`GET /health` reports what this process is configured to talk to. It deliberately does not probe the LLM, the MCP server, or the database: a health check that makes three network calls fails for reasons unrelated to this process being up.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

No database, no LLM, and no running MCP server required — the LLM is a scripted `FunctionModel`, the MCP transport is an in-process fake, and retrieval is stubbed. The sample compound question from the design doc runs as a repeatable test asserting that two different v0 tools get chained and that every citation resolves.
