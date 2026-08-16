"""Sequential worker/verifier orchestration for research answers.

The research worker owns retrieval and MCP tools.  This module supplies a
second, deliberately tool-free role: a verifier that compares the completed
answer with the evidence trace.  Both the deterministic guardrail and the LLM
verifier must approve an answer; disagreement, timeout, or verifier failure is
conservatively escalated through ``needs_review``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .guardrails import ReviewVerdict
from .models import AskRequest, Citation

log = logging.getLogger(__name__)

VERIFIER_PROMPT = """\
You are AllotMint's evidence verifier. You do not answer the user's question
and you have no tools. Review the worker answer only against the supplied
evidence. Check that material numbers and claims have a matching citation and
that the answer does not overstate the evidence.

Reply on exactly one line:
APPROVE
or
NEEDS_REVIEW: <short reason>
"""


@dataclass(frozen=True)
class VerifierVerdict:
    needs_review: bool
    reason: str = ""


def _make_verifier(model: Any, temperature: float):
    """Construct the distinct, tool-free verifier agent role."""
    from pydantic_ai import Agent
    from pydantic_ai.settings import ModelSettings

    return Agent(
        model,
        instructions=VERIFIER_PROMPT,
        model_settings=ModelSettings(temperature=temperature),
        retries=0,
    )


def _verifier_input(request: AskRequest, answer: str, citations: list[Citation]) -> str:
    evidence = "\n".join(
        f"[{item.id}] {item.kind} {item.ref}: {item.excerpt}" for item in citations
    ) or "(no evidence)"
    return f"Question: {request.question}\nWorker answer: {answer}\nEvidence:\n{evidence}"


async def run_verifier(
    request: AskRequest,
    answer: str,
    citations: list[Citation],
    model: Any,
    temperature: float,
) -> VerifierVerdict:
    """Run and strictly parse the verifier; malformed output is not approval."""
    result = await _make_verifier(model, temperature).run(
        _verifier_input(request, answer, citations)
    )
    text = str(result.output).strip()
    if text == "APPROVE":
        return VerifierVerdict(False)
    if text.startswith("NEEDS_REVIEW:") and text.partition(":")[2].strip():
        return VerifierVerdict(True, text.partition(":")[2].strip())
    return VerifierVerdict(True, "verifier returned a malformed verdict")


async def combine_reviews(
    deterministic: ReviewVerdict,
    verifier_call: Callable[[], Awaitable[VerifierVerdict]],
    timeout_seconds: float,
) -> ReviewVerdict:
    """Merge the two reviewers and handle all inter-agent failure modes."""
    reasons = list(deterministic.reasons)
    try:
        verifier = await asyncio.wait_for(verifier_call(), timeout=timeout_seconds)
    except TimeoutError:
        reasons.append("verifier timed out; human review required")
        return ReviewVerdict(True, reasons)
    except Exception as exc:  # noqa: BLE001 - isolation boundary between agents
        log.warning("Verifier agent failed", exc_info=True)
        reasons.append(f"verifier failed ({type(exc).__name__}); human review required")
        return ReviewVerdict(True, reasons)

    if deterministic.needs_review != verifier.needs_review:
        reasons.append("worker guardrail and verifier disagreed; human review required")
    if verifier.needs_review:
        reasons.append(f"verifier: {verifier.reason}")
    return ReviewVerdict(bool(reasons), reasons)
