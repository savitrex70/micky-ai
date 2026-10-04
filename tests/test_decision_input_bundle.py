"""Tests for Task 037 decision input bundle contract.

Task 037 packages the Task 035 candidate set and Task 036 assessment
set into one cross-validated structure. Never selects a winner,
reranks, rescores, filters, deduplicates, or persists.
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
    DecisionCandidateAssessmentService,
)
from rop.services.decision_candidate_evaluation import (
    DecisionCandidateEvaluationService,
)
from rop.services.decision_candidate_set import (
    CANDIDATE_SET_SOURCE_DECISION_CANDIDATE_SET_TASK_035,
    DecisionCandidateSetService,
)
from rop.services.decision_context import DecisionContextService
from rop.services.decision_evaluation_consistency import (
    DecisionEvaluationConsistencyService,
)
from rop.services.decision_input_bundle import (
    INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037,
    DecisionInputBundleContractError,
    DecisionInputBundleService,
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
    "candidate_set",
    "assessment_set",
    "candidate_count",
    "candidate_order_preserved",
    "candidate_assessment_alignment_complete",
    "input_structure_consistent",
    "input_source",
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


def _bundle_service() -> DecisionInputBundleService:
    return DecisionInputBundleService(
        _candidate_set_service(),
        _assessment_service(),
    )


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


def _chain(entries):
    """Return (candidate_set, assessment_set)."""
    context = _make_context(entries)
    evaluations = _candidate_evaluation_service().evaluate(context)
    expected = [e["hypothesis_id"] for e in context["differential"]]
    consistency = _consistency_service().check(evaluations, expected)
    eligibility = _eligibility_service().build(context, consistency)
    cs = _candidate_set_service().build(context, eligibility)
    aset = _assessment_service().build(cs, evaluations, consistency)
    return cs, aset


def _ready_bundle() -> tuple[dict[str, Any], dict[str, Any]]:
    return _chain(
        [
            _score_result(hypothesis_name="H1", hypothesis_score=10.0),
            _score_result(hypothesis_name="H2", hypothesis_score=5.0),
        ]
    )


# ---------------------------------------------------------------------------
# Valid package
# ---------------------------------------------------------------------------


def test_single_candidate_bundle() -> None:
    cs, aset = _chain([_score_result(hypothesis_name="H1", hypothesis_score=5.0)])
    result = _bundle_service().build(cs, aset)

    assert set(result) == set(RESULT_FIELDS)
    assert result["available"] is True
    assert result["candidate_count"] == 1
    assert result["candidate_assessment_alignment_complete"] is True
    assert result["input_structure_consistent"] is True


def test_multiple_candidates_bundle() -> None:
    cs, aset = _ready_bundle()
    result = _bundle_service().build(cs, aset)

    assert result["available"] is True
    assert result["candidate_count"] == 2
    assert len(result["candidate_set"]["candidates"]) == 2
    assert len(result["assessment_set"]["assessments"]) == 2


def test_source_fixed() -> None:
    cs, aset = _ready_bundle()
    result = _bundle_service().build(cs, aset)
    assert result["input_source"] == INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037


def test_nested_sources_preserved() -> None:
    cs, aset = _ready_bundle()
    result = _bundle_service().build(cs, aset)
    assert (
        result["candidate_set"]["candidate_set_source"]
        == CANDIDATE_SET_SOURCE_DECISION_CANDIDATE_SET_TASK_035
    )
    assert (
        result["assessment_set"]["assessment_source"]
        == ASSESSMENT_SOURCE_DECISION_CANDIDATE_ASSESSMENT_TASK_036
    )


def test_candidate_set_preserved_verbatim() -> None:
    cs, aset = _ready_bundle()
    result = _bundle_service().build(cs, aset)
    assert result["candidate_set"] == cs


def test_assessment_set_preserved_verbatim() -> None:
    cs, aset = _ready_bundle()
    result = _bundle_service().build(cs, aset)
    assert result["assessment_set"] == aset


def test_candidate_order_preserved_true() -> None:
    cs, aset = _ready_bundle()
    result = _bundle_service().build(cs, aset)
    assert result["candidate_order_preserved"] is True


# ---------------------------------------------------------------------------
# Identity alignment
# ---------------------------------------------------------------------------


def test_rejects_id_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"][0]["hypothesis_id"] = uuid4()
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "ID_MISMATCH"


def test_rejects_count_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"] = broken["assessments"][:1]
    broken["candidate_count"] = 1
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "CANDIDATE_COUNT_MISMATCH"


# ---------------------------------------------------------------------------
# Metadata alignment
# ---------------------------------------------------------------------------


def test_rejects_name_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"][0]["hypothesis_name"] = "WRONG"
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "NAME_MISMATCH"


def test_rejects_rank_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"][0]["rank"] = 99
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "RANK_MISMATCH"


def test_rejects_score_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"][0]["score"] = 999.0
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "SCORE_MISMATCH"


def test_rejects_is_tied_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"][0]["is_tied"] = not broken["assessments"][0]["is_tied"]
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "IS_TIED_MISMATCH"


def test_rejects_tie_group_size_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"][0]["tie_group_size"] = 99
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "TIE_GROUP_SIZE_MISMATCH"


def test_rejects_gap_higher_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"][0]["score_gap_to_next_higher"] = 999.0
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "GAP_HIGHER_MISMATCH"


def test_rejects_gap_lower_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"][0]["score_gap_to_next_lower"] = 999.0
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "GAP_LOWER_MISMATCH"


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def test_order_preserved_when_identical() -> None:
    cs, aset = _ready_bundle()
    result = _bundle_service().build(cs, aset)
    assert result["candidate_order_preserved"] is True


def test_rejects_reordered_assessments() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"] = list(reversed(broken["assessments"]))
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "ID_MISMATCH"


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_unavailable_when_candidate_set_unavailable() -> None:
    cs, aset = _ready_bundle()
    broken_cs = copy.deepcopy(cs)
    broken_cs["available"] = False
    broken_cs["candidate_count"] = 0
    broken_cs["candidates"] = []
    broken_cs["candidate_set_complete"] = False
    broken_as = copy.deepcopy(aset)
    broken_as["available"] = False
    broken_as["candidate_count"] = 0
    broken_as["assessments"] = []

    result = _bundle_service().build(broken_cs, broken_as)
    assert result["available"] is False
    assert result["candidate_count"] == 0


def test_unavailable_when_assessment_set_unavailable() -> None:
    cs, aset = _ready_bundle()
    broken_cs = copy.deepcopy(cs)
    broken_cs["available"] = False
    broken_cs["candidate_count"] = 0
    broken_cs["candidates"] = []
    broken_cs["candidate_set_complete"] = False
    broken_as = copy.deepcopy(aset)
    broken_as["available"] = False
    broken_as["candidate_count"] = 0
    broken_as["assessments"] = []

    result = _bundle_service().build(broken_cs, broken_as)
    assert result["available"] is False


def test_alignment_incomplete_when_one_side_unavailable() -> None:
    cs, aset = _ready_bundle()
    broken_as = copy.deepcopy(aset)
    broken_as["available"] = False
    broken_as["candidate_count"] = 0
    broken_as["assessments"] = []

    result = _bundle_service().build(cs, broken_as)
    assert result["available"] is False
    assert result["candidate_assessment_alignment_complete"] is False


# ---------------------------------------------------------------------------
# Contract failures -- candidate_set input
# ---------------------------------------------------------------------------


def test_rejects_none_candidate_set() -> None:
    _, aset = _ready_bundle()
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(None, aset)
    assert ei.value.invariant == "MISSING_CANDIDATE_SET"


def test_rejects_non_mapping_candidate_set() -> None:
    _, aset = _ready_bundle()
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build("nope", aset)  # type: ignore[arg-type]
    assert ei.value.invariant == "CANDIDATE_SET_TYPE"


def test_rejects_missing_candidate_set_field() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(cs)
    del broken["candidate_order_preserved"]
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(broken, aset)
    assert ei.value.invariant == "MISSING_CANDIDATE_SET_FIELD"


def test_rejects_non_bool_candidate_set_field() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(cs)
    broken["available"] = "yes"
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(broken, aset)
    assert ei.value.invariant == "AVAILABLE_TYPE"


def test_rejects_negative_candidate_set_count() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(cs)
    broken["candidate_count"] = -1
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(broken, aset)
    assert ei.value.invariant == "CANDIDATE_SET_COUNT_NEGATIVE"


def test_rejects_candidate_set_count_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(cs)
    broken["candidate_count"] = 99
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(broken, aset)
    assert ei.value.invariant == "CANDIDATE_SET_COUNT_MISMATCH"


def test_rejects_non_list_candidates() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(cs)
    broken["candidates"] = "nope"
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(broken, aset)
    assert ei.value.invariant == "CANDIDATES_TYPE"


def test_rejects_malformed_candidate() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(cs)
    broken["candidates"][0] = "not-a-mapping"
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(broken, aset)
    assert ei.value.invariant == "MALFORMED_CANDIDATE"


def test_rejects_missing_candidate_field() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(cs)
    del broken["candidates"][0]["rank"]
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(broken, aset)
    assert ei.value.invariant == "MISSING_CANDIDATE_FIELD"


def test_rejects_invalid_candidate_set_source() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(cs)
    broken["candidate_set_source"] = "WRONG"
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(broken, aset)
    assert ei.value.invariant == "INVALID_CANDIDATE_SET_SOURCE"


def test_rejects_upstream_order_not_preserved() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(cs)
    broken["candidate_order_preserved"] = False
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(broken, aset)
    assert ei.value.invariant == "UPSTREAM_ORDER_NOT_PRESERVED"


def test_rejects_candidate_set_complete_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(cs)
    broken["candidate_set_complete"] = not broken["candidate_set_complete"]
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(broken, aset)
    assert ei.value.invariant == "CANDIDATE_SET_COMPLETE_MISMATCH"


# ---------------------------------------------------------------------------
# Contract failures -- assessment_set input
# ---------------------------------------------------------------------------


def test_rejects_none_assessment_set() -> None:
    cs, _ = _ready_bundle()
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, None)
    assert ei.value.invariant == "MISSING_ASSESSMENT_SET"


def test_rejects_non_mapping_assessment_set() -> None:
    cs, _ = _ready_bundle()
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, "nope")  # type: ignore[arg-type]
    assert ei.value.invariant == "ASSESSMENT_SET_TYPE"


def test_rejects_missing_assessment_set_field() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    del broken["assessment_structure_consistent"]
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "MISSING_ASSESSMENT_SET_FIELD"


def test_rejects_non_bool_assessment_set_field() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["available"] = "yes"
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "AVAILABLE_TYPE"


def test_rejects_negative_assessment_set_count() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["candidate_count"] = -1
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "ASSESSMENT_SET_COUNT_NEGATIVE"


def test_rejects_assessment_set_count_mismatch() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["candidate_count"] = 99
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "ASSESSMENT_SET_COUNT_MISMATCH"


def test_rejects_non_list_assessments() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"] = "nope"
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "ASSESSMENTS_TYPE"


def test_rejects_malformed_assessment() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessments"][0] = "not-a-mapping"
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "MALFORMED_ASSESSMENT"


def test_rejects_missing_assessment_field() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    del broken["assessments"][0]["rank"]
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "MISSING_ASSESSMENT_FIELD"


def test_rejects_invalid_assessment_set_source() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessment_source"] = "WRONG"
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "INVALID_ASSESSMENT_SET_SOURCE"


def test_rejects_assessment_order_not_preserved() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["candidate_order_preserved"] = False
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "ASSESSMENT_ORDER_NOT_PRESERVED"


# ---------------------------------------------------------------------------
# Determinism / integrity
# ---------------------------------------------------------------------------


def test_does_not_mutate_candidate_set() -> None:
    cs, aset = _ready_bundle()
    before = copy.deepcopy(cs)
    _bundle_service().build(cs, aset)
    assert cs == before


def test_does_not_mutate_assessment_set() -> None:
    cs, aset = _ready_bundle()
    before = copy.deepcopy(aset)
    _bundle_service().build(cs, aset)
    assert aset == before


def test_deterministic() -> None:
    cs, aset = _ready_bundle()
    s = _bundle_service()
    assert s.build(cs, aset) == s.build(cs, aset)


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------


def test_build_for_session_delegates_to_task035_and_036(monkeypatch) -> None:
    calls = {"cs": 0, "as": 0}
    orig_cs = DecisionCandidateSetService.build_for_session_with_inputs
    orig_as = DecisionCandidateAssessmentService.build

    def spy_cs(self, db, session_id, candidates):
        calls["cs"] += 1
        return orig_cs(self, db, session_id, candidates)

    def spy_as(self, candidate_set, evaluations, consistency_result):
        calls["as"] += 1
        return orig_as(self, candidate_set, evaluations, consistency_result)

    monkeypatch.setattr(
        DecisionCandidateSetService, "build_for_session_with_inputs", spy_cs
    )
    monkeypatch.setattr(DecisionCandidateAssessmentService, "build", spy_as)

    sid = _seed_session("Task 037 delegation")
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        result = _bundle_service().build_for_session(db, session_uuid, candidates)
    finally:
        db_gen.close()

    assert calls["cs"] == 1
    assert calls["as"] == 1
    assert result["available"] is True


# ---------------------------------------------------------------------------
# No-decision regression
# ---------------------------------------------------------------------------


def test_no_decision_fields_present() -> None:
    cs, aset = _ready_bundle()
    result = _bundle_service().build(cs, aset)
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
    for f in forbidden:
        assert f not in result


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
            "metadata": {"source": "decision-input-bundle-test"},
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
    sid = _seed_session("Task 037 API test")
    r = client.get(f"/sessions/{sid}/decision-input-bundle")
    assert r.status_code == 200
    payload = r.json()
    assert set(payload) == set(RESULT_FIELDS)
    assert payload["input_source"] == INPUT_BUNDLE_SOURCE_DECISION_INPUT_BUNDLE_TASK_037
    assert payload["available"] is True
    assert payload["candidate_count"] >= 1
    assert payload["candidate_assessment_alignment_complete"] is True
    assert payload["input_structure_consistent"] is True


def test_api_empty_session() -> None:
    sid = _create_session("Task 037 empty session")
    r = client.get(f"/sessions/{sid}/decision-input-bundle")
    assert r.status_code == 200
    payload = r.json()
    assert payload["available"] is False
    assert payload["candidate_count"] == 0


def test_api_missing_session_returns_404() -> None:
    r = client.get(f"/sessions/{uuid4()}/decision-input-bundle")
    assert r.status_code == 404


def test_api_is_read_only() -> None:
    sid = _seed_session("Task 037 read-only")
    before = client.get(f"/sessions/{sid}/decision-candidate-assessments").json()
    r = client.get(f"/sessions/{sid}/decision-input-bundle")
    assert r.status_code == 200
    after = client.get(f"/sessions/{sid}/decision-candidate-assessments").json()
    assert after == before


def test_api_is_deterministic() -> None:
    sid = _seed_session("Task 037 deterministic")
    first = client.get(f"/sessions/{sid}/decision-input-bundle").json()
    second = client.get(f"/sessions/{sid}/decision-input-bundle").json()
    assert first == second


def test_api_matches_service_output() -> None:
    sid = _seed_session("Task 037 agreement")
    api_result = client.get(f"/sessions/{sid}/decision-input-bundle").json()

    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        service_result = _bundle_service().build_for_session(
            db, session_uuid, candidates
        )
    finally:
        db_gen.close()

    assert api_result == _json_safe(service_result)


def _json_safe(result: dict[str, Any]) -> dict[str, Any]:
    cs = result["candidate_set"]
    aset = result["assessment_set"]
    return {
        **result,
        "candidate_set": {
            **cs,
            "candidates": [
                {**c, "hypothesis_id": str(c["hypothesis_id"])}
                for c in cs["candidates"]
            ],
        },
        "assessment_set": {
            **aset,
            "assessments": [
                {**a, "hypothesis_id": str(a["hypothesis_id"])}
                for a in aset["assessments"]
            ],
        },
    }


# ---------------------------------------------------------------------------
# Task 036 availability-consistency (reviewer round 2)
# ---------------------------------------------------------------------------


def test_rejects_assessment_available_with_incomplete_coverage() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["evaluation_coverage_complete"] = False
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "ASSESSMENT_AVAILABILITY_INCONSISTENT"


def test_rejects_assessment_available_with_inconsistent_structure() -> None:
    cs, aset = _ready_bundle()
    broken = copy.deepcopy(aset)
    broken["assessment_structure_consistent"] = False
    with pytest.raises(DecisionInputBundleContractError) as ei:
        _bundle_service().build(cs, broken)
    assert ei.value.invariant == "ASSESSMENT_AVAILABILITY_INCONSISTENT"
