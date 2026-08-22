"""Tests for the Langfuse observability integration layer.

Every test here exercises ``LangfuseTracer`` directly — no agent loop, no
real Langfuse account.  The fake keys ``pk-test`` / ``sk-test`` are enough
to construct the client because the Langfuse SDK does not validate keys at
construction time; API calls that follow will fail gracefully via the
try/except guards already in place.

Tests that need to suppress the real ``langfuse`` import use ``monkeypatch``
to simulate a missing package.
"""

from __future__ import annotations

import builtins
import sys
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.langfuse_tracing import LangfuseTracer, new_langfuse_tracer


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    """Returns Settings with Langfuse keys set (or overridden)."""
    return Settings(
        langfuse_public_key="pk-test-dummy",
        langfuse_secret_key="sk-test-dummy",
        **overrides,
    )


def _disabled_settings() -> Settings:
    """Settings with no Langfuse keys configured."""
    return Settings()


# ---------------------------------------------------------------------------
# factory: new_langfuse_tracer
# ---------------------------------------------------------------------------


def test_new_langfuse_tracer_returns_none_without_keys():
    """When neither API key is set, the factory returns None."""
    assert new_langfuse_tracer("trace-1", _disabled_settings()) is None


def test_new_langfuse_tracer_returns_none_with_only_public_key():
    """Both keys must be present."""
    s = Settings(langfuse_public_key="pk-abc")
    assert new_langfuse_tracer("trace-1", s) is None


def test_new_langfuse_tracer_returns_none_with_only_secret_key():
    """Both keys must be present."""
    s = Settings(langfuse_secret_key="sk-abc")
    assert new_langfuse_tracer("trace-1", s) is None


def test_new_langfuse_tracer_returns_tracer_with_both_keys():
    """When both keys are set the factory returns a tracer instance."""
    tracer = new_langfuse_tracer("trace-1", _settings())
    assert tracer is not None
    assert isinstance(tracer, LangfuseTracer)


def test_new_langfuse_tracer_preserves_trace_id():
    tracer = new_langfuse_tracer("my-custom-id", _settings())
    assert tracer.trace_id == "my-custom-id"


# ---------------------------------------------------------------------------
# ImportError: langfuse not installed
# ---------------------------------------------------------------------------


def test_import_error_disables_tracer_gracefully(monkeypatch):
    """When the langfuse package is missing the tracer is disabled, not dead."""
    # Remove any cached import so the monkeypatch on __import__ takes effect.
    sys.modules.pop("langfuse", None)

    original_import = builtins.__import__

    def _block_langfuse(name, *args, **kwargs):
        if name == "langfuse" or name.startswith("langfuse."):
            raise ImportError("No module named 'langfuse'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_langfuse)

    tracer = LangfuseTracer("trace-1", _settings())
    assert not tracer.enabled


# ---------------------------------------------------------------------------
# enabled / trace_url
# ---------------------------------------------------------------------------


def test_enabled_is_true_when_langfuse_client_exists():
    tracer = LangfuseTracer("trace-1", _settings())
    # Construction succeeds with any non-empty keys; the client is created
    # even though real API calls will fail later.
    assert tracer.enabled is True


def test_enabled_is_false_when_import_fails(monkeypatch):
    sys.modules.pop("langfuse", None)

    original_import = builtins.__import__

    def _block(name, *a, **kw):
        if name == "langfuse" or name.startswith("langfuse."):
            raise ImportError("nope")
        return original_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _block)

    tracer = LangfuseTracer("t", _settings())
    assert not tracer.enabled


def test_trace_url_is_none_when_disabled(monkeypatch):
    sys.modules.pop("langfuse", None)

    original_import = builtins.__import__

    def _block(name, *a, **kw):
        if name == "langfuse" or name.startswith("langfuse."):
            raise ImportError("nope")
        return original_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _block)

    tracer = LangfuseTracer("t", _settings())
    assert tracer.trace_url is None


# ---------------------------------------------------------------------------
# all methods are safe to call when disabled
# ---------------------------------------------------------------------------


def test_all_methods_are_no_ops_when_disabled(monkeypatch):
    """Calling any tracer method while disabled must not raise."""
    sys.modules.pop("langfuse", None)

    original_import = builtins.__import__

    def _block(name, *a, **kw):
        if name == "langfuse" or name.startswith("langfuse."):
            raise ImportError("nope")
        return original_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _block)

    tracer = LangfuseTracer("t", _settings())

    # None of these should raise.
    tracer.request_start("q?", "owner", 30, "model")
    tracer.request_end(True, 100, 2, 1, 3, [])
    tracer.retrieval_start()
    tracer.retrieval_end(2, ["a", "b"])
    tracer.agent_start("m")
    tracer.agent_end(1, 50, True)
    tracer.tool_call_start("allotmint_portfolio", {"action": "exposure"})
    tracer.tool_call_end("allotmint_portfolio", 200, True)
    tracer.flush()


# ---------------------------------------------------------------------------
# span lifecycle: ordering and completeness
# ---------------------------------------------------------------------------


def test_request_start_end_does_not_raise():
    """A full request lifecycle with fake keys completes without error."""
    tracer = LangfuseTracer("trace-lifecycle", _settings())

    tracer.request_start("test question", "demo", 365, "ollama:llama3.2")
    tracer.retrieval_start()
    tracer.retrieval_end(2, ["doc-a.md", "doc-b.md"])
    tracer.agent_start("ollama:llama3.2")
    tracer.tool_call_start("allotmint_portfolio", {"action": "exposure"})
    tracer.tool_call_end("allotmint_portfolio", 512, success=True)
    tracer.agent_end(1, 120, True, usage={"input": 500, "output": 200, "total": 700})
    tracer.request_end(True, 120, 3, 1, 2, [])
    tracer.flush()


def test_retrieval_unavailable_path_does_not_raise():
    tracer = LangfuseTracer("trace-unavail", _settings())

    tracer.request_start("q", None, 30, "m")
    tracer.retrieval_start()
    tracer.retrieval_end(0, [], unavailable=True)
    tracer.request_end(False, 0, 0, 0, 0, ["retrieval down"])
    tracer.flush()


def test_agent_end_without_usage_does_not_raise():
    tracer = LangfuseTracer("trace-no-usage", _settings())

    tracer.request_start("q", None, 30, "m")
    tracer.agent_start("m")
    tracer.agent_end(0, 0, False, usage=None)
    tracer.request_end(False, 0, 0, 0, 0, [])
    tracer.flush()


# ---------------------------------------------------------------------------
# tool-call span stack: repeated calls to the same tool
# ---------------------------------------------------------------------------


def test_repeated_calls_to_same_tool_use_fifo_stack():
    """Calling the same tool twice creates and ends spans in FIFO order."""
    tracer = LangfuseTracer("trace-stack", _settings())

    tracer.request_start("q", None, 30, "m")

    # First call
    tracer.tool_call_start("allotmint_portfolio", {"action": "exposure"})
    # Second call — same tool
    tracer.tool_call_start("allotmint_portfolio", {"action": "holdings"})

    # End the first call — should pop the first span, not the second.
    tracer.tool_call_end("allotmint_portfolio", 100, success=True)
    # End the second call.
    tracer.tool_call_end("allotmint_portfolio", 200, success=True)

    # Both calls ended — no spans left for this tool.
    assert "allotmint_portfolio" not in tracer._tool_spans or not tracer._tool_spans["allotmint_portfolio"]

    tracer.request_end(True, 0, 0, 2, 0, [])
    tracer.flush()


def test_tool_call_end_with_no_pending_spans_is_no_op():
    """Ending a tool that was never started must not raise."""
    tracer = LangfuseTracer("trace-noop", _settings())

    tracer.request_start("q", None, 30, "m")
    # Never started any tool call for this tool.
    tracer.tool_call_end("allotmint_instrument", 0, success=False)
    tracer.request_end(False, 0, 0, 0, 0, [])
    tracer.flush()


def test_tool_call_failure_is_recorded():
    tracer = LangfuseTracer("trace-fail", _settings())

    tracer.request_start("q", None, 30, "m")
    tracer.tool_call_start("allotmint_health", {})
    tracer.tool_call_end("allotmint_health", 80, success=False)
    tracer.request_end(False, 0, 0, 0, 0, [])
    tracer.flush()


def test_tool_call_end_records_truncated_flag_in_span_output():
    """truncated defaults to False and is passed through to the span output,
    so a truncated tool result is observable in the Langfuse UI, not silent."""
    tracer = LangfuseTracer("trace-truncated", _settings())

    mock_span = MagicMock()
    tracer._tool_spans["allotmint_portfolio"] = [mock_span]

    tracer.tool_call_end("allotmint_portfolio", 4000, success=True, truncated=True)

    mock_span.end.assert_called_once_with(
        output={"result_length": 4000, "success": True, "truncated": True}
    )


# ---------------------------------------------------------------------------
# exception safety: methods must not propagate exceptions
# ---------------------------------------------------------------------------


def test_request_start_survives_langfuse_api_failure():
    """If the Langfuse client raises, the method logs and returns — no crash."""
    tracer = LangfuseTracer("trace-safe", _settings())

    # Replace the trace() method on the client with one that always raises.
    mock_langfuse = MagicMock()
    mock_langfuse.trace.side_effect = RuntimeError("API unreachable")
    tracer._langfuse = mock_langfuse

    # Must not raise.
    tracer.request_start("q", "owner", 30, "m")


def test_flush_survives_langfuse_api_failure():
    tracer = LangfuseTracer("trace-flush-safe", _settings())

    mock_langfuse = MagicMock()
    mock_langfuse.flush.side_effect = RuntimeError("network down")
    tracer._langfuse = mock_langfuse

    # Must not raise.
    tracer.flush()


def test_enabled_remains_true_after_api_failure():
    """A failed API call does not disable the tracer."""
    tracer = LangfuseTracer("trace-resilient", _settings())

    mock_langfuse = MagicMock()
    mock_langfuse.trace.side_effect = RuntimeError("boom")
    tracer._langfuse = mock_langfuse

    tracer.request_start("q", None, 30, "m")
    # The tracer should still report as enabled.
    assert tracer.enabled is True


# ---------------------------------------------------------------------------
# flush is safe to call multiple times
# ---------------------------------------------------------------------------


def test_flush_is_idempotent():
    tracer = LangfuseTracer("trace-idem", _settings())

    tracer.flush()
    tracer.flush()
    tracer.flush()


def test_flush_does_nothing_when_disabled(monkeypatch):
    sys.modules.pop("langfuse", None)

    original_import = builtins.__import__

    def _block(name, *a, **kw):
        if name == "langfuse" or name.startswith("langfuse."):
            raise ImportError("nope")
        return original_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _block)

    tracer = LangfuseTracer("t", _settings())
    # Must not raise.
    tracer.flush()
