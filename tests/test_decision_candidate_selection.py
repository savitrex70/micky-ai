"""Tests for the Task 035 decision candidate selection boundary.

Task 035 is the narrow forwarding step between Task 034's decision
input eligibility gate and the future decision layer. When Task 034
reports the input eligible, every already-established candidate is
forwarded in the exact order supplied by the Task 031 context's
differential; when Task 034 reports it ineligible, no candidate is
forwarded. Never selects a winner, never diagnoses, never ranks,
never scores, never persists.

Regression note: running this file alone is not a substitute for the
full suite. Tasks 020-034 must be re-run alongside this file before
Task 035 is considered done.
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
from rop.services.decision_candidate_selection import (
    SELECTION_SOURCE_DECISION_CANDIDATE_SELECTION_TASK_035,
    DecisionCandidateSelectionContractError,
    DecisionCandidateSelectionService,
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

SELECTION_RESULT_FIELDS = (
    "selection_available",
    "eligible_candidate_count",
    "eligible_candidate_ids",
    "eligible_candidate_names",
    "all_candidates_forwarded",
    "candidate_order_preserved",
    "selection_source",
)


# ---------------------------------------------------------------------------
# Helpers -- real Tasks 027-034 chain
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


def _candidate_evaluation_service() -> DecisionCandidateEvaluationService:
    return DecisionCandidateEvaluationService(_context_service())


def _consistency_service() -> DecisionEvaluationConsistencyService:
    return DecisionEvaluationConsistencyService(_candidate_evaluation_service())


def _eligibility_service() -> DecisionInputEligibilityService:
    return DecisionInputEligibilityService(_consistency_service())


def _selection_service() -> DecisionCandidateSelectionService:
    return DecisionCandidateSelectionService(_eligibility_service())


def _score_result(
    *,
    hypothesis_name: str,
    hypothesis_score: float,
    evidence_consistency: str = CONSISTENCY_SUPPORT_ONLY,
) -> dict[str, Any]:
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
        "total_evidence_items": 1,
        "total_support_contribution": max(hypothesis_score, 0.0),
        "total_contradiction_contribution": max(-hypothesis_score, 0.0),
        "net_contribution": hypothesis_score,
        "has_evidence": True,
        "has_mixed_evidence": False,
        "score_direction": score_direction,
        "evidence_coverage_ratio": 1.0,
        "informative_evidence_ratio": 1.0,
        "support_to_contradiction_ratio": None,
        "evidence_position": "SUPPORTING",
    }


def _make_context(entries: list[dict[str, Any]]) -> dict[str, Any]:
    ranking_service = _ranking_service()
    summary_service = DifferentialRankingSummaryService(ranking_service)
    consistency_service = DifferentialRankingConsistencyService(summary_service)
    readiness_service = DifferentialDecisionReadinessService(consistency_service)

    ranked = ranking_service.rank_score_results(entries)
    summary = summary_service.summarize_ranked(ranked)
    consistency = consistency_service.check_consistency(ranked, summary)
    readiness = readiness_service.evaluate(ranked, summary, consistency)
    return _context_service().build(ranked, summary, consistency, readiness)


def _make_context_and_consistency(
    entries: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    context = _make_context(entries)
    evaluations = _candidate_evaluation_service().evaluate(context)
    expected_ids = [entry["hypothesis_id"] for entry in context["differential"]]
    consistency_result = _consistency_service().check(evaluations, expected_ids)
    return context, consistency_result


def _ready_eligibility_and_differential() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    context, consistency_result = _make_context_and_consistency(
        [
            _score_result(hypothesis_name="H1", hypothesis_score=10.0),
            _score_result(hypothesis_name="H2", hypothesis_score=5.0),
        ]
    )
    eligibility = _eligibility_service().build(context, consistency_result)
    return eligibility, context["differential"]


def _ineligible_eligibility_result() -> dict[str, Any]:
    """A contract-valid Task 034 result that says 'not eligible'."""
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
# Valid / eligible cases
# ---------------------------------------------------------------------------


def test_single_candidate_is_forwarded() -> None:
    context, consistency_result = _make_context_and_consistency(
        [_score_result(hypothesis_name="H1", hypothesis_score=5.0)]
    )
    eligibility = _eligibility_service().build(context, consistency_result)
    result = _selection_service().build(eligibility, context["differential"])

    assert set(result) == set(SELECTION_RESULT_FIELDS)
    assert result["selection_available"] is True
    assert result["eligible_candidate_count"] == 1
    assert len(result["eligible_candidate_ids"]) == 1
    assert len(result["eligible_candidate_names"]) == 1


def test_multiple_candidates_are_all_forwarded() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    result = _selection_service().build(eligibility, differential)

    assert result["selection_available"] is True
    assert result["eligible_candidate_count"] == 2
    assert len(result["eligible_candidate_ids"]) == 2
    assert len(result["eligible_candidate_names"]) == 2


def test_candidate_order_is_preserved() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    upstream_ids = [entry["hypothesis_id"] for entry in differential]
    upstream_names = [entry["hypothesis_name"] for entry in differential]

    result = _selection_service().build(eligibility, differential)

    assert result["eligible_candidate_ids"] == upstream_ids
    assert result["eligible_candidate_names"] == upstream_names
    assert result["candidate_order_preserved"] is True


def test_ids_and_names_are_positionally_aligned() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    result = _selection_service().build(eligibility, differential)

    for i, entry in enumerate(differential):
        assert result["eligible_candidate_ids"][i] == entry["hypothesis_id"]
        assert result["eligible_candidate_names"][i] == entry["hypothesis_name"]


def test_eligible_candidate_count_matches_list_length() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    result = _selection_service().build(eligibility, differential)

    assert result["eligible_candidate_count"] == len(result["eligible_candidate_ids"])
    assert result["eligible_candidate_count"] == len(result["eligible_candidate_names"])


def test_selection_source_is_fixed() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    result = _selection_service().build(eligibility, differential)

    assert (
        result["selection_source"]
        == SELECTION_SOURCE_DECISION_CANDIDATE_SELECTION_TASK_035
    )


def test_all_candidates_forwarded_is_true_when_eligible() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    result = _selection_service().build(eligibility, differential)

    assert result["all_candidates_forwarded"] is True


def test_no_decision_fields_are_introduced() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    result = _selection_service().build(eligibility, differential)

    assert set(result) == set(SELECTION_RESULT_FIELDS)
    for forbidden in (
        "winner",
        "selected_candidate",
        "preferred_candidate",
        "diagnosis",
        "recommendation",
        "action",
        "probability",
        "confidence",
        "utility",
        "utility_score",
        "weighted_score",
        "expected_outcome",
        "treatment",
        "is_winner",
        "score",
        "ranking",
    ):
        assert forbidden not in result


# ---------------------------------------------------------------------------
# Ineligible cases
# ---------------------------------------------------------------------------


def test_ineligible_forwards_no_candidates() -> None:
    eligibility = _ineligible_eligibility_result()
    differential = [
        {"hypothesis_id": uuid4(), "hypothesis_name": "H1"},
        {"hypothesis_id": uuid4(), "hypothesis_name": "H2"},
    ]
    result = _selection_service().build(eligibility, differential)

    assert result["selection_available"] is False
    assert result["eligible_candidate_count"] == 0
    assert result["eligible_candidate_ids"] == []
    assert result["eligible_candidate_names"] == []


def test_ineligible_all_candidates_forwarded_is_false() -> None:
    eligibility = _ineligible_eligibility_result()
    differential = [{"hypothesis_id": uuid4(), "hypothesis_name": "H1"}]
    result = _selection_service().build(eligibility, differential)

    assert result["all_candidates_forwarded"] is False


def test_ineligible_candidate_order_preserved_is_still_true() -> None:
    eligibility = _ineligible_eligibility_result()
    differential = [{"hypothesis_id": uuid4(), "hypothesis_name": "H1"}]
    result = _selection_service().build(eligibility, differential)

    assert result["candidate_order_preserved"] is True


def test_ineligible_with_empty_differential() -> None:
    eligibility = _ineligible_eligibility_result()
    result = _selection_service().build(eligibility, [])

    assert result["selection_available"] is False
    assert result["eligible_candidate_count"] == 0
    assert result["eligible_candidate_ids"] == []
    assert result["eligible_candidate_names"] == []


# ---------------------------------------------------------------------------
# Input contract failures -- eligibility_result
# ---------------------------------------------------------------------------


def test_rejects_none_eligibility() -> None:
    _, differential = _ready_eligibility_and_differential()
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(None, differential)
    assert exc_info.value.invariant == "MISSING_ELIGIBILITY"


def test_rejects_non_mapping_eligibility() -> None:
    _, differential = _ready_eligibility_and_differential()
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build("not-a-mapping", differential)  # type: ignore[arg-type]
    assert exc_info.value.invariant == "ELIGIBILITY_TYPE"


def test_rejects_missing_eligibility_field() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    malformed = copy.deepcopy(eligibility)
    del malformed["eligible"]
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(malformed, differential)
    assert exc_info.value.invariant == "MISSING_ELIGIBILITY_FIELD"


def test_rejects_non_boolean_eligibility_field() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    malformed = copy.deepcopy(eligibility)
    malformed["eligible"] = "true"
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(malformed, differential)
    assert exc_info.value.invariant == "ELIGIBLE_TYPE"


def test_rejects_invalid_eligibility_source() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    malformed = copy.deepcopy(eligibility)
    malformed["eligibility_source"] = "SOMETHING_ELSE"
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(malformed, differential)
    assert exc_info.value.invariant == "INVALID_ELIGIBILITY_SOURCE"


# ---------------------------------------------------------------------------
# Input contract failures -- differential
# ---------------------------------------------------------------------------


def test_rejects_none_differential() -> None:
    eligibility, _ = _ready_eligibility_and_differential()
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(eligibility, None)
    assert exc_info.value.invariant == "MISSING_DIFFERENTIAL"


def test_rejects_non_list_differential() -> None:
    eligibility, _ = _ready_eligibility_and_differential()
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(eligibility, "not-a-list")  # type: ignore[arg-type]
    assert exc_info.value.invariant == "DIFFERENTIAL_TYPE"


def test_rejects_malformed_differential_entry() -> None:
    eligibility, _ = _ready_eligibility_and_differential()
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(eligibility, ["not-a-mapping"])  # type: ignore[list-item]
    assert exc_info.value.invariant == "MALFORMED_DIFFERENTIAL_ENTRY"


def test_rejects_missing_hypothesis_id() -> None:
    eligibility, _ = _ready_eligibility_and_differential()
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(eligibility, [{"hypothesis_name": "H1"}])
    assert exc_info.value.invariant == "MISSING_HYPOTHESIS_ID"


def test_rejects_missing_hypothesis_name() -> None:
    eligibility, _ = _ready_eligibility_and_differential()
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(eligibility, [{"hypothesis_id": uuid4()}])
    assert exc_info.value.invariant == "MISSING_HYPOTHESIS_NAME"


def test_rejects_non_uuid_hypothesis_id() -> None:
    eligibility, _ = _ready_eligibility_and_differential()
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(
            eligibility,
            [{"hypothesis_id": "not-a-uuid", "hypothesis_name": "H1"}],  # type: ignore[list-item]
        )
    assert exc_info.value.invariant == "INVALID_HYPOTHESIS_ID"


def test_rejects_non_string_hypothesis_name() -> None:
    eligibility, _ = _ready_eligibility_and_differential()
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(
            eligibility, [{"hypothesis_id": uuid4(), "hypothesis_name": 123}]
        )
    assert exc_info.value.invariant == "INVALID_HYPOTHESIS_NAME"


def test_rejects_duplicate_hypothesis_id() -> None:
    eligibility, _ = _ready_eligibility_and_differential()
    same_id = uuid4()
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        _selection_service().build(
            eligibility,
            [
                {"hypothesis_id": same_id, "hypothesis_name": "H1"},
                {"hypothesis_id": same_id, "hypothesis_name": "H2"},
            ],
        )
    assert exc_info.value.invariant == "DUPLICATE_HYPOTHESIS_ID"


# ---------------------------------------------------------------------------
# Validator hardening -- tampered output fields
# ---------------------------------------------------------------------------


def _valid_result_and_upstream() -> tuple[dict[str, Any], list[UUID], list[str]]:
    eligibility, differential = _ready_eligibility_and_differential()
    result = _selection_service().build(eligibility, differential)
    upstream_ids = [entry["hypothesis_id"] for entry in differential]
    upstream_names = [entry["hypothesis_name"] for entry in differential]
    return result, upstream_ids, upstream_names


def test_tampered_selection_available_is_rejected() -> None:
    result, ids, names = _valid_result_and_upstream()
    corrupted = copy.deepcopy(result)
    corrupted["selection_available"] = False
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        DecisionCandidateSelectionService._validate_result(corrupted, True, ids, names)
    assert exc_info.value.invariant == "SELECTION_AVAILABLE_MISMATCH"


def test_tampered_count_is_rejected() -> None:
    result, ids, names = _valid_result_and_upstream()
    corrupted = copy.deepcopy(result)
    corrupted["eligible_candidate_count"] = 99
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        DecisionCandidateSelectionService._validate_result(corrupted, True, ids, names)
    assert exc_info.value.invariant == "COUNT_MISMATCH"


def test_tampered_negative_count_is_rejected() -> None:
    result, ids, names = _valid_result_and_upstream()
    corrupted = copy.deepcopy(result)
    corrupted["eligible_candidate_count"] = -1
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        DecisionCandidateSelectionService._validate_result(corrupted, True, ids, names)
    assert exc_info.value.invariant == "COUNT_NEGATIVE"


def test_tampered_ids_are_rejected() -> None:
    result, ids, names = _valid_result_and_upstream()
    corrupted = copy.deepcopy(result)
    corrupted["eligible_candidate_ids"] = [uuid4() for _ in ids]
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        DecisionCandidateSelectionService._validate_result(corrupted, True, ids, names)
    assert exc_info.value.invariant == "IDS_MISMATCH"


def test_tampered_names_are_rejected() -> None:
    result, ids, names = _valid_result_and_upstream()
    corrupted = copy.deepcopy(result)
    corrupted["eligible_candidate_names"] = ["WRONG" for _ in names]
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        DecisionCandidateSelectionService._validate_result(corrupted, True, ids, names)
    assert exc_info.value.invariant == "NAMES_MISMATCH"


def test_tampered_all_forwarded_is_rejected() -> None:
    result, ids, names = _valid_result_and_upstream()
    corrupted = copy.deepcopy(result)
    corrupted["all_candidates_forwarded"] = False
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        DecisionCandidateSelectionService._validate_result(corrupted, True, ids, names)
    assert exc_info.value.invariant == "ALL_FORWARDED_MISMATCH"


def test_tampered_order_preserved_is_rejected() -> None:
    result, ids, names = _valid_result_and_upstream()
    corrupted = copy.deepcopy(result)
    corrupted["candidate_order_preserved"] = False
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        DecisionCandidateSelectionService._validate_result(corrupted, True, ids, names)
    assert exc_info.value.invariant == "ORDER_NOT_PRESERVED"


def test_tampered_source_is_rejected() -> None:
    result, ids, names = _valid_result_and_upstream()
    corrupted = copy.deepcopy(result)
    corrupted["selection_source"] = "SOMETHING_ELSE"
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        DecisionCandidateSelectionService._validate_result(corrupted, True, ids, names)
    assert exc_info.value.invariant == "INVALID_SELECTION_SOURCE"


def test_tampered_ineligible_with_forwarded_ids_is_rejected() -> None:
    result, ids, names = _valid_result_and_upstream()
    corrupted = copy.deepcopy(result)
    corrupted["selection_available"] = False
    corrupted["all_candidates_forwarded"] = False
    with pytest.raises(DecisionCandidateSelectionContractError) as exc_info:
        DecisionCandidateSelectionService._validate_result(
            corrupted, False, [], []
        )
    assert exc_info.value.invariant == "NONEMPTY_IDS_WHEN_INELIGIBLE"


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


def test_build_does_not_mutate_eligibility_result() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    before = copy.deepcopy(eligibility)
    _selection_service().build(eligibility, differential)
    assert eligibility == before


def test_build_does_not_mutate_differential() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    before = copy.deepcopy(differential)
    _selection_service().build(eligibility, differential)
    assert differential == before


def test_build_is_deterministic() -> None:
    eligibility, differential = _ready_eligibility_and_differential()
    service = _selection_service()
    first = service.build(eligibility, differential)
    second = service.build(eligibility, differential)
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
            "metadata": {"source": "decision-candidate-selection-test"},
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


def test_api_decision_candidate_selection_endpoint() -> None:
    session_id = _seed_session("Task 035 selection endpoint test")

    response = client.get(f"/sessions/{session_id}/decision-candidate-selection")
    assert response.status_code == 200
    payload = response.json()

    assert set(payload) == set(SELECTION_RESULT_FIELDS)
    assert (
        payload["selection_source"]
        == SELECTION_SOURCE_DECISION_CANDIDATE_SELECTION_TASK_035
    )
    assert payload["selection_available"] is True
    assert payload["eligible_candidate_count"] >= 1
    assert len(payload["eligible_candidate_ids"]) == payload["eligible_candidate_count"]
    assert (
        len(payload["eligible_candidate_names"]) == payload["eligible_candidate_count"]
    )
    assert payload["all_candidates_forwarded"] is True
    assert payload["candidate_order_preserved"] is True
    for forbidden in (
        "winner",
        "selected_candidate",
        "diagnosis",
        "recommendation",
        "probability",
        "confidence",
        "utility_score",
        "weighted_score",
        "is_winner",
        "score",
        "ranking",
    ):
        assert forbidden not in payload


def test_api_decision_candidate_selection_empty_session() -> None:
    session_id = _create_session("Task 035 empty selection test")

    response = client.get(f"/sessions/{session_id}/decision-candidate-selection")
    assert response.status_code == 200
    payload = response.json()

    assert payload["selection_available"] is False
    assert payload["eligible_candidate_count"] == 0
    assert payload["eligible_candidate_ids"] == []
    assert payload["eligible_candidate_names"] == []
    assert payload["all_candidates_forwarded"] is False


def test_api_decision_candidate_selection_missing_session_returns_404() -> None:
    response = client.get(f"/sessions/{uuid4()}/decision-candidate-selection")
    assert response.status_code == 404


def test_api_decision_candidate_selection_is_read_only() -> None:
    session_id = _seed_session("Task 035 read-only test")

    eligibility_before = client.get(
        f"/sessions/{session_id}/decision-input-eligibility"
    ).json()

    response = client.get(f"/sessions/{session_id}/decision-candidate-selection")
    assert response.status_code == 200

    eligibility_after = client.get(
        f"/sessions/{session_id}/decision-input-eligibility"
    ).json()
    assert eligibility_after == eligibility_before


def test_api_decision_candidate_selection_is_deterministic() -> None:
    session_id = _seed_session("Task 035 determinism test")

    first = client.get(f"/sessions/{session_id}/decision-candidate-selection").json()
    second = client.get(f"/sessions/{session_id}/decision-candidate-selection").json()
    assert first == second


def test_api_response_matches_service_output() -> None:
    session_id = _seed_session("Task 035 service-agreement test")

    api_result = client.get(
        f"/sessions/{session_id}/decision-candidate-selection"
    ).json()

    session_uuid = UUID(session_id)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        from rop.services.candidate_generation import CandidateGenerationService

        candidates = CandidateGenerationService().list_by_session(
            db, session_uuid, offset=0, limit=100
        )
        service_result = _selection_service().build_for_session(
            db, session_uuid, candidates
        )
    finally:
        db_gen.close()

    assert api_result == {
        **service_result,
        "eligible_candidate_ids": [
            str(hid) for hid in service_result["eligible_candidate_ids"]
        ],
    }


# ---------------------------------------------------------------------------
# Regression: order preserved even with different scores
# ---------------------------------------------------------------------------


def test_order_preserved_even_with_different_scores() -> None:
    """Candidates must be forwarded in exactly the Task 031 context
    order, never re-sorted by score. The upstream differential is
    already sorted by score descending per Task 026/027, so this test
    feeds a differential whose score order is not alphabetical and
    confirms Task 035 forwards it verbatim.
    """
    entries = [
        _score_result(hypothesis_name="zeta", hypothesis_score=20.0),
        _score_result(hypothesis_name="alpha", hypothesis_score=10.0),
        _score_result(hypothesis_name="mu", hypothesis_score=1.0),
    ]
    context, consistency_result = _make_context_and_consistency(entries)
    eligibility = _eligibility_service().build(context, consistency_result)
    differential = context["differential"]

    result = _selection_service().build(eligibility, differential)

    upstream_names = [entry["hypothesis_name"] for entry in differential]
    assert result["eligible_candidate_names"] == upstream_names
    assert result["eligible_candidate_names"] == ["zeta", "alpha", "mu"]
