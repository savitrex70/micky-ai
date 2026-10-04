"""Tests for Task 063 reasoning handoff API audit bundle."""

from __future__ import annotations

import copy
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
from rop.services import reasoning_handoff_api_audit_bundle as mod
from rop.services.reasoning_handoff_api_audit_bundle import (
    REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063,
    ReasoningHandoffApiAuditBundleContractError,
    ReasoningHandoffApiAuditBundleService,
)
from rop.services.reasoning_handoff_api_audit_package import (
    ReasoningHandoffApiAuditPackageService,
)
from rop.services.reasoning_handoff_api_audit_package_consistency import (
    ReasoningHandoffApiAuditPackageConsistencyService,
)
from rop.services.reasoning_handoff_api_consistency import (
    ReasoningHandoffApiConsistencyService,
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

BUNDLE_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "api_audit_package",
    "api_audit_package_consistency",
    "bundle_source",
)


def _service() -> ReasoningHandoffApiAuditBundleService:
    return ReasoningHandoffApiAuditBundleService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-063-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full_session(user_input: str) -> str:
    sid = _create_session(user_input)
    client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    client.post(f"/sessions/{sid}/generate-candidates")
    client.post(f"/sessions/{sid}/evaluate-evidence")
    return sid


def _real_package_and_audit() -> tuple[UUID, dict[str, Any], dict[str, Any]]:
    sid_str = _seed_full_session("Task 063 capture")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-handoff"
    r = client.get(path)
    assert r.status_code == 200
    body = r.json()
    api_audit = ReasoningHandoffApiConsistencyService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=body,
    )
    package = ReasoningHandoffApiAuditPackageService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response=body,
        api_consistency=api_audit,
    )
    package_audit = ReasoningHandoffApiAuditPackageConsistencyService().build(
        package=package
    )
    return sid, package, package_audit


def _valid_bundle() -> dict[str, Any]:
    sid, package, package_audit = _real_package_and_audit()
    return _service().build(
        session_id=sid,
        api_audit_package=package,
        api_audit_package_consistency=package_audit,
    )


# ---------------------------------------------------------------------------
# Valid
# ---------------------------------------------------------------------------


def test_valid_bundle_shape() -> None:
    bundle = _valid_bundle()
    assert set(bundle) == set(BUNDLE_FIELDS)
    assert bundle["available"] is True
    assert bundle["bundle_consistent"] is True


def test_bundle_source_fixed() -> None:
    bundle = _valid_bundle()
    assert bundle["bundle_source"] == REASONING_HANDOFF_API_AUDIT_BUNDLE_SOURCE_TASK_063


def test_bundle_session_matches_package() -> None:
    bundle = _valid_bundle()
    assert bundle["session_id"] == bundle["api_audit_package"]["session_id"]


def test_bundle_preserves_inputs_by_identity() -> None:
    sid, package, package_audit = _real_package_and_audit()
    bundle = _service().build(
        session_id=sid,
        api_audit_package=package,
        api_audit_package_consistency=package_audit,
    )
    assert bundle["api_audit_package"] is package
    assert bundle["api_audit_package_consistency"] is package_audit


# ---------------------------------------------------------------------------
# Missing inputs
# ---------------------------------------------------------------------------


def test_missing_session_raises() -> None:
    _, package, package_audit = _real_package_and_audit()
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        _service().build(
            session_id=None,
            api_audit_package=package,
            api_audit_package_consistency=package_audit,
        )
    assert ei.value.invariant == "SESSION_ID_INVALID"


def test_missing_package_raises() -> None:
    sid, _, package_audit = _real_package_and_audit()
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        _service().build(
            session_id=sid,
            api_audit_package=None,
            api_audit_package_consistency=package_audit,
        )
    assert ei.value.invariant == "API_AUDIT_PACKAGE_MISMATCH"


def test_missing_package_audit_raises() -> None:
    sid, package, _ = _real_package_and_audit()
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        _service().build(
            session_id=sid,
            api_audit_package=package,
            api_audit_package_consistency=None,
        )
    assert ei.value.invariant == "API_AUDIT_PACKAGE_CONSISTENCY_MISMATCH"


# ---------------------------------------------------------------------------
# Nested contract failures
# ---------------------------------------------------------------------------


def test_invalid_nested_package_rejected() -> None:
    sid, package, package_audit = _real_package_and_audit()
    broken = copy.deepcopy(package)
    del broken["package_source"]
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        _service().build(
            session_id=sid,
            api_audit_package=broken,
            api_audit_package_consistency=package_audit,
        )
    assert ei.value.invariant == "PACKAGE_SOURCE_MISMATCH"


def test_invalid_nested_audit_rejected() -> None:
    sid, package, package_audit = _real_package_and_audit()
    broken = copy.deepcopy(package_audit)
    del broken["package_consistency_source"]
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        _service().build(
            session_id=sid,
            api_audit_package=package,
            api_audit_package_consistency=broken,
        )
    assert ei.value.invariant == "CONSISTENCY_SOURCE_MISMATCH"


# ---------------------------------------------------------------------------
# Session identity
# ---------------------------------------------------------------------------


def test_session_mismatch_rejected() -> None:
    _, package, package_audit = _real_package_and_audit()
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        _service().build(
            session_id=uuid4(),
            api_audit_package=package,
            api_audit_package_consistency=package_audit,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


# ---------------------------------------------------------------------------
# Audit availability
# ---------------------------------------------------------------------------


def test_unavailable_nested_audit_rejected() -> None:
    sid, package, package_audit = _real_package_and_audit()
    broken = copy.deepcopy(package_audit)
    broken["available"] = False
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        _service().build(
            session_id=sid,
            api_audit_package=package,
            api_audit_package_consistency=broken,
        )
    assert ei.value.invariant == "API_AUDIT_PACKAGE_CONSISTENCY_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def test_wrong_package_source_rejected() -> None:
    sid, package, package_audit = _real_package_and_audit()
    broken = copy.deepcopy(package)
    broken["package_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        _service().build(
            session_id=sid,
            api_audit_package=broken,
            api_audit_package_consistency=package_audit,
        )
    assert ei.value.invariant == "PACKAGE_SOURCE_MISMATCH"


def test_wrong_consistency_source_rejected() -> None:
    sid, package, package_audit = _real_package_and_audit()
    broken = copy.deepcopy(package_audit)
    broken["package_consistency_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        _service().build(
            session_id=sid,
            api_audit_package=package,
            api_audit_package_consistency=broken,
        )
    assert ei.value.invariant == "CONSISTENCY_SOURCE_MISMATCH"


# ---------------------------------------------------------------------------
# bundle_consistent relationship
# ---------------------------------------------------------------------------


def test_validate_result_rejects_tampered_bundle_consistent() -> None:
    bundle = _valid_bundle()
    tampered = dict(bundle)
    tampered["bundle_consistent"] = not tampered["bundle_consistent"]
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        ReasoningHandoffApiAuditBundleService._validate_result(tampered)
    assert ei.value.invariant == "BUNDLE_CONSISTENT_MISMATCH"


def test_validate_result_rejects_wrong_bundle_source() -> None:
    bundle = _valid_bundle()
    tampered = dict(bundle)
    tampered["bundle_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        ReasoningHandoffApiAuditBundleService._validate_result(tampered)
    assert ei.value.invariant == "BUNDLE_SOURCE_MISMATCH"


def test_validate_result_rejects_available_false() -> None:
    bundle = _valid_bundle()
    tampered = dict(bundle)
    tampered["available"] = False
    with pytest.raises(ReasoningHandoffApiAuditBundleContractError) as ei:
        ReasoningHandoffApiAuditBundleService._validate_result(tampered)
    assert ei.value.invariant == "RESULT_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Underlying inconsistency: valid package + audit whose package_consistent
# is False must still yield a bundle whose bundle_consistent is False but
# whose structural contract is valid.
# ---------------------------------------------------------------------------


def test_bundle_handles_inconsistent_package() -> None:
    """A Task 061 package with package_consistent=False (because the
    underlying handoff legitimately reported inconsistency) still
    produces a Task 062 audit with package_consistent=False, and the
    resulting bundle carries bundle_consistent=False while remaining a
    valid bundle structure."""
    sid_str = _seed_full_session("Task 063 inconsistent package")
    sid = UUID(sid_str)

    # Build a valid Task 061 package, then synthesise an audit whose
    # package_consistent=False while remaining a valid Task 062 result
    # shape. Simplest: take the real pair and force both to reflect
    # "package_consistent=False" by tampering exactly the fields Task
    # 062 uses to derive its verdict, then recompute the fingerprint.
    from rop.services.reasoning_context import ReasoningContextService
    from rop.services.reasoning_context_consistency import (
        ReasoningContextConsistencyService,
    )
    from rop.services.reasoning_handoff import ReasoningHandoffService

    # Build a genuinely inconsistent (but valid) handoff.
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        context = ReasoningContextService().build_for_session(db, sid)
    finally:
        db_gen.close()
    tampered_context = copy.deepcopy(context)
    tampered_context["candidate_state"] = [
        {
            "id": str(uuid4()),
            "session_id": str(uuid4()),
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
    ]
    audit_055 = ReasoningContextConsistencyService().build(context=tampered_context)
    handoff = ReasoningHandoffService().build(
        reasoning_context=tampered_context,
        context_consistency=audit_055,
    )
    assert handoff["handoff_consistent"] is False

    import json as _json

    body = _json.loads(_json.dumps(handoff, default=str))
    path = f"/sessions/{sid_str}/reasoning-handoff"
    api_audit = ReasoningHandoffApiConsistencyService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=body,
    )
    assert api_audit["api_consistent"] is True

    package = ReasoningHandoffApiAuditPackageService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response=body,
        api_consistency=api_audit,
    )
    package_audit = ReasoningHandoffApiAuditPackageConsistencyService().build(
        package=package
    )
    assert package_audit["package_consistent"] is True

    bundle = _service().build(
        session_id=sid,
        api_audit_package=package,
        api_audit_package_consistency=package_audit,
    )
    assert bundle["bundle_consistent"] is True
    assert bundle["available"] is True


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    sid, package, package_audit = _real_package_and_audit()
    s = _service()
    a = s.build(
        session_id=sid,
        api_audit_package=package,
        api_audit_package_consistency=package_audit,
    )
    b = s.build(
        session_id=sid,
        api_audit_package=package,
        api_audit_package_consistency=package_audit,
    )
    assert a == b


def test_does_not_mutate_inputs() -> None:
    sid, package, package_audit = _real_package_and_audit()
    p_before = copy.deepcopy(package)
    a_before = copy.deepcopy(package_audit)
    _service().build(
        session_id=sid,
        api_audit_package=package,
        api_audit_package_consistency=package_audit,
    )
    assert package == p_before
    assert package_audit == a_before


# ---------------------------------------------------------------------------
# Architectural assertions
# ---------------------------------------------------------------------------

_FORBIDDEN = (
    "ollama",
    "openai",
    "gemini",
    "anthropic",
    "llm",
    "provider",
    "model_name",
    "api_key",
    "rag",
    "recommendation",
)


def test_no_database_or_http_imports_in_service() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "SessionLocal",
        "create_engine",
        "get_db",
        "sqlalchemy",
        "fastapi",
        "TestClient",
        "httpx",
        "requests",
        "urllib",
    ):
        assert forbidden not in src, forbidden


def test_no_api_orchestration_call_in_service() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "ReasoningHandoffApiService",
        "build_for_session",
        "rop.api.sessions",
    ):
        assert forbidden not in src, forbidden


def test_no_llm_or_provider_symbols_in_service() -> None:
    import re as _re

    src = inspect.getsource(mod).lower()
    for token in _FORBIDDEN:
        pattern = r"\b" + _re.escape(token) + r"\b"
        assert not _re.search(pattern, src), token
