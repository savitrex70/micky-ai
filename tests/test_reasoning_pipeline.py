"""Tests for Task 041 end-to-end reasoning pipeline composition.

Task 041 composes the established decision-pipeline stages (031-040)
into one inspectable view. It introduces no new reasoning, no
re-selection, and no mutation.
"""

from __future__ import annotations

import copy
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
from rop.services.reasoning_pipeline import (
    PIPELINE_SOURCE_REASONING_PIPELINE_TASK_041,
    ReasoningPipelineContractError,
    ReasoningPipelineService,
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
    "pipeline_consistent",
    "pipeline_complete",
    "stage_count",
    "completed_stage_count",
    "stages",
    "final_execution",
    "final_execution_consistency",
    "pipeline_source",
)

STAGE_FIELDS = (
    "stage_id",
    "stage_order",
    "stage_source",
    "available",
    "consistent",
    "complete",
)

EXPECTED_STAGE_IDS = [
    "031_DECISION_CONTEXT",
    "032_DECISION_CANDIDATE_EVALUATION",
    "033_DECISION_EVALUATION_CONSISTENCY",
    "034_DECISION_INPUT_ELIGIBILITY",
    "035_DECISION_CANDIDATE_SET",
    "036_DECISION_CANDIDATE_ASSESSMENT",
    "037_DECISION_INPUT_BUNDLE",
    "038_DECISION_POLICY",
    "039_DECISION_EXECUTION",
    "040_DECISION_EXECUTION_CONSISTENCY",
]


def _service() -> ReasoningPipelineService:
    return ReasoningPipelineService()


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "reasoning-pipeline-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_session(user_input: str) -> str:
    sid = _create_session(user_input)
    obs = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert obs.status_code == 201
    g = client.post(f"/sessions/{sid}/generate-candidates")
    assert g.status_code == 201
    assert len(g.json()) > 0
    e = client.post(f"/sessions/{sid}/evaluate-evidence")
    assert e.status_code == 200
    return sid


def _build_for(session_id: str) -> dict[str, Any]:
    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        return _service().build_for_session(db, session_uuid, candidates)
    finally:
        db_gen.close()


# ---------------------------------------------------------------------------
# Valid pipeline
# ---------------------------------------------------------------------------


def test_valid_pipeline_shape() -> None:
    sid = _seed_session("Task 041 shape")
    result = _build_for(sid)
    assert set(result) == set(RESULT_FIELDS)


def test_pipeline_source_fixed() -> None:
    sid = _seed_session("Task 041 source")
    result = _build_for(sid)
    assert (
        result["pipeline_source"]
        == PIPELINE_SOURCE_REASONING_PIPELINE_TASK_041
    )


def test_stage_count_and_ids() -> None:
    sid = _seed_session("Task 041 stages")
    result = _build_for(sid)
    assert result["stage_count"] == 10
    ids = [s["stage_id"] for s in result["stages"]]
    assert ids == EXPECTED_STAGE_IDS


def test_stage_orders_are_sequential() -> None:
    sid = _seed_session("Task 041 stage order")
    result = _build_for(sid)
    for i, s in enumerate(result["stages"]):
        assert s["stage_order"] == i + 1
        assert set(s) == set(STAGE_FIELDS)


def test_completed_stage_count_matches() -> None:
    sid = _seed_session("Task 041 completed")
    result = _build_for(sid)
    actual = sum(1 for s in result["stages"] if s["complete"])
    assert result["completed_stage_count"] == actual


def test_pipeline_flags_consistent_with_stages() -> None:
    sid = _seed_session("Task 041 flags")
    result = _build_for(sid)
    assert result["pipeline_complete"] == all(
        s["complete"] for s in result["stages"]
    )
    assert result["pipeline_consistent"] == all(
        s["consistent"] for s in result["stages"]
    )


def test_final_execution_preserved() -> None:
    sid = _seed_session("Task 041 final exec")
    result = _build_for(sid)
    assert set(result["final_execution"]) == {
        "available",
        "outcome",
        "selected_candidate",
        "eligible_candidate_count",
        "eligible_candidate_ids",
        "policy_id",
        "policy_version",
        "decision_execution_source",
    }


def test_final_audit_preserved() -> None:
    sid = _seed_session("Task 041 final audit")
    result = _build_for(sid)
    assert set(result["final_execution_consistency"]) == {
        "available",
        "execution_consistent",
        "outcome_consistent",
        "eligibility_consistent",
        "selection_consistent",
        "metadata_consistent",
        "source_consistent",
        "consistency_issues",
        "execution_source",
    }


def test_each_stage_source_is_upstream_identifier() -> None:
    sid = _seed_session("Task 041 stage sources")
    result = _build_for(sid)
    expected_sources = {
        "031_DECISION_CONTEXT": "DECISION_CONTEXT_TASK_031",
        "032_DECISION_CANDIDATE_EVALUATION":
            "DECISION_CANDIDATE_EVALUATION_TASK_032",
        "033_DECISION_EVALUATION_CONSISTENCY":
            "DECISION_EVALUATION_CONSISTENCY_TASK_033",
        "034_DECISION_INPUT_ELIGIBILITY":
            "DECISION_INPUT_ELIGIBILITY_TASK_034",
        "035_DECISION_CANDIDATE_SET": "DECISION_CANDIDATE_SET_TASK_035",
        "036_DECISION_CANDIDATE_ASSESSMENT":
            "DECISION_CANDIDATE_ASSESSMENT_TASK_036",
        "037_DECISION_INPUT_BUNDLE": "DECISION_INPUT_BUNDLE_TASK_037",
        "038_DECISION_POLICY": "DECISION_POLICY_TASK_038",
        "039_DECISION_EXECUTION": "DECISION_EXECUTION_TASK_039",
        "040_DECISION_EXECUTION_CONSISTENCY":
            "DECISION_EXECUTION_CONSISTENCY_TASK_040",
    }
    for s in result["stages"]:
        assert s["stage_source"] == expected_sources[s["stage_id"]]


# ---------------------------------------------------------------------------
# Final execution outcomes
# ---------------------------------------------------------------------------


def test_empty_session_remains_available() -> None:
    """An empty session produces INPUT_UNAVAILABLE at Task 039 but the
    Task 041 composition itself must still be available."""
    sid = _create_session("Task 041 empty")
    result = _build_for(sid)
    assert result["available"] is True
    assert result["final_execution"]["outcome"] == "INPUT_UNAVAILABLE"
    assert result["final_execution"]["available"] is False


def test_selected_outcome_visible() -> None:
    sid = _seed_session("Task 041 selected")
    result = _build_for(sid)
    assert result["final_execution"]["outcome"] in (
        "SELECTED",
        "NO_ELIGIBLE_CANDIDATE",
        "UNRESOLVED",
    )
    # Whatever it is, the audit should be consistent with it.
    assert result["final_execution_consistency"]["execution_consistent"] is True


# ---------------------------------------------------------------------------
# Determinism / no mutation
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    sid = _seed_session("Task 041 deterministic")
    first = _build_for(sid)
    second = _build_for(sid)
    assert first == second


# ---------------------------------------------------------------------------
# Contract failures
# ---------------------------------------------------------------------------


def _valid_inputs() -> dict[str, Any]:
    """Build the full set of composed upstream results for one session."""
    sid = _seed_session("Task 041 raw inputs")
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService
        from rop.services.decision_candidate_assessment import (
            DecisionCandidateAssessmentService,
        )
        from rop.services.decision_candidate_evaluation import (
            DecisionCandidateEvaluationService,
        )
        from rop.services.decision_candidate_set import (
            DecisionCandidateSetService,
        )
        from rop.services.decision_context import DecisionContextService
        from rop.services.decision_evaluation_consistency import (
            DecisionEvaluationConsistencyService,
        )
        from rop.services.decision_execution import DecisionExecutionService
        from rop.services.decision_execution_consistency import (
            DecisionExecutionConsistencyService,
        )
        from rop.services.decision_input_bundle import (
            DecisionInputBundleService,
        )
        from rop.services.decision_input_eligibility import (
            DecisionInputEligibilityService,
        )
        from rop.services.decision_policy import DecisionPolicyService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        ctx_svc = DecisionContextService()
        eval_svc = DecisionCandidateEvaluationService(ctx_svc)
        cons_svc = DecisionEvaluationConsistencyService(eval_svc)
        elig_svc = DecisionInputEligibilityService(cons_svc)
        cs_svc = DecisionCandidateSetService(elig_svc)
        asmt_svc = DecisionCandidateAssessmentService(cs_svc)
        bundle_svc = DecisionInputBundleService(cs_svc, asmt_svc)
        policy_svc = DecisionPolicyService(bundle_svc)
        exec_svc = DecisionExecutionService(bundle_svc, policy_svc)
        audit_svc = DecisionExecutionConsistencyService(
            bundle_svc, policy_svc, exec_svc
        )

        context = ctx_svc.build_for_session(db, session_uuid, candidates)
        expected = [e["hypothesis_id"] for e in context["differential"]]
        evaluations = eval_svc.evaluate(context)
        consistency = cons_svc.check(evaluations, expected)
        eligibility = elig_svc.build(context, consistency)
        candidate_set = cs_svc.build(context, eligibility)
        assessment = asmt_svc.build(candidate_set, evaluations, consistency)
        bundle = bundle_svc.build(candidate_set, assessment)
        policy = policy_svc.build()
        execution = exec_svc.build(bundle, policy)
        audit = audit_svc.build(bundle, policy, execution)
        return {
            "context": context,
            "evaluations": evaluations,
            "consistency": consistency,
            "eligibility": eligibility,
            "candidate_set": candidate_set,
            "assessment": assessment,
            "bundle": bundle,
            "policy": policy,
            "execution": execution,
            "audit": audit,
        }
    finally:
        db_gen.close()


def test_missing_context_rejected() -> None:
    inputs = _valid_inputs()
    inputs["context"] = None
    with pytest.raises(ReasoningPipelineContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "MISSING_CONTEXT"


def test_missing_execution_rejected() -> None:
    inputs = _valid_inputs()
    inputs["execution"] = None
    with pytest.raises(ReasoningPipelineContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "MISSING_EXECUTION"


def test_malformed_execution_rejected() -> None:
    inputs = _valid_inputs()
    inputs["execution"] = "not-a-mapping"
    with pytest.raises(ReasoningPipelineContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "EXECUTION_TYPE"


def test_malformed_final_execution_missing_field_rejected() -> None:
    inputs = _valid_inputs()
    broken = copy.deepcopy(inputs["execution"])
    del broken["outcome"]
    inputs["execution"] = broken
    with pytest.raises(ReasoningPipelineContractError) as ei:
        _service().build(**inputs)
    assert ei.value.invariant == "INVALID_FINAL_EXECUTION"


def test_invalid_stage_source_rejected() -> None:
    inputs = _valid_inputs()
    # Tamper with a raw upstream mapping so its source no longer matches.
    broken_bundle = copy.deepcopy(inputs["bundle"])
    broken_bundle["input_source"] = "WRONG"
    inputs["bundle"] = broken_bundle
    # Bundle's own Task 037 validator will reject; the wrapper error
    # depends on which stage notices it first, but rejection is required.
    with pytest.raises(ReasoningPipelineContractError):
        _service().build(**inputs)


# ---------------------------------------------------------------------------
# Output validator hardening
# ---------------------------------------------------------------------------


def _valid_result() -> dict[str, Any]:
    inputs = _valid_inputs()
    return _service().build(**inputs)


def test_tamper_duplicate_stage_id_rejected() -> None:
    inputs = _valid_inputs()
    result = _service().build(**inputs)
    # Re-run the validator directly on a tampered result.
    tampered = copy.deepcopy(result)
    tampered["stages"][1]["stage_id"] = tampered["stages"][0]["stage_id"]
    with pytest.raises(ReasoningPipelineContractError) as ei:
        ReasoningPipelineService._validate_result(
            tampered, inputs["execution"], inputs["audit"]
        )
    assert ei.value.invariant == "DUPLICATE_STAGE_ID"


def test_tamper_stage_order_rejected() -> None:
    inputs = _valid_inputs()
    result = _service().build(**inputs)
    tampered = copy.deepcopy(result)
    tampered["stages"][1]["stage_order"] = 99
    with pytest.raises(ReasoningPipelineContractError) as ei:
        ReasoningPipelineService._validate_result(
            tampered, inputs["execution"], inputs["audit"]
        )
    assert ei.value.invariant == "STAGE_ORDER_MISMATCH"


def test_tamper_stage_count_rejected() -> None:
    inputs = _valid_inputs()
    result = _service().build(**inputs)
    tampered = copy.deepcopy(result)
    tampered["stage_count"] = 99
    with pytest.raises(ReasoningPipelineContractError) as ei:
        ReasoningPipelineService._validate_result(
            tampered, inputs["execution"], inputs["audit"]
        )
    assert ei.value.invariant == "STAGE_COUNT_MISMATCH"


def test_tamper_completed_count_rejected() -> None:
    inputs = _valid_inputs()
    result = _service().build(**inputs)
    tampered = copy.deepcopy(result)
    tampered["completed_stage_count"] = 0
    with pytest.raises(ReasoningPipelineContractError) as ei:
        ReasoningPipelineService._validate_result(
            tampered, inputs["execution"], inputs["audit"]
        )
    assert ei.value.invariant == "COMPLETED_COUNT_MISMATCH"


def test_tamper_pipeline_complete_rejected() -> None:
    inputs = _valid_inputs()
    result = _service().build(**inputs)
    tampered = copy.deepcopy(result)
    tampered["pipeline_complete"] = not tampered["pipeline_complete"]
    with pytest.raises(ReasoningPipelineContractError) as ei:
        ReasoningPipelineService._validate_result(
            tampered, inputs["execution"], inputs["audit"]
        )
    assert ei.value.invariant == "PIPELINE_COMPLETE_MISMATCH"


def test_tamper_pipeline_consistent_rejected() -> None:
    inputs = _valid_inputs()
    result = _service().build(**inputs)
    tampered = copy.deepcopy(result)
    tampered["pipeline_consistent"] = not tampered["pipeline_consistent"]
    with pytest.raises(ReasoningPipelineContractError) as ei:
        ReasoningPipelineService._validate_result(
            tampered, inputs["execution"], inputs["audit"]
        )
    assert ei.value.invariant == "PIPELINE_CONSISTENT_MISMATCH"


def test_tamper_pipeline_source_rejected() -> None:
    inputs = _valid_inputs()
    result = _service().build(**inputs)
    tampered = copy.deepcopy(result)
    tampered["pipeline_source"] = "WRONG"
    with pytest.raises(ReasoningPipelineContractError) as ei:
        ReasoningPipelineService._validate_result(
            tampered, inputs["execution"], inputs["audit"]
        )
    assert ei.value.invariant == "INVALID_PIPELINE_SOURCE"


# ---------------------------------------------------------------------------
# No-decision regression
# ---------------------------------------------------------------------------


def test_no_forbidden_fields() -> None:
    sid = _seed_session("Task 041 no forbidden fields")
    result = _build_for(sid)
    forbidden = (
        "winner",
        "recommendation",
        "diagnosis",
        "treatment",
        "action",
        "probability",
        "confidence",
        "utility",
        "expected_outcome",
    )
    assert set(result) == set(RESULT_FIELDS)
    for f in forbidden:
        assert f not in result
    for s in result["stages"]:
        assert set(s) == set(STAGE_FIELDS)
        for f in forbidden:
            assert f not in s


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_endpoint() -> None:
    sid = _seed_session("Task 041 API")
    r = client.get(f"/sessions/{sid}/reasoning-pipeline")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(RESULT_FIELDS)
    assert (
        payload["pipeline_source"]
        == PIPELINE_SOURCE_REASONING_PIPELINE_TASK_041
    )
    assert payload["stage_count"] == 10


def test_api_empty_session() -> None:
    sid = _create_session("Task 041 empty API")
    r = client.get(f"/sessions/{sid}/reasoning-pipeline")
    assert r.status_code == 200
    payload = r.json()
    assert payload["available"] is True
    assert payload["final_execution"]["outcome"] == "INPUT_UNAVAILABLE"


def test_api_missing_session_returns_404() -> None:
    r = client.get(f"/sessions/{uuid4()}/reasoning-pipeline")
    assert r.status_code == 404


def test_api_is_deterministic() -> None:
    sid = _seed_session("Task 041 api deterministic")
    first = client.get(f"/sessions/{sid}/reasoning-pipeline").json()
    second = client.get(f"/sessions/{sid}/reasoning-pipeline").json()
    assert first == second


def test_api_is_read_only() -> None:
    sid = _seed_session("Task 041 read-only")
    before = client.get(f"/sessions/{sid}/decision-execution").json()
    r = client.get(f"/sessions/{sid}/reasoning-pipeline")
    assert r.status_code == 200
    after = client.get(f"/sessions/{sid}/decision-execution").json()
    assert after == before


def test_api_matches_service_output() -> None:
    sid = _seed_session("Task 041 agreement")
    api_result = client.get(f"/sessions/{sid}/reasoning-pipeline").json()
    service_result = _build_for(sid)
    assert api_result == _json_safe(service_result)


def _json_safe(result: dict[str, Any]) -> dict[str, Any]:
    def safe_execution(e: dict[str, Any]) -> dict[str, Any]:
        return {
            **e,
            "selected_candidate": (
                {
                    **e["selected_candidate"],
                    "hypothesis_id": str(
                        e["selected_candidate"]["hypothesis_id"]
                    ),
                }
                if e["selected_candidate"] is not None
                else None
            ),
            "eligible_candidate_ids": [
                str(hid) for hid in e["eligible_candidate_ids"]
            ],
        }

    return {
        **result,
        "final_execution": safe_execution(result["final_execution"]),
    }
