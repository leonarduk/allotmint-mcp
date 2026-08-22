# 0002. pgvector for retrieval

## Status

Accepted

## Context

`allotmint_research` grounds its answers in two sources: retrieved documents
(key findings, news, report snapshots) and live tool calls. The retrieval
half needs a vector similarity search over embedded documents.

This was proved out first as a throwaway spike tracked in
[issue #11](https://github.com/leonarduk/allotmint-mcp/issues/11) —
`scripts/spikes/pgvector_research/README.md` — before being promoted into
the real retrieval path in `research-agent/app/retrieval.py` (see that
module's docstring: "pgvector retrieval, promoted from the issue #11
spike").

The spike considered two options:

- **pgvector (Postgres + the `pgvector` extension)** — gets a similarity
  operator (`<=>`) and an HNSW index for free, runs entirely locally via
  Docker at no cost.
- **DynamoDB/S3 brute-force cosine similarity** — no vector index; would
  require loading and comparing every document's embedding in application
  code at query time. Rejected: fine at a trivial document count, but
  doesn't scale, and adds bespoke similarity-search code to maintain
  instead of using pgvector's built-in operator and index.

Embeddings themselves are computed locally with `sentence-transformers`
(`all-MiniLM-L6-v2`), not a hosted embeddings API — see the spike README's
"Decision: embeddings source" section for that sub-decision (zero marginal
cost, no second external API/egress dependency, good enough quality at this
document count). `research-agent/app/retrieval.py` keeps that model
process-wide cached and CPU-only.

## Decision

We will use Postgres with the `pgvector` extension as the retrieval store
for `allotmint_research`, queried with the cosine distance operator
(`embedding <=> %s`) and an HNSW index on the `research_docs` table, running
locally via Docker Compose (`docker-compose.yml`'s `pgvector` service,
`pgvector/pgvector:pg16`).

`research-agent/app/retrieval.py` implements the query path against this
store: a `lookback_days` filter on dated documents, an optional `owner`
filter (documents with no owner are shared context and always eligible),
and graceful degradation (`RetrievalUnavailable`) when the store or the
`psycopg`/`pgvector` driver is unreachable, so a down retrieval store
doesn't take down the whole research tool — the agent can still answer using
live tool calls, with a warning that retrieval was unavailable.

## Consequences

- Adds Postgres (with the `pgvector` extension specifically) as a runtime
  dependency of the research feature, on top of the AllotMint backend the
  Java server already depends on — but only when `allotmint_research` is
  enabled; the four core tools have no database dependency at all.
- Retrieval quality is bounded by a general-purpose, locally-run embedding
  model rather than a larger hosted one; acceptable at the current document
  count and revisited only if embedding quality — not LLM synthesis —
  becomes the bottleneck (per the spike README).
- Degradation-not-failure on retrieval outage means the agent's `grounded`
  flag must be trusted to reflect what actually happened (tool calls vs.
  retrieved documents vs. both), rather than assuming retrieval always
  succeeded when the tool returns 200.
- Local Docker Compose keeps the retrieval store free and zero-egress by
  default, consistent with the cost-conscious default established for the
  agent LLM itself (issues #12/#13 — local model or DeepSeek, not a premium
  hosted API by default).
