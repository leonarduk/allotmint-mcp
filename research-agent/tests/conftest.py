"""Shared fixtures.

Every test here runs without a database, without an LLM, and without a running
MCP server. That is deliberate: the agent's grounding and citation logic is the
part that must not regress, and tying its tests to three external services
would mean it only gets checked when someone has all three running locally.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.models import RetrievedDocument, ToolCallRecord  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    return Settings(
        llm_provider="ollama",
        llm_model="llama3.2",
        mcp_url="http://localhost:8080/mcp",
        max_tool_calls=3,
        retrieval_enabled=True,
    )


@pytest.fixture
def documents() -> list[RetrievedDocument]:
    return [
        RetrievedDocument(
            source="key_findings.md",
            content="Technology exposure rose from 18% to 27% over the past year.",
            distance=0.5579,
            doc_type="key_findings",
            published="2026-08-01",
        ),
        RetrievedDocument(
            source="report:portfolio.sectors",
            content="Technology 27.0% (was 18.0%), Financials 15.5% (was 17.0%).",
            distance=0.6171,
            doc_type="report",
            published="2026-08-01",
        ),
    ]


@pytest.fixture
def tool_calls() -> list[ToolCallRecord]:
    return [
        ToolCallRecord(
            tool="allotmint_portfolio",
            arguments={"action": "exposure", "owner": "demo"},
            result_excerpt='{"sectors": [{"sector": "Technology", "weight_pct": 27.0}]}',
        ),
        ToolCallRecord(
            tool="allotmint_instrument",
            arguments={"action": "news", "ticker": "NVDA"},
            result_excerpt='{"items": [{"headline": "NVIDIA raises guidance"}]}',
        ),
    ]
