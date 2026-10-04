"""Tests for the Task 031 decision-context packaging layer.

Task 031 packages Tasks 027-030's already-validated outputs into one
deterministic, read-only ``DecisionContext``. It computes nothing new
except three convenience mirrors (``candidate_count``,
``decision_ready``, ``consistency_verified``) and the derived
``context_available`` verdict -- every nested component is preserved
exactly, and Task 031 never gets to disagree with what it packages.
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
from rop.services.decision_context import (
    CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031,
    DecisionContextContractError,
    DecisionContextService,
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


TOP_LEVEL_FIELDS = (
    "context_available",
    "decision_ready",
    "consistency_verified",
    "candidate_count",
    "differential",
    "differential_summary",
    "differential_consistency",
    "decision_readiness",
    "context_source",
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


def _score_result(
    *,
    hypothesis_name: str,
    hypothesis_score: float,
    has_evidence: bool = True,
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
        "evidence_consistency": "SUPPORT_ONLY" if has_evidence else "NO_EVIDENCE",
        "total_evidence_items": 1 if has_evidence else 0,
        "total_support_contribution": 0.0,
        "total_contradiction_contribution": 0.0,
        "net_contribution": hypothesis_score,
        "has_evidence": has_evidence,
        "has_mixed_evidence": False,
        "score_direction": score_direction,
        "evidence_coverage_ratio": 1.0 if has_evidence else 0.0,
        "informative_evidence_ratio": 1.0 if has_evidence else 0.0,
        "support_to_contradiction_ratio": None,
        "evidence_position": "SUPPORTING" if has_evidence else "NO_EVIDENCE",
    }


def _build(
    scores: list[float], evidence: list[bool] | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Produce a genuine (ranked, summary, consistency, readiness) quadruple."""
    if evidence is None:
        evidence = [True] * len(scores)

    ranking_service = _ranking_service()
    summary_service = DifferentialRankingSummaryService(ranking_service)
    consistency_service = DifferentialRankingConsistencyService(summary_service)
    readiness_service = DifferentialDecisionReadinessService(consistency_service)

    entries = [
        _score_result(
            hypothesis_name=f"H{index}",
            hypothesis_score=score,
            has_evidence=evidence[index],
        )
        for index, score in enumerate(scores)
    ]
    ranked = ranking_service.rank_score_results(entries)
    summary = summary_service.summarize_ranked(ranked)
    consistency = consistency_service.check_consistency(ranked, summary)
    readiness = readiness_service.evaluate(ranked, summary, consistency)
    return ranked, summary, consistency, readiness


def _make_context(
    scores: list[float], evidence: list[bool] | None = None
) -> dict[str, Any]:
    ranked, summary, consistency, readiness = _build(scores, evidence)
    return _context_service().build(ranked, summary, consistency, readiness)


# ---------------------------------------------------------------------------
# Empty differential
# ---------------------------------------------------------------------------


def test_empty_differential_context() -> None:
    result = _make_context([])

    assert result["context_available"] is False
    assert result["decision_ready"] is False
    assert result["consistency_verified"] is True
    assert result["candidate_count"] == 0
    assert result["differential"] == []
    assert result["context_source"] == CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031


# ---------------------------------------------------------------------------
# Valid non-empty contexts
# ---------------------------------------------------------------------------


def test_single_candidate_context() -> None:
    result = _make_context([10.0])

    assert result["context_available"] is True
    assert result["decision_ready"] is True
    assert result["consistency_verified"] is True
    assert result["candidate_count"] == 1
    assert len(result["differential"]) == 1


def test_multiple_candidates_context() -> None:
    result = _make_context([10.0, 8.0, 5.0])

    assert result["context_available"] is True
    assert result["decision_ready"] is True
    assert result["consistency_verified"] is True
    assert result["candidate_count"] == 3
    assert [entry["rank"] for entry in result["differential"]] == [1, 2, 3]


def test_tied_candidates_context_remains_valid() -> None:
    """A tie must never invalidate the context."""
    result = _make_context([10.0, 10.0, 5.0])

    assert result["context_available"] is True
    assert result["decision_ready"] is True
    assert result["candidate_count"] == 3
    assert result["differential_summary"]["has_any_ties"] is True


def test_all_tied_context_remains_valid_with_no_hidden_winner_logic() -> None:
    result = _make_context([10.0, 10.0, 10.0])

    assert result["context_available"] is True
    assert result["decision_ready"] is True
    assert result["decision_readiness"]["has_score_separation"] is False
    assert result["decision_readiness"]["has_unresolved_ties"] is True


def test_no_evidence_context_is_still_available() -> None:
    result = _make_context([10.0, 8.0, 5.0], evidence=[False, False, False])

    assert result["decision_readiness"]["evidence_present_for_any_candidate"] is False
    assert result["context_available"] is True


# ---------------------------------------------------------------------------
# Preservation of upstream contracts
# ---------------------------------------------------------------------------


def test_nested_components_are_preserved_exactly() -> None:
    ranked, summary, consistency, readiness = _build([10.0, 8.0, 5.0])
    result = _context_service().build(ranked, summary, consistency, readiness)

    assert result["differential"] == ranked
    assert result["differential_summary"] == summary
    assert result["differential_consistency"] == consistency
    assert result["decision_readiness"] == readiness


def test_top_level_mirrors_match_nested_fields() -> None:
    ranked, summary, consistency, readiness = _build([10.0, 10.0, 7.0])
    result = _context_service().build(ranked, summary, consistency, readiness)

    assert result["decision_ready"] == readiness["ready"]
    assert result["consistency_verified"] == consistency["consistent"]
    assert result["candidate_count"] == len(result["differential"])


def test_no_decision_fields_are_introduced() -> None:
    """The architectural boundary, asserted directly."""
    result = _make_context([10.0, 8.0, 5.0])

    assert set(result) == set(TOP_LEVEL_FIELDS)
    for forbidden in (
        "is_winner",
        "selected_hypothesis",
        "winning_score",
        "decision",
        "diagnosis",
        "probability",
        "confidence",
        "recommendation",
        "treatment",
        "action",
    ):
        assert forbidden not in result


# ---------------------------------------------------------------------------
# Non-mutation
# ---------------------------------------------------------------------------


def test_service_does_not_mutate_any_of_its_four_inputs() -> None:
    ranked, summary, consistency, readiness = _build([10.0, 10.0, 7.0, 5.0])
    ranked_before = copy.deepcopy(ranked)
    summary_before = copy.deepcopy(summary)
    consistency_before = copy.deepcopy(consistency)
    readiness_before = copy.deepcopy(readiness)

    _context_service().build(ranked, summary, consistency, readiness)

    assert ranked == ranked_before
    assert summary == summary_before
    assert consistency == consistency_before
    assert readiness == readiness_before


def test_returned_differential_is_not_the_same_object() -> None:
    """Mutating the result must not affect the caller's original list."""
    ranked, summary, consistency, readiness = _build([10.0, 8.0])
    result = _context_service().build(ranked, summary, consistency, readiness)

    result["differential"][0]["rank"] = 99
    result["differential_summary"]["total_candidates"] = 99

    assert ranked[0]["rank"] != 99
    assert summary["total_candidates"] != 99


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_identical_input_is_deterministic() -> None:
    ranked, summary, consistency, readiness = _build([10.0, 10.0, 7.0, 5.0])
    service = _context_service()

    first = service.build(ranked, summary, consistency, readiness)
    second = service.build(ranked, summary, consistency, readiness)

    assert first == second


def test_context_source_is_fixed() -> None:
    assert CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031 == "DECISION_CONTEXT_TASK_031"
    for scores in ([], [1.0], [3.0, 3.0, 1.0]):
        result = _make_context(scores)
        assert result["context_source"] == CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031


# ---------------------------------------------------------------------------
# Missing nested components -> dedicated contract error
# ---------------------------------------------------------------------------


def test_missing_differential_raises_contract_error() -> None:
    _, summary, consistency, readiness = _build([10.0, 8.0])

    with pytest.raises(DecisionContextContractError):
        _context_service().build(None, summary, consistency, readiness)


def test_missing_summary_raises_contract_error() -> None:
    ranked, _, consistency, readiness = _build([10.0, 8.0])

    with pytest.raises(DecisionContextContractError):
        _context_service().build(ranked, None, consistency, readiness)


def test_missing_consistency_raises_contract_error() -> None:
    ranked, summary, _, readiness = _build([10.0, 8.0])

    with pytest.raises(DecisionContextContractError):
        _context_service().build(ranked, summary, None, readiness)


def test_missing_readiness_raises_contract_error() -> None:
    ranked, summary, consistency, _ = _build([10.0, 8.0])

    with pytest.raises(DecisionContextContractError):
        _context_service().build(ranked, summary, consistency, None)


def test_ranked_entry_missing_field_raises_contract_error() -> None:
    ranked, summary, consistency, readiness = _build([10.0, 8.0])
    corrupted = copy.deepcopy(ranked)
    del corrupted[0]["is_tied"]

    with pytest.raises(DecisionContextContractError):
        _context_service().build(corrupted, summary, consistency, readiness)


@pytest.mark.parametrize(
    "field",
    [
        "total_candidates",
        "distinct_score_groups",
        "highest_score",
        "score_range",
    ],
)
def test_summary_missing_field_raises_contract_error(field: str) -> None:
    ranked, summary, consistency, readiness = _build([10.0, 8.0])
    corrupted = dict(summary)
    del corrupted[field]

    with pytest.raises(DecisionContextContractError):
        _context_service().build(ranked, corrupted, consistency, readiness)


@pytest.mark.parametrize(
    "field",
    ["consistent", "candidate_count_matches", "rank_structure_matches"],
)
def test_consistency_missing_field_raises_contract_error(field: str) -> None:
    ranked, summary, consistency, readiness = _build([10.0, 8.0])
    corrupted = dict(consistency)
    del corrupted[field]

    with pytest.raises(DecisionContextContractError):
        _context_service().build(ranked, summary, corrupted, readiness)


@pytest.mark.parametrize(
    "field",
    ["ready", "consistency_verified", "has_candidates"],
)
def test_readiness_missing_field_raises_contract_error(field: str) -> None:
    ranked, summary, consistency, readiness = _build([10.0, 8.0])
    corrupted = dict(readiness)
    del corrupted[field]

    with pytest.raises(DecisionContextContractError):
        _context_service().build(ranked, summary, consistency, corrupted)


def test_contract_error_carries_invariant_name() -> None:
    ranked, summary, consistency, readiness = _build([10.0, 8.0])

    with pytest.raises(DecisionContextContractError) as exc_info:
        _context_service().build(ranked, summary, consistency, None)

    assert exc_info.value.invariant == "MISSING_READINESS"


# ---------------------------------------------------------------------------
# The context validator -- nothing is accepted, everything is derived
# ---------------------------------------------------------------------------


def _context_result(**overrides: Any) -> dict[str, Any]:
    ranked, summary, consistency, readiness = _build([10.0, 8.0, 5.0])
    result = {
        "context_available": True,
        "decision_ready": True,
        "consistency_verified": True,
        "candidate_count": 3,
        "differential": ranked,
        "differential_summary": summary,
        "differential_consistency": consistency,
        "decision_readiness": readiness,
        "context_source": CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031,
    }
    result.update(overrides)
    return result


def test_validator_accepts_a_well_formed_context() -> None:
    DecisionContextService._validate_context(_context_result())


def test_validator_rejects_candidate_count_mismatch() -> None:
    """5 declared, 4 actually present in the differential."""
    ranked, summary, consistency, readiness = _build([10.0, 8.0, 5.0, 3.0])
    with pytest.raises(DecisionContextContractError) as exc_info:
        DecisionContextService._validate_context(
            _context_result(
                candidate_count=5,
                differential=ranked,
                differential_summary=summary,
                differential_consistency=consistency,
                decision_readiness=readiness,
            )
        )
    assert exc_info.value.invariant == "CANDIDATE_COUNT_MISMATCH"


def test_validator_rejects_readiness_mismatch() -> None:
    """decision_ready=True while decision_readiness.ready=False."""
    with pytest.raises(DecisionContextContractError) as exc_info:
        DecisionContextService._validate_context(
            _context_result(
                decision_ready=True,
                decision_readiness={
                    "ready": False,
                    "consistency_verified": True,
                    "has_candidates": True,
                    "ranking_available": True,
                    "summary_available": True,
                    "separation_metadata_available": True,
                    "has_score_separation": True,
                    "has_unresolved_ties": False,
                    "evidence_present_for_any_candidate": True,
                },
            )
        )
    assert exc_info.value.invariant == "READINESS_MISMATCH"


def test_validator_rejects_consistency_mismatch() -> None:
    """consistency_verified=True while differential_consistency.consistent=False."""
    with pytest.raises(DecisionContextContractError) as exc_info:
        DecisionContextService._validate_context(
            _context_result(
                consistency_verified=True,
                differential_consistency={
                    "consistent": False,
                    "candidate_count_matches": True,
                    "score_groups_match": True,
                    "tie_statistics_match": True,
                    "score_range_matches": True,
                    "rank_structure_matches": True,
                    "separation_metadata_matches": True,
                    "summary_consistent": False,
                    "consistency_source": "DIFFERENTIAL_RANKING_TASK_029",
                },
            )
        )
    assert exc_info.value.invariant == "CONSISTENCY_MISMATCH"


def test_validator_rejects_forged_context_available() -> None:
    """decision_ready and decision_readiness.ready agree (both False),
    so this isolates a forged context_available from a readiness
    mismatch."""
    ranked, summary, consistency, readiness = _build([10.0, 8.0, 5.0])
    not_ready = {**readiness, "ready": False}

    with pytest.raises(DecisionContextContractError) as exc_info:
        DecisionContextService._validate_context(
            _context_result(
                context_available=True,
                decision_ready=False,
                differential=ranked,
                differential_summary=summary,
                differential_consistency=consistency,
                decision_readiness=not_ready,
            )
        )
    assert exc_info.value.invariant == "CONTEXT_AVAILABLE_MISMATCH"


def test_validator_rejects_context_available_true_with_zero_candidates() -> None:
    ranked, summary, consistency, readiness = _build([])
    with pytest.raises(DecisionContextContractError) as exc_info:
        DecisionContextService._validate_context(
            _context_result(
                context_available=True,
                decision_ready=True,
                consistency_verified=True,
                candidate_count=0,
                differential=ranked,
                differential_summary=summary,
                differential_consistency=consistency,
                decision_readiness={**readiness, "ready": True},
            )
        )
    assert exc_info.value.invariant in (
        "READINESS_MISMATCH",
        "CONTEXT_AVAILABLE_MISMATCH",
    )


@pytest.mark.parametrize(
    "field", ["context_available", "decision_ready", "consistency_verified"]
)
def test_validator_rejects_non_boolean_field(field: str) -> None:
    with pytest.raises(DecisionContextContractError):
        DecisionContextService._validate_context(_context_result(**{field: "yes"}))


def test_validator_rejects_wrong_source() -> None:
    with pytest.raises(DecisionContextContractError):
        DecisionContextService._validate_context(
            _context_result(context_source="SOMETHING_ELSE")
        )


def test_validator_rejects_missing_nested_component() -> None:
    with pytest.raises(DecisionContextContractError):
        DecisionContextService._validate_context(_context_result(differential=None))


def test_build_rejects_a_hand_forged_mismatch_end_to_end() -> None:
    """A caller cannot smuggle a forged candidate_count through build().

    ``build`` always derives candidate_count from len(differential)
    internally, so this exercises the validator's rejection path via
    a corrupted *nested* summary that disagrees with the differential
    it is packaged alongside -- proving build() does not simply trust
    whatever summary it is handed.
    """
    ranked, summary, consistency, readiness = _build([10.0, 8.0, 5.0])
    corrupted_summary = dict(summary)
    corrupted_summary["total_candidates"] = 99
    # Re-run consistency so it reports the real disagreement rather
    # than being handed a stale, still-consistent verdict.
    consistency_service = DifferentialRankingConsistencyService(
        DifferentialRankingSummaryService(_ranking_service())
    )
    real_consistency = consistency_service.check_consistency(ranked, corrupted_summary)
    readiness_service = DifferentialDecisionReadinessService(consistency_service)
    real_readiness = readiness_service.evaluate(
        ranked, corrupted_summary, real_consistency
    )

    result = _context_service().build(
        ranked, corrupted_summary, real_consistency, real_readiness
    )

    # Task 029 correctly detected the disagreement, so consistency is
    # False, readiness is False, and the context reports unavailable --
    # nothing here is silently repaired.
    assert result["consistency_verified"] is False
    assert result["decision_ready"] is False
    assert result["context_available"] is False


# ---------------------------------------------------------------------------
# Dependency chain
# ---------------------------------------------------------------------------


def test_build_for_session_walks_the_full_dependency_chain() -> None:
    """Tasks 027-030 must each be consumed, not reimplemented."""
    calls: list[str] = []

    class RecordingRanking(DifferentialRankingService):
        def rank_session(
            self, db: Session, session_id: UUID, candidates: list[Any]
        ) -> list[dict[str, Any]]:
            calls.append("rank_session")
            return super().rank_session(db, session_id, candidates)

    class RecordingSummary(DifferentialRankingSummaryService):
        def summarize_ranked(self, ranked: list[dict[str, Any]]) -> dict[str, Any]:
            calls.append("summarize_ranked")
            return super().summarize_ranked(ranked)

    class RecordingConsistency(DifferentialRankingConsistencyService):
        def check_consistency(
            self, ranked: list[dict[str, Any]], summary: Any
        ) -> dict[str, Any]:
            calls.append("check_consistency")
            return super().check_consistency(ranked, summary)

    class RecordingReadiness(DifferentialDecisionReadinessService):
        def evaluate(
            self, ranked: list[dict[str, Any]], summary: Any, consistency: Any
        ) -> dict[str, Any]:
            calls.append("evaluate_readiness")
            return super().evaluate(ranked, summary, consistency)

    ranking = RecordingRanking(HypothesisScoringService(EvidenceAggregationService()))
    consistency = RecordingConsistency(RecordingSummary(ranking))
    readiness = RecordingReadiness(consistency)
    service = DecisionContextService(readiness)

    with TestingSessionLocal() as db:
        result = service.build_for_session(db, uuid4(), [])

    assert calls == [
        "rank_session",
        "summarize_ranked",
        "check_consistency",
        "evaluate_readiness",
    ]
    assert result["context_available"] is False
    assert result["candidate_count"] == 0


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "decision-context-test"},
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


def test_api_decision_context_endpoint() -> None:
    session_id = _seed_session("Task 031 decision context test")

    response = client.get(f"/sessions/{session_id}/decision-context")
    assert response.status_code == 200
    payload = response.json()

    assert set(payload) == set(TOP_LEVEL_FIELDS)
    assert payload["context_source"] == CONTEXT_SOURCE_DECISION_CONTEXT_TASK_031
    assert payload["candidate_count"] == len(payload["differential"])
    assert payload["decision_ready"] == payload["decision_readiness"]["ready"]
    assert (
        payload["consistency_verified"]
        == payload["differential_consistency"]["consistent"]
    )
    assert payload["context_available"] is True


def test_api_decision_context_empty_session() -> None:
    session_id = _create_session("Task 031 empty decision context test")

    response = client.get(f"/sessions/{session_id}/decision-context")
    assert response.status_code == 200
    payload = response.json()

    assert payload["context_available"] is False
    assert payload["decision_ready"] is False
    assert payload["consistency_verified"] is True
    assert payload["candidate_count"] == 0
    assert payload["differential"] == []


def test_api_decision_context_missing_session_returns_404() -> None:
    response = client.get(f"/sessions/{uuid4()}/decision-context")
    assert response.status_code == 404


def test_api_decision_context_is_read_only() -> None:
    session_id = _seed_session("Task 031 read-only test")

    differential_before = client.get(f"/sessions/{session_id}/differential").json()
    summary_before = client.get(f"/sessions/{session_id}/differential-summary").json()
    consistency_before = client.get(
        f"/sessions/{session_id}/differential-consistency"
    ).json()
    readiness_before = client.get(
        f"/sessions/{session_id}/differential-readiness"
    ).json()

    response = client.get(f"/sessions/{session_id}/decision-context")
    assert response.status_code == 200

    assert (
        client.get(f"/sessions/{session_id}/differential").json() == differential_before
    )
    assert (
        client.get(f"/sessions/{session_id}/differential-summary").json()
        == summary_before
    )
    assert (
        client.get(f"/sessions/{session_id}/differential-consistency").json()
        == consistency_before
    )
    assert (
        client.get(f"/sessions/{session_id}/differential-readiness").json()
        == readiness_before
    )


def test_api_decision_context_is_deterministic() -> None:
    session_id = _seed_session("Task 031 determinism test")

    first = client.get(f"/sessions/{session_id}/decision-context").json()
    second = client.get(f"/sessions/{session_id}/decision-context").json()

    assert first == second


def test_api_decision_context_agrees_with_live_layer_endpoints() -> None:
    session_id = _seed_session("Task 031 agreement test")

    differential = client.get(f"/sessions/{session_id}/differential").json()
    summary = client.get(f"/sessions/{session_id}/differential-summary").json()
    consistency = client.get(f"/sessions/{session_id}/differential-consistency").json()
    readiness = client.get(f"/sessions/{session_id}/differential-readiness").json()
    context = client.get(f"/sessions/{session_id}/decision-context").json()

    assert context["differential"] == differential
    assert context["differential_summary"] == summary
    assert context["differential_consistency"] == consistency
    assert context["decision_readiness"] == readiness
