"""Tests for Task 038 decision policy contract.

Task 038 defines the explicit policy a future decision-execution layer
is permitted to apply to a Task 037 decision-input bundle. It does not
execute the policy, select a candidate, rank, rerank, rescore, break
ties, or produce a decision.
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
from rop.services.decision_candidate_assessment import (
    DecisionCandidateAssessmentService,
)
from rop.services.decision_candidate_evaluation import (
    DecisionCandidateEvaluationService,
)
from rop.services.decision_candidate_set import DecisionCandidateSetService
from rop.services.decision_context import DecisionContextService
from rop.services.decision_evaluation_consistency import (
    DecisionEvaluationConsistencyService,
)
from rop.services.decision_input_bundle import DecisionInputBundleService
from rop.services.decision_input_eligibility import DecisionInputEligibilityService
from rop.services.decision_policy import (
    POLICY_ID_DEFAULT,
    POLICY_NAME_DEFAULT,
    POLICY_SOURCE_DECISION_POLICY_TASK_038,
    POLICY_VERSION_DEFAULT,
    DecisionPolicyContractError,
    DecisionPolicyService,
)
from rop.services.differential_decision_readiness import (
    DifferentialDecisionReadinessService,
)
from rop.services.differential_ranking import DifferentialRankingService
from rop.services.differential_ranking_consistency import (
    DifferentialRankingConsistencyService,
)
from rop.services.differential_ranking_summary import (
    DifferentialRankingSummaryService,
)
from rop.services.evidence_aggregation import EvidenceAggregationService
from rop.services.hypothesis_scoring import HypothesisScoringService

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

POLICY_FIELDS = (
    "policy_id",
    "policy_version",
    "policy_name",
    "required_candidate_count",
    "allowed_selection_mode",
    "required_criteria_behavior",
    "tie_behavior",
    "insufficient_input_behavior",
    "incomplete_input_behavior",
    "policy_source",
)


def _bundle_service() -> DecisionInputBundleService:
    ranking = DifferentialRankingService(
        HypothesisScoringService(EvidenceAggregationService())
    )
    summary = DifferentialRankingSummaryService(ranking)
    consistency = DifferentialRankingConsistencyService(summary)
    readiness = DifferentialDecisionReadinessService(consistency)
    context = DecisionContextService(readiness)
    eval_svc = DecisionCandidateEvaluationService(context)
    cons_svc = DecisionEvaluationConsistencyService(eval_svc)
    elig_svc = DecisionInputEligibilityService(cons_svc)
    cs_svc = DecisionCandidateSetService(elig_svc)
    asmt_svc = DecisionCandidateAssessmentService(cs_svc)
    return DecisionInputBundleService(cs_svc, asmt_svc)


def _policy_service() -> DecisionPolicyService:
    return DecisionPolicyService(_bundle_service())


# ---------------------------------------------------------------------------
# Valid policy construction
# ---------------------------------------------------------------------------


def test_valid_policy_construction() -> None:
    policy = _policy_service().build()
    assert set(policy) == set(POLICY_FIELDS)


def test_fixed_source() -> None:
    policy = _policy_service().build()
    assert policy["policy_source"] == POLICY_SOURCE_DECISION_POLICY_TASK_038


def test_policy_id_and_version_preserved() -> None:
    policy = _policy_service().build()
    assert policy["policy_id"] == POLICY_ID_DEFAULT
    assert policy["policy_version"] == POLICY_VERSION_DEFAULT
    assert policy["policy_name"] == POLICY_NAME_DEFAULT


def test_all_required_fields_present() -> None:
    policy = _policy_service().build()
    for field in POLICY_FIELDS:
        assert field in policy


def test_selection_mode_is_valid() -> None:
    policy = _policy_service().build()
    assert policy["allowed_selection_mode"] == "SINGLE_CANDIDATE"


def test_tie_behavior_is_explicit_unresolved() -> None:
    policy = _policy_service().build()
    assert policy["tie_behavior"] == "MUST_RETURN_UNRESOLVED"


def test_required_criteria_behavior_is_explicit() -> None:
    policy = _policy_service().build()
    assert (
        policy["required_criteria_behavior"] == "MUST_ALL_BE_SATISFIED"
    )


def test_insufficient_input_behavior_is_explicit() -> None:
    policy = _policy_service().build()
    assert (
        policy["insufficient_input_behavior"] == "MUST_RETURN_UNAVAILABLE"
    )


def test_incomplete_input_behavior_is_explicit() -> None:
    policy = _policy_service().build()
    assert (
        policy["incomplete_input_behavior"] == "MUST_RETURN_INCONSISTENT"
    )


def test_required_candidate_count_is_one() -> None:
    policy = _policy_service().build()
    assert policy["required_candidate_count"] == 1


# ---------------------------------------------------------------------------
# Determinism / no mutation
# ---------------------------------------------------------------------------


def test_deterministic_repeated_calls() -> None:
    s = _policy_service()
    assert s.build() == s.build()


def test_validator_does_not_mutate_input() -> None:
    policy = _policy_service().build()
    before = copy.deepcopy(policy)
    DecisionPolicyService._validate_policy(policy)
    assert policy == before


# ---------------------------------------------------------------------------
# Validator rejections
# ---------------------------------------------------------------------------


def _valid_policy() -> dict[str, Any]:
    return _policy_service().build()


def test_rejects_missing_field() -> None:
    p = _valid_policy()
    del p["tie_behavior"]
    with pytest.raises(DecisionPolicyContractError) as ei:
        DecisionPolicyService._validate_policy(p)
    assert ei.value.invariant == "MISSING_POLICY_FIELD"


def test_rejects_invalid_selection_mode() -> None:
    p = _valid_policy()
    p["allowed_selection_mode"] = "HIGHEST_SCORE_WINS"
    with pytest.raises(DecisionPolicyContractError) as ei:
        DecisionPolicyService._validate_policy(p)
    assert ei.value.invariant == "INVALID_SELECTION_MODE"


def test_rejects_invalid_tie_behavior() -> None:
    p = _valid_policy()
    p["tie_behavior"] = "BREAK_BY_NAME"
    with pytest.raises(DecisionPolicyContractError) as ei:
        DecisionPolicyService._validate_policy(p)
    assert ei.value.invariant == "INVALID_TIE_BEHAVIOR"


def test_rejects_invalid_required_criteria_behavior() -> None:
    p = _valid_policy()
    p["required_criteria_behavior"] = "IGNORE"
    with pytest.raises(DecisionPolicyContractError) as ei:
        DecisionPolicyService._validate_policy(p)
    assert ei.value.invariant == "INVALID_REQUIRED_CRITERIA_BEHAVIOR"


def test_rejects_invalid_insufficient_input_behavior() -> None:
    p = _valid_policy()
    p["insufficient_input_behavior"] = "PROCEED"
    with pytest.raises(DecisionPolicyContractError) as ei:
        DecisionPolicyService._validate_policy(p)
    assert ei.value.invariant == "INVALID_INSUFFICIENT_INPUT_BEHAVIOR"


def test_rejects_invalid_incomplete_input_behavior() -> None:
    p = _valid_policy()
    p["incomplete_input_behavior"] = "PROCEED"
    with pytest.raises(DecisionPolicyContractError) as ei:
        DecisionPolicyService._validate_policy(p)
    assert ei.value.invariant == "INVALID_INCOMPLETE_INPUT_BEHAVIOR"


def test_rejects_invalid_source() -> None:
    p = _valid_policy()
    p["policy_source"] = "SOMETHING_ELSE"
    with pytest.raises(DecisionPolicyContractError) as ei:
        DecisionPolicyService._validate_policy(p)
    assert ei.value.invariant == "INVALID_POLICY_SOURCE"


def test_rejects_non_string_field() -> None:
    p = _valid_policy()
    p["policy_id"] = 123
    with pytest.raises(DecisionPolicyContractError) as ei:
        DecisionPolicyService._validate_policy(p)
    assert ei.value.invariant == "POLICY_ID_TYPE"


def test_rejects_empty_string_field() -> None:
    p = _valid_policy()
    p["policy_version"] = ""
    with pytest.raises(DecisionPolicyContractError) as ei:
        DecisionPolicyService._validate_policy(p)
    assert ei.value.invariant == "POLICY_VERSION_TYPE"


def test_rejects_negative_required_candidate_count() -> None:
    p = _valid_policy()
    p["required_candidate_count"] = -1
    with pytest.raises(DecisionPolicyContractError) as ei:
        DecisionPolicyService._validate_policy(p)
    assert ei.value.invariant == "REQUIRED_CANDIDATE_COUNT_NEGATIVE"


def test_rejects_non_int_required_candidate_count() -> None:
    p = _valid_policy()
    p["required_candidate_count"] = "one"
    with pytest.raises(DecisionPolicyContractError) as ei:
        DecisionPolicyService._validate_policy(p)
    assert ei.value.invariant == "REQUIRED_CANDIDATE_COUNT_TYPE"


def test_accepts_none_required_candidate_count() -> None:
    p = _valid_policy()
    p["required_candidate_count"] = None
    DecisionPolicyService._validate_policy(p)


# ---------------------------------------------------------------------------
# No-decision regression
# ---------------------------------------------------------------------------


def test_no_forbidden_decision_fields_present() -> None:
    policy = _policy_service().build()
    forbidden = (
        "winner",
        "selected_candidate",
        "selected",
        "best_candidate",
        "best",
        "diagnosis",
        "recommendation",
        "action",
        "probability",
        "confidence",
        "utility",
        "expected_outcome",
        "treatment",
        "decision",
        "score",
        "rank",
    )
    assert set(policy) == set(POLICY_FIELDS)
    for f in forbidden:
        assert f not in policy


def test_no_session_data_leaks_into_policy() -> None:
    policy = _policy_service().build()
    for field in POLICY_FIELDS:
        value = policy[field]
        if isinstance(value, str):
            assert "hypothesis" not in value.lower()
            assert "session" not in value.lower()
            assert "candidate_" not in value.lower() or field == (
                "required_candidate_count"
            )


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------


def test_build_for_session_delegates_to_task037(monkeypatch) -> None:
    calls = {"n": 0}
    original = DecisionInputBundleService.build_for_session

    def spy(self, db, session_id, candidates):
        calls["n"] += 1
        return original(self, db, session_id, candidates)

    monkeypatch.setattr(
        DecisionInputBundleService, "build_for_session", spy
    )

    sid = _create_session("Task 038 delegation")
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        policy = _policy_service().build_for_session(
            db, session_uuid, candidates
        )
    finally:
        db_gen.close()

    assert calls["n"] == 1
    assert policy["policy_source"] == POLICY_SOURCE_DECISION_POLICY_TASK_038


def test_policy_identical_across_sessions() -> None:
    """The policy is session-independent. Two different sessions must
    receive byte-identical policy contracts."""
    sid_a = _create_session("Task 038 session A")
    sid_b = _create_session("Task 038 session B")

    for sid in (sid_a, sid_b):
        session_uuid = UUID(sid)
        db_gen = app.dependency_overrides[get_db]()
        db = next(db_gen)
        try:
            from rop.services.candidate_generation import CandidateGenerationService

            candidates = CandidateGenerationService().list_by_session(
                db, session_uuid, offset=0, limit=100
            )
            policy = _policy_service().build_for_session(
                db, session_uuid, candidates
            )
        finally:
            db_gen.close()
        if sid == sid_a:
            policy_a = policy
        else:
            policy_b = policy

    assert policy_a == policy_b


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "decision-policy-test"},
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


def test_api_endpoint() -> None:
    sid = _seed_session("Task 038 API test")
    r = client.get(f"/sessions/{sid}/decision-policy")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(POLICY_FIELDS)
    assert payload["policy_source"] == POLICY_SOURCE_DECISION_POLICY_TASK_038


def test_api_empty_session() -> None:
    """The policy is session-independent, so even an empty session
    whose Task 037 boundary is constructible returns the policy."""
    sid = _create_session("Task 038 empty session")
    r = client.get(f"/sessions/{sid}/decision-policy")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(POLICY_FIELDS)
    assert payload["policy_source"] == POLICY_SOURCE_DECISION_POLICY_TASK_038


def test_api_missing_session_returns_404() -> None:
    r = client.get(f"/sessions/{uuid4()}/decision-policy")
    assert r.status_code == 404


def test_api_is_deterministic() -> None:
    sid = _seed_session("Task 038 deterministic")
    first = client.get(f"/sessions/{sid}/decision-policy").json()
    second = client.get(f"/sessions/{sid}/decision-policy").json()
    assert first == second


def test_api_is_read_only() -> None:
    sid = _seed_session("Task 038 read-only")
    before = client.get(f"/sessions/{sid}/decision-input-bundle").json()
    r = client.get(f"/sessions/{sid}/decision-policy")
    assert r.status_code == 200
    after = client.get(f"/sessions/{sid}/decision-input-bundle").json()
    assert after == before


def test_api_matches_service_output() -> None:
    sid = _seed_session("Task 038 agreement")
    api_result = client.get(f"/sessions/{sid}/decision-policy").json()

    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        service_result = _policy_service().build_for_session(
            db, session_uuid, candidates
        )
    finally:
        db_gen.close()

    assert api_result == service_result


def test_api_policy_identical_across_sessions() -> None:
    sid_a = _seed_session("Task 038 identical A")
    sid_b = _seed_session("Task 038 identical B")
    a = client.get(f"/sessions/{sid_a}/decision-policy").json()
    b = client.get(f"/sessions/{sid_b}/decision-policy").json()
    assert a == b
