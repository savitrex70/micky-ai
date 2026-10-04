"""Task 123: ROP model-agnostic deterministic architecture tests.

Proves ROP production code depends on no concrete model runtime: no
Ollama/OpenAI/Gemini/Anthropic imports, clients, keys, servers,
auto-selection, or import-time network. The generic Task 057 boundary
remains intact and fully exercisable through test-only fakes. No real
model, no network.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from rop.config import get_settings

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "rop"

MODEL_TOKENS = ("ollama", "openai", "gemini", "anthropic", "claude")

_CLEAN_ENV = {
    "ROP_APP_NAME": "Reasoning Operating Platform",
    "ROP_ENVIRONMENT": "testing",
    "ROP_LOG_LEVEL": "INFO",
    "ROP_DATABASE_URL": "postgresql+psycopg://rop:rop@localhost:5432/rop",
}


def test_no_concrete_model_imports_in_production() -> None:
    offenders: list[str] = []
    for path in (
        *sorted((SRC_ROOT / "services").glob("*.py")),
        *sorted((SRC_ROOT / "schemas").glob("*.py")),
        SRC_ROOT / "config.py",
        SRC_ROOT / "main.py",
    ):
        source = path.read_text(encoding="utf-8").lower()
        for token in MODEL_TOKENS:
            if token in source:
                offenders.append(f"{path.name}: {token}")
    assert offenders == []


def test_no_network_clients_in_production_services() -> None:
    offenders: list[str] = []
    for path in sorted((SRC_ROOT / "services").glob("*.py")):
        for client in ("httpx", "aiohttp", "urllib3", "requests"):
            if client in path.read_text(encoding="utf-8"):
                offenders.append(f"{path.name}: {client}")
    assert offenders == []


def test_no_concrete_provider_module_exists() -> None:
    assert not (SRC_ROOT / "services" / "ollama_reasoning_provider.py").exists()
    import rop.services as services_pkg

    assert not hasattr(services_pkg, "OllamaReasoningProvider")


def test_settings_have_no_model_runtime_configuration() -> None:
    fields = list(type(get_settings()).model_fields.keys())
    lowered = [name.lower() for name in fields]
    for token in (*MODEL_TOKENS, "provider", "api_key", "apikey", "model"):
        assert not any(token in name for name in lowered), token


def test_fresh_interpreter_imports_nothing_model_specific() -> None:
    env = {**os.environ, **_CLEAN_ENV}
    code = (
        "import sys;"
        "import rop.services, rop.main, rop.config;"
        "mods = [m for m in sys.modules"
        " if 'ollama' in m.lower() or 'openai' in m.lower()"
        " or 'gemini' in m.lower() or 'anthropic' in m.lower()];"
        "assert mods == [], mods;"
        "from rop.services.llm_reasoning import LLMReasoningService;"
        "assert LLMReasoningService().provider is None;"
        "print('AGNOSTIC_CLEAN')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(SRC_ROOT.parent.parent),
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "AGNOSTIC_CLEAN" in proc.stdout


def test_generic_boundary_intact_through_fakes() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    from rop.services.llm_reasoning_audit import LLMReasoningAuditService

    ctx = _valid_context()
    proposal = _service_with(
        FakeProvider(response_text=_valid_model_output(ctx))
    ).build(context=ctx)
    assert proposal["available"] is True
    audit = LLMReasoningAuditService.build(proposal=proposal, context=ctx)
    assert audit["proposal_consistent"] is True
