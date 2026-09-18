"""Tests for Task 057 validated reasoning handoff contract.

Task 057 packages the exact Task 055 canonical context and the exact
Task 056 consistency audit into a single inspectable handoff package.
Pure, deterministic, model-neutral. No LLM, no provider, no HTTP, no
database, no external dependencies.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services import reasoning_handoff as mod
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_context_consistency import (
    ReasoningContextConsistencyService,
)
from rop.services.reasoning_handoff import (
    REASONING_HANDOFF_TASK_057,
    ReasoningHandoffContractError,
    ReasoningHandoffService,
)

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def override_get_db() -> Generator[Session, None, None]:
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

RESULT_FIELDS = (
    "available",
    "handoff_consistent",
    "session_id",
    "reasoning_context",
    "context_consistency",
    "handoff_source",
)


def _service() -> ReasoningHandoffService:
    return ReasoningHandoffService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-057-handoff-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full_session(user_input: str) -> str:
    sid = _create_session(user_input)
    r = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert r.status_code == 201
    g = client.post(f"/sessions/{sid}/generate-candidates")
    assert g.status_code == 201
    e = client.post(f"/sessions/{sid}/evaluate-evidence")
    assert e.status_code == 200
    return sid


def _valid_inputs(
    user_input: str = "Task 057 handoff valid",
) -> tuple[dict[str, Any], dict[str, Any]]:
    sid = _seed_full_session(user_input)
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        context = ReasoningContextService().build_for_session(db, session_uuid)
    finally:
        db_gen.close()
    audit = ReasoningContextConsistencyService().build(context=context)
    return context, audit


# ---------------------------------------------------------------------------
# Valid case
# ---------------------------------------------------------------------------


def test_valid_handoff_shape_and_flags() -> None:
    context, audit = _valid_inputs()
    result = _service().build(reasoning_context=context, context_consistency=audit)

    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["handoff_consistent"] is True
    assert result["handoff_source"] == REASONING_HANDOFF_TASK_057


def test_valid_handoff_session_matches_context() -> None:
    context, audit = _valid_inputs()
    result = _service().build(reasoning_context=context, context_consistency=audit)
    assert result["session_id"] == str(context["session_id"])


def test_valid_handoff_preserves_sources() -> None:
    context, audit = _valid_inputs()
    result = _service().build(reasoning_context=context, context_consistency=audit)
    assert result["reasoning_context"]["context_source"] == "REASONING_CONTEXT_TASK_055"
    assert (
        result["context_consistency"]["context_consistency_source"]
        == "REASONING_CONTEXT_CONSISTENCY_TASK_056"
    )


def test_valid_handoff_reasoning_context_preserved_exactly() -> None:
    """The Task 055 context is packaged verbatim -- same top-level
    fields, same nested values. Only UUIDs are serialized to strings
    by the JSON-safe projection."""
    context, audit = _valid_inputs()
    result = _service().build(reasoning_context=context, context_consistency=audit)
    packaged = result["reasoning_context"]
    assert set(packaged.keys()) == set(context.keys())
    assert len(packaged["candidate_state"]) == len(context["candidate_state"])
    assert len(packaged["observations"]) == len(context["observations"])


def test_valid_handoff_context_consistency_preserved_exactly() -> None:
    context, audit = _valid_inputs()
    result = _service().build(reasoning_context=context, context_consistency=audit)
    packaged = result["context_consistency"]
    assert set(packaged.keys()) == set(audit.keys())
    assert packaged["consistency_issues"] == audit["consistency_issues"]
    assert packaged["context_consistent"] == audit["context_consistent"]


# ---------------------------------------------------------------------------
# Required-field enforcement on the handoff inputs
# ---------------------------------------------------------------------------


def test_missing_reasoning_context_rejected() -> None:
    _, audit = _valid_inputs()
    with pytest.raises(ReasoningHandoffContractError) as ei:
        _service().build(reasoning_context=None, context_consistency=audit)
    assert ei.value.invariant == "MISSING_REASONING_CONTEXT"


def test_missing_context_consistency_rejected() -> None:
    context, _ = _valid_inputs()
    with pytest.raises(ReasoningHandoffContractError) as ei:
        _service().build(reasoning_context=context, context_consistency=None)
    assert ei.value.invariant == "MISSING_CONTEXT_CONSISTENCY"


def test_non_mapping_reasoning_context_rejected() -> None:
    _, audit = _valid_inputs()
    with pytest.raises(ReasoningHandoffContractError) as ei:
        _service().build(
            reasoning_context="nope",  # type: ignore[arg-type]
            context_consistency=audit,
        )
    assert ei.value.invariant == "REASONING_CONTEXT_TYPE"


def test_non_mapping_context_consistency_rejected() -> None:
    context, _ = _valid_inputs()
    with pytest.raises(ReasoningHandoffContractError) as ei:
        _service().build(
            reasoning_context=context,
            context_consistency="nope",  # type: ignore[arg-type]
        )
    assert ei.value.invariant == "CONTEXT_CONSISTENCY_TYPE"


# ---------------------------------------------------------------------------
# Task 055 validation is reused, not re-implemented
# ---------------------------------------------------------------------------


def test_malformed_reasoning_context_rejected() -> None:
    context, audit = _valid_inputs()
    broken = dict(context)
    del broken["observations"]
    with pytest.raises(ReasoningHandoffContractError) as ei:
        _service().build(reasoning_context=broken, context_consistency=audit)
    assert ei.value.invariant == "INVALID_REASONING_CONTEXT"


def test_wrong_task055_source_rejected() -> None:
    context, audit = _valid_inputs()
    broken = dict(context)
    broken["context_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffContractError) as ei:
        _service().build(reasoning_context=broken, context_consistency=audit)
    assert ei.value.invariant == "INVALID_REASONING_CONTEXT"


def test_invalid_session_uuid_rejected() -> None:
    context, audit = _valid_inputs()
    broken = dict(context)
    broken["session_id"] = "not-a-uuid"
    with pytest.raises(ReasoningHandoffContractError) as ei:
        _service().build(reasoning_context=broken, context_consistency=audit)
    assert ei.value.invariant == "INVALID_REASONING_CONTEXT"


# ---------------------------------------------------------------------------
# Task 056 validation is reused, not re-implemented
# ---------------------------------------------------------------------------


def test_malformed_context_consistency_rejected() -> None:
    context, audit = _valid_inputs()
    broken = dict(audit)
    del broken["context_consistent"]
    with pytest.raises(ReasoningHandoffContractError) as ei:
        _service().build(reasoning_context=context, context_consistency=broken)
    assert ei.value.invariant == "INVALID_CONTEXT_CONSISTENCY"


def test_wrong_task056_source_rejected() -> None:
    context, audit = _valid_inputs()
    broken = dict(audit)
    broken["context_consistency_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffContractError) as ei:
        _service().build(reasoning_context=context, context_consistency=broken)
    assert ei.value.invariant == "INVALID_CONTEXT_CONSISTENCY"


def test_non_boolean_context_consistent_rejected() -> None:
    context, audit = _valid_inputs()
    broken = dict(audit)
    broken["context_consistent"] = "yes"
    with pytest.raises(ReasoningHandoffContractError) as ei:
        _service().build(reasoning_context=context, context_consistency=broken)
    assert ei.value.invariant == "INVALID_CONTEXT_CONSISTENCY"


# ---------------------------------------------------------------------------
# Audit disagreement is preserved (not raised, not repaired)
# ---------------------------------------------------------------------------


def _context_with_cross_session_candidate() -> dict[str, Any]:
    """Build a context that still passes Task 055's validator but will
    fail Task 056's per-element session check. This is what we need to
    exercise the "audit reports inconsistency" path without breaking
    the upstream Task 055 contract."""
    context, _ = _valid_inputs("Task 057 cross-session")
    fake_candidate = {
        "id": str(uuid4()),
        "session_id": str(uuid4()),  # different from context.session_id
        "name": "cross-session",
        "category": "fake",
        "trigger_reason": "test",
        "initial_score": 1.0,
        "confidence": 0.5,
        "supporting_observations": [],
        "contradicting_observations": [],
        "missing_information": [],
        "status": "pending",
        "created_at": "2026-01-01T00:00:00",
    }
    tampered = dict(context)
    tampered["candidate_state"] = [fake_candidate]
    return tampered


def test_audit_disagreement_does_not_produce_consistent_handoff() -> None:
    """A valid Task 056 audit reporting context inconsistency must not
    yield handoff_consistent == True -- and must not be silently
    repaired into a success."""
    tampered_context = _context_with_cross_session_candidate()

    audit = ReasoningContextConsistencyService().build(context=tampered_context)
    # The audit is structurally valid; it just says "inconsistent".
    assert audit["context_consistent"] is False
    assert "CANDIDATE_SESSION_MISMATCH" in audit["consistency_issues"]

    result = _service().build(
        reasoning_context=tampered_context,
        context_consistency=audit,
    )
    assert result["handoff_consistent"] is False
    assert result["available"] is True
    # And the audit verdict is preserved verbatim.
    assert result["context_consistency"]["context_consistent"] is False


# ---------------------------------------------------------------------------
# Mutation safety
# ---------------------------------------------------------------------------


def test_does_not_mutate_inputs() -> None:
    context, audit = _valid_inputs()
    context_keys_before = list(context.keys())
    audit_keys_before = list(audit.keys())
    context_snap = {
        name: (
            id(context[name]),
            len(context[name]),
            [id(x) for x in context[name]],
        )
        for name in (
            "observations",
            "entities",
            "missing_information",
            "template_context",
            "candidate_state",
        )
    }
    audit_issues_id = id(audit["consistency_issues"])
    audit_issues_len = len(audit["consistency_issues"])

    _service().build(reasoning_context=context, context_consistency=audit)

    assert list(context.keys()) == context_keys_before
    assert list(audit.keys()) == audit_keys_before
    for name, (lst_id, length, item_ids) in context_snap.items():
        assert id(context[name]) == lst_id
        assert len(context[name]) == length
        assert [id(x) for x in context[name]] == item_ids
    assert id(audit["consistency_issues"]) == audit_issues_id
    assert len(audit["consistency_issues"]) == audit_issues_len


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    context, audit = _valid_inputs()
    service = _service()
    first = service.build(reasoning_context=context, context_consistency=audit)
    second = service.build(reasoning_context=context, context_consistency=audit)
    assert first == second


# ---------------------------------------------------------------------------
# Architectural assertions: no LLM / provider / HTTP / DB / model code
# ---------------------------------------------------------------------------

_FORBIDDEN_SUBSTRINGS = (
    "ollama",
    "openai",
    "anthropic",
    "gemini",
    "llm",
    "httpx",
    "requests.",
    "urllib",
    "aiohttp",
    "socket",
    "provider",
    "model_name",
    "api_key",
    "sessionlocal",
    "create_engine",
    ".commit(",
    ".flush(",
    ".add(",
    "fastapi",
    "aprouter",
    "router.",
)


def _module_code_without_docstrings() -> str:
    src = inspect.getsource(mod)
    tree = ast.parse(src)
    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(
                    first.value, ast.Constant
                ):
                    start = first.lineno
                    end = getattr(first, "end_lineno", start) or start
                    for i in range(start, end + 1):
                        docstring_lines.add(i)
    lines = [
        line
        for i, line in enumerate(src.splitlines(), start=1)
        if i not in docstring_lines
    ]
    return "\n".join(lines).lower()


def test_no_llm_or_provider_symbols_in_module_code() -> None:
    code = _module_code_without_docstrings()
    for token in _FORBIDDEN_SUBSTRINGS:
        assert token not in code, token


def test_module_does_not_import_llm_or_http_modules() -> None:
    src = inspect.getsource(mod)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "ollama" not in alias.name.lower()
                assert "openai" not in alias.name.lower()
                assert "httpx" not in alias.name.lower()
                assert "requests" not in alias.name.lower()
        if isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            assert "ollama" not in module
            assert "openai" not in module
            assert "httpx" not in module
            assert "requests" not in module


def test_module_does_not_define_a_route() -> None:
    src = inspect.getsource(mod)
    assert "@router" not in src
    assert "APIRouter" not in src
    assert "FastAPI" not in src


def test_module_does_not_open_database_session() -> None:
    src = inspect.getsource(mod)
    assert "SessionLocal" not in src
    assert "create_engine" not in src
    assert "sessionmaker" not in src


def test_service_has_no_provider_constructor_argument() -> None:
    """The Task 057 service signature must not accept a provider or
    model adapter. It is a handoff contract, not an integration."""
    sig = inspect.signature(ReasoningHandoffService.__init__)
    for name in sig.parameters:
        lowered = name.lower()
        assert "provider" not in lowered
        assert "model" not in lowered
        assert "client" not in lowered
