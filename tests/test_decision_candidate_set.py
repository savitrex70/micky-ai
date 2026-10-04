"""Tests for Task 035 decision candidate set contract.

Task 035 packages the Task 031 differential candidate set into a
stable handoff contract for the future decision engine. When Task
034 reports eligible AND the Task 031 context is available and
decision-ready, every candidate is forwarded in exact order;
otherwise the set is empty. Never selects a winner, ranks, scores,
breaks ties, filters, or persists.
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
    DecisionCandidateEvaluationService,
)
from rop.services.decision_candidate_set import (
    CANDIDATE_SET_SOURCE_DECISION_CANDIDATE_SET_TASK_035,
    DecisionCandidateSetContractError,
    DecisionCandidateSetService,
)
from rop.services.decision_context import DecisionContextService
from rop.services.decision_evaluation_consistency import (
    DecisionEvaluationConsistencyService,
)
from rop.services.decision_input_eligibility import (
    ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034,
    DecisionInputEligibilityService,
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
from rop.services.evidence_aggregation import (
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

RESULT_FIELDS = (
    "available",
    "candidate_count",
    "candidates",
    "candidate_order_preserved",
    "candidate_set_complete",
    "candidate_set_source",
)

CANDIDATE_FIELDS = (
    "hypothesis_id",
    "hypothesis_name",
    "rank",
    "score",
    "is_tied",
    "tie_group_size",
    "score_gap_to_next_higher",
    "score_gap_to_next_lower",
)


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


def _candidate_evaluation_service() -> DecisionCandidateEvaluationService:
    return DecisionCandidateEvaluationService(_context_service())


def _consistency_service() -> DecisionEvaluationConsistencyService:
    return DecisionEvaluationConsistencyService(_candidate_evaluation_service())


def _eligibility_service() -> DecisionInputEligibilityService:
    return DecisionInputEligibilityService(_consistency_service())


def _candidate_set_service() -> DecisionCandidateSetService:
    return DecisionCandidateSetService(_eligibility_service())


def _score_result(
    *,
    hypothesis_name: str,
    hypothesis_score: float,
) -> dict[str, Any]:
    if hypothesis_score > 0:
        direction = "POSITIVE"
    elif hypothesis_score < 0:
        direction = "NEGATIVE"
    else:
        direction = "ZERO"
    return {
        "hypothesis_id": uuid4(),
        "hypothesis_name": hypothesis_name,
        "hypothesis_score": hypothesis_score,
        "score_source": SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
        "evidence_consistency": CONSISTENCY_SUPPORT_ONLY,
        "total_evidence_items": 1,
        "total_support_contribution": max(hypothesis_score, 0.0),
        "total_contradiction_contribution": max(-hypothesis_score, 0.0),
        "net_contribution": hypothesis_score,
        "has_evidence": True,
        "has_mixed_evidence": False,
        "score_direction": direction,
        "evidence_coverage_ratio": 1.0,
        "informative_evidence_ratio": 1.0,
        "support_to_contradiction_ratio": None,
        "evidence_position": "SUPPORTING",
    }


def _make_context(entries: list[dict[str, Any]]) -> dict[str, Any]:
    r = _ranking_service()
    s = DifferentialRankingSummaryService(r)
    c = DifferentialRankingConsistencyService(s)
    d = DifferentialDecisionReadinessService(c)
    ranked = r.rank_score_results(entries)
    summary = s.summarize_ranked(ranked)
    consistency = c.check_consistency(ranked, summary)
    readiness = d.evaluate(ranked, summary, consistency)
    return _context_service().build(ranked, summary, consistency, readiness)


def _make_context_and_consistency(
    entries: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    context = _make_context(entries)
    evaluations = _candidate_evaluation_service().evaluate(context)
    expected = [entry["hypothesis_id"] for entry in context["differential"]]
    return context, _consistency_service().check(evaluations, expected)


def _ready_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    context, consistency = _make_context_and_consistency(
        [
            _score_result(hypothesis_name="H1", hypothesis_score=10.0),
            _score_result(hypothesis_name="H2", hypothesis_score=5.0),
        ]
    )
    eligibility = _eligibility_service().build(context, consistency)
    return context, eligibility


def _empty_context_and_eligibility() -> tuple[dict[str, Any], dict[str, Any]]:
    context, consistency = _make_context_and_consistency([])
    eligibility = _eligibility_service().build(context, consistency)
    return context, eligibility


def _unavailable_eligibility() -> dict[str, Any]:
    return {
        "eligible": False,
        "decision_ready": False,
        "context_available": False,
        "evaluation_consistent": True,
        "has_candidates": False,
        "evaluations_available": False,
        "all_candidates_evaluated": True,
        "all_criteria_evaluated": True,
        "candidate_count_matches": True,
        "evaluation_structure_consistent": True,
        "blocking_conditions": [
            "DECISION_NOT_READY",
            "CONTEXT_UNAVAILABLE",
            "NO_CANDIDATES",
        ],
        "eligibility_source": ELIGIBILITY_SOURCE_DECISION_INPUT_ELIGIBILITY_TASK_034,
    }


# ---------------------------------------------------------------------------
# Valid cases
# ---------------------------------------------------------------------------


def test_single_candidate() -> None:
    context, consistency = _make_context_and_consistency(
        [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    )
    eligibility = _eligibility_service().build(context, consistency)
    result = _candidate_set_service().build(context, eligibility)

    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["candidate_count"] == 1
    assert len(result["candidates"]) == 1
    assert set(result["candidates"][0]) == set(CANDIDATE_FIELDS)


def test_multiple_candidates() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)

    assert result["available"] is True
    assert result["candidate_count"] == 2
    assert len(result["candidates"]) == 2


def test_source_is_fixed() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)

    assert (
        result["candidate_set_source"]
        == CANDIDATE_SET_SOURCE_DECISION_CANDIDATE_SET_TASK_035
    )


def test_order_preserved() -> None:
    context, eligibility = _ready_inputs()
    upstream_ids = [entry["hypothesis_id"] for entry in context["differential"]]
    result = _candidate_set_service().build(context, eligibility)

    result_ids = [c["hypothesis_id"] for c in result["candidates"]]
    assert result_ids == upstream_ids
    assert result["candidate_order_preserved"] is True


def test_identity_preserved() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)

    for i, entry in enumerate(context["differential"]):
        assert result["candidates"][i]["hypothesis_id"] == entry["hypothesis_id"]
        assert result["candidates"][i]["hypothesis_name"] == entry["hypothesis_name"]


def test_rank_preserved() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)

    for i, entry in enumerate(context["differential"]):
        assert result["candidates"][i]["rank"] == entry["rank"]


def test_score_preserved() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)

    for i, entry in enumerate(context["differential"]):
        assert result["candidates"][i]["score"] == entry["hypothesis_score"]


def test_tie_metadata_preserved() -> None:
    entries = [
        _score_result(hypothesis_name="H1", hypothesis_score=10.0),
        _score_result(hypothesis_name="H2", hypothesis_score=10.0),
        _score_result(hypothesis_name="H3", hypothesis_score=5.0),
    ]
    context, consistency = _make_context_and_consistency(entries)
    eligibility = _eligibility_service().build(context, consistency)
    result = _candidate_set_service().build(context, eligibility)

    for i, entry in enumerate(context["differential"]):
        assert result["candidates"][i]["is_tied"] == entry["is_tied"]
        assert result["candidates"][i]["tie_group_size"] == entry["tie_group_size"]


def test_score_gap_metadata_preserved() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)

    for i, entry in enumerate(context["differential"]):
        c = result["candidates"][i]
        assert c["score_gap_to_next_higher"] == entry["score_gap_to_next_higher"]
        assert c["score_gap_to_next_lower"] == entry["score_gap_to_next_lower"]


def test_negative_zero_positive_scores() -> None:
    entries = [
        _score_result(hypothesis_name="pos", hypothesis_score=10.0),
        _score_result(hypothesis_name="zero", hypothesis_score=0.0),
        _score_result(hypothesis_name="neg", hypothesis_score=-3.0),
    ]
    context, consistency = _make_context_and_consistency(entries)
    eligibility = _eligibility_service().build(context, consistency)
    result = _candidate_set_service().build(context, eligibility)

    scores = [c["score"] for c in result["candidates"]]
    assert 10.0 in scores
    assert 0.0 in scores
    assert -3.0 in scores


def test_top_candidate_has_no_higher_gap() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)
    assert result["candidates"][0]["score_gap_to_next_higher"] is None


def test_bottom_candidate_has_no_lower_gap() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)
    assert result["candidates"][-1]["score_gap_to_next_lower"] is None


def test_candidate_count_matches_list() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)
    assert result["candidate_count"] == len(result["candidates"])


def test_candidate_set_complete_when_available() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)
    assert result["candidate_set_complete"] is True


def test_no_decision_fields_introduced() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)
    assert set(result) == set(RESULT_FIELDS)
    for forbidden in (
        "winner",
        "selected_candidate",
        "diagnosis",
        "recommendation",
        "action",
        "probability",
        "confidence",
        "utility",
        "weighted_score",
        "expected_outcome",
        "treatment",
        "is_winner",
    ):
        assert forbidden not in result
    for c in result["candidates"]:
        assert set(c) == set(CANDIDATE_FIELDS)


# ---------------------------------------------------------------------------
# Availability cases
# ---------------------------------------------------------------------------


def test_available_when_fully_eligible() -> None:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)
    assert result["available"] is True


def test_unavailable_when_eligibility_false() -> None:
    context, _ = _ready_inputs()
    result = _candidate_set_service().build(context, _unavailable_eligibility())
    assert result["available"] is False
    assert result["candidate_count"] == 0
    assert result["candidates"] == []
    assert result["candidate_set_complete"] is False
    assert result["candidate_order_preserved"] is True


def test_unavailable_when_context_unavailable() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["context_available"] = False
    result = _candidate_set_service().build(broken, eligibility)
    assert result["available"] is False
    assert result["candidates"] == []


def test_unavailable_when_not_decision_ready() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["decision_ready"] = False
    result = _candidate_set_service().build(broken, eligibility)
    assert result["available"] is False
    assert result["candidates"] == []


def test_unavailable_when_zero_candidates() -> None:
    context, eligibility = _empty_context_and_eligibility()
    result = _candidate_set_service().build(context, eligibility)
    assert result["available"] is False
    assert result["candidate_count"] == 0
    assert result["candidates"] == []


def test_unavailable_when_incomplete_coverage() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(eligibility)
    broken["eligible"] = False
    broken["all_candidates_evaluated"] = False
    broken["blocking_conditions"] = ["CANDIDATE_COVERAGE_INCOMPLETE"]
    result = _candidate_set_service().build(context, broken)
    assert result["available"] is False
    assert result["candidates"] == []


# ---------------------------------------------------------------------------
# Contract failures -- context
# ---------------------------------------------------------------------------


def test_rejects_none_context() -> None:
    _, eligibility = _ready_inputs()
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(None, eligibility)
    assert ei.value.invariant == "MISSING_CONTEXT"


def test_rejects_non_mapping_context() -> None:
    _, eligibility = _ready_inputs()
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build("nope", eligibility)  # type: ignore[arg-type]
    assert ei.value.invariant == "CONTEXT_TYPE"


def test_rejects_missing_context_field() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    del broken["decision_ready"]
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "MISSING_CONTEXT_FIELD"


def test_rejects_non_bool_context_available() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["context_available"] = "yes"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "CONTEXT_AVAILABLE_TYPE"


def test_rejects_negative_candidate_count() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["candidate_count"] = -1
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "CANDIDATE_COUNT_NEGATIVE"


def test_rejects_candidate_count_mismatch() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["candidate_count"] = broken["candidate_count"] + 1
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "CANDIDATE_COUNT_MISMATCH"


def test_rejects_non_list_differential() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["differential"] = "nope"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "DIFFERENTIAL_TYPE"


def test_rejects_malformed_candidate() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["differential"][0] = "not-a-mapping"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "MALFORMED_CANDIDATE"


def test_rejects_missing_candidate_field() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    del broken["differential"][0]["rank"]
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "MISSING_CANDIDATE_FIELD"


def test_rejects_invalid_uuid() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["differential"][0]["hypothesis_id"] = "not-a-uuid"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "INVALID_HYPOTHESIS_ID"


def test_rejects_duplicate_uuid() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["differential"][1]["hypothesis_id"] = broken["differential"][0][
        "hypothesis_id"
    ]
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "DUPLICATE_HYPOTHESIS_ID"


def test_rejects_non_string_name() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["differential"][0]["hypothesis_name"] = 123
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "INVALID_HYPOTHESIS_NAME"


def test_rejects_non_int_rank() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["differential"][0]["rank"] = "1"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "INVALID_RANK"


def test_rejects_non_numeric_score() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["differential"][0]["hypothesis_score"] = "high"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "INVALID_SCORE"


def test_rejects_non_bool_is_tied() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["differential"][0]["is_tied"] = "yes"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "INVALID_IS_TIED"


def test_rejects_non_int_tie_group_size() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["differential"][0]["tie_group_size"] = "one"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "INVALID_TIE_GROUP_SIZE"


def test_rejects_non_numeric_gap_higher() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["differential"][0]["score_gap_to_next_higher"] = "gap"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "INVALID_GAP_HIGHER"


def test_rejects_non_numeric_gap_lower() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["differential"][0]["score_gap_to_next_lower"] = "gap"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "INVALID_GAP_LOWER"


def test_rejects_invalid_context_source() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(context)
    broken["context_source"] = "SOMETHING_ELSE"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(broken, eligibility)
    assert ei.value.invariant == "INVALID_CONTEXT_SOURCE"


# ---------------------------------------------------------------------------
# Contract failures -- eligibility
# ---------------------------------------------------------------------------


def test_rejects_none_eligibility() -> None:
    context, _ = _ready_inputs()
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, None)
    assert ei.value.invariant == "MISSING_ELIGIBILITY"


def test_rejects_non_mapping_eligibility() -> None:
    context, _ = _ready_inputs()
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, "nope")  # type: ignore[arg-type]
    assert ei.value.invariant == "ELIGIBILITY_TYPE"


def test_rejects_missing_eligibility_field() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(eligibility)
    del broken["eligible"]
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, broken)
    assert ei.value.invariant == "MISSING_ELIGIBILITY_FIELD"


def test_rejects_non_bool_eligibility_field() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(eligibility)
    broken["eligible"] = "yes"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, broken)
    assert ei.value.invariant == "ELIGIBLE_TYPE"


def test_rejects_invalid_eligibility_source() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(eligibility)
    broken["eligibility_source"] = "SOMETHING_ELSE"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, broken)
    assert ei.value.invariant == "INVALID_ELIGIBILITY_SOURCE"


def test_rejects_non_list_blocking_conditions() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(eligibility)
    broken["blocking_conditions"] = "garbage"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, broken)
    assert ei.value.invariant == "BLOCKING_CONDITIONS_TYPE"


def test_rejects_invalid_blocking_condition_identifier() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(eligibility)
    broken["eligible"] = False
    broken["blocking_conditions"] = ["NOT_A_REAL_CONDITION"]
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, broken)
    assert ei.value.invariant == "INVALID_BLOCKING_CONDITION"


def test_rejects_duplicate_blocking_conditions() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(eligibility)
    broken["eligible"] = False
    broken["blocking_conditions"] = [
        "DECISION_NOT_READY",
        "DECISION_NOT_READY",
    ]
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, broken)
    assert ei.value.invariant == "DUPLICATE_BLOCKING_CONDITION"


def test_rejects_out_of_order_blocking_conditions() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(eligibility)
    broken["eligible"] = False
    broken["context_available"] = False
    broken["decision_ready"] = False
    broken["blocking_conditions"] = [
        "CONTEXT_UNAVAILABLE",
        "DECISION_NOT_READY",
    ]
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, broken)
    assert ei.value.invariant == "BLOCKING_CONDITIONS_ORDER"


def test_rejects_eligible_true_with_blocking_conditions() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(eligibility)
    broken["blocking_conditions"] = ["DECISION_NOT_READY"]
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, broken)
    assert ei.value.invariant == "ELIGIBLE_WITH_BLOCKING_CONDITIONS"


def test_rejects_eligible_false_with_empty_blocking_conditions() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(eligibility)
    broken["eligible"] = False
    broken["blocking_conditions"] = []
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, broken)
    assert ei.value.invariant == "INELIGIBLE_WITHOUT_BLOCKING_CONDITIONS"


def test_rejects_eligible_conjunction_mismatch() -> None:
    context, eligibility = _ready_inputs()
    broken = copy.deepcopy(eligibility)
    # eligible says True, but one conjunction term says False, and
    # blocking_conditions is non-empty so the eligible<->blocking
    # invariant would also fire -- flip eligible to False and clear
    # blocking to isolate the conjunction check.
    broken["eligible"] = True
    broken["candidate_count_matches"] = False
    # Make blocking_conditions consistent with eligible=True so the
    # earlier invariant passes; the conjunction check must then fire.
    broken["blocking_conditions"] = []
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        _candidate_set_service().build(context, broken)
    assert ei.value.invariant == "ELIGIBLE_CONJUNCTION_MISMATCH"


# ---------------------------------------------------------------------------
# Validator hardening -- tampered output
# ---------------------------------------------------------------------------


def _valid_result_and_upstream() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    context, eligibility = _ready_inputs()
    result = _candidate_set_service().build(context, eligibility)
    return result, context["differential"]


def test_tampered_removed_candidate() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidates"] = c["candidates"][:1]
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "COUNT_MISMATCH"


def test_tampered_added_candidate() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidates"] = c["candidates"] + [copy.deepcopy(c["candidates"][0])]
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "COUNT_MISMATCH"


def test_tampered_reordered_candidates() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidates"] = list(reversed(c["candidates"]))
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "ID_MISMATCH"


def test_tampered_id() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidates"][0]["hypothesis_id"] = uuid4()
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "ID_MISMATCH"


def test_tampered_name() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidates"][0]["hypothesis_name"] = "WRONG"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "NAME_MISMATCH"


def test_tampered_rank() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidates"][0]["rank"] = 99
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "RANK_MISMATCH"


def test_tampered_score() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidates"][0]["score"] = 999.0
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "SCORE_MISMATCH"


def test_tampered_is_tied() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidates"][0]["is_tied"] = not c["candidates"][0]["is_tied"]
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "IS_TIED_MISMATCH"


def test_tampered_tie_group_size() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidates"][0]["tie_group_size"] = 99
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "TIE_GROUP_SIZE_MISMATCH"


def test_tampered_gap_higher() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidates"][0]["score_gap_to_next_higher"] = 999.0
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "GAP_HIGHER_MISMATCH"


def test_tampered_gap_lower() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidates"][0]["score_gap_to_next_lower"] = 999.0
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "GAP_LOWER_MISMATCH"


def test_tampered_count() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidate_count"] = 99
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "COUNT_MISMATCH"


def test_tampered_set_complete() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidate_set_complete"] = False
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "CANDIDATE_SET_COMPLETE_MISMATCH"


def test_tampered_order_preserved() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidate_order_preserved"] = False
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "ORDER_NOT_PRESERVED"


def test_tampered_source() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["candidate_set_source"] = "SOMETHING_ELSE"
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "INVALID_SOURCE"


def test_tampered_available() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["available"] = False
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, True, upstream)
    assert ei.value.invariant == "AVAILABLE_MISMATCH"


def test_tampered_unavailable_with_candidates() -> None:
    result, upstream = _valid_result_and_upstream()
    c = copy.deepcopy(result)
    c["available"] = False
    c["candidate_set_complete"] = False
    with pytest.raises(DecisionCandidateSetContractError) as ei:
        DecisionCandidateSetService._validate_result(c, False, [])
    assert ei.value.invariant == "NONEMPTY_WHEN_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_build_does_not_mutate_context() -> None:
    context, eligibility = _ready_inputs()
    before = copy.deepcopy(context)
    _candidate_set_service().build(context, eligibility)
    assert context == before


def test_build_does_not_mutate_eligibility() -> None:
    context, eligibility = _ready_inputs()
    before = copy.deepcopy(eligibility)
    _candidate_set_service().build(context, eligibility)
    assert eligibility == before


def test_build_is_deterministic() -> None:
    context, eligibility = _ready_inputs()
    service = _candidate_set_service()
    assert service.build(context, eligibility) == service.build(context, eligibility)


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
            "metadata": {"source": "decision-candidate-set-test"},
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _seed_session(user_input: str) -> str:
    session_id = _create_session(user_input)
    obs = client.post(
        f"/sessions/{session_id}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert obs.status_code == 201
    gen = client.post(f"/sessions/{session_id}/generate-candidates")
    assert gen.status_code == 201
    assert len(gen.json()) > 0
    ev = client.post(f"/sessions/{session_id}/evaluate-evidence")
    assert ev.status_code == 200
    return session_id


def test_api_endpoint() -> None:
    session_id = _seed_session("Task 035 candidate set endpoint")

    response = client.get(f"/sessions/{session_id}/decision-candidate-set")
    assert response.status_code == 200
    payload = response.json()

    assert set(payload) == set(RESULT_FIELDS)
    assert (
        payload["candidate_set_source"]
        == CANDIDATE_SET_SOURCE_DECISION_CANDIDATE_SET_TASK_035
    )
    assert payload["available"] is True
    assert payload["candidate_count"] >= 1
    assert len(payload["candidates"]) == payload["candidate_count"]
    assert payload["candidate_order_preserved"] is True
    assert payload["candidate_set_complete"] is True
    for c in payload["candidates"]:
        assert set(c) == set(CANDIDATE_FIELDS)


def test_api_empty_session() -> None:
    session_id = _create_session("Task 035 empty candidate set")

    response = client.get(f"/sessions/{session_id}/decision-candidate-set")
    assert response.status_code == 200
    payload = response.json()

    assert payload["available"] is False
    assert payload["candidate_count"] == 0
    assert payload["candidates"] == []
    assert payload["candidate_set_complete"] is False


def test_api_missing_session_returns_404() -> None:
    response = client.get(f"/sessions/{uuid4()}/decision-candidate-set")
    assert response.status_code == 404


def test_api_is_read_only() -> None:
    session_id = _seed_session("Task 035 candidate set read-only")

    before = client.get(f"/sessions/{session_id}/decision-input-eligibility").json()
    response = client.get(f"/sessions/{session_id}/decision-candidate-set")
    assert response.status_code == 200
    after = client.get(f"/sessions/{session_id}/decision-input-eligibility").json()
    assert after == before


def test_api_is_deterministic() -> None:
    session_id = _seed_session("Task 035 candidate set determinism")

    first = client.get(f"/sessions/{session_id}/decision-candidate-set").json()
    second = client.get(f"/sessions/{session_id}/decision-candidate-set").json()
    assert first == second


def test_api_matches_service_output() -> None:
    session_id = _seed_session("Task 035 candidate set agreement")

    api_result = client.get(f"/sessions/{session_id}/decision-candidate-set").json()

    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        service_result = _candidate_set_service().build_for_session(
            db, session_uuid, candidates
        )
    finally:
        db_gen.close()

    assert api_result == _json_safe(service_result)


def _json_safe(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "candidates": [
            {**c, "hypothesis_id": str(c["hypothesis_id"])}
            for c in result["candidates"]
        ],
    }
