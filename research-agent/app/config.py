"""Environment-driven configuration for the research agent sidecar.

Every knob is an env var with a working local default, because the whole point
of the cost constraint on issue #13 is that the default configuration runs at
$0: a local Ollama model for synthesis, a local sentence-transformers model for
embeddings, and a local Postgres+pgvector for retrieval. Nothing here requires
an API key unless you deliberately switch `ALLOTMINT_RESEARCH_LLM_PROVIDER` to a
hosted provider.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import replace

# The four read-only v0 tools the agent is allowed to call. This is an
# allowlist, not documentation: `mcp_tools.py` refuses to invoke anything
# outside it, which is what keeps `allotmint_research` read-only and stops the
# agent recursing into itself (`allotmint_research` is deliberately absent).
V0_TOOL_ALLOWLIST = (
    "allotmint_portfolio",
    "allotmint_instrument",
    "allotmint_market",
    "allotmint_health",
)

DEFAULT_LOOKBACK_DAYS = 365


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw.strip() if raw and raw.strip() else default


def _env_float_optional(name: str) -> float | None:
    """Like `_env_float`, but returns `None` (rather than a default) when unset.

    Used for the verifier-role overrides in #549: `None` means "not
    configured", which is a distinct state from "configured to 0.0" and is
    what lets `Settings.verifier_settings()` tell "fall back to the worker's
    temperature" apart from "deliberately set to zero".
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass(frozen=True)
class Settings:
    """Resolved configuration for one process."""

    # --- LLM ---------------------------------------------------------------
    # "ollama" (default, free/local), "deepseek" (low-cost hosted), or
    # "openai-compatible" for anything else exposing an OpenAI-shaped /v1 API.
    llm_provider: str = "ollama"
    llm_model: str = "llama3.2"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_temperature: float = 0.0

    # --- Verifier LLM (#549) ------------------------------------------------
    # The verifier is a distinct role from the worker (see "Multi-agent
    # review" below) and can optionally run on its own provider/model -- e.g.
    # a cheap local worker checked by a stronger hosted verifier, or vice
    # versa. Every field here defaults to empty/`None`, meaning "unset"; unset
    # fields fall back to the worker's equivalent via `verifier_settings()`,
    # so today's single-model behavior (worker and verifier on the same
    # model) is exactly what you get until you deliberately configure one of
    # these. This is a per-process configuration choice, distinct from the
    # per-request `select_llm_provider()` override below, which retargets
    # only the worker -- see that function's docstring for why.
    verifier_llm_provider: str = ""
    verifier_llm_model: str = ""
    verifier_llm_base_url: str = ""
    verifier_llm_api_key: str = ""
    verifier_llm_temperature: float | None = None

    # --- MCP ---------------------------------------------------------------
    # The allotmint-mcp server's own streamable HTTP endpoint. The agent is an
    # ordinary MCP client of it, which is what "reuse the v0 tools as-is" means
    # in practice -- no reimplementation of portfolio maths in Python.
    mcp_url: str = "http://localhost:8080/mcp"
    mcp_timeout_seconds: float = 30.0
    max_tool_calls: int = 6

    # --- Multi-turn conversation sessions (#548) ---------------------------
    # A session is an in-memory pydantic_ai message history keyed by the
    # client-supplied `session_id`, scoped to this process only -- see
    # `app/sessions.py`. Both caps exist so a long-running sidecar handling
    # many/long conversations cannot grow that in-memory map unbounded, the
    # same "must exist, even a simple fixed cap" requirement #466/#578 applied
    # to single-request tool-result size.
    max_conversation_sessions: int = 200
    max_conversation_messages: int = 40

    # --- Multi-agent review -----------------------------------------------
    # The verifier is a second, tool-free agent that reviews the worker's
    # answer after synthesis. Its deadline is deliberately separate from MCP
    # tool timeouts so a slow critic cannot hold the request open indefinitely.
    verifier_timeout_seconds: float = 10.0

    # --- Retrieval ---------------------------------------------------------
    db_dsn: str = "postgresql://allotmint:allotmint@localhost:5432/allotmint_research"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    top_k: int = 5
    # Retrieved documents further away than this are dropped rather than fed to
    # the model as if they were relevant. The pgvector spike (#11) measured
    # 0.56-0.75 for genuinely on-topic documents against the sample question, so
    # 0.85 keeps those and cuts the tail.
    max_distance: float = 0.85
    retrieval_enabled: bool = True

    # --- Tracing -----------------------------------------------------------
    # Where structured JSON trace events are written (one line per event).
    # An empty string disables trace logging entirely.
    trace_file: str = ""

    # --- Langfuse ----------------------------------------------------------
    # Observability via Langfuse (cloud or self-hosted). When both
    # LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set, each
    # allotmint_research invocation is sent as a Langfuse trace with distinct
    # spans for retrieval, each tool call, and synthesis.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    tools: tuple[str, ...] = V0_TOOL_ALLOWLIST

    # Providers exposed to clients for per-question selection. The configured
    # default is always included, while hosted alternatives are opt-in so the
    # UI never offers a choice that has no credentials behind it.
    available_llm_providers: tuple[str, ...] = ("ollama",)

    @property
    def model_label(self) -> str:
        """Human-readable model identifier echoed back in the response."""
        return f"{self.llm_provider}:{self.llm_model}"

    @property
    def verifier_model_label(self) -> str:
        """Human-readable identifier for whatever model the verifier actually runs.

        Equal to `model_label` unless a verifier-specific provider/model is
        configured, in which case it reports that instead -- kept as its own
        property (rather than folded into `model_label`) so callers can tell
        worker and verifier apart in tracing/response output without changing
        the meaning of the existing field (#549).
        """
        provider = self.verifier_llm_provider or self.llm_provider
        model = self.verifier_llm_model or self.llm_model
        return f"{provider}:{model}"

    def verifier_settings(self) -> "Settings":
        """Resolved settings for the verifier role.

        Every `verifier_llm_*` field falls back to its worker `llm_*`
        equivalent when unset, so `build_model(settings.verifier_settings())`
        is a drop-in replacement for the old `build_model(settings)` call at
        the verifier call site: identical behavior when no verifier override
        is configured, and an independently-configured model when one is.
        """
        return replace(
            self,
            llm_provider=self.verifier_llm_provider or self.llm_provider,
            llm_model=self.verifier_llm_model or self.llm_model,
            llm_base_url=self.verifier_llm_base_url or self.llm_base_url,
            llm_api_key=self.verifier_llm_api_key or self.llm_api_key,
            llm_temperature=(
                self.llm_temperature
                if self.verifier_llm_temperature is None
                else self.verifier_llm_temperature
            ),
        )


def load_settings() -> Settings:
    """Builds `Settings` from the environment."""
    provider = _env_str("ALLOTMINT_RESEARCH_LLM_PROVIDER", "ollama").lower()
    configured = _env_str("ALLOTMINT_RESEARCH_AVAILABLE_LLM_PROVIDERS", provider)
    available = tuple(dict.fromkeys(p.strip().lower() for p in configured.split(",") if p.strip()))
    if provider not in available:
        available = (provider, *available)
    return Settings(
        llm_provider=provider,
        llm_model=_env_str("ALLOTMINT_RESEARCH_LLM_MODEL", "llama3.2"),
        llm_base_url=_env_str("ALLOTMINT_RESEARCH_LLM_BASE_URL", "http://localhost:11434/v1"),
        llm_api_key=_env_str("ALLOTMINT_RESEARCH_LLM_API_KEY", ""),
        llm_temperature=_env_float("ALLOTMINT_RESEARCH_LLM_TEMPERATURE", 0.0),
        verifier_llm_provider=_env_str("ALLOTMINT_RESEARCH_VERIFIER_LLM_PROVIDER", "").lower(),
        verifier_llm_model=_env_str("ALLOTMINT_RESEARCH_VERIFIER_LLM_MODEL", ""),
        verifier_llm_base_url=_env_str("ALLOTMINT_RESEARCH_VERIFIER_LLM_BASE_URL", ""),
        verifier_llm_api_key=_env_str("ALLOTMINT_RESEARCH_VERIFIER_LLM_API_KEY", ""),
        verifier_llm_temperature=_env_float_optional("ALLOTMINT_RESEARCH_VERIFIER_LLM_TEMPERATURE"),
        mcp_url=_env_str("ALLOTMINT_RESEARCH_MCP_URL", "http://localhost:8080/mcp"),
        mcp_timeout_seconds=_env_float("ALLOTMINT_RESEARCH_MCP_TIMEOUT_SECONDS", 30.0),
        max_tool_calls=_env_int("ALLOTMINT_RESEARCH_MAX_TOOL_CALLS", 6),
        max_conversation_sessions=_env_int("ALLOTMINT_RESEARCH_MAX_CONVERSATION_SESSIONS", 200),
        max_conversation_messages=_env_int("ALLOTMINT_RESEARCH_MAX_CONVERSATION_MESSAGES", 40),
        verifier_timeout_seconds=_env_float(
            "ALLOTMINT_RESEARCH_VERIFIER_TIMEOUT_SECONDS", 10.0
        ),
        db_dsn=_env_str(
            "ALLOTMINT_RESEARCH_DB_DSN",
            "postgresql://allotmint:allotmint@localhost:5432/allotmint_research",
        ),
        embedding_model=_env_str("ALLOTMINT_RESEARCH_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        embedding_dim=_env_int("ALLOTMINT_RESEARCH_EMBEDDING_DIM", 384),
        top_k=_env_int("ALLOTMINT_RESEARCH_TOP_K", 5),
        max_distance=_env_float("ALLOTMINT_RESEARCH_MAX_DISTANCE", 0.85),
        retrieval_enabled=_env_str("ALLOTMINT_RESEARCH_RETRIEVAL_ENABLED", "true").lower()
        not in ("false", "0", "no"),
        trace_file=_env_str("ALLOTMINT_RESEARCH_TRACE_FILE", ""),
        langfuse_public_key=_env_str("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_secret_key=_env_str("LANGFUSE_SECRET_KEY", ""),
        langfuse_host=_env_str("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        available_llm_providers=available,
    )


def select_llm_provider(settings: Settings, provider: str | None) -> Settings:
    """Return request-scoped settings for an advertised provider.

    Design decision (#549): this only ever overrides the worker's
    `llm_provider`/`llm_model`/`llm_base_url`/`llm_api_key` -- it never
    touches `verifier_llm_*`, so a per-request provider choice never
    retargets the verifier. The verifier's job is an independent quality
    check on the worker's output, and a client picking a provider for their
    question is asking about the worker, not asking to also swap out the
    review step checking that worker's answer. If a deployment wants the
    verifier to track per-request choices too, that would need to be a
    separate, explicit opt-in -- not the default here.
    """
    if not provider:
        return settings
    selected = provider.strip().lower()
    if selected not in settings.available_llm_providers:
        raise ValueError(
            f"LLM provider {selected!r} is not available; choose one of: "
            + ", ".join(settings.available_llm_providers)
        )
    if selected == settings.llm_provider:
        return settings

    prefix = f"ALLOTMINT_RESEARCH_{selected.upper().replace('-', '_')}"
    if selected != "ollama" and not os.environ.get(f"{prefix}_API_KEY", "").strip():
        raise ValueError(
            f"LLM provider {selected!r} is advertised but has no "
            f"{prefix}_API_KEY configured; set it before selecting this provider."
        )
    defaults = {
        "ollama": ("llama3.2", "http://localhost:11434/v1"),
        "deepseek": ("deepseek-chat", "https://api.deepseek.com"),
        "openai-compatible": (settings.llm_model, settings.llm_base_url),
    }
    model, base_url = defaults.get(selected, (settings.llm_model, settings.llm_base_url))
    return replace(
        settings,
        llm_provider=selected,
        llm_model=_env_str(f"{prefix}_MODEL", model),
        llm_base_url=_env_str(f"{prefix}_BASE_URL", base_url),
        llm_api_key=_env_str(f"{prefix}_API_KEY", settings.llm_api_key),
    )
