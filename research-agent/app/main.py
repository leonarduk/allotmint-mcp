"""FastAPI surface of the research agent sidecar.

This is the interop boundary settled in spike #12: the Java MCP server calls
this service over plain local HTTP with Spring's `RestClient`, exactly as it
already calls the AllotMint backend. Two endpoints, both read-only.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from .agent import run_research
from .config import load_settings
from .llm import UnsupportedProvider
from .models import AskRequest, AskResponse

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
        "tools": list(settings.tools),
    }


@app.post("/research/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    """Answers one question with a grounded, cited response."""
    settings = load_settings()
    try:
        return await run_research(request, settings)
    except UnsupportedProvider as exc:
        # Misconfiguration, not a failed question - say so in a way the MCP
        # tool's error message can pass straight to whoever has to fix it.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - the boundary; nothing above catches
        log.exception("Research run failed")
        raise HTTPException(status_code=502, detail=f"research run failed: {exc}") from exc
