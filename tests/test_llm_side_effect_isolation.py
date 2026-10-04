"""Task 121: LLM API, persistence, and side-effect isolation gate.

Proves the LLM reasoning layer is a read-only reasoning proposal
boundary: no database writes, no state mutation, no config mutation, no
network, no new HTTP endpoints, no persisted raw text or prompts, and no
model output leaking into deterministic state. No real provider.
"""

from __future__ import annotations

import json
import re
import socket
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text as sql_text

from rop.config import get_settings
from rop.database import Base
from rop.main import app
from rop.services.llm_reasoning import LLMReasoningContractError

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "rop"
LLM_SERVICE_FILES = sorted((SRC_ROOT / "services").glob("llm_*.py"))
LLM_SCHEMA_FILES = sorted((SRC_ROOT / "schemas").glob("llm_*.py"))

# Task 123 realignment: no LLM boundary file is exempt from the
# network-import ban. No concrete model provider ships with ROP, so no
# llm_* module may import any network client at all.

_BANNED_SOURCE_PATTERNS = (
    r"\bimport\s+socket\b",
    r"\bfrom\s+socket\b",
    r"\bimport\s+urllib\b",
    r"\bfrom\s+urllib\b",
    r"\bimport\s+requests\b",
    r"\bfrom\s+requests\b",
    r"\bimport\s+httpx\b",
    r"\bfrom\s+httpx\b",
    r"session\.add\b",
    r"session\.delete\b",
    r"\.commit\(",
    r"\.rollback\(",
    r"\bsessionmaker\b",
    r"\bget_db\b",
    r"from\s+rop\.database\s+import",
    r"Base\.metadata\.create_all",
    r"\bopen\(",
    r"APIRouter",
    r"include_router",
    r"@app\.(get|post|put|patch|delete)",
    r"@router\.(get|post|put|patch|delete)",
)
_COMPILED_BANNED = tuple(re.compile(p) for p in _BANNED_SOURCE_PATTERNS)


def _db_counts(db: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        counts[table.name] = db.execute(
            sql_text(f'SELECT COUNT(*) FROM "{table.name}"')
        ).scalar_one()
    return counts


def _live_context_and_proposal() -> tuple[Any, Any, Any]:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    service = _service_with(FakeProvider(response_text=_valid_model_output(ctx)))
    return ctx, service, FakeProvider


def test_successful_reasoning_writes_no_db_state() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider as _Fake,
    )
    from tests.test_llm_live_boundary_enforcement import (
        TestingSessionLocal,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    service = _service_with(_Fake(response_text=_valid_model_output(ctx)))
    with TestingSessionLocal() as db:
        before = _db_counts(db)
    result = service.build(context=ctx)
    assert result["proposal_consistent"] is True
    with TestingSessionLocal() as db:
        assert _db_counts(db) == before


def test_failed_reasoning_writes_no_db_state() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider as _Fake,
    )
    from tests.test_llm_live_boundary_enforcement import (
        TestingSessionLocal,
        _service_with,
        _valid_context,
    )

    ctx = _valid_context()
    service = _service_with(_Fake(response_text="not-json{{{"))
    with TestingSessionLocal() as db:
        before = _db_counts(db)
    with pytest.raises(LLMReasoningContractError):
        service.build(context=ctx)
    with TestingSessionLocal() as db:
        assert _db_counts(db) == before


def test_reasoning_mutates_no_config() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider as _Fake,
    )
    from tests.test_llm_live_boundary_enforcement import (
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    before = get_settings().model_dump()
    _service_with(_Fake(response_text=_valid_model_output(ctx))).build(context=ctx)
    assert get_settings().model_dump() == before


def test_reasoning_opens_no_sockets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider as _Fake,
    )
    from tests.test_llm_live_boundary_enforcement import (
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("socket opened during reasoning")

    ctx = _valid_context()
    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(socket.socket, "connect", _boom)

    result = _service_with(_Fake(response_text=_valid_model_output(ctx))).build(
        context=ctx
    )
    assert result["proposal_consistent"] is True


def test_no_llm_http_endpoints_exposed() -> None:
    paths = [getattr(route, "path", "") for route in app.routes]
    assert not any("llm" in path.lower() for path in paths if path)


def test_llm_modules_have_no_hidden_persistence_or_network_paths() -> None:
    offenders: list[str] = []
    for path in (*LLM_SERVICE_FILES, *LLM_SCHEMA_FILES):
        source = path.read_text(encoding="utf-8")
        for pattern in _COMPILED_BANNED:
            if pattern.search(source):
                offenders.append(f"{path.name}: {pattern.pattern}")
    assert offenders == []


def test_no_raw_provider_text_or_prompt_persisted() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider as _Fake,
    )
    from tests.test_llm_live_boundary_enforcement import (
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    raw_text = _valid_model_output(ctx)
    result = _service_with(_Fake(response_text=raw_text)).build(context=ctx)

    assert set(result.keys()) == {
        "session_id",
        "context_fingerprint",
        "provider",
        "model",
        "candidate_assessments",
        "available",
        "proposal_consistent",
        "llm_reasoning_source",
    }
    assert "text" not in result
    assert "raw_text" not in result
    assert "prompt" not in result
    # The raw JSON blob itself never appears verbatim in the result.
    assert raw_text not in json.dumps(result)
