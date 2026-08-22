"""Tests for provider pluggability.

Issue #13's cost constraint: the default must be free/local, and swapping to a
low-cost hosted provider must be a config change, not a code change.
"""

from __future__ import annotations

import pytest

from app.config import Settings, load_settings
from app.llm import UnsupportedProvider, build_model


def test_the_default_provider_is_local_and_needs_no_api_key(monkeypatch):
    monkeypatch.delenv("ALLOTMINT_RESEARCH_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ALLOTMINT_RESEARCH_LLM_API_KEY", raising=False)

    settings = load_settings()

    assert settings.llm_provider == "ollama"
    assert settings.llm_api_key == ""
    assert settings.llm_base_url == "http://localhost:11434/v1"
    # Building it must not require a credential.
    assert build_model(settings) is not None


def test_switching_to_deepseek_needs_only_environment(monkeypatch):
    monkeypatch.setenv("ALLOTMINT_RESEARCH_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("ALLOTMINT_RESEARCH_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("ALLOTMINT_RESEARCH_LLM_API_KEY", "sk-test")

    settings = load_settings()
    model = build_model(settings)

    assert settings.model_label == "deepseek:deepseek-chat"
    assert model is not None


def test_deepseek_without_a_key_fails_with_the_variable_to_set():
    settings = Settings(llm_provider="deepseek", llm_model="deepseek-chat", llm_api_key="")

    with pytest.raises(UnsupportedProvider, match="ALLOTMINT_RESEARCH_LLM_API_KEY"):
        build_model(settings)


def test_any_openai_compatible_endpoint_is_reachable_by_config():
    settings = Settings(
        llm_provider="openai-compatible",
        llm_model="qwen3:8b",
        llm_base_url="http://vllm.internal:8000/v1",
    )

    assert build_model(settings) is not None


def test_an_unknown_provider_names_the_supported_ones():
    settings = Settings(llm_provider="anthropic-premium")

    with pytest.raises(UnsupportedProvider, match="ollama"):
        build_model(settings)


def test_unparseable_numeric_settings_fall_back_to_the_default(monkeypatch):
    monkeypatch.setenv("ALLOTMINT_RESEARCH_TOP_K", "lots")

    assert load_settings().top_k == 5


def test_build_model_error_names_the_caller_supplied_env_vars():
    """The verifier call site (#549) passes its own env var names so a
    misconfiguration error points at ALLOTMINT_RESEARCH_VERIFIER_LLM_* rather
    than the worker's names, even though the underlying settings object still
    exposes plain `llm_provider`/`llm_api_key`."""
    settings = Settings(llm_provider="deepseek", llm_model="deepseek-chat", llm_api_key="")

    with pytest.raises(UnsupportedProvider, match="ALLOTMINT_RESEARCH_VERIFIER_LLM_API_KEY"):
        build_model(
            settings,
            provider_env_var="ALLOTMINT_RESEARCH_VERIFIER_LLM_PROVIDER",
            api_key_env_var="ALLOTMINT_RESEARCH_VERIFIER_LLM_API_KEY",
        )


def test_build_model_error_defaults_to_worker_env_vars():
    """Without an explicit override, error text is unchanged from before #549."""
    settings = Settings(llm_provider="anthropic-premium")

    with pytest.raises(UnsupportedProvider, match="ALLOTMINT_RESEARCH_LLM_PROVIDER"):
        build_model(settings)


def test_the_tool_allowlist_excludes_the_research_tool_itself():
    settings = load_settings()

    assert "allotmint_research" not in settings.tools
    assert set(settings.tools) == {
        "allotmint_portfolio",
        "allotmint_instrument",
        "allotmint_market",
        "allotmint_health",
    }
