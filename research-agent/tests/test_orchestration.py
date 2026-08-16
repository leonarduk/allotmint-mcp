"""Failure-mode tests for the sequential worker/verifier hand-off."""

from __future__ import annotations

import asyncio

import pytest

from app.guardrails import ReviewVerdict
from app.orchestration import VerifierVerdict, combine_reviews


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
    async def slow_verifier():
        await asyncio.sleep(0.1)
        return VerifierVerdict(False)

    verdict = await combine_reviews(ReviewVerdict(False, []), slow_verifier, 0.001)
    assert verdict.needs_review is True
    assert verdict.reasons == ["verifier timed out; human review required"]


@pytest.mark.asyncio
async def test_verifier_failure_escalates_to_needs_review():
    async def broken_verifier():
        raise RuntimeError("provider unavailable")

    verdict = await combine_reviews(ReviewVerdict(False, []), broken_verifier, 1)
    assert verdict.needs_review is True
    assert "verifier failed (RuntimeError)" in verdict.reasons[0]
