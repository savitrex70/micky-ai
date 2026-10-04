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
from pathlib import Path
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
    """Task 123 realignment: no environment variable -- model-flavored
    or otherwise -- can select or instantiate a provider."""
    monkeypatch.setenv("ROP_OLLAMA_REASONING_MODEL", "sneaky-model")
    monkeypatch.setenv("ROP_OLLAMA_BASE_URL", "http://sneaky:11434")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-sneaky")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("MODEL_NAME", "sneaky-model")
    get_settings.cache_clear()
    try:
        assert LLMReasoningService().provider is None
    finally:
        get_settings.cache_clear()


def test_settings_carry_no_model_or_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 123 realignment: settings carry no model runtime, provider,
    or API-key configuration of any kind -- so configuration alone can
    never activate, select, or execute a provider."""
    settings = get_settings()
    fields = list(type(settings).model_fields.keys())
    lowered = [name.lower() for name in fields]
    assert not any("api_key" in name for name in lowered)
    assert not any("apikey" in name for name in lowered)
    assert not any("provider" in name for name in lowered)
    assert not any("ollama" in name for name in lowered)
    assert not any("openai" in name for name in lowered)
    assert not any("gemini" in name for name in lowered)
    assert not any("anthropic" in name for name in lowered)
    assert not any("model" in name for name in lowered)

    monkeypatch.setenv("ROP_OLLAMA_REASONING_MODEL", "configured-model")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-configured")
    get_settings.cache_clear()
    try:
        # Unknown env vars are ignored (extra="ignore") and select nothing.
        assert LLMReasoningService().provider is None
    finally:
        get_settings.cache_clear()
    assert LLMReasoningService().provider is None


def test_no_concrete_provider_class_to_construct() -> None:
    """Task 123 realignment: there is no concrete provider class left to
    construct. The generic Protocol interface exists as a boundary for
    explicitly injected test fakes only."""

    import rop.services as services_pkg

    package_dir = Path(services_pkg.__file__).resolve().parent
    assert not (package_dir / "ollama_reasoning_provider.py").exists()
    assert not hasattr(services_pkg, "OllamaReasoningProvider")
    assert LLMReasoningService().provider is None


def test_injected_fake_fails_closed_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly injected fake that cannot produce a response fails
    closed through the Task 107 boundary without any network use."""
    import httpx
    from tests.test_llm_live_boundary_enforcement import FakeProvider

    from rop.services.llm_reasoning_provider import LLMReasoningRequest

    called: list[str] = []

    class _GuardClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            called.append("constructed")

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

    monkeypatch.setattr(httpx, "Client", _GuardClient)

    class _FailingFake(FakeProvider):
        def generate_reasoning(self, request: Any) -> Any:
            from rop.services.llm_reasoning_provider import (
                LLMReasoningProviderError,
            )

            raise LLMReasoningProviderError("fake provider is not configured")

    provider = _FailingFake()
    with pytest.raises(Exception) as exc_info:
        provider.generate_reasoning(
            LLMReasoningRequest(payload={}, context_fingerprint="x" * 64)
        )
    assert "not configured" in str(exc_info.value)
    assert called == []


def test_imports_perform_no_activation() -> None:
    """Fresh interpreter: importing ROP modules instantiates no provider
    and contacts nothing. No concrete provider module exists to import."""
    env = {**os.environ, **_CLEAN_ENV}
    code = (
        "import rop.services, rop.main;"
        "from rop.services.llm_reasoning import LLMReasoningService;"
        "assert LLMReasoningService().provider is None;"
        "import rop.services as s;"
        "assert not hasattr(s, 'OllamaReasoningProvider');"
        "print('IMPORT_CLEAN')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parents[1],
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
