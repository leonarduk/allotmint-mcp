"""Pluggable LLM provider selection.

Issue #13's cost constraint is explicit: the default must run at $0, and no
single provider's SDK may be hardcoded into the agent loop. So the agent loop
(`agent.py`) never imports a provider; it asks for a model here and gets back a
Pydantic AI `Model` object.

All three supported providers speak the OpenAI-compatible chat API, which is
why one `OpenAIChatModel` covers them:

* `ollama` (default) -- a locally-hosted model, no API key, no egress, no cost.
* `deepseek` -- the low-cost hosted option the issue names, for when local
  answer quality is not good enough.
* `openai-compatible` -- an escape hatch for any other OpenAI-shaped endpoint
  (vLLM, LM Studio, OpenRouter, a hosted gateway) without a code change.

A caveat carried over from the #12 spike: not every local model can actually
call tools. `qwen2.5-coder` and vanilla `deepseek-r1:8b` emit tool calls as
plain text, and `gemma3` rejects tool binding outright. The default here is
`llama3.2` because it was one of the two models observed producing real
structured tool calls.
"""

from __future__ import annotations

from typing import Any

from .config import Settings


class UnsupportedProvider(ValueError):
    """Raised for an `ALLOTMINT_RESEARCH_LLM_PROVIDER` value we don't know."""


def build_model(
    settings: Settings,
    *,
    provider_env_var: str = "ALLOTMINT_RESEARCH_LLM_PROVIDER",
    api_key_env_var: str = "ALLOTMINT_RESEARCH_LLM_API_KEY",
) -> Any:
    """Returns a Pydantic AI model for the configured provider.

    `provider_env_var`/`api_key_env_var` only affect error message text, not
    behavior -- they let a caller building a model for a different role (the
    #549 verifier, via `settings.verifier_settings()`) name the env var a
    user should actually go set, instead of always pointing at the worker's
    `ALLOTMINT_RESEARCH_LLM_*` names even when the misconfiguration is in the
    verifier's own (or its worker-fallback) settings.
    """
    from pydantic_ai.models.openai import OpenAIChatModel

    provider = settings.llm_provider

    if provider == "ollama":
        from pydantic_ai.providers.ollama import OllamaProvider

        return OpenAIChatModel(
            settings.llm_model,
            provider=OllamaProvider(base_url=settings.llm_base_url),
        )

    if provider == "deepseek":
        from pydantic_ai.providers.deepseek import DeepSeekProvider

        if not settings.llm_api_key:
            raise UnsupportedProvider(
                f"{api_key_env_var} is required when {provider_env_var}=deepseek"
            )
        return OpenAIChatModel(
            settings.llm_model,
            provider=DeepSeekProvider(api_key=settings.llm_api_key),
        )

    if provider in ("openai-compatible", "openai_compatible", "openai"):
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIChatModel(
            settings.llm_model,
            provider=OpenAIProvider(
                base_url=settings.llm_base_url,
                # Many OpenAI-compatible servers ignore the key but require the
                # header to be present at all; a placeholder keeps those working
                # without inventing a credential requirement.
                api_key=settings.llm_api_key or "not-needed",
            ),
        )

    raise UnsupportedProvider(
        f"unknown {provider_env_var} {provider!r}; "
        "expected 'ollama', 'deepseek', or 'openai-compatible'"
    )
