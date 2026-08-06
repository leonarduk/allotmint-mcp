"""The agentic RAG loop: retrieve, chain the v0 MCP tools, synthesize, cite.

Shape of one run:

1. Retrieve the nearest documents for the question from pgvector, numbered
   `[1]..[n]` and injected into the prompt.
2. Run a Pydantic AI agent (the framework chosen in spike #12) with the four
   read-only v0 MCP tools bound. The agent decides which to call and in what
   order; nothing here hardcodes a tool sequence, because "always calls the
   same tool regardless of the question" is one of the issue's named failure
   modes.
3. Assemble citations from what actually happened, rewrite the model's
   `[tool:name]` markers into numbered ones, and report whether the answer is
   grounded at all.

The grounding rule is the important part. `grounded` is computed from real
retrieved documents and real recorded tool calls -- never from the prose. A
model that writes a confident answer having called nothing gets
`grounded=False`, and the Java tool turns that into an error.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from .config import Settings
from .llm import build_model
from .mcp_tools import ToolSession, open_session
from .models import AskRequest, AskResponse, Citation, RetrievedDocument, ToolCallRecord
from .retrieval import RetrievalUnavailable, search
from .tracing import TraceLogger
from .langfuse_tracing import LangfuseTracer, new_langfuse_tracer

log = logging.getLogger(__name__)

MAX_DOC_CHARS = 1200
MAX_CITATION_EXCERPT = 240

# Reasoning models served over Ollama's OpenAI-compatible /v1 endpoint leak
# their scratchpad into the message content -- a concrete finding from the #12
# spike, which saw raw <think> markup in Pydantic AI's output. Strip it rather
# than showing it to the user as if it were the answer.
_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_TOOL_MARKER = re.compile(r"\[tool:([a-z_]+)\]", re.IGNORECASE)
_NUMERIC_MARKER = re.compile(r"\[(\d+)\]")

SYSTEM_PROMPT = """\
You are AllotMint's portfolio research assistant. You answer questions about a \
real person's real money, so every number, ticker, and headline you state must \
come from either the retrieved context below or a tool you actually called.

Tools available to you (all read-only):
- allotmint_portfolio(action, owner, account_type, currency, lookback_days): action is one of \
summary, exposure, holdings. Use exposure for sector/asset-class/currency \
weights, holdings for the per-position list, summary for totals and performance.
- allotmint_instrument(action, query, ticker, exchange): action is one of \
search, detail, prices, news. Use news to explain *why* something moved.
- allotmint_market(action): action is one of overview, movers, indices.
- allotmint_health(): checks the backend is reachable. Only useful for \
diagnosing failures.

How to work:
1. Decide which tools the question actually needs. A question about a \
portfolio needs allotmint_portfolio. A question asking "why" additionally \
needs news or market data. A question about one instrument needs \
allotmint_instrument. Do not call tools that cannot contribute.
2. Call them. Read the JSON that comes back. If a call fails or returns \
nothing, say so in your answer -- do not fill the gap with plausible content.
3. Answer using only what the context and the tool responses contain.

Citing (required):
- Cite a retrieved document as [n], using the number shown next to it.
- Cite a tool result as [tool:allotmint_portfolio] (or whichever tool it was).
- Every sentence containing a number, a ticker, a percentage, or a headline \
must carry a citation.
- If you did not obtain the information needed, say plainly that you could not \
retrieve it. An honest "I could not determine this" is a correct answer; an \
invented one is not.
"""


def build_context_block(documents: list[RetrievedDocument]) -> str:
    """Renders retrieved documents as the numbered context the prompt cites."""
    if not documents:
        return (
            "Retrieved context: none. No relevant documents were found, so every "
            "claim in your answer must come from a tool call."
        )
    lines = ["Retrieved context (cite these by their number):"]
    for index, document in enumerate(documents, start=1):
        content = document.content.strip().replace("\n", " ")
        if len(content) > MAX_DOC_CHARS:
            content = content[:MAX_DOC_CHARS] + "..."
        dated = f", published {document.published}" if document.published else ""
        lines.append(f"[{index}] source={document.source}{dated}\n    {content}")
    return "\n".join(lines)


def build_user_prompt(request: AskRequest, documents: list[RetrievedDocument]) -> str:
    """Assembles the single user turn: question, scope, and retrieved context."""
    parts = [f"Question: {request.question}"]
    if request.owner:
        parts.append(
            f"The owner slug for portfolio lookups is '{request.owner}' -- pass it as "
            "the `owner` argument."
        )
    else:
        parts.append(
            "No owner slug was supplied. If the question needs portfolio data, say so "
            "rather than guessing an owner."
        )
    parts.append(f"Consider documents and news from the last {request.lookback_days} days.")
    parts.append("")
    parts.append(build_context_block(documents))
    return "\n".join(parts)


def _make_agent(model: Any, tools: ToolSession, settings: Settings):
    """Builds a Pydantic AI agent whose tools proxy to the live MCP session.

    The four wrappers exist as explicit typed functions rather than a generic
    passthrough so the model sees the real per-tool argument names and
    docstrings -- the #12 spike found small local models are markedly better at
    producing well-typed calls against a narrow, concrete schema.
    """
    from pydantic_ai import Agent
    from pydantic_ai.settings import ModelSettings

    agent = Agent(
        model,
        instructions=SYSTEM_PROMPT,
        model_settings=ModelSettings(temperature=settings.llm_temperature),
        retries=2,
    )

    @agent.tool_plain
    async def allotmint_portfolio(
        action: str,
        owner: str,
        account_type: str | None = None,
        currency: str | None = None,
        include_history: bool = False,
        lookback_days: int | None = None,
    ) -> str:
        """Read one owner's portfolio. action: summary, exposure, or holdings.

        When action='exposure', lookback_days (default 365) adds a
        weight_pct_year_ago field to each sector for historical comparison."""
        args: dict[str, object] = {
            "action": action,
            "owner": owner,
            "account_type": account_type,
            "currency": currency,
            "lookback_days": lookback_days,
        }
        if action.lower() == "summary":
            args["include_history"] = include_history
        return await tools.call_tool("allotmint_portfolio", args)

    @agent.tool_plain
    async def allotmint_instrument(
        action: str,
        query: str | None = None,
        ticker: str | None = None,
        exchange: str | None = None,
    ) -> str:
        """Look up an instrument. action: search, detail, prices, or news."""
        return await tools.call_tool(
            "allotmint_instrument",
            {"action": action, "query": query, "ticker": ticker, "exchange": exchange},
        )

    @agent.tool_plain
    async def allotmint_market(action: str) -> str:
        """Market data. action: overview, movers, or indices."""
        return await tools.call_tool("allotmint_market", {"action": action})

    @agent.tool_plain
    async def allotmint_health() -> str:
        """Check that the AllotMint backend is reachable."""
        return await tools.call_tool("allotmint_health", {})

    return agent


def strip_reasoning(text: str) -> str:
    """Removes leaked `<think>...</think>` scratchpad from a model's output."""
    cleaned = _THINK_BLOCK.sub("", text)
    # An unterminated <think> means the whole tail is scratchpad; keep whatever
    # came before it rather than returning reasoning markup as the answer.
    if "<think>" in cleaned.lower():
        cleaned = re.split(r"<think>", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    return cleaned.strip()


def build_citations(
    documents: list[RetrievedDocument], tool_calls: list[ToolCallRecord]
) -> list[Citation]:
    """Numbers every real source: documents first, then tool calls.

    Documents keep the numbers they were given in the prompt, so the model's
    `[n]` markers stay valid. Tool calls are appended after them, which is why
    the model cites tools by name (`[tool:x]`) instead -- it cannot know these
    numbers while it is writing.
    """
    citations: list[Citation] = []
    for index, document in enumerate(documents, start=1):
        citations.append(
            Citation(
                id=index,
                kind="document",
                ref=document.source,
                detail=f"cosine distance {document.distance:.4f}",
                excerpt=document.content.strip()[:MAX_CITATION_EXCERPT],
            )
        )
    offset = len(documents)
    for index, call in enumerate(tool_calls, start=offset + 1):
        arguments = ", ".join(f"{k}={v!r}" for k, v in call.arguments.items())
        citations.append(
            Citation(
                id=index,
                kind="tool_call",
                ref=call.tool,
                detail=f"{call.tool}({arguments})",
                excerpt=call.result_excerpt[:MAX_CITATION_EXCERPT],
            )
        )
    return citations


def resolve_markers(
    answer: str, documents: list[RetrievedDocument], tool_calls: list[ToolCallRecord]
) -> tuple[str, set[int], list[str]]:
    """Rewrites `[tool:name]` markers to numbers and validates every marker.

    Returns the rewritten answer, the set of citation ids it actually
    references, and any warnings. A marker pointing at a source that does not
    exist (`[7]` when four documents were retrieved, or a tool the agent never
    called) is reported rather than silently accepted -- that is the model
    claiming a source it does not have.
    """
    warnings: list[str] = []
    offset = len(documents)
    first_call_id: dict[str, int] = {}
    for index, call in enumerate(tool_calls, start=offset + 1):
        first_call_id.setdefault(call.tool, index)

    uncited_tools: set[str] = set()

    def replace_tool(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        citation_id = first_call_id.get(name)
        if citation_id is None:
            uncited_tools.add(name)
            return match.group(0)
        return f"[{citation_id}]"

    rewritten = _TOOL_MARKER.sub(replace_tool, answer)

    if uncited_tools:
        warnings.append(
            "The answer cites tools that were never called: "
            + ", ".join(sorted(uncited_tools))
        )

    total = offset + len(tool_calls)
    referenced: set[int] = set()
    dangling: set[int] = set()
    for match in _NUMERIC_MARKER.finditer(rewritten):
        value = int(match.group(1))
        if 1 <= value <= total:
            referenced.add(value)
        else:
            dangling.add(value)
    if dangling:
        warnings.append(
            "The answer references citation markers that do not exist: "
            + ", ".join(f"[{value}]" for value in sorted(dangling))
        )

    return rewritten, referenced, warnings


async def run_research(
    request: AskRequest,
    settings: Settings,
    trace_logger: TraceLogger | None = None,
    langfuse_tracer: LangfuseTracer | None = None,
) -> AskResponse:
    """Runs one full research question end to end."""
    started = time.monotonic()
    warnings: list[str] = []

    if trace_logger is not None:
        trace_logger.request_start(
            request.question,
            request.owner,
            request.lookback_days,
            settings.model_label,
        )
    if langfuse_tracer is not None:
        langfuse_tracer.request_start(
            request.question,
            request.owner,
            request.lookback_days,
            settings.model_label,
        )

    # --- retrieval ---------------------------------------------------------
    documents: list[RetrievedDocument] = []
    if trace_logger is not None:
        trace_logger.retrieval_start()
    if langfuse_tracer is not None:
        langfuse_tracer.retrieval_start()
    try:
        documents = await search(
            request.question,
            settings,
            owner=request.owner,
            lookback_days=request.lookback_days,
        )
    except RetrievalUnavailable as exc:
        log.warning("Retrieval unavailable, continuing on tool calls alone: %s", exc)
        warnings.append(
            f"Retrieval store unavailable ({exc}); the answer rests on tool calls alone."
        )
        if trace_logger is not None:
            trace_logger.retrieval_end(0, [], unavailable=True)
        if langfuse_tracer is not None:
            langfuse_tracer.retrieval_end(0, [], unavailable=True)
    else:
        if trace_logger is not None:
            trace_logger.retrieval_end(
                len(documents),
                [d.source for d in documents],
                unavailable=False,
            )
        if langfuse_tracer is not None:
            langfuse_tracer.retrieval_end(
                len(documents),
                [d.source for d in documents],
                unavailable=False,
            )

    # --- agent run ---------------------------------------------------------
    model = build_model(settings)
    prompt = build_user_prompt(request, documents)

    if trace_logger is not None:
        trace_logger.agent_start(settings.model_label)
    if langfuse_tracer is not None:
        langfuse_tracer.agent_start(settings.model_label)

    async with open_session(settings, trace_logger=trace_logger) as tools:
        agent = _make_agent(model, tools, settings)
        result = await agent.run(prompt)
        tool_calls = list(tools.calls)

    answer = strip_reasoning(str(result.output))

    # Extract cumulative token usage from the pydantic_ai result.
    # `result.usage()` returns a RunUsage (pydantic BaseModel) with
    # input_tokens / output_tokens at the top level.  cost is Decimal|None.
    agent_usage: dict[str, int] | None = None
    try:
        run_usage = result.usage()
        total_input = getattr(run_usage, "input_tokens", 0) or 0
        total_output = getattr(run_usage, "output_tokens", 0) or 0
        if total_input > 0 or total_output > 0:
            agent_usage = {"input": total_input, "output": total_output}
            # Include total for Langfuse UI cost calculation when available.
            total = getattr(run_usage, "total_tokens", 0) or 0
            if total > 0:
                agent_usage["total"] = total
    except Exception:
        log.debug("Failed to extract token usage from pydantic_ai result", exc_info=True)

    if trace_logger is not None:
        trace_logger.agent_end(
            tool_call_count=len(tool_calls),
            answer_length=len(answer),
            grounded=bool(documents) or bool(tool_calls),
        )
    if langfuse_tracer is not None:
        langfuse_tracer.agent_end(
            tool_call_count=len(tool_calls),
            answer_length=len(answer),
            grounded=bool(documents) or bool(tool_calls),
            usage=agent_usage,
        )

    answer, referenced, marker_warnings = resolve_markers(answer, documents, tool_calls)
    warnings.extend(marker_warnings)

    if not referenced:
        warnings.append(
            "The answer carries no inline citation markers; see the numbered sources "
            "below for everything it could have drawn on."
        )
    if documents and not tool_calls:
        warnings.append(
            "The agent answered from retrieved context alone and called no tools."
        )

    grounded = bool(documents) or bool(tool_calls)

    from .guardrails import review

    safety = review(
        request=request,
        answer=answer,
        documents=documents,
        tool_calls=tool_calls,
        grounded=grounded,
        warnings=warnings,
    )

    log.info(
        "research complete in %.1fs: %d document(s), %d tool call(s), grounded=%s",
        time.monotonic() - started,
        len(documents),
        len(tool_calls),
        grounded,
    )

    citations = build_citations(documents, tool_calls)

    if trace_logger is not None:
        trace_logger.request_end(
            grounded=grounded,
            answer_length=len(answer),
            citation_count=len(citations),
            tool_call_count=len(tool_calls),
            document_count=len(documents),
            warnings=warnings,
        )
    if langfuse_tracer is not None:
        langfuse_tracer.request_end(
            grounded=grounded,
            answer_length=len(answer),
            citation_count=len(citations),
            tool_call_count=len(tool_calls),
            document_count=len(documents),
            warnings=warnings,
        )

    return AskResponse(
        question=request.question,
        owner=request.owner,
        lookback_days=request.lookback_days,
        answer=answer,
        citations=citations,
        tool_calls=tool_calls,
        retrieved_documents=documents,
        grounded=grounded,
        needs_review=safety.needs_review,
        review_reasons=safety.reasons,
        warnings=warnings,
        model=settings.model_label,
        trace_id=trace_logger.trace_id if trace_logger is not None else None,
    )
