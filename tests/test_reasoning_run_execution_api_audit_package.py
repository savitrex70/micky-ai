"""Tests for Task 051 fully audited API response package.

Task 051 composes a Task 049 API response with its Task 050 audit into
one package. It is a composition layer only: no HTTP, no DB, no calls
to Task 048/049/050 build_for_session.
"""

from __future__ import annotations

import copy
import inspect
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services import reasoning_run_execution_api_audit_package as mod
from rop.services.reasoning_run_execution_api_audit_package import (
    REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_SOURCE_TASK_051,
    ReasoningRunExecutionApiAuditPackageContractError,
    ReasoningRunExecutionApiAuditPackageService,
)
from rop.services.reasoning_run_execution_audit_package_api_consistency import (
    ReasoningRunExecutionAuditPackageApiConsistencyService,
)

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)
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


def _service() -> ReasoningRunExecutionApiAuditPackageService:
    return ReasoningRunExecutionApiAuditPackageService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-051-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _real_response_and_audit(
) -> tuple[UUID, str, str, int, dict[str, Any], dict[str, Any]]:
    """Call the real endpoint and audit it with Task 050."""
    sid_str = _create_session("Patient reports chest pain")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-run/execute-fully-audited"
    r = client.post(path)
    assert r.status_code == 200
    body = r.json()
    audit = ReasoningRunExecutionAuditPackageApiConsistencyService().build(
        session_id=sid,
        method="POST",
        path=path,
        status_code=200,
        response_body=body,
    )
    return sid, "POST", path, 200, body, audit


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
        package["package_source"]
        == REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_SOURCE_TASK_051
    )


def test_nested_response_present() -> None:
    package = _valid_package()
    r = package["response"]
    assert r["package_source"] == "REASONING_RUN_EXECUTION_AUDIT_PACKAGE_TASK_048"
    assert r["available"] is True


def test_nested_audit_present() -> None:
    package = _valid_package()
    a = package["api_consistency"]
    assert a["available"] is True
    assert (
        a["api_consistency_source"]
        == "REASONING_RUN_EXECUTION_AUDIT_PACKAGE_API_CONSISTENCY_TASK_050"
    )


def test_package_consistent_matches_task050() -> None:
    package = _valid_package()
    assert package["package_consistent"] == (
        package["api_consistency"]["api_consistent"]
    )


def test_http_metadata_preserved() -> None:
    package = _valid_package()
    assert package["method"] == "POST"
    assert package["status_code"] == 200
    assert package["path"].endswith("/reasoning-run/execute-fully-audited")


def test_valid_failed_execution_path() -> None:
    """A legitimate FAILED Task 044 execution must still produce a
    valid Task 051 package."""
    from rop.services.observation_extraction import ObservationExtractionService

    original = ObservationExtractionService.extract_and_store

    def boom(self, db, session_id, text):
        raise RuntimeError("forced")

    ObservationExtractionService.extract_and_store = boom
    try:
        sid_str = _create_session("Patient reports chest pain")
        path = f"/sessions/{sid_str}/reasoning-run/execute-fully-audited"
        r = client.post(path)
        assert r.status_code == 200
        body = r.json()
    finally:
        ObservationExtractionService.extract_and_store = original

    assert body["execution_bundle"]["execution"]["outcome"] == "FAILED"
    sid = UUID(sid_str)
    audit = ReasoningRunExecutionAuditPackageApiConsistencyService().build(
        session_id=sid,
        method="POST",
        path=path,
        status_code=200,
        response_body=body,
    )
    package = _service().build(
        session_id=sid,
        method="POST",
        path=path,
        status_code=200,
        response=body,
        api_consistency=audit,
    )
    assert package["available"] is True
    assert package["package_consistent"] is True


def test_package_consistent_false_with_api_consistent_true() -> None:
    """Task 048 package_consistent=False + Task 050 api_consistent=True
    -> Task 051 package_consistent=True."""
    sid, method, path, status, body, _ = _real_response_and_audit()
    tampered = copy.deepcopy(body)
    tampered["package_consistent"] = False
    tampered["bundle_consistency"]["bundle_consistent"] = False
    tampered["bundle_consistency"]["consistency_issues"] = [
        "NESTED_EXECUTION_MISMATCH"
    ]
    audit = ReasoningRunExecutionAuditPackageApiConsistencyService().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=tampered,
    )
    assert audit["api_consistent"] is True
    package = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response=tampered,
        api_consistency=audit,
    )
    assert package["package_consistent"] is True


# ---------------------------------------------------------------------------
# Contract rejections
# ---------------------------------------------------------------------------


def _valid_inputs() -> dict[str, Any]:
    sid, method, path, status, body, audit = _real_response_and_audit()
    return {
        "session_id": sid,
        "method": method,
        "path": path,
        "status_code": status,
        "response": body,
        "api_consistency": audit,
    }


def test_invalid_method() -> None:
    inputs = _valid_inputs()
    inputs["method"] = "GET"
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "INVALID_METHOD"


def test_invalid_path() -> None:
    inputs = _valid_inputs()
    inputs["path"] = "/sessions/x/reasoning-run/execute"
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "INVALID_PATH"


def test_invalid_status() -> None:
    inputs = _valid_inputs()
    inputs["status_code"] = 500
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "INVALID_STATUS"


def test_session_id_mismatch() -> None:
    inputs = _valid_inputs()
    inputs["session_id"] = uuid4()
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_invalid_session_id() -> None:
    inputs = _valid_inputs()
    inputs["session_id"] = "not-a-uuid"
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "SESSION_ID_INVALID"


def test_malformed_task048_response() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["response"])
    del tampered["package_source"]
    inputs["response"] = tampered
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(**inputs)
    assert ei.value.invariant in (
        "RESPONSE_MISMATCH",
        "RESPONSE_SOURCE_MISMATCH",
    )


def test_malformed_task050_audit() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["api_consistency"])
    del tampered["api_consistency_source"]
    inputs["api_consistency"] = tampered
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(**inputs)
    assert ei.value.invariant in (
        "API_CONSISTENCY_MISMATCH",
        "API_AUDIT_SOURCE_MISMATCH",
    )


def test_api_audit_unavailable() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["api_consistency"])
    tampered["available"] = False
    inputs["api_consistency"] = tampered
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(**inputs)
    assert ei.value.invariant in (
        "API_CONSISTENCY_MISMATCH",
        "API_AUDIT_UNAVAILABLE",
    )


def test_wrong_task048_source() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["response"])
    tampered["package_source"] = "WRONG"
    inputs["response"] = tampered
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(**inputs)
    assert ei.value.invariant in (
        "RESPONSE_MISMATCH",
        "RESPONSE_SOURCE_MISMATCH",
    )


def test_wrong_task050_source() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["api_consistency"])
    tampered["api_consistency_source"] = "WRONG"
    inputs["api_consistency"] = tampered
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(**inputs)
    assert ei.value.invariant in (
        "API_CONSISTENCY_MISMATCH",
        "API_AUDIT_SOURCE_MISMATCH",
    )


def test_wrong_task051_source() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["package_source"] = "WRONG"
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        ReasoningRunExecutionApiAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "PACKAGE_SOURCE_MISMATCH"


def test_package_consistent_mismatch() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["package_consistent"] = not tampered["package_consistent"]
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        ReasoningRunExecutionApiAuditPackageService._validate_result(tampered)
    assert ei.value.invariant == "API_CONSISTENCY_MISMATCH"


# ---------------------------------------------------------------------------
# Identity / pass-through
# ---------------------------------------------------------------------------


def test_exact_response_passed_through() -> None:
    inputs = _valid_inputs()
    package = _service().build(**inputs)
    assert package["response"] is inputs["response"]


def test_exact_audit_passed_through() -> None:
    inputs = _valid_inputs()
    package = _service().build(**inputs)
    assert package["api_consistency"] is inputs["api_consistency"]


# ---------------------------------------------------------------------------
# No mutation / determinism
# ---------------------------------------------------------------------------


def test_inputs_not_mutated() -> None:
    inputs = _valid_inputs()
    response_before = copy.deepcopy(inputs["response"])
    audit_before = copy.deepcopy(inputs["api_consistency"])
    _service().build(**inputs)
    assert inputs["response"] == response_before
    assert inputs["api_consistency"] == audit_before


def test_deterministic() -> None:
    inputs = _valid_inputs()
    s = _service()
    a = s.build(**inputs)
    b = s.build(**inputs)
    assert a == b


# ---------------------------------------------------------------------------
# No side effects outside Task 048/050 validators
# ---------------------------------------------------------------------------


def test_no_database_access() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "SessionLocal",
        "get_db",
        "session.query",
        "db.execute",
        "Repository(",
        "sqlalchemy",
    ):
        assert forbidden not in src


def test_no_http_or_testclient() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "TestClient",
        "requests.",
        "httpx",
        "fastapi",
    ):
        assert forbidden not in src


def test_no_task049_invocation() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "from rop.api",
        "import rop.api",
        "sessions.py",
        "router.",
    ):
        assert forbidden not in src


def test_no_task050_build_invocation() -> None:
    src = inspect.getsource(mod)
    assert "ApiConsistencyService().build" not in src
    assert "api_consistency_service.build" not in src


def test_no_task048_build_for_session() -> None:
    src = inspect.getsource(mod)
    import re as _re
    assert not _re.search(r"\.build_for_session\s*\(", src)


def test_no_direct_task044_calls() -> None:
    src = inspect.getsource(mod)
    assert "ReasoningRunExecutionService" not in src
    assert "execute_for_session" not in src


def test_no_direct_task045_calls() -> None:
    src = inspect.getsource(mod)
    assert "ReasoningRunExecutionConsistencyService" not in src


def test_no_direct_task046_calls() -> None:
    src = inspect.getsource(mod)
    assert "ReasoningRunExecutionBundleService" not in src


def test_no_direct_task047_calls() -> None:
    src = inspect.getsource(mod)
    assert "ReasoningRunExecutionBundleConsistencyService" not in src


def test_no_decision_or_llm_logic() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "DecisionPolicy",
        "CandidateGeneration",
        "EvidenceEvaluation",
        "openai",
        "gemini",
        "ollama",
        "llm",
        "rag",
        "winner",
        "recommendation",
    ):
        assert forbidden not in src.lower()

# ---------------------------------------------------------------------------
# Provenance binding (reviewer round 2)
# ---------------------------------------------------------------------------


def test_stale_audit_from_other_response_rejected() -> None:
    """Valid Response A + valid audit for A + different valid Response B
    -> Task 051 must reject the mismatch."""
    # Build Response A and its audit.
    sid_a_str = _create_session("Patient reports chest pain")
    sid_a = UUID(sid_a_str)
    path_a = f"/sessions/{sid_a_str}/reasoning-run/execute-fully-audited"
    r_a = client.post(path_a)
    assert r_a.status_code == 200
    body_a = r_a.json()
    audit_a = ReasoningRunExecutionAuditPackageApiConsistencyService().build(
        session_id=sid_a,
        method="POST",
        path=path_a,
        status_code=200,
        response_body=body_a,
    )

    # Build a *different* valid Response B (different session).
    sid_b_str = _create_session("Patient reports different symptoms")
    sid_b = UUID(sid_b_str)
    path_b = f"/sessions/{sid_b_str}/reasoning-run/execute-fully-audited"
    r_b = client.post(path_b)
    assert r_b.status_code == 200
    body_b = r_b.json()

    # Pair B's response with A's audit -- must be rejected.
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(
            session_id=sid_b,
            method="POST",
            path=path_b,
            status_code=200,
            response=body_b,
            api_consistency=audit_a,
        )
    # The first mismatch caught will be the session id.
    assert ei.value.invariant in (
        "SESSION_ID_MISMATCH",
        "RESPONSE_MISMATCH",
        "INVALID_PATH",
    )


def test_tampered_fingerprint_rejected() -> None:
    """If the audit's response fingerprint doesn't match the supplied
    response, Task 051 rejects."""
    sid, method, path, status, body, audit = _real_response_and_audit()
    tampered = copy.deepcopy(audit)
    tampered["audited_response_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageContractError
    ) as ei:
        _service().build(
            session_id=sid,
            method=method,
            path=path,
            status_code=status,
            response=body,
            api_consistency=tampered,
        )
    assert ei.value.invariant == "RESPONSE_MISMATCH"


def test_audit_provenance_fields_present() -> None:
    sid, method, path, status, body, audit = _real_response_and_audit()
    assert audit["audited_session_id"] == str(sid)
    assert audit["audited_method"] == "POST"
    assert audit["audited_path"] == path
    assert audit["audited_status_code"] == 200
    assert isinstance(audit["audited_response_fingerprint"], str)
    assert len(audit["audited_response_fingerprint"]) == 64

