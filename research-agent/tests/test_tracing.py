"""Tests for structured trace logging: event emission, file persistence, query,
and end-to-end integration with the agent loop.

Every test that drives the real agent loop uses a scripted `FunctionModel` and
an in-process fake MCP session — no real LLM, no real MCP server. The trace
file is a pytest `tmp_path` so tests are isolated and leave no state behind.
"""

from __future__ import annotations

import contextlib
import json

import pytest

from app import agent as agent_module
from app.mcp_tools import ToolSession
from app.models import AskRequest, RetrievedDocument
from app.retrieval import RetrievalUnavailable
from app.tracing import TraceLogger, new_trace, read_trace

# ——— trace module unit tests ——————————————————————————————————————————————


def test_new_trace_returns_none_when_disabled():
    """When no file path is configured, tracing is a no-op."""
    assert new_trace(None) is None


def test_new_trace_creates_a_unique_uuid():
    """Every trace logger gets its own ID."""
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        path = Path(f.name)

    try:
        t1 = new_trace(path)
        t2 = new_trace(path)
        assert t1 is not None
        assert t2 is not None
        assert t1.trace_id != t2.trace_id
        assert len(t1.trace_id) == 36  # standard UUID string
    finally:
        path.unlink(missing_ok=True)


def test_read_trace_returns_empty_for_missing_file(tmp_path):
    trace_file = tmp_path / "nonexistent.jsonl"
    assert read_trace("any-id", trace_file) == []


def test_read_trace_returns_empty_when_trace_id_not_found(tmp_path):
    trace_file = tmp_path / "traces.jsonl"
    trace_file.write_text(
        json.dumps({"trace_id": "abc", "event": "request.start"}) + "\n"
    )
    assert read_trace("xyz", trace_file) == []


def test_read_trace_skips_invalid_json_lines(tmp_path):
    trace_file = tmp_path / "traces.jsonl"
    trace_file.write_text(
        "not-json\n"
        + json.dumps({"trace_id": "abc", "event": "request.start"})
        + "\n"
    )
    events = read_trace("abc", trace_file)
    assert len(events) == 1
    assert events[0]["event"] == "request.start"


def test_events_are_written_immediately_and_read_back_in_order(tmp_path):
    trace_file = tmp_path / "traces.jsonl"
    logger = TraceLogger("trace-1", trace_file)

    logger.request_start("test question", "demo", 365, "ollama:llama3.2")
    logger.retrieval_start()
    logger.retrieval_end(2, ["doc-a.md", "doc-b.md"])
    logger.agent_start("ollama:llama3.2")
    logger.tool_call_start("allotmint_portfolio", {"action": "exposure", "owner": "demo"})
    logger.tool_call_end("allotmint_portfolio", 512, success=True)
    logger.agent_end(1, 120, grounded=True)
    logger.request_end(True, 120, 3, 1, 2, [])

    events = read_trace("trace-1", trace_file)
    assert len(events) == 8

    event_names = [e["event"] for e in events]
    assert event_names == [
        "request.start",
        "retrieval.start",
        "retrieval.end",
        "agent.start",
        "tool_call.start",
        "tool_call.end",
        "agent.end",
        "request.end",
    ]

    # Every event shares the trace_id.
    for event in events:
        assert event["trace_id"] == "trace-1"
        assert "timestamp" in event
        assert "elapsed_ms" in event

    # Payloads are stored under "data".
    assert events[0]["data"]["question"] == "test question"
    assert events[2]["data"]["document_count"] == 2
    assert events[2]["data"]["sources"] == ["doc-a.md", "doc-b.md"]
    assert events[4]["data"]["tool"] == "allotmint_portfolio"
    assert events[4]["data"]["arguments"] == {"action": "exposure", "owner": "demo"}
    assert events[5]["data"]["tool"] == "allotmint_portfolio"
    assert events[5]["data"]["result_length"] == 512
    assert events[5]["data"]["success"] is True
    assert events[7]["data"]["grounded"] is True
    assert events[7]["data"]["citation_count"] == 3


def test_tool_call_failure_is_recorded(tmp_path):
    trace_file = tmp_path / "traces.jsonl"
    logger = TraceLogger("trace-1", trace_file)

    logger.tool_call_start("allotmint_health", {})
    logger.tool_call_end("allotmint_health", 80, success=False)

    events = read_trace("trace-1", trace_file)
    assert events[1]["data"]["success"] is False
    assert events[1]["data"]["truncated"] is False


def test_tool_call_truncation_is_recorded(tmp_path):
    trace_file = tmp_path / "traces.jsonl"
    logger = TraceLogger("trace-1", trace_file)

    logger.tool_call_start("allotmint_portfolio", {"action": "summary", "owner": "demo"})
    logger.tool_call_end("allotmint_portfolio", 4000, success=True, truncated=True)

    events = read_trace("trace-1", trace_file)
    assert events[1]["data"]["truncated"] is True


# ——— integration tests: agent loop with tracing ————————————————————————————


# Reuse the fixture data from test_run_research.py.
EXPOSURE = {
    "action": "exposure",
    "owner": "demo",
    "as_of": "2026-08-01",
    "sectors": [
        {"sector": "Technology", "weight_pct": 27.0, "weight_pct_year_ago": 18.0},
        {"sector": "Financials", "weight_pct": 15.5, "weight_pct_year_ago": 17.0},
    ],
}
NEWS = {
    "action": "news",
    "ticker": "NVDA",
    "items": [
        {
            "ticker": "NVDA",
            "headline": "NVIDIA raises data center revenue guidance on AI chip demand",
            "published": "2026-05-14",
        }
    ],
}


class _FakeMcpSession:
    """In-process stand-in for a live MCP session over the v0 tools."""

    def __init__(self):
        self.received: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments):
        self.received.append((name, arguments))
        payload = {
            "allotmint_portfolio": EXPOSURE,
            "allotmint_instrument": NEWS,
            "allotmint_market": {"action": "overview", "sentiment": "risk-on"},
            "allotmint_health": {"reachable": True},
        }[name]
        return type("Result", (), {"structured_content": payload, "content": []})()


@pytest.fixture
def patched(monkeypatch, settings):
    """Wires run_research to the fake MCP session."""
    fake_session = _FakeMcpSession()

    @contextlib.asynccontextmanager
    async def fake_open_session(_settings, trace_logger=None):
        yield ToolSession(settings=_settings, session=fake_session, trace_logger=trace_logger)

    monkeypatch.setattr(agent_module, "open_session", fake_open_session)
    return fake_session


def _use_model(monkeypatch, model):
    monkeypatch.setattr(agent_module, "build_model", lambda _settings: model)


def _stub_search(monkeypatch, documents=None, unavailable=False):
    async def fake_search(question, settings, owner=None, lookback_days=365):
        if unavailable:
            raise RetrievalUnavailable("connection refused")
        return documents or []

    monkeypatch.setattr(agent_module, "search", fake_search)


@pytest.mark.asyncio
async def test_the_sample_compound_question_emits_a_full_trace(
    monkeypatch, settings, patched, documents, tmp_path
):
    """The #14 success criterion: every step emits an event with a shared trace_id."""
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    _stub_search(monkeypatch, documents)

    state = {"index": 0}
    turns = [
        [("allotmint_portfolio", {"action": "exposure", "owner": "demo"})],
        [("allotmint_instrument", {"action": "news", "ticker": "NVDA"})],
        "Technology rose from 18% to 27% [1] [tool:allotmint_portfolio], driven by "
        "NVIDIA's raised data center guidance [tool:allotmint_instrument].",
    ]

    async def respond(messages, info: AgentInfo) -> ModelResponse:
        turn = turns[min(state["index"], len(turns) - 1)]
        state["index"] += 1
        if isinstance(turn, str):
            return ModelResponse(parts=[TextPart(turn)])
        return ModelResponse(
            parts=[ToolCallPart(tool_name=name, args=args) for name, args in turn]
        )

    _use_model(monkeypatch, FunctionModel(respond))

    trace_file = tmp_path / "traces.jsonl"
    logger = TraceLogger("trace-sample", trace_file)

    response = await agent_module.run_research(
        AskRequest(
            question="how has my tech exposure changed this year, and why?",
            owner="demo",
        ),
        settings,
        trace_logger=logger,
    )

    # The response carries the trace_id back to the caller.
    assert response.trace_id == "trace-sample"

    events = read_trace("trace-sample", trace_file)
    assert len(events) >= 8

    # Walk the event sequence and verify it reconstructs the full decision path.
    event_seq = [e["event"] for e in events]

    # Retrieval happened first.
    assert "retrieval.start" in event_seq
    assert "retrieval.end" in event_seq
    retrieval_idx = event_seq.index("retrieval.end")
    assert events[retrieval_idx]["data"]["document_count"] == 2
    assert events[retrieval_idx]["data"]["sources"] == [
        "key_findings.md",
        "report:portfolio.sectors",
    ]

    # The agent started.
    assert "agent.start" in event_seq

    # Two tool calls happened, interleaved start/end.
    tool_starts = [e for e in events if e["event"] == "tool_call.start"]
    tool_ends = [e for e in events if e["event"] == "tool_call.end"]
    assert len(tool_starts) == 2
    assert len(tool_ends) == 2

    assert tool_starts[0]["data"]["tool"] == "allotmint_portfolio"
    assert tool_starts[0]["data"]["arguments"] == {"action": "exposure", "owner": "demo"}
    assert tool_starts[1]["data"]["tool"] == "allotmint_instrument"
    assert tool_starts[1]["data"]["arguments"] == {"action": "news", "ticker": "NVDA"}

    # Both succeeded.
    for end_event in tool_ends:
        assert end_event["data"]["success"] is True

    # The agent ended with tool call count.
    assert "agent.end" in event_seq
    agent_end = events[event_seq.index("agent.end")]
    assert agent_end["data"]["tool_call_count"] == 2
    assert agent_end["data"]["grounded"] is True

    # request.end summarizes the whole run.
    assert "request.end" in event_seq
    req_end = events[event_seq.index("request.end")]
    assert req_end["data"]["grounded"] is True
    assert req_end["data"]["tool_call_count"] == 2
    assert req_end["data"]["document_count"] == 2
    assert req_end["data"]["citation_count"] == 4  # 2 docs + 2 tool calls


@pytest.mark.asyncio
async def test_tracing_does_not_log_document_contents(
    monkeypatch, settings, patched, tmp_path
):
    """Sensitive document bodies must not appear in trace events."""
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    sensitive = "This document contains account numbers and personal data."
    documents = [
        RetrievedDocument(
            source="private.md", content=sensitive, distance=0.5
        )
    ]
    _stub_search(monkeypatch, documents)

    async def respond(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Done [1].")])

    _use_model(monkeypatch, FunctionModel(respond))

    trace_file = tmp_path / "traces.jsonl"
    logger = TraceLogger("trace-safe", trace_file)

    await agent_module.run_research(
        AskRequest(question="what does the private doc say?"),
        settings,
        trace_logger=logger,
    )

    events = read_trace("trace-safe", trace_file)
    all_text = json.dumps(events)

    # Document source identifiers are logged.
    assert "private.md" in all_text
    # Document body content is not.
    assert sensitive not in all_text


@pytest.mark.asyncio
async def test_retrieval_failure_is_recorded_in_trace(
    monkeypatch, settings, patched, tmp_path
):
    """When the retrieval store is down, the trace records it."""
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    _stub_search(monkeypatch, unavailable=True)

    async def respond(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Unable to determine.")])

    _use_model(monkeypatch, FunctionModel(respond))

    trace_file = tmp_path / "traces.jsonl"
    logger = TraceLogger("trace-unavailable", trace_file)

    await agent_module.run_research(
        AskRequest(question="why?"),
        settings,
        trace_logger=logger,
    )

    events = read_trace("trace-unavailable", trace_file)
    retrieval_end = [e for e in events if e["event"] == "retrieval.end"][0]
    assert retrieval_end["data"]["unavailable"] is True
    assert retrieval_end["data"]["document_count"] == 0


# ——— API integration tests ——————————————————————————————————————————————————


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def test_trace_endpoint_returns_404_when_tracing_is_disabled(client):
    """No trace file configured => 404."""
    response = client.get("/research/trace/any-id")
    assert response.status_code == 404
    assert "not enabled" in response.json()["detail"]


def test_trace_endpoint_returns_404_for_unknown_trace_id(client, monkeypatch, tmp_path):
    """Trace file exists but trace_id not found => 404."""
    trace_file = tmp_path / "traces.jsonl"
    trace_file.write_text(
        json.dumps({"trace_id": "abc", "event": "request.start"}) + "\n"
    )

    monkeypatch.setenv("ALLOTMINT_RESEARCH_TRACE_FILE", str(trace_file))
    monkeypatch.setattr("app.main.load_settings", lambda: _settings_with_trace(trace_file))

    response = client.get("/research/trace/xyz")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_trace_endpoint_returns_events_for_a_known_trace_id(client, monkeypatch, tmp_path):
    """Found trace_id returns all its events."""
    trace_file = tmp_path / "traces.jsonl"
    trace_file.write_text(
        json.dumps({"trace_id": "abc", "event": "request.start"}) + "\n"
        + json.dumps({"trace_id": "abc", "event": "request.end"}) + "\n"
        + json.dumps({"trace_id": "other", "event": "request.start"}) + "\n"
    )

    monkeypatch.setenv("ALLOTMINT_RESEARCH_TRACE_FILE", str(trace_file))
    monkeypatch.setattr("app.main.load_settings", lambda: _settings_with_trace(trace_file))

    response = client.get("/research/trace/abc")
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == "abc"
    assert len(body["events"]) == 2
    assert body["events"][0]["event"] == "request.start"
    assert body["events"][1]["event"] == "request.end"


def _settings_with_trace(trace_file):
    from app.config import Settings

    return Settings(
        llm_provider="ollama",
        llm_model="llama3.2",
        trace_file=str(trace_file),
        max_tool_calls=3,
    )
