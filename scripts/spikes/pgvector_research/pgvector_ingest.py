"""
Throwaway spike script for allotmint-mcp issue #11.

Proves an end-to-end round trip: embed a handful of AllotMint-shaped documents
locally (no hosted API, no API key), store them in Postgres+pgvector, and run
a similarity query against a sample question.

Not a production ingestion pipeline and not wired into the MCP server -- see
the issue for scope. Run `docker compose up -d` from the repo root first.

Usage:
    pip install -r requirements.txt
    python pgvector_ingest.py
"""

import json
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DB_DSN = "postgresql://allotmint:allotmint@localhost:5432/allotmint_research"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # local, CPU-friendly, 384 dimensions
EMBEDDING_DIM = 384
SAMPLE_QUESTION = "how has my tech exposure changed this year, and why?"


def load_documents():
    docs = []

    key_findings = (FIXTURES_DIR / "key_findings.md").read_text(encoding="utf-8")
    docs.append({"source": "key_findings.md", "content": key_findings})

    news_items = json.loads((FIXTURES_DIR / "news_items.json").read_text(encoding="utf-8"))
    for item in news_items:
        content = f"{item['headline']}. {item['summary']}"
        docs.append({"source": f"news:{item['ticker']}:{item['published']}", "content": content})

    report = json.loads((FIXTURES_DIR / "report_snapshot.json").read_text(encoding="utf-8"))
    sectors_text = ", ".join(f"{s['name']} {s['weight_pct']}% (was {s['weight_pct_year_ago']}%)" for s in report["sectors"])
    report_content = f"Portfolio sector report as of {report['as_of']}: {sectors_text}. {report['note']}"
    docs.append({"source": "report:portfolio.sectors", "content": report_content})

    return docs


def main():
    print(f"Loading local embedding model '{EMBEDDING_MODEL}' ...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    docs = load_documents()
    print(f"Loaded {len(docs)} documents from fixtures/")

    with psycopg.connect(DB_DSN, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)

        conn.execute("DROP TABLE IF EXISTS research_docs")
        conn.execute(
            f"""
            CREATE TABLE research_docs (
                id SERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding VECTOR({EMBEDDING_DIM}) NOT NULL
            )
            """
        )

        print("Embedding and inserting documents ...")
        embeddings = model.encode([d["content"] for d in docs], normalize_embeddings=True)
        for doc, embedding in zip(docs, embeddings):
            conn.execute(
                "INSERT INTO research_docs (source, content, embedding) VALUES (%s, %s, %s)",
                (doc["source"], doc["content"], embedding),
            )

        conn.execute(
            "CREATE INDEX ON research_docs USING hnsw (embedding vector_cosine_ops)"
        )

        print(f"\nSample question: {SAMPLE_QUESTION!r}")
        query_embedding = model.encode(SAMPLE_QUESTION, normalize_embeddings=True)

        rows = conn.execute(
            """
            SELECT source, content, embedding <=> %s AS distance
            FROM research_docs
            ORDER BY distance
            LIMIT 5
            """,
            (query_embedding,),
        ).fetchall()

        print("\nNearest neighbors (lower distance = more similar):")
        for source, content, distance in rows:
            snippet = content[:120].replace("\n", " ")
            print(f"  [{distance:.4f}] {source}: {snippet}...")


if __name__ == "__main__":
    main()
