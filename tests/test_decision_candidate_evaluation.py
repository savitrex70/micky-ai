"""Tests for the Task 032 decision-candidate evaluation layer.

Task 032 consumes the Task 031 ``DecisionContext`` exclusively and
evaluates each candidate against a fixed, deterministic set of decision
criteria (support, contradiction, evidence coverage, consistency,
separation, readiness). It never selects a winner, never diagnoses,
never computes a probability, and never runs an LLM.
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
from rop.services.decision_candidate_evaluation import (
    DEFAULT_CRITERIA,
    EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032,
    CriterionType,
    DecisionCandidateEvaluationContractError,
    DecisionCandidateEvaluationService,
)
from rop.services.decision_context import DecisionContextService
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
from rop.services.evidence_aggregation import (
    CONSISTENCY_CONTRADICTION_ONLY,
    CONSISTENCY_MIXED,
    CONSISTENCY_NO_EVIDENCE,
    CONSISTENCY_SUPPORT_ONLY,
    EvidenceAggregationService,
)
from rop.services.hypothesis_scoring import (
    SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
    HypothesisScoringService,
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


CANDIDATE_EVALUATION_FIELDS = (
    "hypothesis_id",
    "hypothesis_name",
    "criteria",
    "criterion_count",
    "criteria_satisfied",
    "criteria_unsatisfied",
    "required_criteria_satisfied",
    "required_criteria_unsatisfied",
    "evaluation_complete",
    "evaluation_source",
)

CRITERION_RESULT_FIELDS = (
    "criterion_id",
    "criterion_name",
    "satisfied",
    "required",
    "reason",
)


# ---------------------------------------------------------------------------
# Helpers -- build a genuine Tasks 027-031 chain from hand-crafted score
# results, exactly like the Task 031 test suite does.
# ---------------------------------------------------------------------------


def _ranking_service() -> DifferentialRankingService:
    return DifferentialRankingService(
        HypothesisScoringService(EvidenceAggregationService())
    )


def _readiness_service() -> DifferentialDecisionReadinessService:
    return DifferentialDecisionReadinessService(
        DifferentialRankingConsistencyService(
            DifferentialRankingSummaryService(_ranking_service())
        )
    )


def _context_service() -> DecisionContextService:
    return DecisionContextService(_readiness_service())


def _evaluation_service() -> DecisionCandidateEvaluationService:
    return DecisionCandidateEvaluationService(_context_service())


def _score_result(
    *,
    hypothesis_name: str,
    hypothesis_score: float,
    evidence_consistency: str = CONSISTENCY_SUPPORT_ONLY,
    total_support_contribution: float = 0.0,
    total_contradiction_contribution: float = 0.0,
    evidence_coverage_ratio: float | None = None,
) -> dict[str, Any]:
    has_evidence = evidence_consistency != CONSISTENCY_NO_EVIDENCE
    if evidence_coverage_ratio is None:
        evidence_coverage_ratio = 1.0 if has_evidence else 0.0

    if hypothesis_score > 0:
        score_direction = "POSITIVE"
    elif hypothesis_score < 0:
        score_direction = "NEGATIVE"
    else:
        score_direction = "ZERO"

    return {
        "hypothesis_id": uuid4(),
        "hypothesis_name": hypothesis_name,
        "hypothesis_score": hypothesis_score,
        "score_source": SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
        "evidence_consistency": evidence_consistency,
        "total_evidence_items": 1 if has_evidence else 0,
        "total_support_contribution": total_support_contribution,
        "total_contradiction_contribution": total_contradiction_contribution,
        "net_contribution": (
            total_support_contribution - total_contradiction_contribution
        ),
        "has_evidence": has_evidence,
        "has_mixed_evidence": evidence_consistency == CONSISTENCY_MIXED,
        "score_direction": score_direction,
        "evidence_coverage_ratio": evidence_coverage_ratio,
        "informative_evidence_ratio": evidence_coverage_ratio,
        "support_to_contradiction_ratio": None,
        "evidence_position": "SUPPORTING" if has_evidence else "UNSUPPORTED",
    }


def _build(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    ranking_service = _ranking_service()
    summary_service = DifferentialRankingSummaryService(ranking_service)
    consistency_service = DifferentialRankingConsistencyService(summary_service)
    readiness_service = DifferentialDecisionReadinessService(consistency_service)

    ranked = ranking_service.rank_score_results(entries)
    summary = summary_service.summarize_ranked(ranked)
    consistency = consistency_service.check_consistency(ranked, summary)
    readiness = readiness_service.evaluate(ranked, summary, consistency)
    return ranked, summary, consistency, readiness


def _make_context(
    entries: list[dict[str, Any]],
    *,
    consistent_override: bool | None = None,
    ready_override: bool | None = None,
) -> dict[str, Any]:
    ranked, summary, consistency, readiness = _build(entries)
    if consistent_override is not None:
        consistency = dict(consistency)
        consistency["consistent"] = consistent_override
    if ready_override is not None:
        readiness = dict(readiness)
        readiness["ready"] = ready_override
    return _context_service().build(ranked, summary, consistency, readiness)


def _evaluate(
    entries: list[dict[str, Any]],
    *,
    consistent_override: bool | None = None,
    ready_override: bool | None = None,
) -> list[dict[str, Any]]:
    context = _make_context(
        entries,
        consistent_override=consistent_override,
        ready_override=ready_override,
    )
    return _evaluation_service().evaluate(context)


def _criterion(result: dict[str, Any], criterion_id: str) -> dict[str, Any]:
    for entry in result["criteria"]:
        if entry["criterion_id"] == criterion_id:
            return entry
    raise AssertionError(f"criterion {criterion_id!r} not found")


# ---------------------------------------------------------------------------
# Default criteria set
# ---------------------------------------------------------------------------


def test_default_criteria_types_are_exactly_the_declared_set() -> None:
    assert {c.criterion_type for c in DEFAULT_CRITERIA} == set(CriterionType)


def test_default_criteria_ids_are_unique() -> None:
    ids = [c.criterion_id for c in DEFAULT_CRITERIA]
    assert len(ids) == len(set(ids))


def test_default_criteria_source_is_fixed() -> None:
    for criterion in DEFAULT_CRITERIA:
        assert (
            criterion.source == EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032
        )


# ---------------------------------------------------------------------------
# Normal cases
# ---------------------------------------------------------------------------


def test_multiple_candidates_evaluated() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
        _score_result(hypothesis_name="H3", hypothesis_score=1.0),
    ]
    results = _evaluate(entries)

    assert len(results) == 3
    for result in results:
        assert set(result) == set(CANDIDATE_EVALUATION_FIELDS)


def test_single_candidate_evaluated() -> None:
    entries = [_score_result(hypothesis_name="H1", hypothesis_score=10.0)]
    results = _evaluate(entries)

    assert len(results) == 1
    assert results[0]["hypothesis_name"] == "H1"


def test_all_criteria_satisfied() -> None:
    entries = [
        _score_result(
            hypothesis_name="H1",
            hypothesis_score=10.0,
            evidence_consistency=CONSISTENCY_SUPPORT_ONLY,
            total_support_contribution=10.0,
            total_contradiction_contribution=0.0,
        ),
        _score_result(
            hypothesis_name="H2",
            hypothesis_score=1.0,
            evidence_consistency=CONSISTENCY_SUPPORT_ONLY,
            total_support_contribution=1.0,
        ),
    ]
    results = _evaluate(entries)
    top = results[0]

    assert top["hypothesis_name"] == "H1"
    assert top["criteria_satisfied"] == top["criterion_count"]
    assert top["criteria_unsatisfied"] == 0
    for criterion in top["criteria"]:
        assert criterion["satisfied"] is True


def test_mixed_satisfied_unsatisfied_criteria() -> None:
    entries = [
        _score_result(
            hypothesis_name="H1",
            hypothesis_score=10.0,
            evidence_consistency=CONSISTENCY_CONTRADICTION_ONLY,
            total_contradiction_contribution=4.0,
        ),
        _score_result(hypothesis_name="H2", hypothesis_score=1.0),
    ]
    results = _evaluate(entries)
    top = results[0]

    assert _criterion(top, "support")["satisfied"] is False
    assert _criterion(top, "contradiction")["satisfied"] is False
    assert top["criteria_satisfied"] < top["criterion_count"]
    assert top["criteria_unsatisfied"] > 0


def test_zero_supporting_evidence() -> None:
    entries = [
        _score_result(
            hypothesis_name="H1",
            hypothesis_score=0.0,
            evidence_consistency=CONSISTENCY_CONTRADICTION_ONLY,
            total_support_contribution=0.0,
            total_contradiction_contribution=3.0,
        ),
    ]
    results = _evaluate(entries)
    support = _criterion(results[0], "support")

    assert support["satisfied"] is False
    assert "could not be established" not in support["reason"]
    assert "no positive supporting evidence" in support["reason"]


def test_contradiction_present() -> None:
    entries = [
        _score_result(
            hypothesis_name="H1",
            hypothesis_score=0.0,
            evidence_consistency=CONSISTENCY_CONTRADICTION_ONLY,
            total_contradiction_contribution=2.5,
        ),
    ]
    results = _evaluate(entries)
    contradiction = _criterion(results[0], "contradiction")

    assert contradiction["satisfied"] is False
    assert "contradicting evidence is present" in contradiction["reason"]


def test_contradicting_evidence_with_zero_contribution_is_not_satisfied() -> None:
    # Regression: contradicting evidence can exist with zero
    # contribution, so the criterion must be decided from
    # evidence_consistency, not total_contradiction_contribution.
    entries = [
        _score_result(
            hypothesis_name="H1",
            hypothesis_score=0.0,
            evidence_consistency=CONSISTENCY_CONTRADICTION_ONLY,
            total_contradiction_contribution=0.0,
        ),
    ]
    results = _evaluate(entries)
    contradiction = _criterion(results[0], "contradiction")

    assert contradiction["satisfied"] is False
    assert "contradicting evidence is present" in contradiction["reason"]


def test_missing_information_is_not_support_or_contradiction() -> None:
    entries = [
        _score_result(
            hypothesis_name="H1",
            hypothesis_score=0.0,
            evidence_consistency=CONSISTENCY_NO_EVIDENCE,
        ),
    ]
    results = _evaluate(entries)
    top = results[0]
    support = _criterion(top, "support")
    contradiction = _criterion(top, "contradiction")

    assert support["satisfied"] is False
    assert "could not be established" in support["reason"]
    assert contradiction["satisfied"] is False
    assert "could not be established" in contradiction["reason"]


def test_missing_information_evidence_coverage() -> None:
    entries = [
        _score_result(
            hypothesis_name="H1",
            hypothesis_score=0.0,
            evidence_consistency=CONSISTENCY_NO_EVIDENCE,
        ),
    ]
    results = _evaluate(entries)
    coverage = _criterion(results[0], "evidence_coverage")

    assert coverage["satisfied"] is False


def test_tied_candidates() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=5.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    results = _evaluate(entries)

    for result in results:
        separation = _criterion(result, "separation")
        assert separation["satisfied"] is False
        assert "tied with" in separation["reason"]


def test_separated_candidates() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    results = _evaluate(entries)

    for result in results:
        separation = _criterion(result, "separation")
        assert separation["satisfied"] is True
        assert "not tied" in separation["reason"]


def test_readiness_true() -> None:
    entries = [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    results = _evaluate(entries)

    assert _criterion(results[0], "readiness")["satisfied"] is True


def test_readiness_false() -> None:
    entries = [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    results = _evaluate(entries, ready_override=False)

    readiness = _criterion(results[0], "readiness")
    assert readiness["satisfied"] is False
    assert "not ready" in readiness["reason"]


def test_consistency_true_and_false() -> None:
    entries = [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]

    consistent_results = _evaluate(entries, consistent_override=True)
    inconsistent_results = _evaluate(entries, consistent_override=False)

    assert _criterion(consistent_results[0], "consistency")["satisfied"] is True
    assert _criterion(inconsistent_results[0], "consistency")["satisfied"] is False


def test_evidence_coverage_zero_and_positive() -> None:
    entries = [
        _score_result(
            hypothesis_name="H1",
            hypothesis_score=5.0,
            evidence_consistency=CONSISTENCY_SUPPORT_ONLY,
            evidence_coverage_ratio=0.0,
        ),
        _score_result(
            hypothesis_name="H2",
            hypothesis_score=4.0,
            evidence_consistency=CONSISTENCY_SUPPORT_ONLY,
            evidence_coverage_ratio=0.5,
        ),
    ]
    results = _evaluate(entries)

    zero_coverage = next(r for r in results if r["hypothesis_name"] == "H1")
    positive_coverage = next(r for r in results if r["hypothesis_name"] == "H2")

    assert _criterion(zero_coverage, "evidence_coverage")["satisfied"] is False
    assert _criterion(positive_coverage, "evidence_coverage")["satisfied"] is True


# ---------------------------------------------------------------------------
# Empty differential
# ---------------------------------------------------------------------------


def test_empty_differential_produces_empty_evaluation_list() -> None:
    results = _evaluate([])
    assert results == []


# ---------------------------------------------------------------------------
# Evaluation completeness and required-criteria counts
# ---------------------------------------------------------------------------


def test_evaluation_complete_is_true_for_every_candidate() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    results = _evaluate(entries)

    for result in results:
        assert result["evaluation_complete"] is True
        assert result["criterion_count"] == len(DEFAULT_CRITERIA)


def test_required_criteria_counts_only_cover_required_criteria() -> None:
    entries = [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    result = _evaluate(entries)[0]

    required_count = sum(1 for c in result["criteria"] if c["required"])
    assert (
        result["required_criteria_satisfied"] + result["required_criteria_unsatisfied"]
        == required_count
    )
    assert required_count < result["criterion_count"]


def test_evaluation_source_is_fixed() -> None:
    entries = [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    result = _evaluate(entries)[0]

    assert (
        result["evaluation_source"]
        == EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032
    )


def test_no_winner_or_decision_fields_are_introduced() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=5.0),
    ]
    results = _evaluate(entries)

    for result in results:
        assert set(result) == set(CANDIDATE_EVALUATION_FIELDS)
        for forbidden in (
            "winner",
            "selected_candidate",
            "decision",
            "diagnosis",
            "probability",
            "confidence",
            "utility_score",
            "weighted_score",
            "is_winner",
        ):
            assert forbidden not in result
        for criterion in result["criteria"]:
            assert set(criterion) == set(CRITERION_RESULT_FIELDS)


# ---------------------------------------------------------------------------
# Contract tests -- missing/malformed input
# ---------------------------------------------------------------------------


def test_missing_context_raises_contract_error() -> None:
    with pytest.raises(DecisionCandidateEvaluationContractError):
        _evaluation_service().evaluate(None)


def test_context_not_a_mapping_raises_contract_error() -> None:
    with pytest.raises(DecisionCandidateEvaluationContractError):
        _evaluation_service().evaluate([])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "differential",
        "differential_summary",
        "differential_consistency",
        "decision_readiness",
    ],
)
def test_missing_context_field_raises_contract_error(field: str) -> None:
    context = _make_context([_score_result(hypothesis_name="H1", hypothesis_score=5.0)])
    corrupted = dict(context)
    del corrupted[field]

    with pytest.raises(DecisionCandidateEvaluationContractError):
        _evaluation_service().evaluate(corrupted)


def test_ranked_entry_missing_field_raises_contract_error() -> None:
    context = _make_context([_score_result(hypothesis_name="H1", hypothesis_score=5.0)])
    corrupted = dict(context)
    corrupted["differential"] = copy.deepcopy(context["differential"])
    del corrupted["differential"][0]["is_tied"]

    with pytest.raises(DecisionCandidateEvaluationContractError):
        _evaluation_service().evaluate(corrupted)


def test_missing_consistency_field_raises_contract_error() -> None:
    context = _make_context([_score_result(hypothesis_name="H1", hypothesis_score=5.0)])
    corrupted = dict(context)
    consistency = dict(context["differential_consistency"])
    del consistency["consistent"]
    corrupted["differential_consistency"] = consistency

    with pytest.raises(DecisionCandidateEvaluationContractError):
        _evaluation_service().evaluate(corrupted)


def test_missing_readiness_field_raises_contract_error() -> None:
    context = _make_context([_score_result(hypothesis_name="H1", hypothesis_score=5.0)])
    corrupted = dict(context)
    readiness = dict(context["decision_readiness"])
    del readiness["ready"]
    corrupted["decision_readiness"] = readiness

    with pytest.raises(DecisionCandidateEvaluationContractError):
        _evaluation_service().evaluate(corrupted)


def test_contract_error_carries_invariant_name() -> None:
    with pytest.raises(DecisionCandidateEvaluationContractError) as exc_info:
        _evaluation_service().evaluate(None)

    assert exc_info.value.invariant == "MISSING_CONTEXT"


# ---------------------------------------------------------------------------
# Contract tests -- the output validator, exercised directly
# ---------------------------------------------------------------------------


def _well_formed_candidate() -> dict[str, Any]:
    entries = [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    return _evaluate(entries)[0]


def test_validator_accepts_well_formed_output() -> None:
    result = _well_formed_candidate()
    DecisionCandidateEvaluationService._validate_output([result])


def test_validator_rejects_malformed_criterion() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    corrupted["criteria"][0] = "not-a-mapping"

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_criterion_missing_field() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    del corrupted["criteria"][0]["reason"]

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_duplicate_criterion_id() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    duplicate = copy.deepcopy(corrupted["criteria"][0])
    duplicate["criterion_id"] = corrupted["criteria"][1]["criterion_id"]
    corrupted["criteria"][0] = duplicate

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_duplicate_candidate_id() -> None:
    result = _well_formed_candidate()
    duplicate = copy.deepcopy(result)

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([result, duplicate])


def test_validator_rejects_invalid_boolean() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    corrupted["criteria"][0]["satisfied"] = "yes"

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_invalid_integer() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    corrupted["criterion_count"] = "6"

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_boolean_in_integer_field() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    corrupted["criterion_count"] = True

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_incorrect_criterion_count() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    corrupted["criterion_count"] = corrupted["criterion_count"] + 1

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_incorrect_satisfied_count() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    corrupted["criteria_satisfied"] = corrupted["criteria_satisfied"] + 1

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_incorrect_unsatisfied_count() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    corrupted["criteria_unsatisfied"] = corrupted["criteria_unsatisfied"] + 1

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_incorrect_required_satisfied_count() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    corrupted["required_criteria_satisfied"] = (
        corrupted["required_criteria_satisfied"] + 1
    )

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_incorrect_required_unsatisfied_count() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    corrupted["required_criteria_unsatisfied"] = (
        corrupted["required_criteria_unsatisfied"] + 1
    )

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_incorrect_evaluation_complete() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    corrupted["evaluation_complete"] = not corrupted["evaluation_complete"]

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_incomplete_criteria_set() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    removed = corrupted["criteria"].pop()
    corrupted["criterion_count"] = len(corrupted["criteria"])
    corrupted["criteria_satisfied"] = sum(
        1 for c in corrupted["criteria"] if c["satisfied"]
    )
    corrupted["criteria_unsatisfied"] = (
        corrupted["criterion_count"] - corrupted["criteria_satisfied"]
    )
    # evaluation_complete still claims True even though a criterion is gone.
    assert removed["criterion_id"] not in {
        c["criterion_id"] for c in corrupted["criteria"]
    }

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_incorrect_source() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    corrupted["evaluation_source"] = "SOMETHING_ELSE"

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


def test_validator_rejects_missing_criteria_list() -> None:
    result = _well_formed_candidate()
    corrupted = copy.deepcopy(result)
    del corrupted["criteria"]

    with pytest.raises(DecisionCandidateEvaluationContractError):
        DecisionCandidateEvaluationService._validate_output([corrupted])


# ---------------------------------------------------------------------------
# Integrity: no mutation, determinism
# ---------------------------------------------------------------------------


def test_evaluate_does_not_mutate_the_context() -> None:
    context = _make_context(
        [
            _score_result(hypothesis_name="H1", hypothesis_score=10.0),
            _score_result(hypothesis_name="H2", hypothesis_score=5.0),
        ]
    )
    before = copy.deepcopy(context)

    _evaluation_service().evaluate(context)

    assert context == before


def test_evaluate_is_deterministic() -> None:
    context = _make_context(
        [
            _score_result(hypothesis_name="H1", hypothesis_score=10.0),
            _score_result(hypothesis_name="H2", hypothesis_score=5.0),
        ]
    )
    service = _evaluation_service()

    first = service.evaluate(context)
    second = service.evaluate(context)

    assert first == second


# ---------------------------------------------------------------------------
# API integration
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "decision-candidate-evaluation-test"},
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _seed_session(user_input: str) -> str:
    session_id = _create_session(user_input)

    obs_response = client.post(
        f"/sessions/{session_id}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert obs_response.status_code == 201

    generate_response = client.post(f"/sessions/{session_id}/generate-candidates")
    assert generate_response.status_code == 201
    assert len(generate_response.json()) > 0

    evaluate_response = client.post(f"/sessions/{session_id}/evaluate-evidence")
    assert evaluate_response.status_code == 200

    return session_id


def test_api_decision_candidate_evaluations_endpoint() -> None:
    session_id = _seed_session("Task 032 candidate evaluation test")

    response = client.get(f"/sessions/{session_id}/decision-candidate-evaluations")
    assert response.status_code == 200
    payload = response.json()

    assert isinstance(payload, list)
    assert len(payload) > 0
    for candidate in payload:
        assert set(candidate) == set(CANDIDATE_EVALUATION_FIELDS)
        assert (
            candidate["evaluation_source"]
            == EVALUATION_SOURCE_DECISION_CANDIDATE_EVALUATION_TASK_032
        )
        assert candidate["criterion_count"] == len(DEFAULT_CRITERIA)


def test_api_decision_candidate_evaluations_empty_session() -> None:
    session_id = _create_session("Task 032 empty candidate evaluation test")

    response = client.get(f"/sessions/{session_id}/decision-candidate-evaluations")
    assert response.status_code == 200
    assert response.json() == []


def test_api_decision_candidate_evaluations_missing_session_returns_404() -> None:
    response = client.get(f"/sessions/{uuid4()}/decision-candidate-evaluations")
    assert response.status_code == 404


def test_api_decision_candidate_evaluations_is_read_only() -> None:
    session_id = _seed_session("Task 032 read-only test")

    context_before = client.get(f"/sessions/{session_id}/decision-context").json()
    differential_before = client.get(f"/sessions/{session_id}/differential").json()

    response = client.get(f"/sessions/{session_id}/decision-candidate-evaluations")
    assert response.status_code == 200

    assert (
        client.get(f"/sessions/{session_id}/decision-context").json() == context_before
    )
    assert (
        client.get(f"/sessions/{session_id}/differential").json() == differential_before
    )


def test_api_decision_candidate_evaluations_is_deterministic() -> None:
    session_id = _seed_session("Task 032 determinism test")

    first = client.get(f"/sessions/{session_id}/decision-candidate-evaluations").json()
    second = client.get(f"/sessions/{session_id}/decision-candidate-evaluations").json()

    assert first == second


def test_api_response_matches_service_output() -> None:
    session_id = _seed_session("Task 032 service-agreement test")

    api_result = client.get(
        f"/sessions/{session_id}/decision-candidate-evaluations"
    ).json()

    # Use whichever db dependency is actually wired into `client` right now
    # rather than this module's own engine directly: when the full suite
    # runs, test-module import order decides which override "wins" on the
    # shared `app` object, and it need not be this module's.
    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        service_result = _evaluation_service().evaluate_session(
            db, session_uuid, candidates
        )
    finally:
        db_gen.close()

    assert len(api_result) == len(service_result)
    for api_candidate, service_candidate in zip(
        api_result, service_result, strict=True
    ):
        assert api_candidate["hypothesis_id"] == str(service_candidate["hypothesis_id"])
        assert (
            api_candidate["evaluation_source"] == service_candidate["evaluation_source"]
        )
