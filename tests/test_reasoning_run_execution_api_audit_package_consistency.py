"""Tests for Task 052 API audit package consistency audit.

Task 052 is a pure audit over a supplied Task 051 package. It does
not call upstream build() workflows, does not call HTTP, does not
access the database, and does not mutate its input.
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
from rop.services import reasoning_run_execution_api_audit_package_consistency as mod
from rop.services.reasoning_run_execution_api_audit_package import (
    ReasoningRunExecutionApiAuditPackageService,
)
from rop.services.reasoning_run_execution_api_audit_package_consistency import (
    REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_052,
    ReasoningRunExecutionApiAuditPackageConsistencyContractError,
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
    "package_consistent",
    "session_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "nested_response_consistent",
    "nested_api_consistency_consistent",
    "provenance_consistent",
    "package_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "package_consistency_source",
    "audited_package_fingerprint",
)


def _service() -> ReasoningRunExecutionApiAuditPackageConsistencyService:
    return ReasoningRunExecutionApiAuditPackageConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-052-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _valid_package() -> dict[str, Any]:
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
    return ReasoningRunExecutionApiAuditPackageService().build(
        session_id=sid,
        method="POST",
        path=path,
        status_code=200,
        response=body,
        api_consistency=audit,
    )


# ---------------------------------------------------------------------------
# Valid
# ---------------------------------------------------------------------------


def test_valid_package_consistent() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["package_consistent"] is True
    assert result["consistency_issues"] == []


def test_valid_package_all_flags_true() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    for flag in (
        "session_consistent",
        "method_consistent",
        "path_consistent",
        "status_consistent",
        "nested_response_consistent",
        "nested_api_consistency_consistent",
        "provenance_consistent",
        "package_relationship_consistent",
        "source_consistency",
        "metadata_consistent",
    ):
        assert result[flag] is True, flag


def test_audit_source_fixed() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    assert (
        result["package_consistency_source"]
        == REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_CONSISTENCY_SOURCE_TASK_052
    )


def test_valid_package_with_response_package_consistent_false() -> None:
    """Task 048 response.package_consistent=False + Task 050
    api_consistent=True + Task 051 package_consistent=True must
    produce Task 052 package_consistent=True."""
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["response"]["package_consistent"] = False
    tampered["response"]["bundle_consistency"]["bundle_consistent"] = False
    tampered["response"]["bundle_consistency"]["consistency_issues"] = [
        "NESTED_EXECUTION_MISMATCH"
    ]
    # Rebuild audit to reflect this response.
    sid = UUID(str(tampered["session_id"]))
    new_audit = ReasoningRunExecutionAuditPackageApiConsistencyService().build(
        session_id=sid,
        method="POST",
        path=tampered["path"],
        status_code=200,
        response_body=tampered["response"],
    )
    tampered["api_consistency"] = new_audit
    tampered["package_consistent"] = new_audit["api_consistent"]

    result = _service().build(package=tampered)
    assert result["package_consistent"] is True
    assert result["consistency_issues"] == []


# ---------------------------------------------------------------------------
# Structural / metadata rejections
# ---------------------------------------------------------------------------


def test_missing_package() -> None:
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageConsistencyContractError
    ) as ei:
        _service().build(package=None)
    assert ei.value.invariant == "MISSING_PACKAGE"


def test_missing_required_field() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    del tampered["package_source"]
    result = _service().build(package=tampered)
    assert "MISSING_PACKAGE_FIELD" in result["consistency_issues"]
    assert result["metadata_consistent"] is False


def test_invalid_session_uuid() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["session_id"] = "not-a-uuid"
    result = _service().build(package=tampered)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]


def test_lowercase_method_invalid() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["method"] = "post"
    result = _service().build(package=tampered)
    assert "METHOD_INVALID" in result["consistency_issues"]


def test_titlecase_method_invalid() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["method"] = "Post"
    result = _service().build(package=tampered)
    assert "METHOD_INVALID" in result["consistency_issues"]


def test_wrong_status_code() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["status_code"] = 500
    result = _service().build(package=tampered)
    assert "AUDITED_STATUS_CODE_MISMATCH" in result["consistency_issues"]


def test_session_mismatch() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["response"]["session_id"] = str(uuid4())
    result = _service().build(package=tampered)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]


def test_audited_session_mismatch() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["api_consistency"]["audited_session_id"] = str(uuid4())
    result = _service().build(package=tampered)
    assert "AUDITED_SESSION_ID_MISMATCH" in result["consistency_issues"]


def test_audited_method_mismatch() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["api_consistency"]["audited_method"] = "GET"
    result = _service().build(package=tampered)
    assert "AUDITED_METHOD_MISMATCH" in result["consistency_issues"]


def test_audited_path_mismatch() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["api_consistency"]["audited_path"] = "/other/path"
    result = _service().build(package=tampered)
    assert "AUDITED_PATH_MISMATCH" in result["consistency_issues"]


def test_nested_response_mismatch() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    del tampered["response"]["package_source"]
    result = _service().build(package=tampered)
    assert "NESTED_RESPONSE_MISMATCH" in result["consistency_issues"]


def test_nested_api_consistency_mismatch() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    del tampered["api_consistency"]["audited_method"]
    result = _service().build(package=tampered)
    assert (
        "NESTED_API_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    )


def test_stale_audit_from_other_response() -> None:
    """A valid audit for Response A paired with a different Response B
    must be rejected via the fingerprint mismatch."""
    # Build Response A + audit A.
    sid_a_str = _create_session("Patient reports chest pain")
    sid_a = UUID(sid_a_str)
    path_a = f"/sessions/{sid_a_str}/reasoning-run/execute-fully-audited"
    body_a = client.post(path_a).json()
    audit_a = ReasoningRunExecutionAuditPackageApiConsistencyService().build(
        session_id=sid_a,
        method="POST",
        path=path_a,
        status_code=200,
        response_body=body_a,
    )

    # Build Response B (different session).
    sid_b_str = _create_session("Different symptoms entirely")
    sid_b = UUID(sid_b_str)
    path_b = f"/sessions/{sid_b_str}/reasoning-run/execute-fully-audited"
    body_b = client.post(path_b).json()

    # Construct a Task 051 package that lies about which response the
    # audit belongs to: use B's response body but A's audit.
    fake_package = {
        "available": True,
        "package_consistent": audit_a["api_consistent"],
        "session_id": str(sid_b),
        "method": "POST",
        "path": path_b,
        "status_code": 200,
        "response": body_b,
        "api_consistency": audit_a,
        "package_source": "REASONING_RUN_EXECUTION_API_AUDIT_PACKAGE_TASK_051",
    }
    result = _service().build(package=fake_package)
    assert (
        "AUDITED_RESPONSE_FINGERPRINT_MISMATCH"
        in result["consistency_issues"]
        or "AUDITED_PATH_MISMATCH" in result["consistency_issues"]
        or "AUDITED_SESSION_ID_MISMATCH" in result["consistency_issues"]
    )
    assert result["package_consistent"] is False


def test_tampered_fingerprint() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["api_consistency"]["audited_response_fingerprint"] = "0" * 64
    result = _service().build(package=tampered)
    assert (
        "AUDITED_RESPONSE_FINGERPRINT_MISMATCH"
        in result["consistency_issues"]
    )
    assert result["provenance_consistent"] is False


def test_package_relationship_mismatch() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["package_consistent"] = not tampered["package_consistent"]
    result = _service().build(package=tampered)
    assert "PACKAGE_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["package_relationship_consistent"] is False


def test_wrong_task048_source() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["response"]["package_source"] = "WRONG"
    result = _service().build(package=tampered)
    assert "RESPONSE_SOURCE_MISMATCH" in result["consistency_issues"]


def test_wrong_task050_source() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["api_consistency"]["api_consistency_source"] = "WRONG"
    result = _service().build(package=tampered)
    assert (
        "API_CONSISTENCY_SOURCE_MISMATCH" in result["consistency_issues"]
    )


def test_wrong_task051_source() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["package_source"] = "WRONG"
    result = _service().build(package=tampered)
    assert "PACKAGE_SOURCE_MISMATCH" in result["consistency_issues"]


def test_wrong_task052_source() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    tampered = copy.deepcopy(result)
    tampered["package_consistency_source"] = "WRONG"
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningRunExecutionApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "PACKAGE_CONSISTENCY_SOURCE_MISMATCH"


# ---------------------------------------------------------------------------
# Determinism, ordering, no mutation
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    package = _valid_package()
    s = _service()
    assert s.build(package=package) == s.build(package=package)


def test_deterministic_issue_ordering() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["package_source"] = "WRONG"
    tampered["method"] = "post"
    result = _service().build(package=tampered)
    # METHOD_INVALID comes before PACKAGE_SOURCE_MISMATCH in the fixed order.
    expected_order = [
        "METHOD_INVALID",
        "AUDITED_METHOD_MISMATCH",
        "PACKAGE_SOURCE_MISMATCH",
    ]
    assert result["consistency_issues"] == expected_order


def test_no_duplicate_issues() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["method"] = "post"
    tampered["api_consistency"]["audited_method"] = "post"
    result = _service().build(package=tampered)
    assert result["consistency_issues"].count("METHOD_INVALID") == 1


def test_input_not_mutated() -> None:
    package = _valid_package()
    before = copy.deepcopy(package)
    _service().build(package=package)
    assert package == before


def test_exact_nested_objects_preserved() -> None:
    """The audit operates on the supplied nested objects; it does not
    reconstruct them."""
    package = _valid_package()
    before_response = package["response"]
    before_audit = package["api_consistency"]
    _service().build(package=package)
    assert package["response"] is before_response
    assert package["api_consistency"] is before_audit


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
# Round 2: exact route + nested Task 050 flag checks
# ---------------------------------------------------------------------------


def test_wrong_task049_path() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["path"] = "/wrong/path"
    # Keep provenance matching so PATH_INVALID is the specific hit.
    tampered["api_consistency"]["audited_path"] = "/wrong/path"
    result = _service().build(package=tampered)
    assert "PATH_INVALID" in result["consistency_issues"]
    assert result["path_consistent"] is False


def test_api_consistency_available_false() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["api_consistency"]["available"] = False
    result = _service().build(package=tampered)
    assert (
        "NESTED_API_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    )
    assert result["nested_api_consistency_consistent"] is False


def test_api_consistency_session_consistent_false() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["api_consistency"]["session_consistent"] = False
    result = _service().build(package=tampered)
    assert (
        "NESTED_API_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    )


def test_api_consistency_method_consistent_false() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["api_consistency"]["method_consistent"] = False
    result = _service().build(package=tampered)
    assert (
        "NESTED_API_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    )


def test_api_consistency_path_consistent_false() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["api_consistency"]["path_consistent"] = False
    result = _service().build(package=tampered)
    assert (
        "NESTED_API_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    )


def test_api_consistency_status_consistent_false() -> None:
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["api_consistency"]["status_consistent"] = False
    result = _service().build(package=tampered)
    assert (
        "NESTED_API_CONSISTENCY_MISMATCH" in result["consistency_issues"]
    )


def test_wrong_status_code_both_sides() -> None:
    """status_code=500 with matching audited_status_code=500 must still
    be flagged, since the Task 049 route is exactly 200."""
    package = _valid_package()
    tampered = copy.deepcopy(package)
    tampered["status_code"] = 500
    tampered["api_consistency"]["audited_status_code"] = 500
    result = _service().build(package=tampered)
    assert "STATUS_CODE_INVALID" in result["consistency_issues"]
    assert result["status_consistent"] is False

# ---------------------------------------------------------------------------
# Round 3: audited_package_fingerprint provenance
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Round 4: fingerprint mandatory (reviewer round 3)
# ---------------------------------------------------------------------------


def test_audited_package_fingerprint_none_rejected() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    tampered = copy.deepcopy(result)
    tampered["audited_package_fingerprint"] = None
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningRunExecutionApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_FORMAT"


def test_audited_package_fingerprint_missing_rejected() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    tampered = copy.deepcopy(result)
    del tampered["audited_package_fingerprint"]
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningRunExecutionApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "MISSING_RESULT_FIELD"


def test_audited_package_fingerprint_valid_hex_accepted() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    fp = result["audited_package_fingerprint"]
    assert isinstance(fp, str)
    assert len(fp) == 64
    assert fp == fp.lower()
    # The existing build path validates without raising.
    ReasoningRunExecutionApiAuditPackageConsistencyService._validate_result(
        result
    )


def test_audited_package_fingerprint_non_hex_rejected() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    tampered = copy.deepcopy(result)
    tampered["audited_package_fingerprint"] = "z" * 64
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningRunExecutionApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_FORMAT"


def test_audited_package_fingerprint_uppercase_rejected() -> None:
    package = _valid_package()
    result = _service().build(package=package)
    tampered = copy.deepcopy(result)
    tampered["audited_package_fingerprint"] = (
        tampered["audited_package_fingerprint"].upper()
    )
    with pytest.raises(
        ReasoningRunExecutionApiAuditPackageConsistencyContractError
    ) as ei:
        ReasoningRunExecutionApiAuditPackageConsistencyService._validate_result(
            tampered
        )
    assert ei.value.invariant == "AUDITED_PACKAGE_FINGERPRINT_FORMAT"

