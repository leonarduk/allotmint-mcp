"""Tests for the grounding and citation layer.

The failure mode issue #13 names first is "plausible-sounding prose with no
traceable citation back to retrieved context or tool calls". These tests are
what stops that regressing: citations must come from real retrievals and real
tool calls, and a model's claim about its sources must never become a citation
on its own.
"""

from __future__ import annotations

from app.agent import (
    build_citations,
    build_context_block,
    build_user_prompt,
    resolve_markers,
    strip_reasoning,
)
from app.models import AskRequest, ToolCallRecord


def test_citations_number_documents_first_then_tool_calls(documents, tool_calls):
    citations = build_citations(documents, tool_calls)

    assert [c.id for c in citations] == [1, 2, 3, 4]
    assert [c.kind for c in citations] == ["document", "document", "tool_call", "tool_call"]
    assert citations[0].ref == "key_findings.md"
    assert "0.5579" in citations[0].detail
    assert citations[2].ref == "allotmint_portfolio"
    assert "action='exposure'" in citations[2].detail
    # The excerpt is the real tool response, so a reader can check the claim.
    assert "Technology" in citations[2].excerpt


def test_citations_are_empty_when_nothing_was_retrieved_or_called():
    assert build_citations([], []) == []


def test_tool_markers_are_rewritten_to_citation_numbers(documents, tool_calls):
    answer = (
        "Technology rose from 18% to 27% [1], confirmed by "
        "[tool:allotmint_portfolio], and driven by AI chip demand "
        "[tool:allotmint_instrument]."
    )

    rewritten, referenced, warnings = resolve_markers(answer, documents, tool_calls)

    assert "[tool:" not in rewritten
    assert "[3]" in rewritten and "[4]" in rewritten
    assert referenced == {1, 3, 4}
    assert warnings == []


def test_citing_a_tool_that_was_never_called_is_reported(documents):
    answer = "Tech is up [1], according to [tool:allotmint_market]."

    rewritten, referenced, warnings = resolve_markers(answer, documents, [])

    # The marker is left visible rather than silently rewritten to something
    # real -- the point is to expose the unsupported claim, not to launder it.
    assert "[tool:allotmint_market]" in rewritten
    assert referenced == {1}
    assert any("never called" in w for w in warnings)


def test_a_marker_past_the_end_of_the_source_list_is_reported(documents, tool_calls):
    answer = "Tech is up [1] and rates fell [9]."

    _, referenced, warnings = resolve_markers(answer, documents, tool_calls)

    assert referenced == {1}
    assert any("[9]" in w for w in warnings)


def test_an_answer_with_no_markers_references_nothing(documents, tool_calls):
    _, referenced, warnings = resolve_markers("Your tech exposure grew.", documents, tool_calls)

    assert referenced == set()
    assert warnings == []


def test_reasoning_scratchpad_is_stripped():
    # From the #12 spike: Ollama's OpenAI-compatible endpoint leaks <think>
    # blocks into message content for reasoning models.
    raw = "<think>The user wants sector data. I should call...</think>Tech rose to 27% [1]."

    assert strip_reasoning(raw) == "Tech rose to 27% [1]."


def test_an_unterminated_reasoning_block_does_not_leak():
    raw = "Tech rose to 27% [1].<think>but wait, maybe I should"

    assert strip_reasoning(raw) == "Tech rose to 27% [1]."


def test_context_block_numbers_documents_for_the_prompt(documents):
    block = build_context_block(documents)

    assert "[1] source=key_findings.md" in block
    assert "[2] source=report:portfolio.sectors" in block
    assert "published 2026-08-01" in block


def test_context_block_says_so_explicitly_when_retrieval_found_nothing():
    block = build_context_block([])

    assert "none" in block
    assert "must come from a tool call" in block


def test_prompt_passes_the_owner_slug_through(documents):
    request = AskRequest(question="how has my tech exposure changed?", owner="demo")

    prompt = build_user_prompt(request, documents)

    assert "how has my tech exposure changed?" in prompt
    assert "'demo'" in prompt
    assert "last 365 days" in prompt


def test_prompt_tells_the_model_not_to_guess_a_missing_owner(documents):
    prompt = build_user_prompt(AskRequest(question="what changed?"), documents)

    assert "rather than guessing an owner" in prompt


def test_duplicate_calls_to_one_tool_cite_the_first(documents):
    calls = [
        ToolCallRecord(tool="allotmint_portfolio", arguments={"action": "exposure"}),
        ToolCallRecord(tool="allotmint_portfolio", arguments={"action": "holdings"}),
    ]

    rewritten, referenced, warnings = resolve_markers(
        "Tech is 27% [tool:allotmint_portfolio].", documents, calls
    )

    assert "[3]" in rewritten
    assert referenced == {3}
    assert warnings == []
