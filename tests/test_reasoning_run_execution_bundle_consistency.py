"""Tests for Task 047 execution + audit bundle consistency audit.

Task 047 is a pure audit layer over a supplied Task 046 bundle. It
does not execute Task 044, does not invoke Task 045's build(), does
not access the database, and does not mutate its input.
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
from rop.services import reasoning_run_execution_bundle_consistency as mod
from rop.services.reasoning_run_execution_bundle_consistency import (
    REASONING_RUN_EXECUTION_BUNDLE_CONSISTENCY_SOURCE_TASK_047,
    ReasoningRunExecutionBundleConsistencyContractError,
    ReasoningRunExecutionBundleConsistencyService,
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
    "nested_execution_consistent",
    "nested_execution_audit_consistent",
    "bundle_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "bundle_consistency_source",
)


def _service() -> ReasoningRunExecutionBundleConsistencyService:
    return ReasoningRunExecutionBundleConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-047-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _valid_bundle() -> dict[str, Any]:
    """Build a real Task 046 bundle via the API."""
    sid = _create_session("Patient reports chest pain")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute-audited")
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Valid bundles
# ---------------------------------------------------------------------------


def test_valid_completed_bundle_consistent() -> None:
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
        "nested_execution_consistent",
        "nested_execution_audit_consistent",
        "bundle_relationship_consistent",
        "source_consistency",
        "metadata_consistent",
    ):
        assert result[flag] is True, flag


def test_audit_source_fixed() -> None:
    bundle = _valid_bundle()
    result = _service().build(bundle=bundle)
    assert (
        result["bundle_consistency_source"]
        == REASONING_RUN_EXECUTION_BUNDLE_CONSISTENCY_SOURCE_TASK_047
    )


def test_valid_failed_execution_bundle() -> None:
    """A valid FAILED Task 044 execution must still produce a valid
    Task 047 audit with bundle_consistent=True."""
    from rop.services.observation_extraction import ObservationExtractionService

    original = ObservationExtractionService.extract_and_store

    def boom(self, db, session_id, text):
        raise RuntimeError("forced")

    ObservationExtractionService.extract_and_store = boom
    try:
        sid = _create_session("Patient reports chest pain")
        r = client.post(f"/sessions/{sid}/reasoning-run/execute-audited")
        assert r.status_code == 200
        bundle = r.json()
    finally:
        ObservationExtractionService.extract_and_store = original

    assert bundle["execution"]["outcome"] == "FAILED"
    result = _service().build(bundle=bundle)
    assert result["available"] is True
    assert result["bundle_consistent"] is True
    assert result["consistency_issues"] == []


def test_valid_bundle_with_task044_execution_consistent_false() -> None:
    """Task 044 execution_consistent may legitimately be False while the
    bundle itself is internally consistent."""
    from rop.services.observation_extraction import ObservationExtractionService

    original = ObservationExtractionService.extract_and_store

    def boom(self, db, session_id, text):
        raise RuntimeError("forced")

    ObservationExtractionService.extract_and_store = boom
    try:
        sid = _create_session("Patient reports chest pain")
        bundle = client.post(
            f"/sessions/{sid}/reasoning-run/execute-audited"
        ).json()
    finally:
        ObservationExtractionService.extract_and_store = original

    assert bundle["execution"]["execution_consistent"] is False
    assert bundle["execution_consistency"]["execution_consistent"] is True
    assert bundle["bundle_consistent"] is True
    result = _service().build(bundle=bundle)
    assert result["bundle_consistent"] is True


def test_valid_bundle_with_task045_execution_consistent_false() -> None:
    """A bundle whose Task 046 bundle_consistent=False (because Task 045
    legitimately flagged the execution) must still produce a Task 047
    bundle_consistent=True."""
    sid = _create_session("Patient reports chest pain")
    r = client.post(f"/sessions/{sid}/reasoning-run/execute")
    assert r.status_code == 200
    execution = r.json()

    # Tamper the nested Task 042 run_source so Task 045 flags it.
    execution["reasoning_run"]["run_source"] = "WRONG"

    from rop.services.reasoning_run_execution_consistency import (
        ReasoningRunExecutionConsistencyService,
    )

    audit = ReasoningRunExecutionConsistencyService().build(
        execution=execution
    )
    assert audit["execution_consistent"] is False

    from rop.services.reasoning_run_execution_bundle import (
        ReasoningRunExecutionBundleService,
    )

    bundle = ReasoningRunExecutionBundleService().build(
        session_id=UUID(sid),
        execution=execution,
        execution_consistency=audit,
    )
    assert bundle["bundle_consistent"] is False

    result = _service().build(bundle=bundle)
    # The Task 046 bundle contract itself is internally consistent even
    # though its bundle_consistent value is False.
    assert result["bundle_consistent"] is True
    assert result["consistency_issues"] == []


# ---------------------------------------------------------------------------
# Missing/invalid bundle fields
# ---------------------------------------------------------------------------


def test_missing_bundle() -> None:
    with pytest.raises(
        ReasoningRunExecutionBundleConsistencyContractError
    ) as ei:
        _service().build(bundle=None)
    assert ei.value.invariant == "MISSING_BUNDLE"


def test_non_mapping_bundle() -> None:
    with pytest.raises(
        ReasoningRunExecutionBundleConsistencyContractError
    ) as ei:
        _service().build(bundle="nope")  # type: ignore[arg-type]
    assert ei.value.invariant == "BUNDLE_TYPE"


def test_missing_bundle_field() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    del tampered["execution"]
    result = _service().build(bundle=tampered)
    assert "MISSING_BUNDLE_FIELD" in result["consistency_issues"]


def test_bundle_available_false() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["available"] = False
    result = _service().build(bundle=tampered)
    assert "INVALID_BUNDLE_AVAILABLE" in result["consistency_issues"]
    assert "BUNDLE_AVAILABILITY_MISMATCH" in result["consistency_issues"]
    assert result["metadata_consistent"] is False


def test_missing_nested_execution() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["execution"] = None
    result = _service().build(bundle=tampered)
    assert "NESTED_EXECUTION_MISMATCH" in result["consistency_issues"]
    assert result["nested_execution_consistent"] is False


def test_missing_nested_audit() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["execution_consistency"] = None
    result = _service().build(bundle=tampered)
    assert (
        "NESTED_EXECUTION_AUDIT_MISMATCH" in result["consistency_issues"]
    )
    assert result["nested_execution_audit_consistent"] is False


# ---------------------------------------------------------------------------
# Source mismatches
# ---------------------------------------------------------------------------


def test_invalid_bundle_source() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_source"] = "WRONG"
    result = _service().build(bundle=tampered)
    assert "BUNDLE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


def test_invalid_execution_source() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["execution"]["execution_source"] = "WRONG"
    result = _service().build(bundle=tampered)
    assert "EXECUTION_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


def test_invalid_audit_source() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["execution_consistency"]["execution_consistency_source"] = "WRONG"
    result = _service().build(bundle=tampered)
    assert (
        "EXECUTION_AUDIT_SOURCE_MISMATCH" in result["consistency_issues"]
    )
    assert result["source_consistency"] is False


# ---------------------------------------------------------------------------
# Session mismatch, audit unavailable, relationship mismatch
# ---------------------------------------------------------------------------


def test_session_id_mismatch() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["execution"]["session_id"] = str(uuid4())
    result = _service().build(bundle=tampered)
    assert "SESSION_ID_MISMATCH" in result["consistency_issues"]
    assert result["session_consistent"] is False


def test_session_id_invalid() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["session_id"] = "not-a-uuid"
    result = _service().build(bundle=tampered)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False


def test_audit_unavailable() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["execution_consistency"]["available"] = False
    result = _service().build(bundle=tampered)
    assert "AUDIT_UNAVAILABLE" in result["consistency_issues"]
    assert result["nested_execution_audit_consistent"] is False


def test_bundle_relationship_mismatch() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    # Task 046 bundle_consistent must mirror the nested Task 045
    # execution_consistent. Flip one so they disagree.
    tampered["bundle_consistent"] = not tampered["bundle_consistent"]
    result = _service().build(bundle=tampered)
    assert "BUNDLE_RELATIONSHIP_MISMATCH" in result["consistency_issues"]
    assert result["bundle_relationship_consistent"] is False


# ---------------------------------------------------------------------------
# Determinism, ordering, no mutation, no side effects
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    bundle = _valid_bundle()
    s = _service()
    assert s.build(bundle=bundle) == s.build(bundle=bundle)


def test_deterministic_issue_ordering() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["bundle_source"] = "WRONG"
    tampered["execution"]["execution_source"] = "WRONG"
    tampered["execution_consistency"]["execution_consistency_source"] = "WRONG"
    result = _service().build(bundle=tampered)
    # Tampering the nested source fields also trips the nested
    # validators, so we get five issues, ordered by the canonical
    # _ISSUE_ORDER:
    #   1. NESTED_EXECUTION_MISMATCH       (Task 044 validator rejects)
    #   2. NESTED_EXECUTION_AUDIT_MISMATCH (Task 045 validator rejects)
    #   3. EXECUTION_SOURCE_MISMATCH       (Task 047's own check)
    #   4. EXECUTION_AUDIT_SOURCE_MISMATCH (Task 047's own check)
    #   5. BUNDLE_SOURCE_MISMATCH          (Task 047's own check)
    expected_order = [
        "NESTED_EXECUTION_MISMATCH",
        "NESTED_EXECUTION_AUDIT_MISMATCH",
        "EXECUTION_SOURCE_MISMATCH",
        "EXECUTION_AUDIT_SOURCE_MISMATCH",
        "BUNDLE_SOURCE_MISMATCH",
    ]
    assert result["consistency_issues"] == expected_order


def test_no_duplicate_issues() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    # Both nested items invalid; each fires its own issue only once.
    tampered["execution"] = None
    tampered["execution_consistency"] = None
    result = _service().build(bundle=tampered)
    assert (
        result["consistency_issues"].count("NESTED_EXECUTION_MISMATCH") == 1
    )
    assert (
        result["consistency_issues"].count(
            "NESTED_EXECUTION_AUDIT_MISMATCH"
        ) == 1
    )


def test_input_not_mutated() -> None:
    bundle = _valid_bundle()
    before = copy.deepcopy(bundle)
    _service().build(bundle=bundle)
    assert bundle == before


def test_no_database_access() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "SessionLocal",
        "get_db",
        "session.query",
        "db.execute",
        "Repository(",
    ):
        assert forbidden not in src


def test_does_not_invoke_task044_execution() -> None:
    src = inspect.getsource(mod)
    assert "ReasoningRunExecutionService(" not in src
    assert "execute_for_session" not in src


def test_does_not_invoke_task045_build() -> None:
    src = inspect.getsource(mod)
    assert "ReasoningRunExecutionConsistencyService(" not in src
    assert "ReasoningRunExecutionConsistencyService().build" not in src


def test_does_not_invoke_task046() -> None:
    src = inspect.getsource(mod)
    assert "ReasoningRunExecutionBundleService(" not in src
    assert "build_for_session" not in src


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
    ):
        assert forbidden not in src.lower()


# ---------------------------------------------------------------------------
# Round 2: metadata_consistent and bundle_relationship_consistent must
# reflect their underlying structural relationships
# ---------------------------------------------------------------------------


def test_metadata_consistent_false_on_session_mismatch() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["execution"]["session_id"] = str(uuid4())
    result = _service().build(bundle=tampered)
    assert result["metadata_consistent"] is False
    assert result["session_consistent"] is False


def test_metadata_consistent_false_on_missing_execution() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["execution"] = None
    result = _service().build(bundle=tampered)
    assert result["metadata_consistent"] is False


def test_metadata_consistent_false_on_missing_audit() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["execution_consistency"] = None
    result = _service().build(bundle=tampered)
    assert result["metadata_consistent"] is False


def test_metadata_consistent_false_on_invalid_bundle_available() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["available"] = False
    result = _service().build(bundle=tampered)
    assert result["metadata_consistent"] is False


def test_bundle_relationship_consistent_false_when_audit_missing() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    tampered["execution_consistency"] = None
    result = _service().build(bundle=tampered)
    assert result["bundle_relationship_consistent"] is False
    assert "BUNDLE_RELATIONSHIP_MISMATCH" in result["consistency_issues"]


def test_bundle_relationship_consistent_false_when_audit_consistent_not_bool() -> None:
    bundle = _valid_bundle()
    tampered = copy.deepcopy(bundle)
    # Force the nested execution_consistent field to be non-bool so the
    # relationship cannot be checked.
    tampered["execution_consistency"]["execution_consistent"] = "yes"
    result = _service().build(bundle=tampered)
    assert result["bundle_relationship_consistent"] is False


def test_bundle_relationship_consistent_true_for_valid_bundle() -> None:
    bundle = _valid_bundle()
    result = _service().build(bundle=bundle)
    assert result["bundle_relationship_consistent"] is True


def test_metadata_consistent_true_for_valid_bundle() -> None:
    bundle = _valid_bundle()
    result = _service().build(bundle=bundle)
    assert result["metadata_consistent"] is True
