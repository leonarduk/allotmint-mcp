"""Tests for the HTTP surface the Java MCP tool calls.

The response field names here are the contract with `ResearchAnswer.java`; if
one of these assertions has to change, the Java record changes with it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.llm import UnsupportedProvider
from app.main import app
from app.models import AskResponse, Citation, ToolCallRecord


@pytest.fixture
def client():
    return TestClient(app)


def test_health_reports_configuration_without_probing_anything(client):
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["model"] == "ollama:llama3.2"
    assert body["llm_provider"] == "ollama"
    assert body["available_llm_providers"] == ["ollama"]
    assert body["tools"] == [
        "allotmint_portfolio",
        "allotmint_instrument",
        "allotmint_market",
        "allotmint_health",
    ]


def test_ask_returns_the_shape_the_java_client_deserializes(client, monkeypatch):
    async def fake_run(request, settings, trace_logger=None, langfuse_tracer=None):
        return AskResponse(
            question=request.question,
            owner=request.owner,
            lookback_days=request.lookback_days,
            answer="Technology rose from 18% to 27% [1].",
            citations=[
                Citation(
                    id=1,
                    kind="document",
                    ref="report:portfolio.sectors",
                    detail="cosine distance 0.6171",
                    excerpt="Technology 27.0%",
                )
            ],
            tool_calls=[
                ToolCallRecord(tool="allotmint_portfolio", arguments={"action": "exposure"})
            ],
            grounded=True,
            model="ollama:llama3.2",
        )

    monkeypatch.setattr(main_module, "run_research", fake_run)

    body = client.post(
        "/research/ask",
        json={"question": "how has my tech exposure changed?", "owner": "demo"},
    ).json()

    assert body["answer"].startswith("Technology rose")
    assert body["grounded"] is True
    assert body["lookback_days"] == 365
    assert body["citations"][0]["ref"] == "report:portfolio.sectors"
    assert body["tool_calls"][0]["tool"] == "allotmint_portfolio"
    assert body["model"] == "ollama:llama3.2"


def test_a_blank_question_is_rejected_before_any_llm_call(client):
    assert client.post("/research/ask", json={"question": ""}).status_code == 422


def test_ask_uses_an_advertised_provider(client, monkeypatch):
    monkeypatch.setenv("ALLOTMINT_RESEARCH_AVAILABLE_LLM_PROVIDERS", "ollama,deepseek")
    monkeypatch.setenv("ALLOTMINT_RESEARCH_DEEPSEEK_API_KEY", "secret")

    async def fake_run(request, settings, trace_logger=None, langfuse_tracer=None):
        assert settings.llm_provider == "deepseek"
        assert settings.llm_model == "deepseek-chat"
        assert settings.llm_api_key == "secret"
        return AskResponse(question=request.question, answer="answer", grounded=True)

    monkeypatch.setattr(main_module, "run_research", fake_run)

    response = client.post(
        "/research/ask", json={"question": "why?", "llm_provider": "deepseek"}
    )
    assert response.status_code == 200


def test_ask_rejects_an_unadvertised_provider(client):
    response = client.post(
        "/research/ask", json={"question": "why?", "llm_provider": "deepseek"}
    )
    assert response.status_code == 422
    assert "not available" in response.json()["detail"]


def test_an_out_of_range_lookback_is_rejected(client):
    response = client.post(
        "/research/ask", json={"question": "why?", "lookback_days": 99999}
    )

    assert response.status_code == 422


def test_a_misconfigured_provider_is_a_500_naming_the_variable(client, monkeypatch):
    async def fail(request, settings, trace_logger=None, langfuse_tracer=None):
        raise UnsupportedProvider("ALLOTMINT_RESEARCH_LLM_API_KEY is required")

    monkeypatch.setattr(main_module, "run_research", fail)

    response = client.post("/research/ask", json={"question": "why?"})

    assert response.status_code == 500
    assert "ALLOTMINT_RESEARCH_LLM_API_KEY" in response.json()["detail"]


def test_a_failed_run_is_a_502_with_the_cause(client, monkeypatch):
    async def fail(request, settings, trace_logger=None, langfuse_tracer=None):
        raise RuntimeError("MCP server unreachable")

    monkeypatch.setattr(main_module, "run_research", fail)

    response = client.post("/research/ask", json={"question": "why?"})

    assert response.status_code == 502
    assert "MCP server unreachable" in response.json()["detail"]
