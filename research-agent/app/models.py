"""Request and response shapes for the sidecar's HTTP API.

These are the contract with the Java side: `ResearchAnswer.java` and
`AllotMintResearchTool.java` in src/main/java deserialize exactly these fields.
Changing a field name here is a breaking change there.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import DEFAULT_LOOKBACK_DAYS


class AskRequest(BaseModel):
    """`POST /research/ask` body, mirroring the MCP tool's input schema."""

    question: str = Field(min_length=1)
    owner: str | None = None
    lookback_days: int = Field(default=DEFAULT_LOOKBACK_DAYS, ge=1, le=3650)
    llm_provider: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Opaque client-chosen id used to hold a multi-turn conversation across "
            "separate /research/ask calls (#548). When supplied, the previous turns' "
            "message history for this id is threaded into the agent run via "
            "pydantic_ai's message_history, and the updated history is stored back "
            "under the same id afterwards. History is held in-memory only, capped "
            "and evicted per Settings.max_conversation_sessions / "
            "max_conversation_messages, and is lost on sidecar restart -- an "
            "unrecognized or expired session_id starts a fresh empty history rather "
            "than erroring. Omitting session_id preserves the original single-shot "
            "behavior exactly."
        ),
    )


class Citation(BaseModel):
    """One numbered, traceable source behind the answer.

    Citations are constructed from what actually happened -- a document
    retrieval returned, or a tool call the agent really made -- never from the
    model's own claims about its sources. A model that invents "[4]" produces a
    dangling marker, not a fabricated citation.
    """

    id: int
    kind: Literal["document", "tool_call"]
    ref: str
    detail: str = ""
    excerpt: str = ""


class ToolCallRecord(BaseModel):
    """One MCP tool invocation observed during the agent run."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_excerpt: str = ""


class RetrievedDocument(BaseModel):
    """One document returned by the pgvector similarity search."""

    source: str
    content: str
    distance: float
    doc_type: str = ""
    published: str | None = None


class AskResponse(BaseModel):
    """`POST /research/ask` response.

    `grounded` is the honest signal: false means nothing traceable stands
    behind the prose, and the Java tool turns that into an MCP error rather
    than passing plausible-sounding text to a client.
    """

    question: str
    owner: str | None = None
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    retrieved_documents: list[RetrievedDocument] = Field(default_factory=list)
    grounded: bool = False
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model: str = ""
    # Worker/verifier can run different models since #549. `model` above is
    # unchanged (worker only, matching the pre-#549 response shape); this is
    # additive so existing consumers reading `model` see no change, while a
    # consumer that cares can compare the two to see whether they diverged.
    verifier_model: str = ""
    trace_id: str | None = None
