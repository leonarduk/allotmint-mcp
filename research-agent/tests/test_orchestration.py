"""Failure-mode tests for the sequential worker/verifier hand-off."""

from __future__ import annotations

import asyncio

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.guardrails import ReviewVerdict
from app.models import AskRequest
from app.orchestration import VerifierVerdict, combine_reviews, run_verifier


@pytest.mark.asyncio
async def test_both_reviewers_must_approve():
    async def approve():
        return VerifierVerdict(False)

    verdict = await combine_reviews(ReviewVerdict(False, []), approve, 1)
    assert verdict == ReviewVerdict(False, [])


@pytest.mark.asyncio
async def test_disagreement_escalates_to_needs_review():
    async def reject():
        return VerifierVerdict(True, "claim is not supported by citation [1]")

    verdict = await combine_reviews(ReviewVerdict(False, []), reject, 1)
    assert verdict.needs_review is True
    assert any("disagreed" in reason for reason in verdict.reasons)
    assert any("not supported" in reason for reason in verdict.reasons)


@pytest.mark.asyncio
async def test_verifier_timeout_escalates_to_needs_review():
    async def never_verifier():
        await asyncio.Event().wait()
        return VerifierVerdict(False)

    verdict = await combine_reviews(ReviewVerdict(False, []), never_verifier, 0.001)
    assert verdict.needs_review is True
    assert verdict.reasons == ["verifier timed out; human review required"]


@pytest.mark.asyncio
async def test_verifier_failure_escalates_to_needs_review():
    async def broken_verifier():
        raise RuntimeError("provider unavailable")

    verdict = await combine_reviews(ReviewVerdict(False, []), broken_verifier, 1)
    assert verdict.needs_review is True
    assert "verifier failed (RuntimeError)" in verdict.reasons[0]


@pytest.mark.asyncio
async def test_deterministic_needs_review_survives_verifier_approval():
    async def approve():
        return VerifierVerdict(False)

    deterministic = ReviewVerdict(True, ["guardrail flagged: unsourced figure"])
    verdict = await combine_reviews(deterministic, approve, 1)
    assert verdict.needs_review is True
    assert "guardrail flagged: unsourced figure" in verdict.reasons


def _verifier_model(text: str) -> FunctionModel:
    def respond(_messages, _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(respond)


@pytest.mark.asyncio
async def test_run_verifier_treats_malformed_output_as_needs_review():
    verdict = await run_verifier(
        AskRequest(question="What is my exposure?"),
        answer="Your exposure is 12%.",
        citations=[],
        model=_verifier_model("APPROVE, though I have reservations"),
        temperature=0.0,
    )
    assert verdict.needs_review is True
    assert verdict.reason == "verifier returned a malformed verdict"


@pytest.mark.asyncio
async def test_run_verifier_treats_empty_output_as_needs_review():
    verdict = await run_verifier(
        AskRequest(question="What is my exposure?"),
        answer="Your exposure is 12%.",
        citations=[],
        model=_verifier_model("   "),
        temperature=0.0,
    )
    assert verdict.needs_review is True
    assert verdict.reason == "verifier returned a malformed verdict"
