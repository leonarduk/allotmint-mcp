"""Structured JSON trace logging for the allotmint_research agent loop.

Every step of a research invocation emits one JSON event line with a shared
trace_id, so the full decision path of any request is reconstructable after
the fact. One line per event; each line is a complete JSON object.

This is the lightweight MVP tier from the design doc: structured file logging,
no tracing SDK, no new infrastructure. The same file is both the write target
and the query source for `GET /research/trace/{trace_id}`.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class TraceLogger:
    """Writes structured JSON trace events to a file, one per line.

    Created once per request with a fresh UUID. Events are written
    immediately (append + flush) so they survive a process crash and are
    visible to the query endpoint before the request completes.
    """

    def __init__(self, trace_id: str, file_path: Path) -> None:
        self.trace_id: str = trace_id
        self.file_path: Path = file_path
        self._started: float = time.monotonic()

    # -- internal -----------------------------------------------------------

    def _emit(self, event: str, **data: Any) -> None:
        record: dict[str, Any] = {
            "trace_id": self.trace_id,
            "event": event,
            "timestamp": time.time(),
            "elapsed_ms": int((time.monotonic() - self._started) * 1000),
        }
        if data:
            record["data"] = data
        try:
            line = json.dumps(record, default=str)
            with open(self.file_path, "a") as f:
                f.write(line + "\n")
                f.flush()
        except OSError as exc:
            log.warning("Failed to write trace event: %s", exc)

    # -- request lifecycle --------------------------------------------------

    def request_start(
        self,
        question: str,
        owner: str | None,
        lookback_days: int,
        model: str,
    ) -> None:
        self._emit(
            "request.start",
            question=question,
            owner=owner,
            lookback_days=lookback_days,
            model=model,
        )

    def request_end(
        self,
        grounded: bool,
        answer_length: int,
        citation_count: int,
        tool_call_count: int,
        document_count: int,
        warnings: list[str],
    ) -> None:
        self._emit(
            "request.end",
            grounded=grounded,
            answer_length=answer_length,
            citation_count=citation_count,
            tool_call_count=tool_call_count,
            document_count=document_count,
            warnings=warnings,
        )

    # -- retrieval ----------------------------------------------------------

    def retrieval_start(self) -> None:
        self._emit("retrieval.start")

    def retrieval_end(
        self,
        document_count: int,
        sources: list[str],
        unavailable: bool = False,
    ) -> None:
        self._emit(
            "retrieval.end",
            document_count=document_count,
            sources=sources,
            unavailable=unavailable,
        )

    # -- agent run ----------------------------------------------------------

    def agent_start(self, model: str) -> None:
        self._emit("agent.start", model=model)

    def agent_end(
        self,
        tool_call_count: int,
        answer_length: int,
        grounded: bool,
    ) -> None:
        self._emit(
            "agent.end",
            tool_call_count=tool_call_count,
            answer_length=answer_length,
            grounded=grounded,
        )

    # -- verifier (#549: may run a different model than the worker) --------

    def verifier_start(self, model: str) -> None:
        self._emit("verifier.start", model=model)

    def verifier_end(self, needs_review: bool, reason: str) -> None:
        self._emit("verifier.end", needs_review=needs_review, reason=reason)

    # -- tool calls ---------------------------------------------------------

    def tool_call_start(self, tool: str, arguments: dict[str, Any]) -> None:
        self._emit("tool_call.start", tool=tool, arguments=arguments)

    def tool_call_end(
        self,
        tool: str,
        result_length: int,
        success: bool,
        truncated: bool = False,
    ) -> None:
        self._emit(
            "tool_call.end",
            tool=tool,
            result_length=result_length,
            success=success,
            truncated=truncated,
        )


def new_trace(trace_file: Path | None) -> TraceLogger | None:
    """Creates a new trace logger when a file path is configured.

    Returns None when trace_file is None, so callers can treat the logger as
    optional everywhere without a separate guard.
    """
    if trace_file is None:
        return None
    return TraceLogger(str(uuid.uuid4()), trace_file)


def read_trace(trace_id: str, trace_file: Path) -> list[dict[str, Any]]:
    """Reads all events for a trace from the JSONL file.

    Returns an empty list when the file is missing or unreadable — the caller
    decides whether that is a 404 or an empty result.
    """
    if not trace_file.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        for line in trace_file.read_text().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if record.get("trace_id") == trace_id:
                events.append(record)
    except OSError:
        pass
    return events
