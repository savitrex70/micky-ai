"""Tests for Task 054 API audit bundle consistency audit.

Task 054 is a pure audit over a supplied Task 053 bundle. It does not
call upstream build() workflows, does not call HTTP, does not access
the database, and does not mutate its input.
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
from rop.services import reasoning_run_execution_api_audit_bundle_consistency as mod
from rop.services.reasoning_run_execution_api_audit_bundle import (
    ReasoningRunExecutionApiAuditBundleService,
)
from rop.services.reasoning_run_execution_api_audit_bundle_consistency import (
    REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_054,
    ReasoningRunExecutionApiAuditBundleConsistencyContractError,
    ReasoningRunExecutionApiAuditBundleConsistencyService,
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

RESULT_FIELDS = (
    "available",
    "bundle_consistent",
    "session_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "nested_package_consistent",
    "nested_package_audit_consistent",
    "package_audit_provenance_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "bundle_consistency_source",
)


def _service() -> ReasoningRunExecutionApiAuditBundleConsistencyService:
    return ReasoningRunExecutionApiAuditBundleConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-054-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _build_task053_bundle() -> dict[str, Any]:
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
    return ReasoningRunExecutionApiAuditBundleService().build(
        session_id=sid,
        method="POST",
        path=path,
        status_code=200,
        api_audit_package=package_051,
        api_audit_package_consistency=audit_052,
    )


def _valid_bundle() -> dict[str, Any]:
    return _build_task053_bundle()


# ---------------------------------------------------------------------------
# Valid
# ---------------------------------------------------------------------------


def test_valid_bundle_consistent() -> None:
    bundle = _valid_bundle()
    result = _service().build(bundle=bundle)
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["bundle_consistent"] is True
    assert result["consistency_issues"] == []


def test_valid_bundle_all_flags_true() -> None:
    bundle = _valid_bundle()
    result = _service().build(bundle=bundle)
    for flag in (
        "session_consistent",
        "method_consistent",
        "path_consistent",
        "status_consistent",
        "nested_package_consistent",
        "nested_package_audit_consistent",
        "package_audit_provenance_consistent",
        "bundle_relationship_consistent",
        "source_consistency",
        "metadata_consistent",
    ):
        assert result[flag] is True, flag


def test_bundle_consistency_source_fixed() -> None:
    bundle = _valid_bundle()
    result = _service().build(bundle=bundle)
    assert (
        result["bundle_consistency_source"]
        == REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_CONSISTENCY_SOURCE_TASK_054
    )


def test_deterministic() -> None:
    bundle = _valid_bundle()
    s = _service()
    assert s.build(bundle=bundle) == s.build(bundle=bundle)


# ---------------------------------------------------------------------------
# Semantic: Task 053.bundle_consistent=False is not a Task 054 failure
# ---------------------------------------------------------------------------


def test_task053_and_task052_false_still_bundle_consistent_true() -> None:
    """Task 053 bundle_consistent=False + Task 052 package_consistent=False
    -> Task 054 bundle_consistent=True. Task 054 audits the bundle, not
    the underlying business consistency."""
    sid_str = _create_session("Patient reports chest pain")
    sid = UUID(sid_str)
    path = f"/sessions/{sid_str}/reasoning-run/execute-fully-audited"
    r = client.post(path)
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
    # Tamper: flip a Task 050 flag so Task 052 flags the package as
    # inconsistent.
    tampered_package = copy.deepcopy(package_051)
    tampered_package["api_consistency"]["path_consistent"] = False
    audit_052 = ReasoningRunExecutionApiAuditPackageConsistencyService().build(
        package=tampered_package
    )
    assert audit_052["package_consistent"] is False
    bundle = ReasoningRunExecutionApiAuditBundleService().build(
        session_id=sid,
        method="POST",
        path=path,
        status_code=200,
        api_audit_package=tampered_package,
        api_audit_package_consistency=audit_052,
    )
    assert bundle["bundle_consistent"] is False
    result = _service().build(bundle=bundle)
    assert result["available"] is True
    assert result["bundle_consistent"] is True
    assert result["bundle_relationship_consistent"] is True


# ---------------------------------------------------------------------------
# Top-level structural checks
# ---------------------------------------------------------------------------


def test_missing_bundle() -> None:
    with pytest.raises(
        ReasoningRunExecutionApiAuditBundleConsistencyContractError
    ) as ei:
        _service().build(bundle=None)
    assert ei.value.invariant == "MISSING_BUNDLE"


def test_non_mapping_bundle() -> None:
    with pytest.raises(
        ReasoningRunExecutionApiAuditBundleConsistencyContractError
    ) as ei:
        _service().build(bundle="nope")  # type: ignore[arg-type]
    assert ei.value.invariant == "BUNDLE_TYPE"


def test_missing_bundle_field() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    del tampered["bundle_source"]
    result = _service().build(bundle=tampered)
    assert "MISSING_BUNDLE_FIELD" in result["consistency_issues"]
    assert result["metadata_consistent"] is False


def test_invalid_bundle_available() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["available"] = False
    result = _service().build(bundle=tampered)
    assert "INVALID_BUNDLE_AVAILABLE" in result["consistency_issues"]


def test_invalid_session_uuid() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["session_id"] = "not-a-uuid"
    result = _service().build(bundle=tampered)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]


def test_wrong_route() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["path"] = "/wrong/path"
    tampered["api_audit_package"]["path"] = "/wrong/path"
    result = _service().build(bundle=tampered)
    assert "PATH_INVALID" in result["consistency_issues"]


def test_wrong_route_session_id() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    other_sid = str(uuid4())
    tampered["path"] = (
        f"/sessions/{other_sid}/reasoning-run/execute-fully-audited"
    )
    tampered["api_audit_package"]["path"] = tampered["path"]
    result = _service().build(bundle=tampered)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]


def test_wrong_method() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["method"] = "GET"
    tampered["api_audit_package"]["method"] = "GET"
    result = _service().build(bundle=tampered)
    assert "METHOD_INVALID" in result["consistency_issues"]


def test_wrong_status() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["status_code"] = 500
    tampered["api_audit_package"]["status_code"] = 500
    result = _service().build(bundle=tampered)
    assert "STATUS_CODE_INVALID" in result["consistency_issues"]


def test_top_level_session_mismatch() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["api_audit_package"]["session_id"] = str(uuid4())
    result = _service().build(bundle=tampered)
    # Either PACKAGE_SESSION_MISMATCH from the direct comparison, or
    # NESTED_PACKAGE_MISMATCH if the nested validator fires first.
    assert any(
        i in result["consistency_issues"]
        for i in ("PACKAGE_SESSION_MISMATCH", "NESTED_PACKAGE_MISMATCH")
    )


# ---------------------------------------------------------------------------
# Nested validator failures
# ---------------------------------------------------------------------------


def test_nested_task051_invalid() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    del tampered["api_audit_package"]["package_source"]
    result = _service().build(bundle=tampered)
    assert "NESTED_PACKAGE_MISMATCH" in result["consistency_issues"]


def test_nested_task052_invalid() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    del tampered["api_audit_package_consistency"][
        "audited_package_fingerprint"
    ]
    result = _service().build(bundle=tampered)
    assert "NESTED_PACKAGE_AUDIT_MISMATCH" in result["consistency_issues"]


def test_nested_task052_unavailable() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["api_audit_package_consistency"]["available"] = False
    result = _service().build(bundle=tampered)
    assert "NESTED_PACKAGE_AUDIT_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def test_wrong_task051_source() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["api_audit_package"]["package_source"] = "WRONG"
    result = _service().build(bundle=tampered)
    assert "RESPONSE_PACKAGE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


def test_wrong_task052_source() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["api_audit_package_consistency"][
        "package_consistency_source"
    ] = "WRONG"
    result = _service().build(bundle=tampered)
    assert "PACKAGE_AUDIT_SOURCE_MISMATCH" in result["consistency_issues"]


def test_wrong_task053_source() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_source"] = "WRONG"
    result = _service().build(bundle=tampered)
    assert "BUNDLE_SOURCE_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_stale_task052_audit_from_other_package() -> None:
    """A Task 052 audit from one Task 051 package paired with another
    Task 051 package in the Task 053 bundle must be flagged."""
    sid_a_str = _create_session("Patient reports chest pain")
    sid_a = UUID(sid_a_str)
    path_a = f"/sessions/{sid_a_str}/reasoning-run/execute-fully-audited"
    body_a = client.post(path_a).json()
    audit_050_a = ReasoningRunExecutionAuditPackageApiConsistencyService().build(
        session_id=sid_a,
        method="POST",
        path=path_a,
        status_code=200,
        response_body=body_a,
    )
    package_051_a = ReasoningRunExecutionApiAuditPackageService().build(
        session_id=sid_a,
        method="POST",
        path=path_a,
        status_code=200,
        response=body_a,
        api_consistency=audit_050_a,
    )
    audit_052_a = ReasoningRunExecutionApiAuditPackageConsistencyService().build(
        package=package_051_a
    )

    # Different valid Task 051 package B.
    sid_b_str = _create_session("Different symptoms")
    sid_b = UUID(sid_b_str)
    path_b = f"/sessions/{sid_b_str}/reasoning-run/execute-fully-audited"
    body_b = client.post(path_b).json()
    audit_050_b = ReasoningRunExecutionAuditPackageApiConsistencyService().build(
        session_id=sid_b,
        method="POST",
        path=path_b,
        status_code=200,
        response_body=body_b,
    )
    package_051_b = ReasoningRunExecutionApiAuditPackageService().build(
        session_id=sid_b,
        method="POST",
        path=path_b,
        status_code=200,
        response=body_b,
        api_consistency=audit_050_b,
    )

    # Build a synthetic Task 053 bundle by hand, mismatching package B
    # with audit A.
    synthetic_bundle = {
        "available": True,
        "bundle_consistent": audit_052_a["package_consistent"],
        "session_id": str(sid_b),
        "method": "POST",
        "path": path_b,
        "status_code": 200,
        "api_audit_package": package_051_b,
        "api_audit_package_consistency": audit_052_a,
        "bundle_source": "REASONING_RUN_EXECUTION_API_AUDIT_BUNDLE_TASK_053",
    }
    result = _service().build(bundle=synthetic_bundle)
    assert (
        "AUDITED_PACKAGE_FINGERPRINT_MISMATCH"
        in result["consistency_issues"]
    )
    assert result["package_audit_provenance_consistent"] is False


def test_tampered_audited_package_fingerprint() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["api_audit_package_consistency"][
        "audited_package_fingerprint"
    ] = "0" * 64
    result = _service().build(bundle=tampered)
    assert (
        "AUDITED_PACKAGE_FINGERPRINT_MISMATCH"
        in result["consistency_issues"]
    )


def test_bundle_relationship_mismatch() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_consistent"] = not tampered["bundle_consistent"]
    result = _service().build(bundle=tampered)
    assert "BUNDLE_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["bundle_relationship_consistent"] is False


# ---------------------------------------------------------------------------
# Determinism / mutation / identity / no side effects
# ---------------------------------------------------------------------------


def test_deterministic_issue_ordering() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    # Two top-level-only tampers that do not cascade into the nested
    # validators or the fingerprint check:
    #   - flipping bundle_consistent breaks the Task 053 relationship
    #   - tampering bundle_source breaks the Task 053 source check
    # Canonical order per _ISSUE_ORDER:
    #   BUNDLE_RELATIONSHIP_MISMATCH (position 15)
    #   before BUNDLE_SOURCE_MISMATCH (position 18).
    tampered["bundle_consistent"] = not tampered["bundle_consistent"]
    tampered["bundle_source"] = "WRONG"
    result = _service().build(bundle=tampered)
    expected_order = [
        "BUNDLE_RELATIONSHIP_MISMATCH",
        "BUNDLE_SOURCE_MISMATCH",
    ]
    assert result["consistency_issues"] == expected_order


def test_no_duplicate_issues() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_source"] = "WRONG"
    result = _service().build(bundle=tampered)
    assert result["consistency_issues"].count("BUNDLE_SOURCE_MISMATCH") == 1


def test_input_not_mutated() -> None:
    bundle = _valid_bundle()
    before = copy.deepcopy(bundle)
    _service().build(bundle=bundle)
    assert bundle == before


def test_exact_nested_objects_preserved() -> None:
    bundle = _valid_bundle()
    before_pkg = bundle["api_audit_package"]
    before_audit = bundle["api_audit_package_consistency"]
    _service().build(bundle=bundle)
    assert bundle["api_audit_package"] is before_pkg
    assert bundle["api_audit_package_consistency"] is before_audit


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
# Round 2: fingerprint-computation failure is a provenance failure
# ---------------------------------------------------------------------------


def test_fingerprint_compute_failure_is_provenance_failure(
    monkeypatch,
) -> None:
    """If the independent fingerprint computation raises, Task 054 must
    record AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED, set
    package_audit_provenance_consistent=False, and set
    bundle_consistent=False. Failure to produce the proof must never
    count as a passing provenance check.

    Note: the bundle is built BEFORE the monkeypatch is installed, so
    Task 052's own build path is unaffected; only Task 054's
    independent recomputation uses the failing double.
    """
    from rop.services.reasoning_run_execution_api_audit_package_consistency import (
        ReasoningRunExecutionApiAuditPackageConsistencyService,
    )

    bundle = _valid_bundle()
    before = copy.deepcopy(bundle)

    def boom(package):
        raise RuntimeError("forced fingerprint failure")

    monkeypatch.setattr(
        ReasoningRunExecutionApiAuditPackageConsistencyService,
        "_package_fingerprint",
        staticmethod(boom),
    )

    result = _service().build(bundle=bundle)

    assert (
        "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED"
        in result["consistency_issues"]
    )
    assert result["package_audit_provenance_consistent"] is False
    assert result["bundle_consistent"] is False
    # Input is not mutated.
    assert bundle == before


def test_fingerprint_compute_failure_does_not_cascade_into_mismatch(
    monkeypatch,
) -> None:
    """When computation fails, only the COMPUTE_FAILED issue should
    appear -- not also a spurious MISMATCH."""
    from rop.services.reasoning_run_execution_api_audit_package_consistency import (
        ReasoningRunExecutionApiAuditPackageConsistencyService,
    )

    bundle = _valid_bundle()

    def boom(package):
        raise RuntimeError("forced")

    monkeypatch.setattr(
        ReasoningRunExecutionApiAuditPackageConsistencyService,
        "_package_fingerprint",
        staticmethod(boom),
    )

    result = _service().build(bundle=bundle)
    assert (
        "AUDITED_PACKAGE_FINGERPRINT_MISMATCH"
        not in result["consistency_issues"]
    )
    assert result["consistency_issues"] == [
        "AUDITED_PACKAGE_FINGERPRINT_COMPUTE_FAILED"
    ]

# ---------------------------------------------------------------------------
# Round 3: provenance flag is False whenever the check cannot be performed
# ---------------------------------------------------------------------------


def test_missing_task051_package_flips_provenance_flag() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["api_audit_package"] = None
    result = _service().build(bundle=tampered)
    assert "PROVENANCE_CHECK_UNAVAILABLE" in result["consistency_issues"]
    assert result["package_audit_provenance_consistent"] is False
    assert result["bundle_consistent"] is False


def test_missing_task052_audit_flips_provenance_flag() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["api_audit_package_consistency"] = None
    result = _service().build(bundle=tampered)
    assert "PROVENANCE_CHECK_UNAVAILABLE" in result["consistency_issues"]
    assert result["package_audit_provenance_consistent"] is False


def test_non_mapping_task051_package_flips_provenance_flag() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["api_audit_package"] = "not-a-mapping"
    result = _service().build(bundle=tampered)
    assert "PROVENANCE_CHECK_UNAVAILABLE" in result["consistency_issues"]
    assert result["package_audit_provenance_consistent"] is False


def test_non_mapping_task052_audit_flips_provenance_flag() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["api_audit_package_consistency"] = "not-a-mapping"
    result = _service().build(bundle=tampered)
    assert "PROVENANCE_CHECK_UNAVAILABLE" in result["consistency_issues"]
    assert result["package_audit_provenance_consistent"] is False


def test_valid_bundle_provenance_flag_true() -> None:
    bundle = _valid_bundle()
    result = _service().build(bundle=bundle)
    assert result["package_audit_provenance_consistent"] is True

