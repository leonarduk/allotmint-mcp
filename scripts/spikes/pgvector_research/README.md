# pgvector retrieval spike (issue #11)

Throwaway spike proving a local, zero-cost round trip: embed AllotMint-shaped
documents, store them in Postgres+pgvector, and run a similarity query. Not
wired into the MCP server — see [issue #11](https://github.com/leonarduk/allotmint-mcp/issues/11)
for scope.

## Setup

```bash
# from the repo root
docker compose up -d

# from this directory
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
./.venv/Scripts/python pgvector_ingest.py          # .venv/bin/python on macOS/Linux
```

`docker compose down -v` tears the container and volume back down.

## What it does

1. Loads three fixture shapes from `fixtures/`, standing in for real content
   (see "Fixtures" below):
   - `key_findings.md` — parsed the same way as `accounts/{owner}/key_findings.md`
   - `news_items.json` — a handful of instrument news items shaped like
     `backend/routes/news.py`'s output
   - `report_snapshot.json` — one `portfolio.sectors` report snapshot
2. Embeds each document locally with `sentence-transformers`
   (`all-MiniLM-L6-v2`, 384 dimensions, CPU, no API key, no network egress).
3. Stores them in a `research_docs` table in Postgres with a `vector(384)`
   column and an HNSW cosine index.
4. Runs a cosine-similarity query for the sample question from the design doc
   ("how has my tech exposure changed this year, and why?") and prints the
   nearest neighbors.

## Result

Ran 2026-08-05. The five nearest neighbors for the sample question, ranked by
cosine distance (lower = more similar):

```
[0.5579] key_findings.md          — the tech-exposure finding itself
[0.6171] report:portfolio.sectors — the sector breakdown backing that finding
[0.7212] news:MSFT:2026-04-28     — Azure/AI growth (tech sector news)
[0.7284] news:ASML:2026-06-02     — lithography order backlog (tech sector news)
[0.7491] news:NVDA:2026-05-14     — data center guidance (tech sector news)
```

The two most relevant documents (the finding and the report backing it) rank
above all news items, and the news items that surface are all tech-sector —
confirming the retrieval round trip returns sensible neighbors, not noise.

## Fixtures

The real `accounts/{owner}/key_findings.md` and `backend/routes/news.py`
outputs live in the main `allotmint` repo, not this one. Per issue #11's
constraint (read-only sampling only, no production S3/DynamoDB access), the
fixtures here are hand-written samples shaped to match those formats rather
than a copy of real account data. Swap in real (non-production) samples if a
closer fidelity check is needed later.

## Decision: embeddings source

**Local (`sentence-transformers`, `all-MiniLM-L6-v2`), not a hosted API.**

This mirrors the cost-conscious decision already made for the
`allotmint_research` agent LLM itself (issues #12/#13 — local model or
DeepSeek, not a premium hosted API by default). Running the embeddings model
locally means:

- **$0 marginal cost** — no per-token billing for ingestion or queries, which
  matters more here than for the agent LLM since embedding happens on every
  document *and* every query.
- **No second external API dependency** — avoids adding an OpenAI (or
  similar) credential/egress requirement on top of whatever the agent LLM
  already needs.
- **Good enough quality for this scope** — `all-MiniLM-L6-v2` is a
  well-established general-purpose sentence embedding model; a handful of
  finance-domain documents don't need a larger/specialized embedding model to
  produce sensibly-ranked neighbors, as the result above shows.

The tradeoff: a hosted API (e.g. OpenAI `text-embedding-3-small`) would likely
give marginally better semantic ranking on ambiguous queries, and offloads
compute from wherever `allotmint-mcp` runs. Neither matters yet at this
scale, so the free/local option wins. Revisit if/when embedding quality
becomes the retrieval bottleneck rather than the LLM synthesis step.

## Fallback considered and rejected: DynamoDB/S3 brute-force cosine similarity

Not implemented — no vector index, would require loading and comparing every
document's embedding at query time in application code rather than letting
the database do it. Fine at this document count, but doesn't scale past a
trivial corpus and adds bespoke similarity-search code to maintain instead of
using pgvector's built-in operator (`<=>`) and HNSW index. pgvector was
chosen because it gets both indexing and the similarity operator for free,
and runs entirely locally via Docker at no cost — there's no scale/cost
tradeoff here that favors the brute-force approach.
