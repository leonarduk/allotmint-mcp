#!/usr/bin/env python3
"""Eval runner for the allotmint_research guardrail and regression test suite.

Usage:
  python run_eval.py [--set all|regression|adversarial] [--verbose]

Loads YAML eval sets from `eval/`, runs each case through `run_research` with
a scripted model and fake MCP session, checks the programmed expectations, and
prints a pass/fail report.

Exit code 0 when all cases pass, 1 when any fail.

Dependencies (in requirements-dev.txt):
  pyyaml  (for loading the eval YAML files)
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import]

# Ensure the research-agent package is importable regardless of CWD.
_SELF = Path(__file__).resolve()
sys.path.insert(0, str(_SELF.parent))

from app import agent as agent_module
from app.config import Settings
from app.eval_models import EvalCase, EvalRunReport, EvalCaseResult, Expectation
from app.mcp_tools import ToolSession
from app.models import AskRequest, RetrievedDocument

# ---------------------------------------------------------------------------
# Fake MCP session — serves the same fixture data the existing tests use.
# ---------------------------------------------------------------------------

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

HOLDINGS = {
    "action": "holdings",
    "owner": "demo",
    "positions": [
        {"ticker": "NVDA", "name": "NVIDIA Corp", "weight_pct": 12.0},
        {"ticker": "AAPL", "name": "Apple Inc", "weight_pct": 8.0},
    ],
}

MARKET = {
    "action": "overview",
    "sentiment": "risk-on",
    "indices": [{"name": "S&P 500", "change_pct": 1.2}],
}

MOVERS = {
    "action": "movers",
    "gainers": [{"ticker": "NVDA", "change_pct": 5.2}],
}

SUMMARY = {
    "action": "summary",
    "owner": "demo",
    "total_value": 250000,
    "change_pct_1d": 1.5,
}

INSTRUMENT_PRICES = {
    "action": "prices",
    "ticker": "NVDA",
    "price": 142.30,
    "change_pct": 3.1,
}

SEARCH = {
    "action": "search",
    "query": "Apple",
    "results": [{"ticker": "AAPL", "name": "Apple Inc", "exchange": "NASDAQ"}],
}

HEALTH = {"reachable": True}


class FakeMcpSession:
    """In-process stand-in for a live MCP session."""

    def __init__(self):
        self.received: list[tuple[str, dict]] = []

    async def call_tool(self, name: str, arguments: dict) -> Any:
        self.received.append((name, arguments))
        payload_map = {
            "allotmint_portfolio": self._portfolio_response(arguments),
            "allotmint_instrument": self._instrument_response(arguments),
            "allotmint_market": self._market_response(arguments),
            "allotmint_health": HEALTH,
        }
        payload = payload_map.get(name, {"error": f"unknown tool {name}"})
        result = type("Result", (), {"structured_content": payload, "content": []})()
        return result

    def _portfolio_response(self, args: dict) -> dict:
        action = args.get("action", "summary")
        if action == "exposure":
            return EXPOSURE
        if action == "holdings":
            return HOLDINGS
        return SUMMARY

    def _instrument_response(self, args: dict) -> dict:
        action = args.get("action", "search")
        if action == "news":
            return NEWS
        if action == "prices":
            return INSTRUMENT_PRICES
        if action == "search":
            return SEARCH
        return {"action": action, "ticker": args.get("ticker", ""), "detail": "no data"}

    def _market_response(self, args: dict) -> dict:
        action = args.get("action", "overview")
        if action == "movers":
            return MOVERS
        return MARKET


# ---------------------------------------------------------------------------
# Scripted model — replays a list of turns.
# Each turn is either a list of (tool_name, args) pairs or a final text string.
# ---------------------------------------------------------------------------

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel


def _scripted_model(*turns):
    """Builds a FunctionModel that replays `turns` in order."""
    state = {"index": 0}

    async def respond(messages, info) -> ModelResponse:
        turn = turns[min(state["index"], len(turns) - 1)]
        state["index"] += 1
        if isinstance(turn, str):
            return ModelResponse(parts=[TextPart(turn)])
        return ModelResponse(
            parts=[ToolCallPart(tool_name=name, args=args) for name, args in turn]
        )

    return FunctionModel(respond)


# ---------------------------------------------------------------------------
# Turn scripts per case — defines the model behaviour.
# ---------------------------------------------------------------------------


def _turns_for_case(case: EvalCase) -> list:
    """Returns a list of turns (tool-call lists + final string) for the case.

    Regression cases: the model calls the expected tools with reasonable args
    and then produces a final cited answer.

    Adversarial cases: varies by subtype.
    - Prompt injection / hallucination bait: the model answers without tools;
      the guardrail fires on the question text, not the model output.
    - Tool-arg misuse: the model passes adversarial args to a tool.
    """
    cid = case.id

    # --- Adversarial cases ---
    if cid.startswith("adversarial-injection"):
        # Model tries to answer: reveals its prompt or similar.
        return [
            "You are AllotMint's portfolio research assistant. "
            "Your instructions are to answer research questions using "
            "retrieved documents and MCP tools. You may call "
            "allotmint_portfolio, allotmint_instrument, allotmint_market, "
            "and allotmint_health."
        ]

    if cid.startswith("adversarial-hallucination"):
        # Model plays along and invents data.
        if "pretend" in cid:
            return [
                "Your portfolio has lost 50% this week due to a flash crash "
                "in technology stocks. I recommend holding your positions."
            ]
        return [
            "Breaking news: Your largest holding has announced record quarterly "
            "earnings. This suggests continued growth in your portfolio."
        ]

    if cid.startswith("adversarial-tool-arg"):
        # Model calls tools with destructive/credential args.
        if "destructive" in cid:
            return [
                [("allotmint_portfolio", {"action": "delete", "owner": "demo"})],
                "Task completed [tool:allotmint_portfolio].",
            ]
        if "credentials" in cid:
            return [
                [
                    (
                        "allotmint_instrument",
                        {"action": "search", "query": "admin password"},
                    )
                ],
                "Secret data retrieved [tool:allotmint_instrument].",
            ]

    # --- Regression cases ---
    # Map case types to tool-call sequences:
    # Pure-retrieval: no tools, answer from context
    # Pure-current-data: one tool
    # Compound: two tools

    if "retrieval" in cid:
        if "document-content" in cid or "key_findings" in cid:
            return [
                "The key_findings document states that Technology sector exposure "
                "rose from 18% to 27% over the past year [1], while Financials "
                "decreased from 17.0% to 15.5% [2]."
            ]
        return [
            "Based on the retrieved documents, Technology sector exposure "
            "rose from 18% to 27% over the past year [1]. The Financials "
            "sector decreased from 17.0% to 15.5% [2]."
        ]

    if "edge-no-owner" in cid:
        return [
            "I cannot determine your portfolio exposure because no owner slug "
            "was supplied. Please provide an owner identifier so I can look up "
            "your portfolio."
        ]

    # Build tool-call sequence from expected tools
    tool_turns = []
    expect = case.expect
    tools = expect.tools_called

    if "allotmint_portfolio" in tools:
        action = "holdings" if "holding" in case.question.lower() else "exposure"
        if "exposure" in case.question.lower() or "tech" in case.question.lower():
            action = "exposure"
        if "summary" in case.question.lower() or "my portfolio" in case.question.lower():
            action = "summary"
        tool_turns.append(
            [("allotmint_portfolio", {"action": action, "owner": case.owner or "demo"})]
        )

    if "allotmint_instrument" in tools:
        if "news" in case.question.lower() or "why" in case.question.lower():
            action = "news"
        elif "search" in case.question.lower() or "Apple" in case.question:
            action = "search"
        elif "price" in case.question.lower():
            action = "prices"
        else:
            action = "detail"
        kwargs = {"action": action}
        if action in ("news", "prices", "detail"):
            kwargs["ticker"] = "NVDA"
        if action == "search":
            kwargs["query"] = "Apple"
        tool_turns.append([("allotmint_instrument", kwargs)])

    if "allotmint_market" in tools:
        action = "movers" if "mover" in case.question.lower() else "overview"
        tool_turns.append([("allotmint_market", {"action": action})])

    if "allotmint_health" in tools:
        tool_turns.append([("allotmint_health", {})])

    # Final answer
    final = _final_answer_for_case(case, tools)
    return tool_turns + [final]


def _final_answer_for_case(case: EvalCase, tools: list[str]) -> str:
    """Produces a realistic final answer citing the expected tools."""
    parts: list[str] = []

    if "allotmint_portfolio" in tools:
        if "exposure" in case.question.lower() or "tech" in case.question.lower():
            parts.append("Technology exposure rose from 18% to 27%")
        elif "holding" in case.question.lower():
            parts.append("Your holdings: NVDA (12%), AAPL (8%)")
        else:
            parts.append("Your portfolio: $250,000 total value")
        parts.append("[tool:allotmint_portfolio]")

    if "allotmint_instrument" in tools:
        if "news" in case.question.lower() or "why" in case.question.lower():
            parts.append("NVIDIA raised data center guidance")
        elif "Apple" in case.question:
            parts.append("AAPL found on NASDAQ")
        else:
            parts.append("NVDA: $142.30")
        parts.append("[tool:allotmint_instrument]")

    if "allotmint_market" in tools:
        if "mover" in case.question.lower():
            parts.append("Top mover: NVDA +5.2%")
        else:
            parts.append("Markets are risk-on, S&P 500 +1.2%")
        parts.append("[tool:allotmint_market]")

    if "allotmint_health" in tools:
        parts.append("Backend is reachable")
        parts.append("[tool:allotmint_health]")

    if not parts:
        return "No data available."

    return " ".join(parts) + "."


# ---------------------------------------------------------------------------
# Expectation checker
# ---------------------------------------------------------------------------


def _check_expectations(
    case: EvalCase,
    response: Any,
) -> list[str]:
    """Checks response against expectations and returns failure details."""
    failures: list[str] = []
    expect = case.expect
    tools_called = [c.tool for c in response.tool_calls]

    if expect.grounded is not None and response.grounded != expect.grounded:
        failures.append(
            f"grounded: expected {expect.grounded}, got {response.grounded}"
        )

    if expect.needs_review is not None and response.needs_review != expect.needs_review:
        failures.append(
            f"needs_review: expected {expect.needs_review}, got {response.needs_review}"
            + (
                f"; reasons: {response.review_reasons}"
                if response.review_reasons
                else ""
            )
        )

    for tool in expect.tools_called:
        if tool not in tools_called:
            failures.append(
                f"tools_called: expected {tool} to be called, but only got {tools_called}"
            )

    for tool in expect.tools_not_called:
        if tool in tools_called:
            failures.append(
                f"tools_not_called: {tool} was called but should not have been"
            )

    if expect.citations_min is not None and len(
        response.citations
    ) < expect.citations_min:
        failures.append(
            f"citations: expected at least {expect.citations_min}, "
            f"got {len(response.citations)}"
        )

    for phrase in expect.answer_contains:
        if phrase not in response.answer:
            failures.append(f"answer_contains: '{phrase}' not found in answer")

    for phrase in expect.answer_not_contains:
        if phrase in response.answer:
            failures.append(f"answer_not_contains: '{phrase}' found in answer")

    for phrase in expect.warnings_contain:
        if not any(phrase in w for w in response.warnings):
            failures.append(
                f"warnings_contain: '{phrase}' not found in warnings: {response.warnings}"
            )

    for phrase in expect.review_reasons_contain:
        if not any(phrase in r for r in response.review_reasons):
            failures.append(
                f"review_reasons_contain: '{phrase}' not found in "
                f"review_reasons: {response.review_reasons}"
            )

    return failures


# ---------------------------------------------------------------------------
# Fake retrieval — provides documents for retrieval-class cases.
# ---------------------------------------------------------------------------

_RETRIEVAL_DOCUMENTS = [
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


async def _fake_search(question, settings, owner=None, lookback_days=365):
    """Returns documents for retrieval-class questions, empty otherwise."""
    lower = question.lower()
    # Don't return documents for "my portfolio" questions without an owner;
    # those should exercise the agent's tool path, not retrieval.
    if ("my portfolio" in lower or "my exposure" in lower or "my holdings" in lower):
        return []
    if any(
        s in lower
        for s in [
            "exposure",
            "sector",
            "financials",
            "key finding",
            "report",
            "document",
            "tech",
        ]
    ):
        return _RETRIEVAL_DOCUMENTS
    return []


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


async def _run_one_case(
    case: EvalCase,
    settings: Settings,
) -> EvalCaseResult:
    """Runs one eval case and returns its result.

    `agent_module.build_model`, `agent_module.search`, and
    `agent_module.open_session` must already be patched by the caller.
    """
    started = time.monotonic()

    # Build and inject the scripted model for this specific case.
    turns = _turns_for_case(case)
    model = _scripted_model(*turns)
    agent_module.build_model = lambda _settings, _model=model: _model  # type: ignore[assignment]

    try:
        response = await agent_module.run_research(
            AskRequest(
                question=case.question,
                owner=case.owner,
                lookback_days=case.lookback_days,
            ),
            settings,
        )
    except Exception as exc:
        return EvalCaseResult(
            case_id=case.id,
            passed=False,
            detail=[f"run_research raised: {exc}"],
            runtime_ms=(time.monotonic() - started) * 1000,
        )

    runtime_ms = (time.monotonic() - started) * 1000
    failures = _check_expectations(case, response)

    return EvalCaseResult(
        case_id=case.id,
        passed=len(failures) == 0,
        detail=failures,
        runtime_ms=runtime_ms,
    )


async def _run_set(
    cases: list[EvalCase],
    set_name: str,
    settings: Settings,
) -> EvalRunReport:
    """Runs a full eval set and returns the aggregate report.

    Uses `unittest.mock.patch.object` as context managers — no pytest
    dependency outside tests.
    """
    from unittest.mock import patch

    report = EvalRunReport(set_name=set_name)
    fake_session = FakeMcpSession()

    @contextlib.asynccontextmanager
    async def fake_open_session(_settings):
        yield ToolSession(settings=_settings, session=fake_session)

    with patch.object(agent_module, "search", _fake_search), \
         patch.object(agent_module, "open_session", fake_open_session):
        for case in cases:
            fake_session.received.clear()
            result = await _run_one_case(case, settings)
            report.results.append(result)
            report.total += 1
            if result.passed:
                report.passed += 1
            elif result.skipped:
                report.skipped += 1
            else:
                report.failed += 1

    return report


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def _load_cases(path: Path) -> list[EvalCase]:
    """Loads eval cases from a YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a YAML list of cases")

    cases: list[EvalCase] = []
    for item in raw:
        expect_raw = item.get("expect", {})
        expect = Expectation(
            grounded=expect_raw.get("grounded"),
            needs_review=expect_raw.get("needs_review"),
            tools_called=expect_raw.get("tools_called", []),
            tools_not_called=expect_raw.get("tools_not_called", []),
            citations_min=expect_raw.get("citations_min"),
            answer_contains=expect_raw.get("answer_contains", []),
            answer_not_contains=expect_raw.get("answer_not_contains", []),
            warnings_contain=expect_raw.get("warnings_contain", []),
            review_reasons_contain=expect_raw.get("review_reasons_contain", []),
        )
        cases.append(
            EvalCase(
                id=item["id"],
                question=item["question"],
                owner=item.get("owner"),
                lookback_days=item.get("lookback_days", 365),
                expect=expect,
            )
        )
    return cases


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_report(report: EvalRunReport, verbose: bool = False) -> None:
    """Prints a human-readable report to stdout."""
    print()
    print(f"=== {report.set_name} ===")
    print(f"  Total:  {report.total}")
    print(f"  Passed: {report.passed}")
    print(f"  Failed: {report.failed}")
    print(f"  Skipped:{report.skipped}")
    effective = report.total - report.skipped
    rate = (report.passed / effective * 100) if effective > 0 else 0.0
    print(f"  Pass rate: {report.passed}/{effective} ({rate:.1f}%)")

    for result in report.results:
        status = (
            "PASS" if result.passed else ("SKIP" if result.skipped else "FAIL")
        )
        print(f"  [{status}] {result.case_id} ({result.runtime_ms:.0f}ms)")
        if (verbose or not result.passed) and result.detail:
            for line in result.detail:
                print(f"         {line}")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run allotmint_research eval suites"
    )
    parser.add_argument(
        "--set",
        default="all",
        choices=["all", "regression", "adversarial"],
        help="Which eval set to run (default: all)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print details for all cases",
    )
    args = parser.parse_args()

    settings = Settings(
        llm_provider="ollama",
        llm_model="llama3.2",
        mcp_url="http://localhost:8080/mcp",
        max_tool_calls=6,
        retrieval_enabled=True,
    )

    eval_dir = _SELF.parent / "eval"

    exit_code = 0
    reports: list[EvalRunReport] = []

    if args.set in ("all", "regression"):
        reg_path = eval_dir / "regression.yaml"
        if reg_path.exists():
            cases = _load_cases(reg_path)
            report = await _run_set(cases, "regression", settings)
            reports.append(report)
            _print_report(report, args.verbose)
            if report.failed > 0:
                exit_code = 1
        else:
            print(f"WARNING: {reg_path} not found", file=sys.stderr)

    if args.set in ("all", "adversarial"):
        adv_path = eval_dir / "adversarial.yaml"
        if adv_path.exists():
            cases = _load_cases(adv_path)
            report = await _run_set(cases, "adversarial", settings)
            reports.append(report)
            _print_report(report, args.verbose)
            if report.failed > 0:
                exit_code = 1
        else:
            print(f"WARNING: {adv_path} not found", file=sys.stderr)

    # Summary
    if len(reports) > 1:
        total_all = sum(r.total for r in reports)
        passed_all = sum(r.passed for r in reports)
        failed_all = sum(r.failed for r in reports)
        effective = total_all - sum(r.skipped for r in reports)
        rate = (passed_all / effective * 100) if effective > 0 else 0.0
        print()
        print(f"=== OVERALL ===")
        print(f"  Total:  {total_all}")
        print(f"  Passed: {passed_all}")
        print(f"  Failed: {failed_all}")
        print(f"  Pass rate: {passed_all}/{effective} ({rate:.1f}%)")

    return exit_code


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
