"""Tests for Task 045 reasoning run execution consistency audit.

Task 045 is a pure audit layer: it consumes a Task 044 execution
result and independently derives every consistency relationship. It
does not query the database, does not execute Task 044, and does not
mutate its input.
"""

from __future__ import annotations

import copy
import inspect
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base
from rop.main import app
from rop.services import reasoning_run_execution_consistency as mod
from rop.services.reasoning_run_execution_consistency import (
    REASONING_RUN_EXECUTION_CONSISTENCY_SOURCE_TASK_045,
    ReasoningRunExecutionConsistencyService,
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
    "execution_consistent",
    "session_consistent",
    "outcome_consistent",
    "availability_consistent",
    "stage_structure_consistent",
    "stage_status_consistent",
    "stage_count_consistent",
    "completed_stage_count_consistent",
    "nested_reasoning_run_consistent",
    "nested_reasoning_run_audit_consistent",
    "metadata_consistent",
    "source_consistency",
    "consistency_issues",
    "execution_consistency_source",
)


def _service() -> ReasoningRunExecutionConsistencyService:
    return ReasoningRunExecutionConsistencyService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-045-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _execute_via_api(session_id: str) -> dict[str, Any]:
    r = client.post(f"/sessions/{session_id}/reasoning-run/execute")
    assert r.status_code == 200
    return r.json()


def _make_valid_execution() -> dict[str, Any]:
    """Build a real Task 044 execution result via the public API."""
    sid = _create_session("Patient reports chest pain")
    return _execute_via_api(sid)


# ---------------------------------------------------------------------------
# Valid executions
# ---------------------------------------------------------------------------


def test_valid_execution_audit_consistent() -> None:
    execution = _make_valid_execution()
    result = _service().build(execution=execution)
    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["execution_consistent"] is True
    assert result["consistency_issues"] == []


def test_valid_execution_all_flags_true() -> None:
    execution = _make_valid_execution()
    result = _service().build(execution=execution)
    for flag in (
        "session_consistent",
        "outcome_consistent",
        "availability_consistent",
        "stage_structure_consistent",
        "stage_status_consistent",
        "stage_count_consistent",
        "completed_stage_count_consistent",
        "nested_reasoning_run_consistent",
        "nested_reasoning_run_audit_consistent",
        "metadata_consistent",
        "source_consistency",
    ):
        assert result[flag] is True, flag


def test_audit_source_fixed() -> None:
    execution = _make_valid_execution()
    result = _service().build(execution=execution)
    assert (
        result["execution_consistency_source"]
        == REASONING_RUN_EXECUTION_CONSISTENCY_SOURCE_TASK_045
    )


def test_valid_failed_execution() -> None:
    """A real failed execution (extraction raises) must audit successfully
    with execution_consistent=False and the correct issue set."""
    from rop.services.observation_extraction import ObservationExtractionService

    original = ObservationExtractionService.extract_and_store

    def boom(self, db, session_id, text):
        raise RuntimeError("forced failure")

    ObservationExtractionService.extract_and_store = boom
    try:
        sid = _create_session("Patient reports chest pain")
        execution = _execute_via_api(sid)
    finally:
        ObservationExtractionService.extract_and_store = original

    assert execution["outcome"] == "FAILED"
    result = _service().build(execution=execution)
    assert result["available"] is True
    assert result["execution_consistent"] is True
    assert result["consistency_issues"] == []


# ---------------------------------------------------------------------------
# Stage structure failures
# ---------------------------------------------------------------------------


def test_wrong_stage_id() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["stages"][0]["stage_id"] = "WHATEVER"
    result = _service().build(execution=tampered)
    assert "STAGE_STRUCTURE_MISMATCH" in result["consistency_issues"]
    assert result["stage_structure_consistent"] is False


def test_duplicate_stage_id() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["stages"][1]["stage_id"] = tampered["stages"][0]["stage_id"]
    result = _service().build(execution=tampered)
    assert "STAGE_STRUCTURE_MISMATCH" in result["consistency_issues"]


def test_wrong_stage_order() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["stages"][1]["stage_order"] = 99
    result = _service().build(execution=tampered)
    assert "STAGE_ORDER_MISMATCH" in result["consistency_issues"]


def test_wrong_stage_source() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["stages"][0]["stage_source"] = "WRONG"
    result = _service().build(execution=tampered)
    assert "STAGE_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


def test_invalid_stage_status() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["stages"][0]["status"] = "NONSENSE"
    result = _service().build(execution=tampered)
    assert "STAGE_STATUS_MISMATCH" in result["consistency_issues"]


def test_missing_stage_field() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    del tampered["stages"][0]["status"]
    result = _service().build(execution=tampered)
    assert "STAGE_STRUCTURE_MISMATCH" in result["consistency_issues"]


def test_wrong_number_of_stages() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["stages"] = tampered["stages"][:5]
    result = _service().build(execution=tampered)
    assert "STAGE_STRUCTURE_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Count failures
# ---------------------------------------------------------------------------


def test_incorrect_stage_count() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["stage_count"] = 99
    result = _service().build(execution=tampered)
    assert "STAGE_COUNT_MISMATCH" in result["consistency_issues"]


def test_incorrect_completed_stage_count() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["completed_stage_count"] = 0
    result = _service().build(execution=tampered)
    assert "COMPLETED_STAGE_COUNT_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Outcome failures
# ---------------------------------------------------------------------------


def test_completed_but_stage_failed() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["stages"][2]["status"] = "FAILED"
    result = _service().build(execution=tampered)
    assert "OUTCOME_MISMATCH" in result["consistency_issues"]


def test_completed_but_stage_skipped() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["stages"][2]["status"] = "SKIPPED"
    result = _service().build(execution=tampered)
    assert "OUTCOME_MISMATCH" in result["consistency_issues"]


def test_completed_with_available_false() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["available"] = False
    result = _service().build(execution=tampered)
    assert "AVAILABILITY_MISMATCH" in result["consistency_issues"]


def test_failed_with_available_true() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["outcome"] = "FAILED"
    # Also strip nested results so only this check fires.
    tampered["reasoning_run"] = None
    tampered["reasoning_run_consistency"] = None
    tampered["execution_consistent"] = False
    tampered["available"] = True
    result = _service().build(execution=tampered)
    assert "AVAILABILITY_MISMATCH" in result["consistency_issues"]


def test_failed_with_multiple_failed_stages() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["outcome"] = "FAILED"
    tampered["available"] = False
    tampered["reasoning_run"] = None
    tampered["reasoning_run_consistency"] = None
    tampered["execution_consistent"] = False
    for i in range(len(tampered["stages"])):
        tampered["stages"][i]["status"] = "FAILED"
    result = _service().build(execution=tampered)
    assert "OUTCOME_MISMATCH" in result["consistency_issues"]


def test_failed_with_completed_stage_after_failure() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["outcome"] = "FAILED"
    tampered["available"] = False
    tampered["reasoning_run"] = None
    tampered["reasoning_run_consistency"] = None
    tampered["execution_consistent"] = False
    tampered["stages"][0]["status"] = "COMPLETED"
    tampered["stages"][1]["status"] = "FAILED"
    tampered["stages"][2]["status"] = "COMPLETED"
    for i in range(3, len(tampered["stages"])):
        tampered["stages"][i]["status"] = "SKIPPED"
    result = _service().build(execution=tampered)
    assert "OUTCOME_MISMATCH" in result["consistency_issues"]


def test_failed_with_nested_run_present() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["outcome"] = "FAILED"
    tampered["available"] = False
    tampered["execution_consistent"] = False
    tampered["stages"][0]["status"] = "COMPLETED"
    tampered["stages"][1]["status"] = "FAILED"
    for i in range(2, len(tampered["stages"])):
        tampered["stages"][i]["status"] = "SKIPPED"
    # reasoning_run remains populated -- invalid for a FAILED outcome.
    result = _service().build(execution=tampered)
    assert "OUTCOME_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Nested contract failures
# ---------------------------------------------------------------------------


def test_malformed_task042_result() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    # Break the nested Task 042 run's stage order, which Task 042's own
    # validator enforces (it does not enforce canonical stage-id names,
    # only non-empty strings).
    tampered["reasoning_run"]["stages"][0]["stage_order"] = 99
    result = _service().build(execution=tampered)
    assert "NESTED_REASONING_RUN_MISMATCH" in result["consistency_issues"]
    assert result["nested_reasoning_run_consistent"] is False


def test_wrong_nested_task042_source() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["reasoning_run"]["run_source"] = "WRONG"
    result = _service().build(execution=tampered)
    assert "NESTED_REASONING_RUN_MISMATCH" in result["consistency_issues"]


def test_malformed_task043_result() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    # Break the nested Task 043 audit's structure.
    tampered["reasoning_run_consistency"]["consistency_issues"] = "nope"
    result = _service().build(execution=tampered)
    assert (
        "NESTED_REASONING_RUN_AUDIT_MISMATCH" in result["consistency_issues"]
    )
    assert result["nested_reasoning_run_audit_consistent"] is False


def test_wrong_nested_task043_source() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["reasoning_run_consistency"]["run_consistency_source"] = "WRONG"
    result = _service().build(execution=tampered)
    assert (
        "NESTED_REASONING_RUN_AUDIT_MISMATCH" in result["consistency_issues"]
    )


def test_execution_consistent_disagrees_with_nested_task043() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    # Nested Task 043 says run_consistent=False, but the top-level
    # execution_consistent says True.
    tampered["reasoning_run_consistency"]["run_consistent"] = False
    tampered["execution_consistent"] = True
    result = _service().build(execution=tampered)
    assert "EXECUTION_CONSISTENCY_MISMATCH" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Source failures
# ---------------------------------------------------------------------------


def test_wrong_task044_execution_source() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["execution_source"] = "WRONG"
    result = _service().build(execution=tampered)
    assert "EXECUTION_SOURCE_MISMATCH" in result["consistency_issues"]
    assert result["source_consistency"] is False


# ---------------------------------------------------------------------------
# Session id
# ---------------------------------------------------------------------------


def test_invalid_session_id() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["session_id"] = "not-a-uuid"
    result = _service().build(execution=tampered)
    assert "SESSION_ID_INVALID" in result["consistency_issues"]
    assert result["session_consistent"] is False


# ---------------------------------------------------------------------------
# Missing fields
# ---------------------------------------------------------------------------


def test_missing_execution_field() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    del tampered["stages"]
    result = _service().build(execution=tampered)
    assert "MISSING_EXECUTION_FIELD" in result["consistency_issues"]


def test_invalid_execution_outcome() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["outcome"] = "NONSENSE"
    result = _service().build(execution=tampered)
    assert "INVALID_EXECUTION_OUTCOME" in result["consistency_issues"]


def test_session_not_found_outcome_rejected() -> None:
    """SESSION_NOT_FOUND is not a valid Task 044 result -- Task 044
    raises for it. A supplied result carrying it must be flagged."""
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["outcome"] = "SESSION_NOT_FOUND"
    result = _service().build(execution=tampered)
    assert "INVALID_EXECUTION_OUTCOME" in result["consistency_issues"]


# ---------------------------------------------------------------------------
# Contract behavior
# ---------------------------------------------------------------------------


def test_deterministic_issue_ordering() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["execution_source"] = "WRONG"
    tampered["stages"][0]["stage_source"] = "WRONG"
    tampered["stage_count"] = 99
    result = _service().build(execution=tampered)
    # Expect the issues in the canonical _ISSUE_ORDER.
    expected_order = [
        "STAGE_SOURCE_MISMATCH",
        "STAGE_COUNT_MISMATCH",
        "EXECUTION_SOURCE_MISMATCH",
    ]
    assert result["consistency_issues"] == expected_order


def test_no_duplicate_issues() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    # Multiple stage sources wrong -> still a single STAGE_SOURCE_MISMATCH.
    tampered["stages"][0]["stage_source"] = "WRONG"
    tampered["stages"][1]["stage_source"] = "WRONG"
    result = _service().build(execution=tampered)
    assert (
        result["consistency_issues"].count("STAGE_SOURCE_MISMATCH") == 1
    )


def test_input_not_mutated() -> None:
    execution = _make_valid_execution()
    before = copy.deepcopy(execution)
    _service().build(execution=execution)
    assert execution == before


def test_no_database_access() -> None:
    """The service must not import or use Session or repositories."""
    src = inspect.getsource(mod)
    for forbidden in (
        "SessionLocal",
        "get_db",
        "session.query",
        "db.execute",
        "Repository(",
    ):
        assert forbidden not in src


def test_no_task044_invocation() -> None:
    """The service must not call ReasoningRunExecutionService."""
    src = inspect.getsource(mod)
    assert "ReasoningRunExecutionService." not in src
    assert "execute_for_session" not in src


def test_no_candidate_generation() -> None:
    src = inspect.getsource(mod)
    assert "CandidateGeneration" not in src


def test_no_evidence_evaluation() -> None:
    src = inspect.getsource(mod)
    assert "EvidenceEvaluation" not in src


def test_no_decision_policy() -> None:
    src = inspect.getsource(mod)
    assert "DecisionPolicy" not in src
    assert "required_candidate_count" not in src


def test_no_llm_or_rag() -> None:
    src = inspect.getsource(mod)
    for forbidden in (
        "openai",
        "gemini",
        "ollama",
        "llm",
        "rag",
        "web_search",
    ):
        assert forbidden not in src.lower()


def test_valid_execution_with_inconsistent_run_audit() -> None:
    """A valid Task 043 audit that legitimately reports run_consistent=False
    must not be treated as malformed; it should flow through to
    execution_consistent=False."""
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    # Flip a nested Task 042 stage flag so the nested Task 043
    # run_consistent legitimately becomes False. Task 042's validator
    # would reject a manual tampering that breaks its own invariants,
    # so we tamper a stage's `consistent` flag (permitted by Task 042
    # since it only checks that run_consistent reflects the AND of
    # stage consistency).
    tampered["reasoning_run"]["stages"][0]["consistent"] = False
    tampered["reasoning_run"]["run_consistent"] = False
    tampered["reasoning_run_consistency"]["run_consistent"] = False
    tampered["reasoning_run_consistency"]["execution_consistent"] = False
    tampered["execution_consistent"] = False
    result = _service().build(execution=tampered)
    # The nested Task 042 result may still be structurally valid.
    # Either way, execution_consistent must reflect the nested audit
    # run_consistent (False).
    assert result["execution_consistent"] is False


# ---------------------------------------------------------------------------
# Round 2 fixes: source_consistency, outcome_consistent, nested flags,
# real failed-stage coverage
# ---------------------------------------------------------------------------


def test_source_consistency_false_on_wrong_task042_source() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["reasoning_run"]["run_source"] = "WRONG"
    result = _service().build(execution=tampered)
    assert result["source_consistency"] is False


def test_source_consistency_false_on_wrong_task043_source() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["reasoning_run_consistency"]["run_consistency_source"] = "WRONG"
    result = _service().build(execution=tampered)
    assert result["source_consistency"] is False


def test_outcome_consistent_false_on_invalid_outcome() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["outcome"] = "NONSENSE"
    result = _service().build(execution=tampered)
    assert "INVALID_EXECUTION_OUTCOME" in result["consistency_issues"]
    assert result["outcome_consistent"] is False


def test_missing_nested_run_flips_flag_on_completed() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["reasoning_run"] = None
    result = _service().build(execution=tampered)
    assert result["nested_reasoning_run_consistent"] is False


def test_missing_nested_audit_flips_flag_on_completed() -> None:
    execution = _make_valid_execution()
    tampered = copy.deepcopy(execution)
    tampered["reasoning_run_consistency"] = None
    result = _service().build(execution=tampered)
    assert result["nested_reasoning_run_audit_consistent"] is False


# ---------------------------------------------------------------------------
# Real failed-stage coverage: force Task 044 to fail at each stage
# ---------------------------------------------------------------------------


def _force_failure(
    monkeypatch,
    stage_id: str,
) -> None:
    """Monkeypatch the service that owns the given stage to raise."""
    from rop.services.candidate_generation import CandidateGenerationService
    from rop.services.evidence_evaluation import EvidenceEvaluationService
    from rop.services.missing_information import MissingInformationService
    from rop.services.observation_extraction import (
        ObservationExtractionService,
    )
    from rop.services.reasoning_run import ReasoningRunService
    from rop.services.reasoning_run_consistency import (
        ReasoningRunConsistencyService,
    )
    from rop.services.template_match import TemplateMatchService

    def boom(*args, **kwargs):
        raise RuntimeError("forced failure at " + stage_id)

    if stage_id == "OBSERVATION_EXTRACTION":
        monkeypatch.setattr(
            ObservationExtractionService, "extract_and_store", boom
        )
    elif stage_id == "MISSING_INFORMATION":
        monkeypatch.setattr(
            MissingInformationService, "detect_and_store", boom
        )
    elif stage_id == "TEMPLATE_MATCHING":
        monkeypatch.setattr(TemplateMatchService, "match", boom)
    elif stage_id == "CANDIDATE_GENERATION":
        monkeypatch.setattr(CandidateGenerationService, "generate", boom)
    elif stage_id == "EVIDENCE_EVALUATION":
        monkeypatch.setattr(
            EvidenceEvaluationService, "evaluate_session", boom
        )
    elif stage_id == "REASONING_RUN":
        monkeypatch.setattr(
            ReasoningRunService, "build_for_session", boom
        )
    elif stage_id == "REASONING_RUN_CONSISTENCY":
        monkeypatch.setattr(
            ReasoningRunConsistencyService, "build_for_session", boom
        )
    else:
        raise AssertionError("unknown stage_id: " + stage_id)


_FAILING_STAGES = (
    "OBSERVATION_EXTRACTION",
    "MISSING_INFORMATION",
    "TEMPLATE_MATCHING",
    "CANDIDATE_GENERATION",
    "EVIDENCE_EVALUATION",
    "REASONING_RUN",
    "REASONING_RUN_CONSISTENCY",
)


@pytest.mark.parametrize("failing_stage", _FAILING_STAGES)
def test_real_failed_execution_each_stage(
    monkeypatch, failing_stage
) -> None:
    """Force Task 044 to fail at each stage after SESSION_VERIFIED.
    The resulting FAILED execution must audit as structurally
    consistent."""
    _force_failure(monkeypatch, failing_stage)

    sid = _create_session("Patient reports chest pain")
    execution = _execute_via_api(sid)

    # Task 044 produced a valid FAILED execution.
    assert execution["outcome"] == "FAILED"
    assert execution["available"] is False
    assert execution["reasoning_run"] is None
    assert execution["reasoning_run_consistency"] is None
    assert execution["execution_consistent"] is False

    failing_index = execution["stages"].index(
        next(
            s
            for s in execution["stages"]
            if s["stage_id"] == failing_stage
        )
    )
    failed_count = sum(
        1 for s in execution["stages"] if s["status"] == "FAILED"
    )
    assert failed_count == 1
    for i, s in enumerate(execution["stages"]):
        if i < failing_index:
            assert s["status"] == "COMPLETED", (failing_stage, s)
        elif i == failing_index:
            assert s["status"] == "FAILED"
        else:
            assert s["status"] == "SKIPPED", (failing_stage, s)

    # Task 045 audits the FAILED execution as structurally consistent.
    result = _service().build(execution=execution)
    assert result["available"] is True
    assert result["execution_consistent"] is True
    assert result["consistency_issues"] == []
