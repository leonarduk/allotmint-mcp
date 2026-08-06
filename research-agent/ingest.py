"""Populates the pgvector retrieval store the research agent queries.

Promoted from the issue #11 spike (scripts/spikes/pgvector_research/), with the
things a running service needs that a spike didn't: a stable schema with owner
and publication-date columns so `owner` and `lookback_days` can filter, an
idempotent upsert keyed on source so re-running doesn't duplicate, and a
directory-based input so real exports can be dropped in without editing code.

Usage:
    docker compose up -d                       # from the repo root
    pip install -r requirements.txt
    python ingest.py --input ./corpus          # a directory of documents
    python ingest.py --sample                  # the spike's fixtures, for a smoke test

Input directory format: one JSON file per batch, each an object or a list of
objects with at least `source` and `content`, optionally `owner`, `doc_type`,
and `published` (ISO date). Plain `.md`/`.txt` files are ingested whole with
their filename as the source.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from app.config import load_settings

log = logging.getLogger("ingest")

# The ALTERs are not redundant with the CREATE: anyone who ran the #11 spike
# already has a `research_docs` table with only (source, content, embedding),
# which CREATE TABLE IF NOT EXISTS would silently leave alone. Adding the
# columns explicitly upgrades that table instead of failing on it.
#
# Uniqueness lives in an index rather than a column constraint for the same
# reason: ADD COLUMN can extend an existing table, but ADD UNIQUE to an
# existing column cannot be made idempotent as cleanly.
SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS research_docs (
    id        SERIAL PRIMARY KEY,
    source    TEXT NOT NULL,
    content   TEXT NOT NULL,
    owner     TEXT,
    doc_type  TEXT,
    published DATE,
    embedding VECTOR({dim}) NOT NULL
);

ALTER TABLE research_docs ADD COLUMN IF NOT EXISTS owner TEXT;
ALTER TABLE research_docs ADD COLUMN IF NOT EXISTS doc_type TEXT;
ALTER TABLE research_docs ADD COLUMN IF NOT EXISTS published DATE;

CREATE UNIQUE INDEX IF NOT EXISTS research_docs_source_key ON research_docs (source);
CREATE INDEX IF NOT EXISTS research_docs_embedding_idx
    ON research_docs USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS research_docs_published_idx ON research_docs (published);
"""

UPSERT = """
INSERT INTO research_docs (source, content, owner, doc_type, published, embedding)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (source) DO UPDATE SET
    content   = EXCLUDED.content,
    owner     = EXCLUDED.owner,
    doc_type  = EXCLUDED.doc_type,
    published = EXCLUDED.published,
    embedding = EXCLUDED.embedding
"""

# Mirrors scripts/spikes/pgvector_research/fixtures/, so `--sample` reproduces
# the spike's verified retrieval result without depending on that directory.
SAMPLE_DOCUMENTS = [
    {
        "source": "key_findings.md",
        "owner": "demo",
        "doc_type": "key_findings",
        "published": "2026-08-01",
        "content": (
            "Technology exposure rose from 18% to 27% of the portfolio over the past year, "
            "the largest single-sector shift. The increase came from price appreciation in "
            "existing semiconductor and cloud holdings rather than new purchases."
        ),
    },
    {
        "source": "report:portfolio.sectors",
        "owner": "demo",
        "doc_type": "report",
        "published": "2026-08-01",
        "content": (
            "Portfolio sector report as of 2026-08-01: Technology 27.0% (was 18.0%), "
            "Financials 15.5% (was 17.0%), Healthcare 12.0% (was 13.5%), Consumer "
            "Discretionary 10.5% (was 11.0%), Industrials 9.0% (was 10.0%), Other 26.0% "
            "(was 29.5%). Technology sector weight increased 9 percentage points "
            "year-over-year, the largest single-sector shift in the portfolio."
        ),
    },
    {
        "source": "news:NVDA:2026-05-14",
        "doc_type": "news",
        "published": "2026-05-14",
        "content": (
            "NVIDIA raises data center revenue guidance on AI chip demand. NVIDIA lifted its "
            "quarterly revenue guidance, citing sustained demand for its data center GPUs "
            "from cloud providers building out AI infrastructure."
        ),
    },
    {
        "source": "news:MSFT:2026-04-28",
        "doc_type": "news",
        "published": "2026-04-28",
        "content": (
            "Microsoft Azure growth accelerates on AI services adoption. Microsoft reported "
            "Azure revenue growth of 31%, ahead of estimates, attributed to enterprise "
            "adoption of Copilot and AI-related cloud services."
        ),
    },
    {
        "source": "news:ASML:2026-06-02",
        "doc_type": "news",
        "published": "2026-06-02",
        "content": (
            "ASML order backlog grows as chipmakers invest in next-gen lithography. ASML "
            "reported a larger-than-expected order backlog as semiconductor manufacturers "
            "continue investing in EUV lithography equipment."
        ),
    },
]


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        log.warning("Ignoring unparseable published date %r", value)
        return None


def load_from_directory(directory: Path) -> list[dict]:
    """Reads every JSON/Markdown/text document under `directory`."""
    documents: list[dict] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not item.get("source") or not item.get("content"):
                    log.warning("Skipping entry in %s without source/content", path.name)
                    continue
                documents.append(item)
        elif path.suffix.lower() in (".md", ".txt"):
            documents.append(
                {
                    "source": str(path.relative_to(directory)).replace("\\", "/"),
                    "content": path.read_text(encoding="utf-8"),
                    "doc_type": path.suffix.lower().lstrip("."),
                }
            )
    return documents


def ingest(documents: list[dict]) -> int:
    """Embeds and upserts `documents`, returning how many were written."""
    import psycopg
    from pgvector.psycopg import register_vector
    from sentence_transformers import SentenceTransformer

    settings = load_settings()

    log.info("Loading local embedding model %r", settings.embedding_model)
    model = SentenceTransformer(settings.embedding_model)
    embeddings = model.encode([d["content"] for d in documents], normalize_embeddings=True)

    with psycopg.connect(settings.db_dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)
        for statement in SCHEMA.format(dim=settings.embedding_dim).split(";"):
            if statement.strip():
                conn.execute(statement)

        for document, embedding in zip(documents, embeddings):
            conn.execute(
                UPSERT,
                (
                    document["source"],
                    document["content"],
                    document.get("owner"),
                    document.get("doc_type"),
                    _parse_date(document.get("published")),
                    embedding,
                ),
            )

    return len(documents)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path, help="Directory of documents to ingest")
    group.add_argument(
        "--sample",
        action="store_true",
        help="Ingest the built-in sample corpus (the #11 spike's fixtures)",
    )
    args = parser.parse_args()

    documents = SAMPLE_DOCUMENTS if args.sample else load_from_directory(args.input)
    if not documents:
        log.error("No documents found; nothing ingested")
        raise SystemExit(1)

    written = ingest(documents)
    log.info("Ingested %d document(s) into research_docs", written)


if __name__ == "__main__":
    main()
