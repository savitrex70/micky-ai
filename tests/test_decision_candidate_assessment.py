"""Tests for Task 036 decision candidate assessment contract.

Task 036 joins the Task 035 candidate set with Task 032's per-candidate
evaluations under Task 033's structural guarantees. Never selects a
winner, aggregates criteria into a score, ranks, breaks ties, filters,
or persists.
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
    ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036,
    DecisionCandidateAssessmentContractError,
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
from rop.services.decision_input_eligibility import DecisionInputEligibilityService
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
    "assessments",
    "candidate_order_preserved",
    "evaluation_coverage_complete",
    "assessment_structure_consistent",
    "assessment_source",
)

ASSESSMENT_FIELDS = (
    "hypothesis_id",
    "hypothesis_name",
    "rank",
    "score",
    "is_tied",
    "tie_group_size",
    "score_gap_to_next_higher",
    "score_gap_to_next_lower",
    "criteria",
    "criterion_count",
    "criteria_satisfied",
    "criteria_unsatisfied",
    "required_criteria_satisfied",
    "required_criteria_unsatisfied",
    "evaluation_complete",
    "assessment_source",
)

CRITERION_FIELDS = (
    "criterion_id",
    "criterion_name",
    "satisfied",
    "required",
    "reason",
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


def _assessment_service() -> DecisionCandidateAssessmentService:
    return DecisionCandidateAssessmentService(_candidate_set_service())


def _score_result(*, hypothesis_name: str, hypothesis_score: float) -> dict[str, Any]:
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


def _chain(entries: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Return (candidate_set, evaluations, consistency, context)."""
    context = _make_context(entries)
    evaluations = _candidate_evaluation_service().evaluate(context)
    expected_ids = [e["hypothesis_id"] for e in context["differential"]]
    consistency = _consistency_service().check(evaluations, expected_ids)
    eligibility = _eligibility_service().build(context, consistency)
    candidate_set = _candidate_set_service().build(context, eligibility)
    return candidate_set, evaluations, consistency, context


def _ready_chain() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    return _chain(
        [
            _score_result(hypothesis_name="H1", hypothesis_score=10.0),
            _score_result(hypothesis_name="H2", hypothesis_score=5.0),
        ]
    )


# ---------------------------------------------------------------------------
# Valid cases
# ---------------------------------------------------------------------------


def test_single_candidate_assessment() -> None:
    cs, ev, co, _ = _chain(
        [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    )
    result = _assessment_service().build(cs, ev, co)

    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["candidate_count"] == 1
    assert len(result["assessments"]) == 1
    a = result["assessments"][0]
    assert set(a) == set(ASSESSMENT_FIELDS)
    for c in a["criteria"]:
        assert set(c) == set(CRITERION_FIELDS)


def test_multiple_candidates_assessment() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)

    assert result["available"] is True
    assert result["candidate_count"] == 2
    assert len(result["assessments"]) == 2


def test_source_fixed() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)
    assert (
        result["assessment_source"]
        == ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036
    )
    for a in result["assessments"]:
        assert (
            a["assessment_source"]
            == ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036
        )


def test_tied_candidates_assessment() -> None:
    cs, ev, co, _ = _chain(
        [
            _score_result(hypothesis_name="H1", hypothesis_score=10.0),
            _score_result(hypothesis_name="H2", hypothesis_score=10.0),
            _score_result(hypothesis_name="H3", hypothesis_score=5.0),
        ]
    )
    result = _assessment_service().build(cs, ev, co)

    for i, a in enumerate(result["assessments"]):
        assert a["is_tied"] == cs["candidates"][i]["is_tied"]
        assert a["tie_group_size"] == cs["candidates"][i]["tie_group_size"]


def test_negative_zero_positive_scores() -> None:
    cs, ev, co, _ = _chain(
        [
            _score_result(hypothesis_name="pos", hypothesis_score=10.0),
            _score_result(hypothesis_name="zero", hypothesis_score=0.0),
            _score_result(hypothesis_name="neg", hypothesis_score=-3.0),
        ]
    )
    result = _assessment_service().build(cs, ev, co)

    scores = [a["score"] for a in result["assessments"]]
    assert 10.0 in scores
    assert 0.0 in scores
    assert -3.0 in scores


def test_candidate_identity_preserved() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)

    for i, c in enumerate(cs["candidates"]):
        a = result["assessments"][i]
        assert a["hypothesis_id"] == c["hypothesis_id"]
        assert a["hypothesis_name"] == c["hypothesis_name"]


def test_candidate_rank_preserved() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)
    for i, c in enumerate(cs["candidates"]):
        assert result["assessments"][i]["rank"] == c["rank"]


def test_candidate_score_preserved() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)
    for i, c in enumerate(cs["candidates"]):
        assert result["assessments"][i]["score"] == c["score"]


def test_candidate_gaps_preserved() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)
    for i, c in enumerate(cs["candidates"]):
        a = result["assessments"][i]
        assert a["score_gap_to_next_higher"] == c["score_gap_to_next_higher"]
        assert a["score_gap_to_next_lower"] == c["score_gap_to_next_lower"]


def test_criterion_results_preserved() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)
    ev_by_id = {e["hypothesis_id"]: e for e in ev}

    for a in result["assessments"]:
        upstream = ev_by_id[a["hypothesis_id"]]
        assert len(a["criteria"]) == len(upstream["criteria"])
        for ac, uc in zip(a["criteria"], upstream["criteria"], strict=True):
            assert ac["criterion_id"] == uc["criterion_id"]
            assert ac["criterion_name"] == uc["criterion_name"]
            assert ac["satisfied"] == uc["satisfied"]
            assert ac["required"] == uc["required"]
            assert ac["reason"] == uc["reason"]


def test_evaluation_counts_preserved() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)
    ev_by_id = {e["hypothesis_id"]: e for e in ev}

    for a in result["assessments"]:
        u = ev_by_id[a["hypothesis_id"]]
        assert a["criterion_count"] == u["criterion_count"]
        assert a["criteria_satisfied"] == u["criteria_satisfied"]
        assert a["criteria_unsatisfied"] == u["criteria_unsatisfied"]
        assert (
            a["required_criteria_satisfied"] == u["required_criteria_satisfied"]
        )
        assert (
            a["required_criteria_unsatisfied"]
            == u["required_criteria_unsatisfied"]
        )
        assert a["evaluation_complete"] == u["evaluation_complete"]


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_candidate_order_preserved() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)
    assert result["candidate_order_preserved"] is True
    upstream_ids = [c["hypothesis_id"] for c in cs["candidates"]]
    result_ids = [a["hypothesis_id"] for a in result["assessments"]]
    assert result_ids == upstream_ids


def test_criterion_order_preserved() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)
    ev_by_id = {e["hypothesis_id"]: e for e in ev}

    for a in result["assessments"]:
        upstream_criterion_ids = [
            c["criterion_id"] for c in ev_by_id[a["hypothesis_id"]]["criteria"]
        ]
        result_criterion_ids = [c["criterion_id"] for c in a["criteria"]]
        assert result_criterion_ids == upstream_criterion_ids


# ---------------------------------------------------------------------------
# Coverage / structural consistency
# ---------------------------------------------------------------------------


def test_all_candidates_evaluated() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)
    assert result["evaluation_coverage_complete"] is True
    assert result["assessment_structure_consistent"] is True


def test_unavailable_when_candidate_set_unavailable() -> None:
    cs, ev, co, _ = _ready_chain()
    broken_cs = copy.deepcopy(cs)
    broken_cs["available"] = False
    broken_cs["candidate_count"] = 0
    broken_cs["candidates"] = []
    broken_cs["candidate_set_complete"] = False

    result = _assessment_service().build(broken_cs, ev, co)
    assert result["available"] is False
    assert result["assessments"] == []
    assert result["candidate_count"] == 0


def test_unavailable_when_inconsistent() -> None:
    cs, ev, co, _ = _ready_chain()
    broken_co = copy.deepcopy(co)
    broken_co["consistent"] = False
    broken_co["has_structural_mismatch"] = True

    result = _assessment_service().build(cs, ev, broken_co)
    assert result["available"] is False
    assert result["assessments"] == []
    assert result["assessment_structure_consistent"] is False


def test_unavailable_when_coverage_incomplete() -> None:
    cs, ev, co, _ = _ready_chain()
    broken_co = copy.deepcopy(co)
    broken_co["all_candidates_evaluated"] = False

    result = _assessment_service().build(cs, ev, broken_co)
    assert result["available"] is False
    assert result["assessments"] == []
    assert result["evaluation_coverage_complete"] is False


def test_unavailable_when_criteria_incomplete() -> None:
    cs, ev, co, _ = _ready_chain()
    broken_co = copy.deepcopy(co)
    broken_co["all_criteria_evaluated"] = False

    result = _assessment_service().build(cs, ev, broken_co)
    assert result["available"] is False
    assert result["assessments"] == []


# ---------------------------------------------------------------------------
# Contract failures -- Task 035 input
# ---------------------------------------------------------------------------


def test_rejects_none_candidate_set() -> None:
    _, ev, co, _ = _ready_chain()
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(None, ev, co)
    assert ei.value.invariant == "MISSING_CANDIDATE_SET"


def test_rejects_non_mapping_candidate_set() -> None:
    _, ev, co, _ = _ready_chain()
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build("nope", ev, co)  # type: ignore[arg-type]
    assert ei.value.invariant == "CANDIDATE_SET_TYPE"


def test_rejects_missing_candidate_set_field() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(cs)
    del broken["available"]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(broken, ev, co)
    assert ei.value.invariant == "MISSING_CANDIDATE_SET_FIELD"


def test_rejects_non_bool_candidate_set_field() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(cs)
    broken["available"] = "yes"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(broken, ev, co)
    assert ei.value.invariant == "AVAILABLE_TYPE"


def test_rejects_negative_candidate_set_count() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(cs)
    broken["candidate_count"] = -1
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(broken, ev, co)
    assert ei.value.invariant == "CANDIDATE_SET_COUNT_NEGATIVE"


def test_rejects_candidate_set_count_mismatch() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(cs)
    broken["candidate_count"] = 99
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(broken, ev, co)
    assert ei.value.invariant == "CANDIDATE_SET_COUNT_MISMATCH"


def test_rejects_non_list_candidates() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(cs)
    broken["candidates"] = "nope"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(broken, ev, co)
    assert ei.value.invariant == "CANDIDATES_TYPE"


def test_rejects_malformed_candidate() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(cs)
    broken["candidates"][0] = "not-a-mapping"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(broken, ev, co)
    assert ei.value.invariant == "MALFORMED_CANDIDATE"


def test_rejects_missing_candidate_field() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(cs)
    del broken["candidates"][0]["rank"]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(broken, ev, co)
    assert ei.value.invariant == "MISSING_CANDIDATE_FIELD"


def test_rejects_invalid_candidate_uuid() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(cs)
    broken["candidates"][0]["hypothesis_id"] = "nope"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(broken, ev, co)
    assert ei.value.invariant == "INVALID_CANDIDATE_ID"


def test_rejects_duplicate_candidate_id() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(cs)
    broken["candidates"][1]["hypothesis_id"] = broken["candidates"][0][
        "hypothesis_id"
    ]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(broken, ev, co)
    assert ei.value.invariant == "DUPLICATE_CANDIDATE_ID"


def test_rejects_invalid_candidate_source() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(cs)
    broken["candidate_set_source"] = "SOMETHING_ELSE"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(broken, ev, co)
    assert ei.value.invariant == "INVALID_CANDIDATE_SET_SOURCE"


# ---------------------------------------------------------------------------
# Contract failures -- Task 032 evaluations
# ---------------------------------------------------------------------------


def test_rejects_none_evaluations() -> None:
    cs, _, co, _ = _ready_chain()
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, None, co)
    assert ei.value.invariant == "MISSING_EVALUATIONS"


def test_rejects_non_list_evaluations() -> None:
    cs, _, co, _ = _ready_chain()
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, "nope", co)  # type: ignore[arg-type]
    assert ei.value.invariant == "EVALUATIONS_TYPE"


def test_rejects_missing_evaluation_field() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(ev)
    del broken[0]["criteria"]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, broken, co)
    assert ei.value.invariant == "MISSING_EVALUATION_FIELD"


def test_rejects_invalid_evaluation_uuid() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(ev)
    broken[0]["hypothesis_id"] = "nope"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, broken, co)
    assert ei.value.invariant == "INVALID_EVALUATION_ID"


def test_rejects_duplicate_evaluation_id() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(ev)
    broken[1]["hypothesis_id"] = broken[0]["hypothesis_id"]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, broken, co)
    assert ei.value.invariant == "DUPLICATE_EVALUATION_ID"


def test_rejects_non_list_criteria() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(ev)
    broken[0]["criteria"] = "nope"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, broken, co)
    assert ei.value.invariant == "CRITERIA_TYPE"


def test_rejects_malformed_criterion() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(ev)
    broken[0]["criteria"][0] = "not-a-mapping"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, broken, co)
    assert ei.value.invariant == "MALFORMED_CRITERION"


def test_rejects_missing_criterion_field() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(ev)
    del broken[0]["criteria"][0]["reason"]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, broken, co)
    assert ei.value.invariant == "MISSING_CRITERION_FIELD"


def test_rejects_duplicate_criterion_id() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(ev)
    broken[0]["criteria"][1]["criterion_id"] = broken[0]["criteria"][0][
        "criterion_id"
    ]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, broken, co)
    assert ei.value.invariant == "DUPLICATE_CRITERION_ID"


def test_rejects_non_bool_criterion_satisfied() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(ev)
    broken[0]["criteria"][0]["satisfied"] = "yes"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, broken, co)
    assert ei.value.invariant == "INVALID_CRITERION_SATISFIED"


def test_rejects_negative_count() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(ev)
    broken[0]["criterion_count"] = -1
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, broken, co)
    assert ei.value.invariant == "NEGATIVE_CRITERION_COUNT"


def test_rejects_invalid_evaluation_source() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(ev)
    broken[0]["evaluation_source"] = ""
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, broken, co)
    assert ei.value.invariant == "INVALID_EVALUATION_SOURCE"


# ---------------------------------------------------------------------------
# Contract failures -- Task 033 consistency
# ---------------------------------------------------------------------------


def test_rejects_none_consistency() -> None:
    cs, ev, _, _ = _ready_chain()
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, ev, None)
    assert ei.value.invariant == "MISSING_CONSISTENCY"


def test_rejects_non_mapping_consistency() -> None:
    cs, ev, _, _ = _ready_chain()
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, ev, "nope")  # type: ignore[arg-type]
    assert ei.value.invariant == "CONSISTENCY_TYPE"


def test_rejects_missing_consistency_field() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(co)
    del broken["consistent"]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, ev, broken)
    assert ei.value.invariant == "MISSING_CONSISTENCY_FIELD"


def test_rejects_non_bool_consistency_field() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(co)
    broken["consistent"] = "yes"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, ev, broken)
    assert ei.value.invariant == "CONSISTENT_TYPE"


def test_rejects_negative_consistency_count() -> None:
    cs, ev, co, _ = _ready_chain()
    broken = copy.deepcopy(co)
    broken["evaluation_count"] = -1
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        _assessment_service().build(cs, ev, broken)
    assert ei.value.invariant == "EVALUATION_COUNT_NEGATIVE"


# ---------------------------------------------------------------------------
# Validator hardening -- tamper the output
# ---------------------------------------------------------------------------


def _valid_result() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)
    return result, cs, ev, co


def test_tamper_assessment_id_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["hypothesis_id"] = uuid4()
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "ID_MISMATCH"


def test_tamper_assessment_name_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["hypothesis_name"] = "WRONG"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "NAME_MISMATCH"


def test_tamper_rank_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["rank"] = 99
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "RANK_MISMATCH"


def test_tamper_score_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["score"] = 999.0
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "SCORE_MISMATCH"


def test_tamper_is_tied_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["is_tied"] = not c["assessments"][0]["is_tied"]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "IS_TIED_MISMATCH"


def test_tamper_tie_group_size_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["tie_group_size"] = 99
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "TIE_GROUP_SIZE_MISMATCH"


def test_tamper_gap_higher_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["score_gap_to_next_higher"] = 999.0
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "GAP_HIGHER_MISMATCH"


def test_tamper_gap_lower_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["score_gap_to_next_lower"] = 999.0
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "GAP_LOWER_MISMATCH"


def test_tamper_criterion_id_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["criteria"][0]["criterion_id"] = "WRONG"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "CRITERION_ID_MISMATCH"


def test_tamper_criterion_name_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["criteria"][0]["criterion_name"] = "WRONG"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "CRITERION_NAME_MISMATCH"


def test_tamper_criterion_satisfied_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["criteria"][0]["satisfied"] = not c["assessments"][0][
        "criteria"
    ][0]["satisfied"]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "CRITERION_SATISFIED_MISMATCH"


def test_tamper_criterion_required_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["criteria"][0]["required"] = not c["assessments"][0][
        "criteria"
    ][0]["required"]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "CRITERION_REQUIRED_MISMATCH"


def test_tamper_criterion_reason_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["criteria"][0]["reason"] = "WRONG"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "CRITERION_REASON_MISMATCH"


def test_tamper_criterion_count_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["criterion_count"] = 99
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "CRITERION_COUNT_MISMATCH"


def test_tamper_criteria_satisfied_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["criteria_satisfied"] = 99
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "CRITERIA_SATISFIED_MISMATCH"


def test_tamper_evaluation_complete_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"][0]["evaluation_complete"] = not c["assessments"][0][
        "evaluation_complete"
    ]
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "EVAL_COMPLETE_MISMATCH"


def test_tamper_candidate_order_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessments"] = list(reversed(c["assessments"]))
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "ID_MISMATCH"


def test_tamper_source_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["assessment_source"] = "SOMETHING_ELSE"
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "INVALID_SOURCE"


def test_tamper_available_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    c["available"] = False
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "AVAILABLE_MISMATCH"


def test_tamper_coverage_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    # coverage is an input to `available`, so flipping it alone trips
    # the AVAILABLE_MISMATCH check first. Flip `available` too so the
    # coverage invariant is what fires.
    c["available"] = False
    c["evaluation_coverage_complete"] = False
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "COVERAGE_MISMATCH"


def test_tamper_structure_rejected() -> None:
    result, cs, ev, co = _valid_result()
    c = copy.deepcopy(result)
    # structure is an input to `available`, so flipping it alone trips
    # the AVAILABLE_MISMATCH check first. Flip `available` too so the
    # structure invariant is what fires.
    c["available"] = False
    c["assessment_structure_consistent"] = False
    with pytest.raises(DecisionCandidateAssessmentContractError) as ei:
        DecisionCandidateAssessmentService._validate_result(c, cs, ev, co)
    assert ei.value.invariant == "STRUCTURE_MISMATCH"


# ---------------------------------------------------------------------------
# No-decision regression
# ---------------------------------------------------------------------------


def test_no_decision_fields_present() -> None:
    cs, ev, co, _ = _ready_chain()
    result = _assessment_service().build(cs, ev, co)
    forbidden = (
        "winner",
        "selected_candidate",
        "best_candidate",
        "diagnosis",
        "recommendation",
        "action",
        "probability",
        "confidence",
        "utility",
        "expected_outcome",
        "treatment",
        "decision",
    )
    assert set(result) == set(RESULT_FIELDS)
    for a in result["assessments"]:
        assert set(a) == set(ASSESSMENT_FIELDS)
        for f in forbidden:
            assert f not in a
        for c in a["criteria"]:
            assert set(c) == set(CRITERION_FIELDS)


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_does_not_mutate_candidate_set() -> None:
    cs, ev, co, _ = _ready_chain()
    before = copy.deepcopy(cs)
    _assessment_service().build(cs, ev, co)
    assert cs == before


def test_does_not_mutate_evaluations() -> None:
    cs, ev, co, _ = _ready_chain()
    before = copy.deepcopy(ev)
    _assessment_service().build(cs, ev, co)
    assert ev == before


def test_does_not_mutate_consistency() -> None:
    cs, ev, co, _ = _ready_chain()
    before = copy.deepcopy(co)
    _assessment_service().build(cs, ev, co)
    assert co == before


def test_deterministic() -> None:
    cs, ev, co, _ = _ready_chain()
    s = _assessment_service()
    assert s.build(cs, ev, co) == s.build(cs, ev, co)


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
            "metadata": {"source": "decision-candidate-assessment-test"},
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
    sid = _seed_session("Task 036 API test")
    r = client.get(f"/sessions/{sid}/decision-candidate-assessments")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(RESULT_FIELDS)
    assert (
        payload["assessment_source"]
        == ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036
    )
    assert payload["available"] is True
    assert payload["candidate_count"] >= 1
    assert len(payload["assessments"]) == payload["candidate_count"]
    for a in payload["assessments"]:
        assert set(a) == set(ASSESSMENT_FIELDS)


def test_api_empty_session() -> None:
    sid = _create_session("Task 036 empty session")
    r = client.get(f"/sessions/{sid}/decision-candidate-assessments")
    assert r.status_code == 200
    payload = r.json()
    assert payload["available"] is False
    assert payload["candidate_count"] == 0
    assert payload["assessments"] == []


def test_api_missing_session_returns_404() -> None:
    r = client.get(f"/sessions/{uuid4()}/decision-candidate-assessments")
    assert r.status_code == 404


def test_api_is_read_only() -> None:
    sid = _seed_session("Task 036 read-only")
    before = client.get(f"/sessions/{sid}/decision-candidate-set").json()
    r = client.get(f"/sessions/{sid}/decision-candidate-assessments")
    assert r.status_code == 200
    after = client.get(f"/sessions/{sid}/decision-candidate-set").json()
    assert after == before


def test_api_is_deterministic() -> None:
    sid = _seed_session("Task 036 deterministic")
    first = client.get(f"/sessions/{sid}/decision-candidate-assessments").json()
    second = client.get(f"/sessions/{sid}/decision-candidate-assessments").json()
    assert first == second


def test_api_matches_service_output() -> None:
    sid = _seed_session("Task 036 agreement")
    api_result = client.get(
        f"/sessions/{sid}/decision-candidate-assessments"
    ).json()

    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        service_result = _assessment_service().build_for_session(
            db, session_uuid, candidates
        )
    finally:
        db_gen.close()

    assert api_result == _json_safe(service_result)


def _json_safe(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "assessments": [
            {**a, "hypothesis_id": str(a["hypothesis_id"])}
            for a in result["assessments"]
        ],
    }
