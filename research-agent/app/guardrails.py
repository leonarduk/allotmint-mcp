"""Guardrail layer for `run_research`: detects low-confidence and adversarial-pattern
responses and flags them `needs_review` rather than passing them through as
confident answers.

Two families of checks, both designed to produce programmatic verdicts rather
than subjective quality judgments:

* **Adversarial detection** — prompt injection, hallucination bait, out-of-scope
  tool argument patterns. These are pattern-based and never call an LLM.
* **Confidence assessment** — groundedness, citation coverage, tool-call
  appropriateness for the question. Computed entirely from the trace (what was
  actually retrieved and called), not from the model's own prose.

The interface is a single function, `review`, that takes the full set of
observables from a run and returns a `ReviewVerdict`. The calling site in
`agent.py` maps that to `AskResponse.needs_review` and `review_reasons`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import AskRequest, RetrievedDocument, ToolCallRecord

# ---------------------------------------------------------------------------
# Pattern libraries — deliberately narrow per the issue scope
# ---------------------------------------------------------------------------

# Prompt-injection signals: the question text itself contains system-prompt
# language, override instructions, or ignore-previous markers.
_INJECTION_PATTERNS = [
    # System prompt / override
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+(?:now|now acting as)\b", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\|system\|>", re.IGNORECASE),
    re.compile(r"\[system\]", re.IGNORECASE),
    # Direct role-switch
    re.compile(r"forget\s+(?:everything|your\s+training|your\s+instructions)", re.IGNORECASE),
    re.compile(r"new\s+(?:instructions|directive|order)\s*:", re.IGNORECASE),
    re.compile(r"do\s+not\s+follow\s+(?:your\s+)?(?:instructions|rules)", re.IGNORECASE),
    # Delimiter injection
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"<\|im_end\|>", re.IGNORECASE),
    re.compile(r"<\|endoftext\|>", re.IGNORECASE),
    # Refusal override
    re.compile(r"you\s+must\s+(?:answer|respond|obey)", re.IGNORECASE),
    re.compile(r"disregard\s+(?:ethics|safety|guidelines|policy)", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
]

# Hallucination-bait patterns in the question: asking for invented data,
# asking the model to pretend, or asking it to confirm a false premise.
_HALLUCINATION_BAIT_PATTERNS = [
    re.compile(r"pretend\s+(?:that|you\s+are)", re.IGNORECASE),
    re.compile(r"make\s+up\b", re.IGNORECASE),
    re.compile(r"invent\b", re.IGNORECASE),
    re.compile(r"fabricate\b", re.IGNORECASE),
    re.compile(r"hallucinate\b", re.IGNORECASE),
    re.compile(r"what\s+would\s+it\s+say\s+if", re.IGNORECASE),
    re.compile(r"imagine\s+(?:that|you)", re.IGNORECASE),
]

# Out-of-scope tool-arg patterns that should never reach a v0 tool.
# These match arguments the agent tried to pass (from the recorded tool calls),
# not the question text — because the question might trick the agent into
# producing them.
_OUT_OF_SCOPE_ARG_PATTERNS = [
    (re.compile(r"drop\b", re.IGNORECASE), "destructive verb"),
    (re.compile(r"delete\b", re.IGNORECASE), "destructive verb"),
    (re.compile(r"insert\b", re.IGNORECASE), "destructive verb"),
    (re.compile(r"update\b", re.IGNORECASE), "destructive verb"),
    (re.compile(r"create\b", re.IGNORECASE), "destructive verb"),
    (re.compile(r"exec\b", re.IGNORECASE), "code execution verb"),
    (re.compile(r"eval\b", re.IGNORECASE), "code execution verb"),
    (re.compile(r"sudo\b", re.IGNORECASE), "privilege escalation"),
    (re.compile(r"password", re.IGNORECASE), "credential keyword"),
    (re.compile(r"token", re.IGNORECASE), "credential keyword"),
]

# ---------------------------------------------------------------------------
# Verdict data class
# ---------------------------------------------------------------------------


@dataclass
class ReviewVerdict:
    """The guardrail's judgment on one `run_research` invocation.

    ``needs_review`` is the actionable bit: True means the answer should not go
    straight to the user without a human looking at it.

    ``reasons`` enumerates *why* so the human reviewer knows what to check.
    These are deterministic strings (never prose from the model) so the eval
    runner can match against them programmatically.
    """

    needs_review: bool = False
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def review(
    request: AskRequest,
    answer: str,
    documents: list[RetrievedDocument],
    tool_calls: list[ToolCallRecord],
    grounded: bool,
    warnings: list[str],
) -> ReviewVerdict:
    """Runs the full guardrail check over one research invocation.

    All checks are deterministic and rely only on the observed trace (question
    text, retrieved documents, recorded tool calls, grounding flag, warnings)
    plus pattern matching on the answer. Nothing here calls an LLM or relies
    on subjective quality assessment.
    """
    reasons: list[str] = []

    # --- Adversarial checks against the question ---
    reasons.extend(_check_injection(request.question))
    reasons.extend(_check_hallucination_bait(request.question))

    # --- Adversarial checks against tool-call arguments ---
    reasons.extend(_check_tool_args(tool_calls))

    # --- Confidence / groundedness checks ---
    if not grounded:
        reasons.append(
            "answer is not grounded: no retrieved documents and no tool calls to back it"
        )

    # An answer that carries no citations at all is claiming authority it
    # does not have, unless the model honestly said it could not answer.
    cited_docs_or_tools = any(
        f"[{c.ref}]" in answer or f"[tool:{c.ref}]" in answer for c in _fake_citations(documents, tool_calls)
    )
    no_citations_detected = not cited_docs_or_tools and _marker_count(answer) == 0
    if no_citations_detected and grounded:
        reasons.append("answer contains no citation markers despite having sources available")

    # If the model was given documents but called no tools and the question
    # looks like it needs tools (asks about the user's own portfolio, current
    # data, or real-time information), flag it.
    if documents and not tool_calls:
        if _question_looks_tool_dependent(request.question):
            reasons.append(
                "question appears to need tool calls (portfolio/market/instrument data) "
                "but the agent called none"
            )

    # Warnings from the citation layer (dangling markers, uncited tools) are
    # often a sign the model invented sources.
    for w in warnings:
        if "never called" in w:
            reasons.append(f"citation warning — {w}")
        elif "do not exist" in w:
            reasons.append(f"citation warning — {w}")

    # An answer that is mostly the model refusing or saying it cannot do
    # something is typically benign, so don't escalate just for that.
    if not grounded and _is_refusal(answer):
        # A refusal with no sources is the correct answer to an unanswerable
        # question — don't flag it.
        reasons = [r for r in reasons if "not grounded" not in r]

    return ReviewVerdict(needs_review=len(reasons) > 0, reasons=reasons)


# ---------------------------------------------------------------------------
# Internal check helpers
# ---------------------------------------------------------------------------


def _check_injection(text: str) -> list[str]:
    reasons: list[str] = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            reasons.append(f"possible prompt injection detected: matched '{pattern.pattern}'")
            break  # One match is enough; don't flood the reasons list
    return reasons


def _check_hallucination_bait(text: str) -> list[str]:
    reasons: list[str] = []
    for pattern in _HALLUCINATION_BAIT_PATTERNS:
        if pattern.search(text):
            reasons.append(f"hallucination-bait question detected: matched '{pattern.pattern}'")
            break
    return reasons


def _check_tool_args(tool_calls: list[ToolCallRecord]) -> list[str]:
    reasons: list[str] = []
    for call in tool_calls:
        flat = " ".join(f"{k}={v!s}" for k, v in call.arguments.items())
        for pattern, label in _OUT_OF_SCOPE_ARG_PATTERNS:
            if pattern.search(flat):
                reasons.append(
                    f"out-of-scope tool argument to {call.tool}: {label} "
                    f"(matched '{pattern.pattern}' in '{flat}')"
                )
                break
    return reasons


def _fake_citations(
    documents: list[RetrievedDocument], tool_calls: list[ToolCallRecord]
) -> list:
    """Produces lightweight objects with a `.ref` for citation-marker matching."""
    class _Ref:
        def __init__(self, ref: str):
            self.ref = ref

    result: list = []
    for d in documents:
        result.append(_Ref(d.source))
    for tc in tool_calls:
        result.append(_Ref(tc.tool))
    return result


def _marker_count(text: str) -> int:
    """Counts `[n]` and `[tool:x]` markers in the answer."""
    markers = set()
    for m in re.finditer(r"\[(\d+|tool:[a-z_]+)\]", text, re.IGNORECASE):
        markers.add(m.group(0))
    return len(markers)


def _question_looks_tool_dependent(question: str) -> bool:
    """Heuristic: does the question likely need live data from MCP tools?

    Purely knowledge/definition questions can be answered from retrieval alone.
    Questions about "my"/"our" portfolio, current prices, or market state need
    the tools.
    """
    lower = question.lower()
    portfolio_signals = [
        "my portfolio", "my exposure", "my holdings", "my account",
        "our portfolio", "our exposure", "my position", "what do i hold",
        "what am i invested in", "how much of", "what is my",
    ]
    market_signals = [
        "today", "right now", "current price", "current value",
        "latest", "this week", "this month", "live",
    ]
    for signal in portfolio_signals:
        if signal in lower:
            return True
    for signal in market_signals:
        if signal in lower:
            return True
    return False


def _is_refusal(answer: str) -> bool:
    """Detects whether the answer is the model declining to answer."""
    lower = answer.lower().strip()
    refusal_phrases = [
        "i cannot", "i can't", "i do not have", "i don't have",
        "i could not", "i couldn't", "unable to", "not able to",
        "no information", "insufficient information", "i am unable",
        "i'm unable", "cannot determine", "can't determine",
        "could not determine", "couldn't determine",
    ]
    if len(lower) < 200:
        for phrase in refusal_phrases:
            if phrase in lower:
                return True
    return False
