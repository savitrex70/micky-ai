"""Tests for Task 050 API response consistency audit.

Task 050 is a pure audit layer over a supplied Task 049 API response.
It does not call HTTP, does not call Task 048, does not access the
database, and does not mutate its input.
"""

from __future__ import annotations

import copy
import inspect
from typing import Any
from uuid import UUID, uuid4

import pytest

from rop.services import (
    reasoning_run_execution_audit_package_api_consistency as mod,
)
from rop.services.reasoning_run_execution_audit_package_api_consistency import (
    REASONING_RUN_EXECUTION_AUDIT_PACKAGE_API_CONSISTENCY_SOURCE_TASK_050,
    ReasoningRunExecutionAuditPackageApiConsistencyContractError,
    ReasoningRunExecutionAuditPackageApiConsistencyService,
)

RESULT_FIELDS = (
    "available",
    "api_consistent",
    "method_consistent",
    "path_consistent",
    "status_consistent",
    "session_consistent",
    "response_shape_consistent",
    "nested_package_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "api_consistency_source",
    "audited_session_id",
    "audited_method",
    "audited_path",
    "audited_status_code",
    "audited_response_fingerprint",
)


def _service() -> ReasoningRunExecutionAuditPackageApiConsistencyService:
    return ReasoningRunExecutionAuditPackageApiConsistencyService()


def _valid_body(session_id: UUID) -> dict[str, Any]:
    """Build a minimal but valid Task 048 package response body."""
    return {
        "available": True,
        "package_consistent": True,
        "session_id": str(session_id),
        "execution_bundle": {},
        "bundle_consistency": {},
        "package_source": "REASONING_RUN_EXECUTION_AUDIT_PACKAGE_TASK_048",
    }


# We use a placeholder package structure that will fail Task 048's
# validator, which the audit reports as NESTED_PACKAGE_MISMATCH. For
# the "fully valid" tests we build a real package via the API.


def _real_api_response() -> tuple[UUID, str, str, int, dict[str, Any]]:
    """Call the real endpoint and return (session_id, method, path,
    status, body)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from rop.database import Base, get_db
    from rop.main import app

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        with TestingSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Patient reports chest pain",
            "current_stage": "initial",
            "metadata": {"source": "task-050-test"},
        },
    )
    assert r.status_code == 201
    sid_str = str(r.json()["id"])
    sid = UUID(sid_str)

    path = f"/sessions/{sid_str}/reasoning-run/execute-fully-audited"
    r2 = client.post(path)
    assert r2.status_code == 200
    return sid, "POST", path, 200, r2.json()


# ---------------------------------------------------------------------------
# Valid cases
# ---------------------------------------------------------------------------


def test_valid_api_response_consistent() -> None:
    sid, method, path, status, body = _real_api_response()
    result = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=body,
    )
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["api_consistent"] is True
    assert result["consistency_issues"] == []


def test_valid_response_all_flags_true() -> None:
    sid, method, path, status, body = _real_api_response()
    result = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=body,
    )
    for flag in (
        "method_consistent",
        "path_consistent",
        "status_consistent",
        "session_consistent",
        "response_shape_consistent",
        "nested_package_consistent",
        "source_consistency",
        "metadata_consistent",
    ):
        assert result[flag] is True, flag


def test_api_source_fixed() -> None:
    sid, method, path, status, body = _real_api_response()
    result = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=body,
    )
    assert (
        result["api_consistency_source"]
        == REASONING_RUN_EXECUTION_AUDIT_PACKAGE_API_CONSISTENCY_SOURCE_TASK_050
    )


def test_package_consistent_false_still_api_consistent() -> None:
    """A valid API response whose Task 048 package_consistent is False
    must still produce api_consistent=True, as long as the API
    faithfully represents it.

    Task 048's validator requires
    package_consistent == bundle_consistency.bundle_consistent,
    and Task 047's validator (applied to bundle_consistency) requires
    bundle_consistency.bundle_consistent == len(consistency_issues)==0.
    So we flip both together and add a legitimate Task 047 issue.
    """
    sid, method, path, status, body = _real_api_response()
    tampered = copy.deepcopy(body)
    tampered["package_consistent"] = False
    tampered["bundle_consistency"]["bundle_consistent"] = False
    tampered["bundle_consistency"]["consistency_issues"] = ["NESTED_EXECUTION_MISMATCH"]

    result = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=tampered,
    )
    assert result["available"] is True
    assert result["api_consistent"] is True
    assert result["nested_package_consistent"] is True


# ---------------------------------------------------------------------------
# Method / path / status
# ---------------------------------------------------------------------------


def test_invalid_method() -> None:
    sid, _, path, status, body = _real_api_response()
    result = _service().build(
        session_id=sid,
        method="GET",
        path=path,
        status_code=status,
        response_body=body,
    )
    assert "INVALID_METHOD" in result["consistency_issues"]
    assert result["method_consistent"] is False


def test_invalid_path() -> None:
    sid, method, _, status, body = _real_api_response()
    result = _service().build(
        session_id=sid,
        method=method,
        path="/sessions/" + str(sid) + "/reasoning-run/execute",
        status_code=status,
        response_body=body,
    )
    assert "INVALID_PATH" in result["consistency_issues"]
    assert result["path_consistent"] is False


def test_invalid_path_uuid() -> None:
    sid, method, _, status, body = _real_api_response()
    result = _service().build(
        session_id=sid,
        method=method,
        path="/sessions/not-a-uuid/reasoning-run/execute-fully-audited",
        status_code=status,
        response_body=body,
    )
    assert "SESSION_ID_INVALID" in result["consistency_issues"]


def test_path_session_mismatch() -> None:
    sid, method, _, status, body = _real_api_response()
    other = uuid4()
    result = _service().build(
        session_id=sid,
        method=method,
        path=f"/sessions/{other}/reasoning-run/execute-fully-audited",
        status_code=status,
        response_body=body,
    )
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]


def test_invalid_status() -> None:
    sid, method, path, _, body = _real_api_response()
    result = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=500,
        response_body=body,
    )
    assert "INVALID_STATUS" in result["consistency_issues"]
    assert result["status_consistent"] is False


def test_invalid_body_session_id() -> None:
    sid, method, path, status, body = _real_api_response()
    tampered = copy.deepcopy(body)
    tampered["session_id"] = "not-a-uuid"
    result = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=tampered,
    )
    assert "SESSION_ID_INVALID" in result["consistency_issues"]


def test_body_session_mismatch() -> None:
    sid, method, path, status, body = _real_api_response()
    tampered = copy.deepcopy(body)
    tampered["session_id"] = str(uuid4())
    result = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=tampered,
    )
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


def test_missing_response_field() -> None:
    sid, method, path, status, body = _real_api_response()
    tampered = copy.deepcopy(body)
    del tampered["package_source"]
    result = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=tampered,
    )
    assert "MISSING_RESPONSE_FIELD" in result["consistency_issues"]
    assert result["response_shape_consistent"] is False


def test_extra_top_level_response_field() -> None:
    sid, method, path, status, body = _real_api_response()
    tampered = copy.deepcopy(body)
    tampered["extra_unknown_field"] = "unexpected"
    result = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=tampered,
    )
    assert "RESPONSE_SHAPE_MISMATCH" in result["consistency_issues"]
    assert result["response_shape_consistent"] is False


# ---------------------------------------------------------------------------
# Nested package
# ---------------------------------------------------------------------------


def test_malformed_nested_package() -> None:
    sid, method, path, status, body = _real_api_response()
    tampered = copy.deepcopy(body)
    # Break the nested execution bundle so Task 048's validator fails.
    del tampered["execution_bundle"]["bundle_source"]
    result = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=tampered,
    )
    assert "NESTED_PACKAGE_MISMATCH" in result["consistency_issues"]
    assert result["nested_package_consistent"] is False


def test_wrong_package_source() -> None:
    sid, method, path, status, body = _real_api_response()
    tampered = copy.deepcopy(body)
    tampered["package_source"] = "WRONG"
    result = _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=tampered,
    )
    assert "PACKAGE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


# ---------------------------------------------------------------------------
# Contract errors
# ---------------------------------------------------------------------------


def test_missing_response_body() -> None:
    with pytest.raises(
        ReasoningRunExecutionAuditPackageApiConsistencyContractError
    ) as ei:
        _service().build(
            session_id=uuid4(),
            method="POST",
            path="/sessions/x/reasoning-run/execute-fully-audited",
            status_code=200,
            response_body=None,
        )
    assert ei.value.invariant == "MISSING_RESPONSE_BODY"


def test_non_mapping_response_body() -> None:
    with pytest.raises(
        ReasoningRunExecutionAuditPackageApiConsistencyContractError
    ) as ei:
        _service().build(
            session_id=uuid4(),
            method="POST",
            path="/sessions/x/reasoning-run/execute-fully-audited",
            status_code=200,
            response_body="nope",  # type: ignore[arg-type]
        )
    assert ei.value.invariant == "RESPONSE_BODY_TYPE"


# ---------------------------------------------------------------------------
# Determinism, ordering, no mutation
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    sid, method, path, status, body = _real_api_response()
    s = _service()
    a = s.build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=body,
    )
    b = s.build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=body,
    )
    assert a == b


def test_deterministic_issue_ordering() -> None:
    sid, method, path, _, body = _real_api_response()
    tampered = copy.deepcopy(body)
    tampered["package_source"] = "WRONG"
    del tampered["execution_bundle"]["bundle_source"]
    result = _service().build(
        session_id=sid,
        method="GET",  # invalid method
        path=path,
        status_code=500,  # invalid status
        response_body=tampered,
    )
    # Canonical order.
    expected_order = [
        "INVALID_METHOD",
        "INVALID_STATUS",
        "NESTED_PACKAGE_MISMATCH",
        "PACKAGE_SOURCE_MISMATCH",
    ]
    assert result["consistency_issues"] == expected_order


def test_no_duplicate_issues() -> None:
    sid, method, _, _, body = _real_api_response()
    tampered = copy.deepcopy(body)
    tampered["session_id"] = "not-a-uuid"
    result = _service().build(
        session_id="not-a-uuid",
        method=method,
        path="/sessions/not-a-uuid/reasoning-run/execute-fully-audited",
        status_code=200,
        response_body=tampered,
    )
    assert result["consistency_issues"].count("SESSION_ID_INVALID") == 1


def test_input_not_mutated() -> None:
    sid, method, path, status, body = _real_api_response()
    before = copy.deepcopy(body)
    _service().build(
        session_id=sid,
        method=method,
        path=path,
        status_code=status,
        response_body=body,
    )
    assert body == before


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
    for forbidden in (
        "TestClient",
        "requests.",
        "httpx",
        "fastapi",
    ):
        assert forbidden not in src


def test_no_task048_build_for_session() -> None:
    src = inspect.getsource(mod)
    # The docstring mentions build_for_session; ensure the service
    # does not actually CALL it.
    import re as _re

    assert not _re.search(r"\.build_for_session\s*\(", src)


def test_no_task049_invocation() -> None:
    src = inspect.getsource(mod)
    # The path string "execute-fully-audited" is the route being
    # audited -- it appears in _PATH_PATTERN by design. We check that
    # the service does not import the API module or reference the
    # FastAPI router.
    for forbidden in (
        "from rop.api",
        "import rop.api",
        "sessions.py",
        "router.",
        "TestClient",
    ):
        assert forbidden not in src


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
# Round 2: exact method case sensitivity
# ---------------------------------------------------------------------------


def test_method_post_uppercase_is_consistent() -> None:
    sid, _, path, status, body = _real_api_response()
    result = _service().build(
        session_id=sid,
        method="POST",
        path=path,
        status_code=status,
        response_body=body,
    )
    assert result["method_consistent"] is True
    assert "INVALID_METHOD" not in result["consistency_issues"]


def test_method_lowercase_post_is_invalid() -> None:
    sid, _, path, status, body = _real_api_response()
    result = _service().build(
        session_id=sid,
        method="post",
        path=path,
        status_code=status,
        response_body=body,
    )
    assert result["method_consistent"] is False
    assert "INVALID_METHOD" in result["consistency_issues"]
    assert result["api_consistent"] is False


def test_method_titlecase_post_is_invalid() -> None:
    sid, _, path, status, body = _real_api_response()
    result = _service().build(
        session_id=sid,
        method="Post",
        path=path,
        status_code=status,
        response_body=body,
    )
    assert result["method_consistent"] is False
    assert "INVALID_METHOD" in result["consistency_issues"]


def test_method_mixedcase_post_is_invalid() -> None:
    sid, _, path, status, body = _real_api_response()
    result = _service().build(
        session_id=sid,
        method="pOsT",
        path=path,
        status_code=status,
        response_body=body,
    )
    assert result["method_consistent"] is False
    assert "INVALID_METHOD" in result["consistency_issues"]
