"""End-to-end tests of `run_research` with a scripted model and MCP session.

These drive the real agent loop -- real Pydantic AI agent, real tool wrappers,
real citation assembly -- with only the two genuinely external things replaced:
the LLM (a `FunctionModel` whose turns are scripted) and the MCP transport (an
in-process fake serving the #11/#12 spike fixtures).

That makes the sample compound question from the design doc, "how has my tech
exposure changed this year, and why?", a repeatable test rather than something
only checkable by hand against a running Ollama.
"""

from __future__ import annotations

import contextlib
import json

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import agent as agent_module
from app.mcp_tools import ToolSession
from app.models import AskRequest, RetrievedDocument
from app.retrieval import RetrievalUnavailable

# Fixture data lifted from the two spikes so this test tells the same story:
# tech weight up 9 points, explained by an NVDA headline.
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
    """Wires `run_research` to the fake MCP session; the caller supplies the model."""
    fake_session = _FakeMcpSession()

    @contextlib.asynccontextmanager
    async def fake_open_session(_settings, trace_logger=None):
        yield ToolSession(settings=_settings, session=fake_session, trace_logger=trace_logger)

    monkeypatch.setattr(agent_module, "open_session", fake_open_session)
    return fake_session


def _scripted_model(*turns):
    """Builds a `FunctionModel` that replays `turns` in order.

    Each turn is either a list of (tool_name, args) pairs or a final string.
    """
    state = {"index": 0}

    async def respond(messages, info: AgentInfo) -> ModelResponse:
        turn = turns[min(state["index"], len(turns) - 1)]
        state["index"] += 1
        if isinstance(turn, str):
            return ModelResponse(parts=[TextPart(turn)])
        return ModelResponse(
            parts=[ToolCallPart(tool_name=name, args=args) for name, args in turn]
        )

    return FunctionModel(respond)


def _use_model(monkeypatch, model):
    monkeypatch.setattr(agent_module, "build_model", lambda _settings: model)


def _stub_search(monkeypatch, documents=None, unavailable=False):
    async def fake_search(question, settings, owner=None, lookback_days=365):
        if unavailable:
            raise RetrievalUnavailable("connection refused")
        return documents or []

    monkeypatch.setattr(agent_module, "search", fake_search)


@pytest.mark.asyncio
async def test_the_sample_compound_question_chains_two_tools_and_cites_them(
    monkeypatch, settings, patched, documents
):
    _stub_search(monkeypatch, documents)
    _use_model(
        monkeypatch,
        _scripted_model(
            [("allotmint_portfolio", {"action": "exposure", "owner": "demo"})],
            [("allotmint_instrument", {"action": "news", "ticker": "NVDA"})],
            "Technology rose from 18% to 27% [1] [tool:allotmint_portfolio], driven by "
            "NVIDIA's raised data center guidance [tool:allotmint_instrument].",
        ),
    )

    response = await agent_module.run_research(
        AskRequest(question="how has my tech exposure changed this year, and why?", owner="demo"),
        settings,
    )

    # Two different v0 tools, chosen by the agent, not hardcoded here.
    assert [name for name, _ in patched.received] == [
        "allotmint_portfolio",
        "allotmint_instrument",
    ]
    assert response.grounded is True

    # Every [n] marker resolves to a real source.
    assert "[tool:" not in response.answer
    assert "[3]" in response.answer and "[4]" in response.answer
    kinds = [(c.id, c.kind, c.ref) for c in response.citations]
    assert kinds == [
        (1, "document", "key_findings.md"),
        (2, "document", "report:portfolio.sectors"),
        (3, "tool_call", "allotmint_portfolio"),
        (4, "tool_call", "allotmint_instrument"),
    ]
    # And the tool citation carries the real response, so the claim is checkable.
    assert "27.0" in response.citations[2].excerpt
    assert response.model == "ollama:llama3.2"
    assert response.warnings == []


@pytest.mark.asyncio
async def test_a_different_question_leads_to_a_different_tool(
    monkeypatch, settings, patched
):
    # Guards the "always calls the same tool regardless of the question"
    # failure mode: nothing in run_research prescribes a tool sequence.
    _stub_search(monkeypatch, [])
    _use_model(
        monkeypatch,
        _scripted_model(
            [("allotmint_market", {"action": "overview"})],
            "The market is risk-on [tool:allotmint_market].",
        ),
    )

    response = await agent_module.run_research(
        AskRequest(question="what is the market doing today?"), settings
    )

    assert [name for name, _ in patched.received] == ["allotmint_market"]
    assert [c.ref for c in response.citations] == ["allotmint_market"]
    assert "[1]" in response.answer


@pytest.mark.asyncio
async def test_an_answer_with_no_retrieval_and_no_tool_calls_is_not_grounded(
    monkeypatch, settings, patched
):
    _stub_search(monkeypatch, [], unavailable=True)
    _use_model(monkeypatch, _scripted_model("Your technology exposure grew substantially."))

    response = await agent_module.run_research(
        AskRequest(question="how has my tech exposure changed?"), settings
    )

    assert response.grounded is False
    assert response.citations == []
    assert patched.received == []
    assert any("Retrieval store unavailable" in w for w in response.warnings)
    assert any("no inline citation markers" in w for w in response.warnings)


@pytest.mark.asyncio
async def test_retrieval_failure_still_allows_a_tool_grounded_answer(
    monkeypatch, settings, patched
):
    # Degrading rather than failing: with the store down but the MCP tools up,
    # an answer citing real tool calls is still a legitimate answer.
    _stub_search(monkeypatch, unavailable=True)
    _use_model(
        monkeypatch,
        _scripted_model(
            [("allotmint_portfolio", {"action": "exposure", "owner": "demo"})],
            "Technology is 27% of the portfolio [tool:allotmint_portfolio].",
        ),
    )

    response = await agent_module.run_research(
        AskRequest(question="what is my tech exposure?", owner="demo"), settings
    )

    assert response.grounded is True
    assert [c.id for c in response.citations] == [1]
    assert "[1]" in response.answer
    assert any("Retrieval store unavailable" in w for w in response.warnings)


@pytest.mark.asyncio
async def test_the_tool_call_budget_bounds_a_runaway_agent(
    monkeypatch, settings, patched
):
    _stub_search(monkeypatch, [])
    _use_model(
        monkeypatch,
        _scripted_model(
            *([[("allotmint_market", {"action": "overview"})]] * 6),
            "Done [tool:allotmint_market].",
        ),
    )

    response = await agent_module.run_research(
        AskRequest(question="what is the market doing?"), settings
    )

    # settings.max_tool_calls is 3 in the fixture; nothing beyond that reached
    # the MCP server, even though the model kept asking.
    assert len(patched.received) == settings.max_tool_calls
    assert len(response.tool_calls) == settings.max_tool_calls


@pytest.mark.asyncio
async def test_reasoning_markup_never_reaches_the_answer(
    monkeypatch, settings, patched, documents
):
    _stub_search(monkeypatch, documents)
    _use_model(
        monkeypatch,
        _scripted_model("<think>I should check the sectors first.</think>Tech rose to 27% [1]."),
    )

    response = await agent_module.run_research(
        AskRequest(question="how has my tech exposure changed?", owner="demo"), settings
    )

    assert response.answer == "Tech rose to 27% [1]."


@pytest.mark.asyncio
async def test_documents_are_passed_to_the_model_as_numbered_context(
    monkeypatch, settings, patched
):
    seen_prompts: list[str] = []
    documents = [
        RetrievedDocument(
            source="key_findings.md",
            content="Technology exposure rose from 18% to 27%.",
            distance=0.5,
        )
    ]
    _stub_search(monkeypatch, documents)

    async def respond(messages, info: AgentInfo) -> ModelResponse:
        seen_prompts.append(str(messages[-1].parts[-1].content))
        return ModelResponse(parts=[TextPart("Tech rose to 27% [1].")])

    _use_model(monkeypatch, FunctionModel(respond))

    await agent_module.run_research(
        AskRequest(question="how has my tech exposure changed?", owner="demo"), settings
    )

    assert "[1] source=key_findings.md" in seen_prompts[0]
    assert "18% to 27%" in seen_prompts[0]


@pytest.mark.asyncio
async def test_tool_arguments_reach_the_v0_tools_unchanged(monkeypatch, settings, patched):
    _stub_search(monkeypatch, [])
    _use_model(
        monkeypatch,
        _scripted_model(
            [("allotmint_portfolio", {"action": "holdings", "owner": "demo", "currency": "GBP"})],
            "Here are the holdings [tool:allotmint_portfolio].",
        ),
    )

    await agent_module.run_research(
        AskRequest(question="what do I hold in GBP?", owner="demo"), settings
    )

    name, arguments = patched.received[0]
    assert name == "allotmint_portfolio"
    # account_type defaulted to None in the wrapper and must not be forwarded.
    assert arguments == {"action": "holdings", "owner": "demo", "currency": "GBP"}
    assert json.dumps(arguments)  # serializable, as the MCP transport requires
