"""Tests for Task 053 API audit bundle.

Task 053 packages a Task 051 API audit package with its Task 052
consistency audit. Pure composition only: no HTTP, no DB, no upstream
build calls.
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

from rop.database import Base
from rop.main import app
from rop.services import reasoning_run_execution_api_audit_bundle as mod
from rop.services.reasoning_run_execution_api_audit_bundle import (
    REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_SOURCE_TASK_053,
    ReasoningRunExecutionApiAuditBundleContractError,
    ReasoningRunExecutionApiAuditBundleService,
)
from rop.services.reasoning_run_execution_api_audit_package import (
    ReasoningRunExecutionApiAuditPackageService,
)
from rop.services.reasoning_run_execution_api_audit_package_consistency import (
    ReasoningRunExecutionApiAuditPackageConsistencyService,
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

BUNDLE_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "method",
    "path",
    "status_code",
    "api_audit_package",
    "api_audit_package_consistency",
    "bundle_source",
)


def _service() -> ReasoningRunExecutionApiAuditBundleService:
    return ReasoningRunExecutionApiAuditBundleService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-053-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _task051_and_052(
) -> tuple[UUID, str, str, int, dict[str, Any], dict[str, Any]]:
    sid_str = _create_session("Patient reports chest pain")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-run/execute-fully-audited"
    r = client.post(path)
    assert r.status_code == 200
    body = r.json()
    audit_050 = ReasoningRunExecutionAuditPackageApiConsistencyService().build(
        session_id=sid,
        method="POST",
        path=path,
        status_code=200,
        response_body=body,
    )
    package_051 = ReasoningRunExecutionApiAuditPackageService().build(
        session_id=sid,
        method="POST",
        path=path,
        status_code=200,
        response=body,
        api_consistency=audit_050,
    )
    audit_052 = ReasoningRunExecutionApiAuditPackageConsistencyService().build(
        package=package_051
    )
    return sid, "POST", path, 200, package_051, audit_052


def _valid_bundle() -> dict[str, Any]:
    sid, method, path, status, package, audit = _task051_and_052()
    return _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        api_audit_package=package,
        api_audit_package_consistency=audit,
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
    assert (
        bundle["bundle_source"]
        == REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_SOURCE_TASK_053
    )


def test_nested_objects_present() -> None:
    bundle = _valid_bundle()
    assert (
        bundle["api_audit_package"]["package_source"]
        == "REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_TASK_051"
    )
    assert (
        bundle["api_audit_package_consistency"]["package_consistency_source"]
        == "REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_TASK_052"
    )


def test_bundle_consistent_matches_task052() -> None:
    bundle = _valid_bundle()
    assert bundle["bundle_consistent"] == (
        bundle["api_audit_package_consistency"]["package_consistent"]
    )


# ---------------------------------------------------------------------------
# Semantic cases
# ---------------------------------------------------------------------------


def test_task051_package_consistent_false_bundle_consistent_true() -> None:
    """Task 051 package_consistent=False + Task 052 package_consistent=True
    -> Task 053 bundle_consistent=True. This is the key semantic
    regression: bundle_consistent must NOT be inherited from Task 051."""
    sid, method, path, status, package, _ = _task051_and_052()
    tampered_package = copy.deepcopy(package)
    tampered_package["package_consistent"] = False
    tampered_package["api_consistency"]["api_consistent"] = False
    tampered_package["api_consistency"]["consistency_issues"] = [
        "NESTED_PACKAGE_MISMATCH"
    ]
    audit_052 = ReasoningRunExecutionApiAuditPackageConsistencyService().build(
        package=tampered_package
    )
    bundle = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        api_audit_package=tampered_package,
        api_audit_package_consistency=audit_052,
    )
    assert bundle["api_audit_package"]["package_consistent"] is False
    assert (
        bundle["api_audit_package_consistency"]["package_consistent"] is True
    )
    assert bundle["bundle_consistent"] is True


def test_task052_package_consistent_false_bundle_consistent_false() -> None:
    """If Task 052 legitimately reports the Task 051 package as
    inconsistent, Task 053 records bundle_consistent=False but the
    bundle is still available."""
    sid, method, path, status, package, _ = _task051_and_052()
    tampered_package = copy.deepcopy(package)
    # Tamper with a nested Task 050 flag so Task 052 will flag the
    # Task 051 package as inconsistent.
    tampered_package["api_consistency"]["path_consistent"] = False
    audit_052 = ReasoningRunExecutionApiAuditPackageConsistencyService().build(
        package=tampered_package
    )
    assert audit_052["package_consistent"] is False
    bundle = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        api_audit_package=tampered_package,
        api_audit_package_consistency=audit_052,
    )
    assert bundle["available"] is True
    assert bundle["bundle_consistent"] is False


# ---------------------------------------------------------------------------
# Contract rejections
# ---------------------------------------------------------------------------


def _valid_inputs() -> dict[str, Any]:
    sid, method, path, status, package, audit = _task051_and_052()
    return {
        "session_id": sid,
        "method": method,
        "path": path,
        "status_code": status,
        "api_audit_package": package,
        "api_audit_package_consistency": audit,
    }


def test_missing_api_audit_package() -> None:
    inputs = _valid_inputs()
    inputs["api_audit_package"] = None
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "MISSING_API_AUDIT_PACKAGE"


def test_missing_api_audit_package_consistency() -> None:
    inputs = _valid_inputs()
    inputs["api_audit_package_consistency"] = None
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "MISSING_API_AUDIT_PACKAGE_CONSISTENCY"


def test_invalid_method() -> None:
    inputs = _valid_inputs()
    inputs["method"] = "GET"
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "INVALID_METHOD"


def test_lowercase_method_invalid() -> None:
    inputs = _valid_inputs()
    inputs["method"] = "post"
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "INVALID_METHOD"


def test_invalid_path() -> None:
    inputs = _valid_inputs()
    inputs["path"] = ""
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "INVALID_PATH"


def test_invalid_status() -> None:
    inputs = _valid_inputs()
    inputs["status_code"] = 500
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "INVALID_STATUS"


def test_session_mismatch() -> None:
    inputs = _valid_inputs()
    inputs["session_id"] = uuid4()
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "SESSION_ID_MISMATCH"


def test_method_mismatch() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["api_audit_package"])
    tampered["method"] = "post"
    inputs["api_audit_package"] = tampered
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError):
        _service().build(**inputs)


def test_path_mismatch() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["api_audit_package"])
    tampered["path"] = "/wrong/path"
    inputs["api_audit_package"] = tampered
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError):
        _service().build(**inputs)


def test_status_mismatch() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["api_audit_package"])
    tampered["status_code"] = 500
    inputs["api_audit_package"] = tampered
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError):
        _service().build(**inputs)


def test_nested_task051_validator_failure() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["api_audit_package"])
    del tampered["package_source"]
    inputs["api_audit_package"] = tampered
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant in (
        "INVALID_API_AUDIT_PACKAGE",
        "INVALID_API_AUDIT_PACKAGE_SOURCE",
    )


def test_nested_task052_validator_failure() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["api_audit_package_consistency"])
    del tampered["package_consistency_source"]
    inputs["api_audit_package_consistency"] = tampered
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant in (
        "INVALID_API_AUDIT_PACKAGE_CONSISTENCY",
        "INVALID_API_AUDIT_CONSISTENCY_SOURCE",
    )


def test_wrong_task051_source() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["api_audit_package"])
    tampered["package_source"] = "WRONG"
    inputs["api_audit_package"] = tampered
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant in (
        "INVALID_API_AUDIT_PACKAGE",
        "INVALID_API_AUDIT_PACKAGE_SOURCE",
    )


def test_wrong_task052_source() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["api_audit_package_consistency"])
    tampered["package_consistency_source"] = "WRONG"
    inputs["api_audit_package_consistency"] = tampered
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant in (
        "INVALID_API_AUDIT_PACKAGE_CONSISTENCY",
        "INVALID_API_AUDIT_CONSISTENCY_SOURCE",
    )


def test_wrong_task053_source() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_source"] = "WRONG"
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        ReasoningRunExecutionApiAuditBundleService._validate_result(tampered)
    assert ei.value.invariant == "INVALID_BUNDLE_SOURCE"


def test_bundle_consistent_mismatch() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_consistent"] = not tampered["bundle_consistent"]
    with pytest.raises(ReasoningRunExecutionApiAuditBundleContractError) as ei:
        ReasoningRunExecutionApiAuditBundleService._validate_result(tampered)
    assert ei.value.invariant == "BUNDLE_CONSISTENT_MISMATCH"


# ---------------------------------------------------------------------------
# Identity / no mutation / determinism
# ---------------------------------------------------------------------------


def test_nested_objects_preserved_by_identity() -> None:
    inputs = _valid_inputs()
    bundle = _service().build(**inputs)
    assert bundle["api_audit_package"] is inputs["api_audit_package"]
    assert (
        bundle["api_audit_package_consistency"]
        is inputs["api_audit_package_consistency"]
    )


def test_inputs_not_mutated() -> None:
    inputs = _valid_inputs()
    package_before = copy.deepcopy(inputs["api_audit_package"])
    audit_before = copy.deepcopy(inputs["api_audit_package_consistency"])
    _service().build(**inputs)
    assert inputs["api_audit_package"] == package_before
    assert inputs["api_audit_package_consistency"] == audit_before


def test_deterministic() -> None:
    inputs = _valid_inputs()
    s = _service()
    assert s.build(**inputs) == s.build(**inputs)


# ---------------------------------------------------------------------------
# No side effects
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
    for forbidden in ("TestClient", "requests.", "httpx", "fastapi"):
        assert forbidden not in src


def test_no_upstream_build_invocations() -> None:
    src = inspect.getsource(mod)
    import re as _re
    assert not _re.search(r"\.build\s*\(", src)
    assert not _re.search(r"\.build_for_session\s*\(", src)


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
# Round 2: Task 052 provenance fingerprint binding
# ---------------------------------------------------------------------------


def test_stale_audit_from_other_package_rejected() -> None:
    sid_a, method_a, path_a, status_a, package_a, _ = _task051_and_052()
    audit_a = (
        ReasoningRunExecutionApiAuditPackageConsistencyService().build(
            package=package_a
        )
    )
    sid_b, method_b, path_b, status_b, package_b, _ = _task051_and_052()

    with pytest.raises(
        ReasoningRunExecutionApiAuditBundleContractError
    ) as ei:
        _service().build(
            session_id=sid_b,
            method=method_b,
            path=path_b,
            status_code=status_b,
            api_audit_package=package_b,
            api_audit_package_consistency=audit_a,
        )
    assert ei.value.invariant == "AUDIT_PACKAGE_FINGERPRINT_MISMATCH"


def test_tampered_audit_fingerprint_rejected() -> None:
    inputs = _valid_inputs()
    tampered = copy.deepcopy(inputs["api_audit_package_consistency"])
    tampered["audited_package_fingerprint"] = "0" * 64
    inputs["api_audit_package_consistency"] = tampered
    with pytest.raises(
        ReasoningRunExecutionApiAuditBundleContractError
    ) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "AUDIT_PACKAGE_FINGERPRINT_MISMATCH"


def test_matching_fingerprint_accepted() -> None:
    inputs = _valid_inputs()
    bundle = _service().build(**inputs)
    assert bundle["available"] is True
    assert bundle["bundle_consistent"] is True

