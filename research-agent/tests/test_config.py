"""Tests for worker/verifier LLM configuration (#549).

The default-passthrough guarantee is the load-bearing behavior here: with no
`ALLOTMINT_RESEARCH_VERIFIER_LLM_*` env vars set, everything must resolve
exactly as it did before this issue -- verifier on the worker's model.
"""

from __future__ import annotations

from app.config import Settings, load_settings, select_llm_provider


def test_verifier_settings_default_to_the_worker_when_unset():
    settings = Settings(
        llm_provider="ollama",
        llm_model="llama3.2",
        llm_base_url="http://localhost:11434/v1",
        llm_api_key="",
        llm_temperature=0.0,
    )

    verifier = settings.verifier_settings()

    assert verifier.llm_provider == "ollama"
    assert verifier.llm_model == "llama3.2"
    assert verifier.llm_base_url == "http://localhost:11434/v1"
    assert verifier.llm_api_key == ""
    assert verifier.llm_temperature == 0.0
    assert settings.verifier_model_label == settings.model_label == "ollama:llama3.2"


def test_verifier_settings_use_the_override_when_configured():
    settings = Settings(
        llm_provider="ollama",
        llm_model="llama3.2",
        llm_temperature=0.0,
        verifier_llm_provider="deepseek",
        verifier_llm_model="deepseek-chat",
        verifier_llm_base_url="https://api.deepseek.com",
        verifier_llm_api_key="sk-verifier",
        verifier_llm_temperature=0.2,
    )

    verifier = settings.verifier_settings()

    assert verifier.llm_provider == "deepseek"
    assert verifier.llm_model == "deepseek-chat"
    assert verifier.llm_base_url == "https://api.deepseek.com"
    assert verifier.llm_api_key == "sk-verifier"
    assert verifier.llm_temperature == 0.2
    # The worker's own settings are untouched.
    assert settings.llm_provider == "ollama"
    assert settings.model_label == "ollama:llama3.2"
    assert settings.verifier_model_label == "deepseek:deepseek-chat"


def test_verifier_settings_override_fields_independently():
    """Setting only the verifier model (not the provider) still falls back per-field."""
    settings = Settings(
        llm_provider="ollama",
        llm_model="llama3.2",
        verifier_llm_model="llama3.1",
    )

    verifier = settings.verifier_settings()

    assert verifier.llm_provider == "ollama"  # fell back
    assert verifier.llm_model == "llama3.1"  # overridden
    assert settings.verifier_model_label == "ollama:llama3.1"


def test_verifier_zero_temperature_override_is_not_treated_as_unset():
    """`None` means unset; `0.0` is a deliberate override and must stick."""
    settings = Settings(llm_temperature=0.7, verifier_llm_temperature=0.0)

    assert settings.verifier_settings().llm_temperature == 0.0


def test_load_settings_leaves_verifier_fields_empty_by_default(monkeypatch):
    for var in (
        "ALLOTMINT_RESEARCH_VERIFIER_LLM_PROVIDER",
        "ALLOTMINT_RESEARCH_VERIFIER_LLM_MODEL",
        "ALLOTMINT_RESEARCH_VERIFIER_LLM_BASE_URL",
        "ALLOTMINT_RESEARCH_VERIFIER_LLM_API_KEY",
        "ALLOTMINT_RESEARCH_VERIFIER_LLM_TEMPERATURE",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = load_settings()

    assert settings.verifier_llm_provider == ""
    assert settings.verifier_llm_model == ""
    assert settings.verifier_llm_base_url == ""
    assert settings.verifier_llm_api_key == ""
    assert settings.verifier_llm_temperature is None
    assert settings.verifier_settings() == settings.verifier_settings()  # stable, no crash
    assert settings.verifier_model_label == settings.model_label


def test_load_settings_reads_verifier_env_vars(monkeypatch):
    monkeypatch.setenv("ALLOTMINT_RESEARCH_VERIFIER_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("ALLOTMINT_RESEARCH_VERIFIER_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("ALLOTMINT_RESEARCH_VERIFIER_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("ALLOTMINT_RESEARCH_VERIFIER_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("ALLOTMINT_RESEARCH_VERIFIER_LLM_TEMPERATURE", "0.3")

    settings = load_settings()

    assert settings.verifier_llm_provider == "deepseek"
    assert settings.verifier_llm_model == "deepseek-chat"
    assert settings.verifier_llm_base_url == "https://api.deepseek.com"
    assert settings.verifier_llm_api_key == "sk-test"
    assert settings.verifier_llm_temperature == 0.3
    assert settings.verifier_model_label == "deepseek:deepseek-chat"


def test_select_llm_provider_never_touches_verifier_settings(monkeypatch):
    """Per-request provider overrides (#554/#559) retarget the worker only (#549)."""
    monkeypatch.setenv("ALLOTMINT_RESEARCH_AVAILABLE_LLM_PROVIDERS", "ollama,deepseek")
    monkeypatch.setenv("ALLOTMINT_RESEARCH_DEEPSEEK_API_KEY", "sk-worker-request")
    base = load_settings()
    base = base.__class__(
        **{
            **base.__dict__,
            "verifier_llm_provider": "openai-compatible",
            "verifier_llm_model": "qwen3:8b",
            "verifier_llm_base_url": "http://vllm.internal:8000/v1",
        }
    )

    selected = select_llm_provider(base, "deepseek")

    assert selected.llm_provider == "deepseek"
    # Verifier config is exactly as configured, unaffected by the worker's
    # per-request override.
    assert selected.verifier_llm_provider == "openai-compatible"
    assert selected.verifier_llm_model == "qwen3:8b"
    assert selected.verifier_settings().llm_provider == "openai-compatible"
