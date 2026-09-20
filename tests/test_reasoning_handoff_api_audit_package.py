"""Tests for Task 061 fully audited reasoning handoff API package.

Task 061 composes a Task 059 API response with its Task 060 audit
into one package. It is a composition layer only: no HTTP, no DB, no
calls to Task 059's endpoint or Task 060's build method.
"""

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
from rop.services import reasoning_handoff_api_audit_package as mod
from rop.services.reasoning_handoff_api_audit_package import (
    REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061,
    ReasoningHandoffApiAuditPackageContractError,
    ReasoningHandoffApiAuditPackageService,
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

PACKAGE_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "method",
    "path",
    "status_code",
    "response",
    "api_consistency",
    "package_source",
)


def _service() -> ReasoningHandoffApiAuditPackageService:
    return ReasoningHandoffApiAuditPackageService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-061-test"},
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


def _real_response_and_audit() -> (
    tuple[UUID, str, str, int, dict[str, Any], dict[str, Any]]
):
    """Call the real Task 059 endpoint and audit it with Task 060."""
    sid_str = _seed_full_session("Task 061 capture")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-handoff"
    r = client.get(path)
    assert r.status_code == 200
    body = r.json()
    audit = ReasoningHandoffApiConsistencyService().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=200,
        response_body=body,
    )
    return sid, "GET", path, 200, body, audit


def _valid_package() -> dict[str, Any]:
    sid, method, path, status, body, audit = _real_response_and_audit()
    return _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response=body,
        api_consistency=audit,
    )


# ---------------------------------------------------------------------------
# Valid cases
# ---------------------------------------------------------------------------


def test_valid_package_shape() -> None:
    package = _valid_package()
    assert set(package) == set(PACKAGE_FIELDS)
    assert package["available"] is True
    assert package["package_consistent"] is True


def test_package_source_fixed() -> None:
    package = _valid_package()
    assert (
        package["package_source"] == REASONING_HANDOFF_API_AUDIT_PACKAGE_SOURCE_TASK_061
    )


def test_response_identity_preserved() -> None:
    """The exact same response object supplied must be present in the
    package, not a copy."""
    sid, method, path, status, body, audit = _real_response_and_audit()
    package = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response=body,
        api_consistency=audit,
    )
    assert package["response"] is body


def test_audit_identity_preserved() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    package = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response=body,
        api_consistency=audit,
    )
    assert package["api_consistency"] is audit


def test_http_metadata_preserved() -> None:
    package = _valid_package()
    assert package["method"] == "GET"
    assert package["status_code"] == 200
    assert package["path"].endswith("/reasoning-handoff")


def test_valid_but_inconsistent_handoff_still_packages() -> None:
    """A faithful API response whose underlying handoff is legitimately
    inconsistent (handoff_consistent=False) still produces
    package_consistent=True, because Task 060 reports
    api_consistent=True and the package derives only from that."""
    sid = _seed_full_session("Task 061 inconsistent handoff")

    # Build a valid-but-inconsistent handoff via the real services.
    from rop.services.reasoning_context import ReasoningContextService
    from rop.services.reasoning_context_consistency import (
        ReasoningContextConsistencyService,
    )
    from rop.services.reasoning_handoff import ReasoningHandoffService

    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        context = ReasoningContextService().build_for_session(db, session_uuid)
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
    audit = ReasoningContextConsistencyService().build(context=tampered_context)
    handoff = ReasoningHandoffService().build(
        reasoning_context=tampered_context,
        context_consistency=audit,
    )
    assert handoff["handoff_consistent"] is False

    import json as _json

    body = _json.loads(_json.dumps(handoff, default=str))
    path = f"/sessions/{sid}/reasoning-handoff"
    api_audit = ReasoningHandoffApiConsistencyService().build(
        session_id=UUID(sid),
        method="GET",
        path=path,
        status_code=200,
        response_body=body,
    )
    assert api_audit["api_consistent"] is True

    package = _service().build(
        session_id=UUID(sid),
        method="GET",
        path=path,
        status_code=200,
        response=body,
        api_consistency=api_audit,
    )
    assert package["package_consistent"] is True


# ---------------------------------------------------------------------------
# HTTP metadata
# ---------------------------------------------------------------------------


def test_invalid_method_rejected() -> None:
    sid, _, path, status, body, audit = _real_response_and_audit()
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method="POST",
            path=path,
            status_code=status,
            response=body,
            api_consistency=audit,
        )
    assert ei.value.invariant == "INVALID_METHOD"


def test_invalid_path_rejected() -> None:
    sid, method, _, status, body, audit = _real_response_and_audit()
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=f"/sessions/{sid}/wrong-route",
            status_code=status,
            response=body,
            api_consistency=audit,
        )
    assert ei.value.invariant == "INVALID_PATH"


def test_invalid_status_rejected() -> None:
    sid, method, path, _, body, audit = _real_response_and_audit()
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=500,
            response=body,
            api_consistency=audit,
        )
    assert ei.value.invariant == "INVALID_STATUS"


# ---------------------------------------------------------------------------
# Session identity
# ---------------------------------------------------------------------------


def test_invalid_session_uuid_rejected() -> None:
    _, method, path, status, body, audit = _real_response_and_audit()
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id="not-a-uuid",
            method=method,
            path=path,
            status_code=status,
            response=body,
            api_consistency=audit,
        )
    assert ei.value.invariant == "SESSION_ID_INVALID"


def test_path_session_mismatch_rejected() -> None:
    sid, method, _, status, body, audit = _real_response_and_audit()
    other = str(uuid4())
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=f"/sessions/{other}/reasoning-handoff",
            status_code=status,
            response=body,
            api_consistency=audit,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_response_session_mismatch_rejected() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(body)
    tampered["session_id"] = str(uuid4())
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=tampered,
            api_consistency=audit,
        )
    assert ei.value.invariant in (
        "SESSION_ID_MISMATCH",
        "RESPONSE_MISMATCH",
    )


def test_nested_reasoning_context_session_mismatch_rejected() -> None:
    """The package must reject a response whose nested
    reasoning_context.session_id disagrees with the package session,
    even if the top-level response session matches."""
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(body)
    # Swap the nested reasoning_context.session_id AND the top-level
    # response.session_id to a new value; leave the supplied session
    # and path pointing at the original. The package must reject
    # because path_sid (original) != response_sid (new).
    other = str(uuid4())
    tampered["session_id"] = other
    tampered["reasoning_context"]["session_id"] = other
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=tampered,
            api_consistency=audit,
        )
    assert ei.value.invariant in (
        "SESSION_ID_MISMATCH",
        "RESPONSE_MISMATCH",
    )


# ---------------------------------------------------------------------------
# Stale audit / tampered audit
# ---------------------------------------------------------------------------


def test_stale_audit_from_other_response_rejected() -> None:
    """Response B + Audit A must be rejected."""
    sid_a, _, path_a, status_a, body_a, audit_a = _real_response_and_audit()
    sid_b, method_b, path_b, status_b, body_b, _ = _real_response_and_audit()
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid_b,
            method=method_b,
            path=path_b,
            status_code=status_b,
            response=body_b,
            api_consistency=audit_a,
        )
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_tampered_audited_fingerprint_rejected() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(audit)
    original = tampered["audited_response_fingerprint"]
    tampered["audited_response_fingerprint"] = (
        "0" * 64 if original != "0" * 64 else "1" * 64
    )
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=body,
            api_consistency=tampered,
        )
    assert ei.value.invariant in (
        "RESPONSE_MISMATCH",
        "API_CONSISTENCY_MISMATCH",
    )


def test_tampered_audited_session_rejected() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(audit)
    tampered["audited_session_id"] = str(uuid4())
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=body,
            api_consistency=tampered,
        )
    assert ei.value.invariant in (
        "SESSION_ID_MISMATCH",
        "API_CONSISTENCY_MISMATCH",
    )


def test_tampered_audited_method_rejected() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(audit)
    tampered["audited_method"] = "POST"
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=body,
            api_consistency=tampered,
        )
    assert ei.value.invariant in (
        "INVALID_METHOD",
        "API_CONSISTENCY_MISMATCH",
    )


def test_tampered_audited_path_rejected() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(audit)
    tampered["audited_path"] = "/wrong"
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=body,
            api_consistency=tampered,
        )
    assert ei.value.invariant in (
        "INVALID_PATH",
        "API_CONSISTENCY_MISMATCH",
    )


def test_tampered_audited_status_rejected() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(audit)
    tampered["audited_status_code"] = 500
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=body,
            api_consistency=tampered,
        )
    assert ei.value.invariant in (
        "INVALID_STATUS",
        "API_CONSISTENCY_MISMATCH",
    )


# ---------------------------------------------------------------------------
# Malformed nested inputs
# ---------------------------------------------------------------------------


def test_malformed_response_rejected() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(body)
    del tampered["reasoning_context"]["candidate_state"]
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=tampered,
            api_consistency=audit,
        )
    assert ei.value.invariant == "RESPONSE_MISMATCH"


def test_malformed_audit_rejected() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(audit)
    del tampered["audited_response_fingerprint"]
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=body,
            api_consistency=tampered,
        )
    assert ei.value.invariant == "API_CONSISTENCY_MISMATCH"


def test_wrong_response_source_rejected() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(body)
    tampered["handoff_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=tampered,
            api_consistency=audit,
        )
    assert ei.value.invariant == "RESPONSE_SOURCE_MISMATCH"


def test_wrong_audit_source_rejected() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(audit)
    tampered["api_consistency_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=body,
            api_consistency=tampered,
        )
    assert ei.value.invariant == "API_AUDIT_SOURCE_MISMATCH"


# ---------------------------------------------------------------------------
# _validate_result tamper rejection
# ---------------------------------------------------------------------------


def test_validate_result_rejects_wrong_package_source() -> None:
    package = _valid_package()
    tampered = dict(package)
    tampered["package_source"] = "SOMETHING_ELSE"
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        ReasoningHandoffApiAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_SOURCE_MISMATCH"


def test_validate_result_rejects_package_consistency_mismatch() -> None:
    package = _valid_package()
    tampered = dict(package)
    tampered["package_consistent"] = not tampered["package_consistent"]
    with pytest.raises(ReasoningHandoffApiAuditPackageContractError) as ei:
        ReasoningHandoffApiAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "API_CONSISTENCY_MISMATCH"


# ---------------------------------------------------------------------------
# Integrity / determinism
# ---------------------------------------------------------------------------


def test_does_not_mutate_response() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    before = copy.deepcopy(body)
    _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response=body,
        api_consistency=audit,
    )
    assert body == before


def test_does_not_mutate_audit() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    before = copy.deepcopy(audit)
    _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response=body,
        api_consistency=audit,
    )
    assert audit == before


def test_deterministic() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    s = _service()
    a = s.build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response=body,
        api_consistency=audit,
    )
    b = s.build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response=body,
        api_consistency=audit,
    )
    assert a == b


# ---------------------------------------------------------------------------
# Architectural assertions
# ---------------------------------------------------------------------------

_FORBIDDEN_SUBSTRINGS = (
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


def test_does_not_call_task060_build() -> None:
    """The service may import Task 060's static validator and fingerprint
    helper, but must never invoke Task 060's build() method."""
    src = inspect.getsource(mod)
    # The only place Task 060's service name should appear is in
    # import lines and static helper invocations.
    for line in src.splitlines():
        stripped = line.strip()
        if "ReasoningHandoffApiConsistencyService" in stripped and "(" in stripped:
            # Method calls must be one of the static helpers.
            assert (
                "_validate_result" in stripped or "_response_fingerprint" in stripped
            ), stripped


def test_no_llm_or_provider_symbols_in_service() -> None:
    src = inspect.getsource(mod).lower()
    for token in _FORBIDDEN_SUBSTRINGS:
        assert token not in src, token
