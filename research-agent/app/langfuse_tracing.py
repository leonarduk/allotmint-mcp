"""Langfuse observability integration for the allotmint_research agent.

Builds on the structured trace logging in tracing.py: uses the same trace_id
and maps the same lifecycle events onto Langfuse traces and spans so every
research invocation is inspectable in the Langfuse UI with distinct spans
for retrieval, each tool call, and synthesis.

Enabled only when both ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY``
are set. Failures to reach Langfuse are logged as warnings but never cause
the research request to fail — observability is best-effort.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class LangfuseTracer:
    """Sends structured trace events to Langfuse alongside the file logger.

    Mirrors the lifecycle of ``TraceLogger`` from ``tracing.py``: each method
    corresponds to one event in the agent loop. The same ``trace_id`` is used
    for both, so the file log and the Langfuse UI can be correlated.
    """

    def __init__(self, trace_id: str, settings: Any) -> None:
        self.trace_id: str = trace_id
        self._settings: Any = settings
        self._langfuse: Any = None
        self._trace: Any = None
        self._active_spans: dict[str, Any] = {}
        self._tool_span_counter: dict[str, int] = {}

        try:
            from langfuse import Langfuse  # type: ignore[import]

            self._langfuse = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            log.info("Langfuse tracer initialised for trace %s", trace_id)
        except Exception as exc:
            log.warning("Failed to initialise Langfuse: %s", exc)

    @property
    def enabled(self) -> bool:
        return self._langfuse is not None

    # -- request lifecycle --------------------------------------------------

    def request_start(
        self,
        question: str,
        owner: str | None,
        lookback_days: int,
        model: str,
    ) -> None:
        if not self.enabled:
            return
        try:
            self._trace = self._langfuse.trace(
                id=self.trace_id,
                name="allotmint_research",
                input={
                    "question": question,
                    "owner": owner,
                    "lookback_days": lookback_days,
                },
                metadata={"model": model},
                tags=["allotmint_research"],
            )
        except Exception as exc:
            log.warning("Langfuse trace creation failed: %s", exc)

    def request_end(
        self,
        grounded: bool,
        answer_length: int,
        citation_count: int,
        tool_call_count: int,
        document_count: int,
        warnings: list[str],
    ) -> None:
        if not self.enabled or self._trace is None:
            return
        try:
            self._trace.update(
                output={
                    "grounded": grounded,
                    "answer_length": answer_length,
                    "citation_count": citation_count,
                    "tool_call_count": tool_call_count,
                    "document_count": document_count,
                    "warnings": warnings,
                }
            )
        except Exception as exc:
            log.warning("Langfuse trace update failed: %s", exc)

    # -- retrieval ----------------------------------------------------------

    def retrieval_start(self) -> None:
        if not self.enabled or self._trace is None:
            return
        try:
            self._active_spans["retrieval"] = self._trace.span(name="retrieval")
        except Exception as exc:
            log.warning("Langfuse retrieval span start failed: %s", exc)

    def retrieval_end(
        self,
        document_count: int,
        sources: list[str],
        unavailable: bool = False,
    ) -> None:
        span = self._active_spans.pop("retrieval", None)
        if span is None:
            return
        try:
            span.end(
                output={
                    "document_count": document_count,
                    "sources": sources,
                    "unavailable": unavailable,
                }
            )
        except Exception as exc:
            log.warning("Langfuse retrieval span end failed: %s", exc)

    # -- agent run ----------------------------------------------------------

    def agent_start(self, model: str) -> None:
        if not self.enabled or self._trace is None:
            return
        try:
            self._active_spans["agent"] = self._trace.span(
                name="agent",
                input={"model": model},
            )
        except Exception as exc:
            log.warning("Langfuse agent span start failed: %s", exc)

    def agent_end(
        self,
        tool_call_count: int,
        answer_length: int,
        grounded: bool,
        usage: dict[str, int] | None = None,
    ) -> None:
        span = self._active_spans.pop("agent", None)
        if span is None:
            return
        try:
            output: dict[str, Any] = {
                "tool_call_count": tool_call_count,
                "answer_length": answer_length,
                "grounded": grounded,
            }
            kwargs: dict[str, Any] = {"output": output}
            if usage:
                kwargs["usage"] = usage
            span.end(**kwargs)
        except Exception as exc:
            log.warning("Langfuse agent span end failed: %s", exc)

    # -- tool calls ---------------------------------------------------------

    def tool_call_start(self, tool: str, arguments: dict[str, Any]) -> None:
        if not self.enabled or self._trace is None:
            return
        try:
            # Use a counter so repeated calls of the same tool produce distinct
            # span names in the Langfuse UI.
            idx = self._tool_span_counter.get(tool, 0) + 1
            self._tool_span_counter[tool] = idx
            span_key = f"tool_{tool}_{idx}"
            self._active_spans[span_key] = self._trace.span(
                name=f"tool_call.{tool}",
                input={"tool": tool, "arguments": arguments},
            )
        except Exception as exc:
            log.warning("Langfuse tool span start failed: %s", exc)

    def tool_call_end(
        self,
        tool: str,
        result_length: int,
        success: bool,
    ) -> None:
        # Find the oldest active span for this tool and end it.
        prefix = f"tool_{tool}_"
        matching = sorted(
            (k for k in self._active_spans if k.startswith(prefix)),
            key=lambda k: int(k.rsplit("_", 1)[1]),
        )
        if not matching:
            return
        span_key = matching[0]
        span = self._active_spans.pop(span_key)
        try:
            span.end(
                output={
                    "result_length": result_length,
                    "success": success,
                }
            )
        except Exception as exc:
            log.warning("Langfuse tool span end failed: %s", exc)

    # -- flush --------------------------------------------------------------

    def flush(self) -> None:
        """Ensure all pending events are sent to Langfuse.

        Must be called before the process exits to avoid dropped traces.
        """
        if not self.enabled:
            return
        try:
            self._langfuse.flush()
        except Exception as exc:
            log.warning("Langfuse flush failed: %s", exc)


def new_langfuse_tracer(trace_id: str, settings: Any) -> LangfuseTracer | None:
    """Creates a Langfuse tracer when API keys are configured.

    Returns ``None`` when Langfuse is not configured, so callers can treat
    the tracer as optional everywhere without a separate guard.
    """
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    return LangfuseTracer(trace_id, settings)
