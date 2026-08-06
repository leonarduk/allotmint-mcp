"""pgvector retrieval, promoted from the issue #11 spike.

The spike (scripts/spikes/pgvector_research/) proved the round trip: embed
locally with sentence-transformers, store in Postgres+pgvector, query with the
cosine operator. This module is that query path, with three things the spike
didn't need: a shared cached embedding model, a `lookback_days` filter on dated
documents, and graceful degradation when the store is unreachable.

Degrading rather than failing is deliberate. Retrieval is one of two grounding
sources; if the store is down but the MCP tools are up, the agent can still
produce an answer that cites real tool calls. The caller gets a warning saying
so, and `grounded` still reflects reality.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from .config import Settings
from .models import RetrievedDocument

log = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model_cache: dict[str, object] = {}


class RetrievalUnavailable(RuntimeError):
    """Raised when the retrieval store or embedding model cannot be used."""


def _load_embedding_model(name: str):
    """Loads (and caches) the local sentence-transformers model.

    Cached process-wide because loading is seconds of CPU work and the model is
    stateless at inference time; a per-request load would dominate the latency
    of everything else this service does.
    """
    with _model_lock:
        cached = _model_cache.get(name)
        if cached is not None:
            return cached
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on install
            raise RetrievalUnavailable(
                "sentence-transformers is not installed; retrieval is unavailable"
            ) from exc
        log.info("Loading local embedding model %r", name)
        model = SentenceTransformer(name)
        _model_cache[name] = model
        return model


def embed(text: str, settings: Settings):
    """Embeds one string with the local model, returning a normalized vector."""
    model = _load_embedding_model(settings.embedding_model)
    return model.encode(text, normalize_embeddings=True)


def _search_sync(
    question: str, settings: Settings, owner: str | None, lookback_days: int
) -> list[RetrievedDocument]:
    try:
        import psycopg
        from pgvector.psycopg import register_vector
    except ImportError as exc:  # pragma: no cover - depends on install
        raise RetrievalUnavailable("psycopg/pgvector are not installed") from exc

    query_embedding = embed(question, settings)

    # The owner predicate is composed in Python rather than passed as a
    # `%s IS NULL OR ...` parameter: psycopg sends bare NULL untyped, and
    # Postgres cannot infer a type for it, which fails the whole query.
    # Documents with no owner are shared context and always eligible.
    filters = ["(published IS NULL OR published >= CURRENT_DATE - make_interval(days => %s))"]
    params: list = [query_embedding, lookback_days]
    if owner:
        filters.append("(owner IS NULL OR owner = %s)")
        params.append(owner)
    params.append(settings.top_k)

    sql = f"""
        SELECT source, content, doc_type, published, embedding <=> %s AS distance
        FROM research_docs
        WHERE {' AND '.join(filters)}
        ORDER BY distance
        LIMIT %s
    """

    try:
        with psycopg.connect(settings.db_dsn, autocommit=True, connect_timeout=5) as conn:
            register_vector(conn)
            rows = conn.execute(sql, tuple(params)).fetchall()
    except Exception as exc:  # noqa: BLE001 - any driver/DB failure degrades the same way
        raise RetrievalUnavailable(str(exc)) from exc

    documents = []
    for source, content, doc_type, published, distance in rows:
        if distance is not None and distance > settings.max_distance:
            continue
        documents.append(
            RetrievedDocument(
                source=source,
                content=content,
                distance=float(distance),
                doc_type=doc_type or "",
                published=published.isoformat() if published is not None else None,
            )
        )
    return documents


async def search(
    question: str,
    settings: Settings,
    owner: str | None = None,
    lookback_days: int = 365,
) -> list[RetrievedDocument]:
    """Returns the most similar documents for `question`, nearest first.

    Both the embedding and the database round trip are blocking, so they run in
    a worker thread to keep the event loop free for concurrent requests.
    """
    if not settings.retrieval_enabled:
        raise RetrievalUnavailable("retrieval is disabled by configuration")
    return await asyncio.to_thread(_search_sync, question, settings, owner, lookback_days)
