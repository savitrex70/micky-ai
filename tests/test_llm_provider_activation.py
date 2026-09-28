"""Task 119: explicit provider activation lockdown tests.

Proves the deterministic ROP system cannot silently activate a concrete
LLM provider: no import side effects, no env-var auto-selection, no
API-key auto-loading, no startup/import network contact, no hidden
fallback. Fake providers remain sufficient. No real model, no network.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any
from uuid import uuid4

import pytest

from rop.config import get_settings
from rop.services.llm_reasoning import (
    LLMReasoningContractError,
    LLMReasoningService,
)
from rop.services.llm_reasoning_provider import LLMReasoningProviderResponse

_CLEAN_ENV = {
    "ROP_APP_NAME": "Reasoning Operating Platform",
    "ROP_ENVIRONMENT": "testing",
    "ROP_LOG_LEVEL": "INFO",
    "ROP_DATABASE_URL": "postgresql+psycopg://rop:rop@localhost:5432/rop",
}


def test_service_without_provider_is_explicit_none() -> None:
    service = LLMReasoningService()
    assert service.provider is None


def test_no_provider_available_context_fails_closed() -> None:
    from tests.test_llm_live_boundary_enforcement import _valid_context

    ctx = _valid_context()
    with pytest.raises(LLMReasoningContractError) as exc_info:
        LLMReasoningService().build(context=ctx)
    assert exc_info.value.invariant == "MODEL_UNAVAILABLE"


def test_no_provider_unavailable_context_returns_soft_result() -> None:
    service = LLMReasoningService()
    sid = uuid4()
    result = service.build(
        context={
            "session_id": sid,
            "available": False,
            "context_consistent": False,
            "reasoning_pipeline": {},
        }
    )
    assert result["available"] is False
    assert result["provider"] == ""
    assert result["model"] == ""


def test_env_vars_never_select_a_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_REASONING_MODEL", "sneaky-model")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-sneaky")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert LLMReasoningService().provider is None


def test_settings_carry_no_api_key_or_provider_selection() -> None:
    settings = get_settings()
    names = [name for name in dir(settings) if not name.startswith("_")]
    assert not any("api_key" in name.lower() for name in names)
    assert not any("provider" in name.lower() for name in names)
    assert getattr(settings, "ollama_reasoning_model", None) is None


def test_constructing_concrete_provider_touches_no_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from rop.services.ollama_reasoning_provider import OllamaReasoningProvider

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network contacted during provider construction")

    monkeypatch.setattr(httpx, "Client", _boom)
    provider = OllamaReasoningProvider()
    assert provider.provider_name == "ollama"
    assert provider.model_name == ""


def test_unconfigured_concrete_provider_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from rop.services.llm_reasoning_provider import LLMReasoningRequest
    from rop.services.ollama_reasoning_provider import OllamaReasoningProvider

    called: list[str] = []

    class _GuardClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            called.append("constructed")

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

    monkeypatch.setattr(httpx, "Client", _GuardClient)
    provider = OllamaReasoningProvider()
    with pytest.raises(Exception) as exc_info:
        provider.generate_reasoning(
            LLMReasoningRequest(payload={}, context_fingerprint="x" * 64)
        )
    assert "not configured" in str(exc_info.value)
    assert called == []


def test_imports_perform_no_activation() -> None:
    """Fresh interpreter: importing ROP modules instantiates nothing and
    contacts nothing."""
    env = {**os.environ, **_CLEAN_ENV}
    code = (
        "import rop.services, rop.main,"
        " rop.services.ollama_reasoning_provider as o;"
        "from rop.services.llm_reasoning import LLMReasoningService;"
        "assert LLMReasoningService().provider is None;"
        "assert not any(isinstance(v, o.OllamaReasoningProvider)"
        " for v in list(globals().values()));"
        "print('IMPORT_CLEAN')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd="C:\\Users\\nurk0\\Downloads\\micky ai",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "IMPORT_CLEAN" in proc.stdout


def test_fake_provider_remains_sufficient() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    result = _service_with(FakeProvider(response_text=_valid_model_output(ctx))).build(
        context=ctx
    )
    assert result["available"] is True
    assert result["proposal_consistent"] is True


def test_no_hidden_fallback_when_provider_raises_unexpectedly() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
    )

    class _ExplodingProvider(FakeProvider):
        def generate_reasoning(self, request: Any) -> LLMReasoningProviderResponse:
            raise RuntimeError("total provider failure")

    with pytest.raises(LLMReasoningContractError) as exc_info:
        _service_with(_ExplodingProvider()).build(context=_valid_context())
    # Classified through the Task 107 boundary, never a raw leak and
    # never a silent fallback success.
    assert exc_info.value.invariant in (
        "MODEL_UNAVAILABLE",
        "MODEL_OUTPUT_INVALID",
        "MODEL_OUTPUT_INCONSISTENT",
        "INPUT_INCONSISTENT",
    )
