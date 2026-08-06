"""FastAPI surface of the research agent sidecar.

This is the interop boundary settled in spike #12: the Java MCP server calls
this service over plain local HTTP with Spring's `RestClient`, exactly as it
already calls the AllotMint backend. Three endpoints, all read-only.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException

from .agent import run_research
from .config import load_settings
from .langfuse_tracing import new_langfuse_tracer
from .llm import UnsupportedProvider
from .models import AskRequest, AskResponse
from .tracing import new_trace, read_trace

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(
    title="AllotMint research agent",
    description="Agentic RAG behind the allotmint_research MCP tool. Read-only.",
    version="1.0.0",
)


@app.get("/health")
async def health() -> dict:
    """Reports what this process is configured to talk to.

    Deliberately does not probe the LLM, the MCP server, or the database: a
    health check that makes three network calls fails for reasons that have
    nothing to do with this process being up. Configuration is what it can
    honestly report.
    """
    settings = load_settings()
    return {
        "status": "ok",
        "model": settings.model_label,
        "mcp_url": settings.mcp_url,
        "retrieval_enabled": settings.retrieval_enabled,
        "trace_file": settings.trace_file or "(disabled)",
        "tools": list(settings.tools),
    }


def _trace_file(settings) -> Path | None:
    """Resolves the trace file path when tracing is enabled."""
    if not settings.trace_file:
        return None
    path = Path(settings.trace_file)
    # Ensure the parent directory exists so the first write does not fail.
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@app.post("/research/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    """Answers one question with a grounded, cited response."""
    settings = load_settings()
    trace_logger = new_trace(_trace_file(settings))
    trace_id = trace_logger.trace_id if trace_logger is not None else str(uuid.uuid4())
    lf_tracer = new_langfuse_tracer(trace_id, settings)
    try:
        return await run_research(request, settings, trace_logger=trace_logger, langfuse_tracer=lf_tracer)
    except UnsupportedProvider as exc:
        # Misconfiguration, not a failed question - say so in a way the MCP
        # tool's error message can pass straight to whoever has to fix it.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - the boundary; nothing above catches
        log.exception("Research run failed")
        raise HTTPException(status_code=502, detail=f"research run failed: {exc}") from exc


@app.get("/research/trace/{trace_id}")
async def trace(trace_id: str):
    """Returns all structured trace events for a single research invocation.

    The trace file is the same one configured for writing, so events are
    visible as soon as they are flushed. Returns 404 when tracing is disabled
    or the trace_id is not in the file.
    """
    settings = load_settings()
    if not settings.trace_file:
        raise HTTPException(
            status_code=404,
            detail="Tracing is not enabled (ALLOTMINT_RESEARCH_TRACE_FILE is empty)",
        )
    trace_file = Path(settings.trace_file)
    events = read_trace(trace_id, trace_file)
    if not events:
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")
    return {"trace_id": trace_id, "events": events}
