"""Tests for app.retrieval.

`_search_sync` itself needs a real Postgres+pgvector store and a local
embedding model, neither of which this suite has (see requirements-dev.txt).
What's actually tested here is what's testable without them: the
retrieval-disabled short-circuit, the graceful-degradation behavior when the
optional dependencies aren't installed (which is genuinely true in this test
environment, not simulated), and the row-to-model mapping/filtering logic in
`_rows_to_documents`, which is pure and doesn't touch the database at all.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from app.retrieval import RetrievalUnavailable, _rows_to_documents, embed, search


@pytest.mark.asyncio
async def test_search_raises_immediately_when_retrieval_is_disabled(settings):
    disabled = dataclasses.replace(settings, retrieval_enabled=False)

    with pytest.raises(RetrievalUnavailable, match="disabled by configuration"):
        await search("why did technology exposure rise?", disabled)


@pytest.mark.asyncio
async def test_search_degrades_gracefully_when_optional_dependencies_are_missing(settings):
    """psycopg/pgvector/sentence-transformers are intentionally not installed for tests."""
    with pytest.raises(RetrievalUnavailable, match="not installed"):
        await search("why did technology exposure rise?", settings)


def test_embed_raises_when_sentence_transformers_is_not_installed(settings):
    with pytest.raises(RetrievalUnavailable, match="sentence-transformers is not installed"):
        embed("why did technology exposure rise?", settings)


def test_rows_to_documents_drops_rows_beyond_the_max_distance():
    rows = [
        ("close.md", "close match", "key_findings", None, 0.2),
        ("far.md", "far match", "key_findings", None, 0.95),
    ]

    documents = _rows_to_documents(rows, max_distance=0.85)

    assert [d.source for d in documents] == ["close.md"]


def test_rows_to_documents_raises_on_a_null_distance():
    """Documents current behavior, not desired behavior.

    The `distance is not None` guard only skips the max-distance comparison;
    `float(distance)` below it still runs unconditionally, so a NULL distance
    (only possible if a row's embedding column is itself NULL) crashes the
    whole retrieval call with a TypeError instead of degrading gracefully like
    every other failure mode in this module. Flagging as a real bug found
    while writing this test, not fixing it here since it's out of scope for
    adding test coverage.
    """
    rows = [("unranked.md", "content", "key_findings", None, None)]

    with pytest.raises(TypeError):
        _rows_to_documents(rows, max_distance=0.85)


def test_rows_to_documents_defaults_missing_doc_type_and_formats_published_date():
    rows = [("report:portfolio.sectors", "content", None, date(2026, 8, 1), 0.5)]

    documents = _rows_to_documents(rows, max_distance=0.85)

    assert documents[0].doc_type == ""
    assert documents[0].published == "2026-08-01"


def test_rows_to_documents_leaves_published_none_when_the_row_has_no_date():
    rows = [("key_findings.md", "content", "key_findings", None, 0.5)]

    documents = _rows_to_documents(rows, max_distance=0.85)

    assert documents[0].published is None
