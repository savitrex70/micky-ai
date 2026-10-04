"""Tests for the Task 030 differential decision-readiness layer.

Task 030 asks one question: is the current differential structurally
complete and internally consistent enough for a *future* decision layer
to consume? It makes no decision, names no winner, and produces no
probability or confidence.

The tests below deliberately pin the three structural facts that are
reported but excluded from ``ready`` -- score separation, unresolved
ties, and evidence presence -- because each of them is a plausible
place for decision logic to leak in later.
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
from rop.services.differential_decision_readiness import (
    READINESS_SOURCE_DIFFERENTIAL_DECISION_TASK_030,
    DifferentialDecisionReadinessContractError,
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


READINESS_FIELDS = (
    "ready",
    "consistency_verified",
    "has_candidates",
    "ranking_available",
    "summary_available",
    "separation_metadata_available",
    "has_score_separation",
    "has_unresolved_ties",
    "evidence_present_for_any_candidate",
)


def _ranking_service() -> DifferentialRankingService:
    return DifferentialRankingService(
        HypothesisScoringService(EvidenceAggregationService())
    )


def _consistency_service() -> DifferentialRankingConsistencyService:
    return DifferentialRankingConsistencyService(
        DifferentialRankingSummaryService(_ranking_service())
    )


def _readiness_service() -> DifferentialDecisionReadinessService:
    return DifferentialDecisionReadinessService(_consistency_service())


def _score_result(
    *,
    hypothesis_name: str,
    hypothesis_score: float,
    has_evidence: bool = True,
) -> dict[str, Any]:
    """Build a well-formed Task 025 score-result dict for these tests."""
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
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Produce a genuine (ranked, summary, consistency) triple.

    Tests then degrade or corrupt a copy of one of the three and assert
    Task 030 reports it without repairing it.
    """
    if evidence is None:
        evidence = [True] * len(scores)

    ranking_service = _ranking_service()
    summary_service = DifferentialRankingSummaryService(ranking_service)
    consistency_service = DifferentialRankingConsistencyService(summary_service)

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
    return ranked, summary, consistency


def _evaluate(
    scores: list[float], evidence: list[bool] | None = None
) -> dict[str, Any]:
    ranked, summary, consistency = _build(scores, evidence)
    return _readiness_service().evaluate(ranked, summary, consistency)


# ---------------------------------------------------------------------------
# Empty differential -- valid, but not ready
# ---------------------------------------------------------------------------


def test_empty_differential_full_contract() -> None:
    """Empty is not the same as structurally corrupt."""
    result = _evaluate([])

    assert result["ready"] is False
    assert result["consistency_verified"] is True
    assert result["has_candidates"] is False
    assert result["ranking_available"] is False
    assert result["summary_available"] is True
    assert result["separation_metadata_available"] is True
    assert result["has_score_separation"] is False
    assert result["has_unresolved_ties"] is False
    assert result["evidence_present_for_any_candidate"] is False
    assert result["readiness_source"] == READINESS_SOURCE_DIFFERENTIAL_DECISION_TASK_030


# ---------------------------------------------------------------------------
# Ready states
# ---------------------------------------------------------------------------


def test_single_candidate_is_ready_without_separation() -> None:
    result = _evaluate([10.0])

    assert result["ready"] is True
    assert result["has_candidates"] is True
    assert result["has_score_separation"] is False
    assert result["has_unresolved_ties"] is False


def test_multiple_distinct_scores_are_ready() -> None:
    result = _evaluate([10.0, 8.0, 5.0])

    assert result["ready"] is True
    assert result["consistency_verified"] is True
    assert result["ranking_available"] is True
    assert result["summary_available"] is True
    assert result["separation_metadata_available"] is True
    assert result["has_score_separation"] is True
    assert result["has_unresolved_ties"] is False


def test_one_tie_is_still_ready() -> None:
    """A tie must never suppress readiness."""
    result = _evaluate([10.0, 10.0, 5.0])

    assert result["ready"] is True
    assert result["has_score_separation"] is True
    assert result["has_unresolved_ties"] is True


def test_all_candidates_tied_is_still_ready() -> None:
    """Proves readiness has not quietly become a 'a winner exists' test."""
    result = _evaluate([10.0, 10.0, 10.0])

    assert result["ready"] is True
    assert result["has_score_separation"] is False
    assert result["has_unresolved_ties"] is True


def test_multiple_tie_groups_are_ready() -> None:
    result = _evaluate([10.0, 10.0, 7.0, 7.0, 3.0])

    assert result["ready"] is True
    assert result["has_score_separation"] is True
    assert result["has_unresolved_ties"] is True


def test_negative_scores_are_ready() -> None:
    result = _evaluate([2.0, -1.0, -4.0])

    assert result["ready"] is True
    assert result["has_score_separation"] is True
    assert result["has_unresolved_ties"] is False


# ---------------------------------------------------------------------------
# Evidence presence is reported, never required
# ---------------------------------------------------------------------------


def test_no_evidence_for_any_candidate_is_still_ready() -> None:
    """Evidence presence must not become a hidden decision threshold."""
    result = _evaluate([10.0, 8.0, 5.0], evidence=[False, False, False])

    assert result["evidence_present_for_any_candidate"] is False
    assert result["ready"] is True


def test_partial_evidence_is_reported() -> None:
    result = _evaluate([10.0, 5.0], evidence=[True, False])

    assert result["evidence_present_for_any_candidate"] is True
    assert result["ready"] is True


def test_all_evidence_present_is_reported() -> None:
    result = _evaluate([10.0, 5.0], evidence=[True, True])

    assert result["evidence_present_for_any_candidate"] is True
    assert result["ready"] is True


# ---------------------------------------------------------------------------
# Task 029 inconsistency suppresses readiness
# ---------------------------------------------------------------------------


def test_consistency_failure_suppresses_readiness() -> None:
    ranked, summary, consistency = _build([10.0, 8.0, 5.0])
    forced = dict(consistency)
    forced["consistent"] = False

    result = _readiness_service().evaluate(ranked, summary, forced)

    assert result["consistency_verified"] is False
    assert result["ready"] is False
    # Everything else still reports truthfully.
    assert result["has_candidates"] is True
    assert result["ranking_available"] is True
    assert result["summary_available"] is True
    assert result["separation_metadata_available"] is True


def test_consistency_verdict_is_taken_verbatim() -> None:
    """Task 030 never redefines or repairs Task 029's verdict."""
    ranked, summary, consistency = _build([10.0, 8.0, 5.0])
    corrupted_summary = dict(summary)
    corrupted_summary["total_candidates"] = 99
    real_verdict = _consistency_service().check_consistency(ranked, corrupted_summary)
    assert real_verdict["consistent"] is False

    result = _readiness_service().evaluate(ranked, corrupted_summary, real_verdict)

    assert result["consistency_verified"] is False
    assert result["ready"] is False


# ---------------------------------------------------------------------------
# Absent upstream structures
# ---------------------------------------------------------------------------


def test_missing_summary_suppresses_readiness() -> None:
    ranked, _summary, consistency = _build([10.0, 8.0, 5.0])

    result = _readiness_service().evaluate(ranked, None, consistency)

    assert result["summary_available"] is False
    assert result["ready"] is False


@pytest.mark.parametrize(
    "field",
    [
        "total_candidates",
        "distinct_score_groups",
        "top_rank",
        "highest_score",
        "score_range",
        "has_any_ties",
    ],
)
def test_structurally_invalid_summary_is_unavailable(field: str) -> None:
    ranked, summary, consistency = _build([10.0, 8.0, 5.0])
    degraded = dict(summary)
    del degraded[field]

    result = _readiness_service().evaluate(ranked, degraded, consistency)

    assert result["summary_available"] is False
    assert result["ready"] is False


def test_summary_with_wrong_field_type_is_unavailable() -> None:
    ranked, summary, consistency = _build([10.0, 8.0, 5.0])
    degraded = dict(summary)
    degraded["total_candidates"] = "three"

    result = _readiness_service().evaluate(ranked, degraded, consistency)

    assert result["summary_available"] is False
    assert result["ready"] is False


@pytest.mark.parametrize(
    "field",
    [
        "is_tied",
        "tie_group_size",
        "score_gap_to_next_higher",
        "score_gap_to_next_lower",
    ],
)
def test_missing_separation_field_suppresses_readiness(field: str) -> None:
    ranked, summary, consistency = _build([10.0, 8.0, 5.0])
    degraded = copy.deepcopy(ranked)
    del degraded[1][field]

    result = _readiness_service().evaluate(degraded, summary, consistency)

    assert result["separation_metadata_available"] is False
    assert result["ready"] is False


def test_separation_metadata_is_not_silently_filled_in() -> None:
    ranked, summary, consistency = _build([10.0, 8.0])
    degraded = copy.deepcopy(ranked)
    del degraded[0]["tie_group_size"]

    _readiness_service().evaluate(degraded, summary, consistency)

    assert "tie_group_size" not in degraded[0]


def test_empty_differential_has_separation_metadata_available() -> None:
    """No candidate entries means no entry is missing metadata."""
    ranked, summary, consistency = _build([])

    result = _readiness_service().evaluate(ranked, summary, consistency)

    assert result["separation_metadata_available"] is True


# ---------------------------------------------------------------------------
# Structurally unusable input -> dedicated contract error
# ---------------------------------------------------------------------------


def test_non_numeric_score_raises_contract_error() -> None:
    ranked, summary, consistency = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["hypothesis_score"] = "ten"

    with pytest.raises(DifferentialDecisionReadinessContractError):
        _readiness_service().evaluate(corrupted, summary, consistency)


def test_missing_score_raises_contract_error() -> None:
    ranked, summary, consistency = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    del corrupted[0]["hypothesis_score"]

    with pytest.raises(DifferentialDecisionReadinessContractError):
        _readiness_service().evaluate(corrupted, summary, consistency)


def test_missing_has_evidence_raises_contract_error() -> None:
    ranked, summary, consistency = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    del corrupted[1]["has_evidence"]

    with pytest.raises(DifferentialDecisionReadinessContractError):
        _readiness_service().evaluate(corrupted, summary, consistency)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("has_evidence", "yes"),
        ("is_tied", "no"),
        ("tie_group_size", "one"),
        ("score_gap_to_next_lower", "five"),
    ],
)
def test_malformed_field_type_raises_contract_error(field: str, value: Any) -> None:
    """Present-but-nonsense differs from absent: absent is reportable."""
    ranked, summary, consistency = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0][field] = value

    with pytest.raises(DifferentialDecisionReadinessContractError):
        _readiness_service().evaluate(corrupted, summary, consistency)


def test_missing_consistent_field_raises_contract_error() -> None:
    ranked, summary, consistency = _build([10.0, 5.0])
    corrupted = dict(consistency)
    del corrupted["consistent"]

    with pytest.raises(DifferentialDecisionReadinessContractError):
        _readiness_service().evaluate(ranked, summary, corrupted)


def test_non_boolean_consistent_raises_contract_error() -> None:
    ranked, summary, consistency = _build([10.0, 5.0])
    corrupted = dict(consistency)
    corrupted["consistent"] = "true"

    with pytest.raises(DifferentialDecisionReadinessContractError):
        _readiness_service().evaluate(ranked, summary, corrupted)


def test_contract_error_carries_invariant_name() -> None:
    ranked, summary, consistency = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["hypothesis_score"] = "ten"

    with pytest.raises(DifferentialDecisionReadinessContractError) as exc_info:
        _readiness_service().evaluate(corrupted, summary, consistency)

    assert exc_info.value.invariant == "NON_NUMERIC_SCORE"


# ---------------------------------------------------------------------------
# The readiness validator -- ready is derived, never accepted
# ---------------------------------------------------------------------------


def _readiness_result(**overrides: Any) -> dict[str, Any]:
    result = {
        "ready": True,
        "consistency_verified": True,
        "has_candidates": True,
        "ranking_available": True,
        "summary_available": True,
        "separation_metadata_available": True,
        "has_score_separation": True,
        "has_unresolved_ties": False,
        "evidence_present_for_any_candidate": True,
        "readiness_source": READINESS_SOURCE_DIFFERENTIAL_DECISION_TASK_030,
    }
    result.update(overrides)
    return result


def test_validator_accepts_a_well_formed_result() -> None:
    DifferentialDecisionReadinessService._validate_readiness(_readiness_result())


@pytest.mark.parametrize(
    "prerequisite",
    [
        "consistency_verified",
        "has_candidates",
        "summary_available",
        "separation_metadata_available",
    ],
)
def test_validator_rejects_forged_ready(prerequisite: str) -> None:
    """A client must never be able to assert readiness it has not earned."""
    overrides: dict[str, Any] = {prerequisite: False}
    if prerequisite == "has_candidates":
        overrides.update(
            ranking_available=False,
            has_score_separation=False,
            has_unresolved_ties=False,
            evidence_present_for_any_candidate=False,
        )

    with pytest.raises(DifferentialDecisionReadinessContractError):
        DifferentialDecisionReadinessService._validate_readiness(
            _readiness_result(**overrides)
        )


def test_validator_rejects_ready_false_when_prerequisites_hold() -> None:
    with pytest.raises(DifferentialDecisionReadinessContractError):
        DifferentialDecisionReadinessService._validate_readiness(
            _readiness_result(ready=False)
        )


def test_validator_rejects_ranking_availability_mismatch() -> None:
    with pytest.raises(DifferentialDecisionReadinessContractError):
        DifferentialDecisionReadinessService._validate_readiness(
            _readiness_result(has_candidates=True, ranking_available=False)
        )


@pytest.mark.parametrize(
    "field",
    [
        "has_score_separation",
        "has_unresolved_ties",
        "evidence_present_for_any_candidate",
    ],
)
def test_validator_rejects_empty_differential_claiming_structure(
    field: str,
) -> None:
    overrides: dict[str, Any] = {
        "ready": False,
        "has_candidates": False,
        "ranking_available": False,
        "has_score_separation": False,
        "has_unresolved_ties": False,
        "evidence_present_for_any_candidate": False,
    }
    overrides[field] = True

    with pytest.raises(DifferentialDecisionReadinessContractError):
        DifferentialDecisionReadinessService._validate_readiness(
            _readiness_result(**overrides)
        )


def test_validator_rejects_non_boolean_field() -> None:
    with pytest.raises(DifferentialDecisionReadinessContractError):
        DifferentialDecisionReadinessService._validate_readiness(
            _readiness_result(has_unresolved_ties="no")
        )


def test_validator_rejects_wrong_source() -> None:
    with pytest.raises(DifferentialDecisionReadinessContractError):
        DifferentialDecisionReadinessService._validate_readiness(
            _readiness_result(readiness_source="SOMETHING_ELSE")
        )


def test_validator_accepts_all_tied_ready_result() -> None:
    """Ties and absent evidence must remain compatible with ready."""
    DifferentialDecisionReadinessService._validate_readiness(
        _readiness_result(
            has_score_separation=False,
            has_unresolved_ties=True,
            evidence_present_for_any_candidate=False,
        )
    )


# ---------------------------------------------------------------------------
# Source, determinism, non-mutation
# ---------------------------------------------------------------------------


def test_readiness_source_is_fixed() -> None:
    assert (
        READINESS_SOURCE_DIFFERENTIAL_DECISION_TASK_030
        == "DIFFERENTIAL_DECISION_READINESS_TASK_030"
    )
    for scores in ([], [1.0], [3.0, 3.0, 1.0]):
        result = _evaluate(scores)
        assert (
            result["readiness_source"]
            == READINESS_SOURCE_DIFFERENTIAL_DECISION_TASK_030
        )


def test_identical_input_is_deterministic() -> None:
    ranked, summary, consistency = _build([10.0, 10.0, 7.0, 5.0])
    service = _readiness_service()

    first = service.evaluate(ranked, summary, consistency)
    second = service.evaluate(ranked, summary, consistency)

    assert first == second


def test_service_does_not_mutate_any_of_its_three_inputs() -> None:
    ranked, summary, consistency = _build([10.0, 10.0, 7.0, 5.0])
    ranked_before = copy.deepcopy(ranked)
    summary_before = copy.deepcopy(summary)
    consistency_before = copy.deepcopy(consistency)

    _readiness_service().evaluate(ranked, summary, consistency)

    assert ranked == ranked_before
    assert summary == summary_before
    assert consistency == consistency_before


def test_no_decision_fields_are_introduced() -> None:
    """The architectural boundary, asserted directly."""
    result = _evaluate([10.0, 8.0, 5.0])

    assert set(result) == set(READINESS_FIELDS) | {"readiness_source"}
    for forbidden in (
        "is_winner",
        "selected_hypothesis",
        "diagnosis",
        "probability",
        "confidence",
        "recommendation",
        "treatment",
        "action",
    ):
        assert forbidden not in result


# ---------------------------------------------------------------------------
# Dependency chain
# ---------------------------------------------------------------------------


def test_evaluate_session_walks_the_full_dependency_chain() -> None:
    """Tasks 027, 028, and 029 must each be consumed, not reimplemented."""
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

    ranking = RecordingRanking(HypothesisScoringService(EvidenceAggregationService()))
    service = DifferentialDecisionReadinessService(
        RecordingConsistency(RecordingSummary(ranking))
    )

    with TestingSessionLocal() as db:
        result = service.evaluate_session(db, uuid4(), [])

    assert calls == ["rank_session", "summarize_ranked", "check_consistency"]
    assert result["ready"] is False
    assert result["consistency_verified"] is True


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
            "metadata": {"source": "differential-readiness-test"},
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


def test_api_differential_readiness_endpoint() -> None:
    session_id = _seed_session("Task 030 readiness test")

    response = client.get(f"/sessions/{session_id}/differential-readiness")
    assert response.status_code == 200
    payload = response.json()

    assert set(payload) == set(READINESS_FIELDS) | {"readiness_source"}
    for field in READINESS_FIELDS:
        assert isinstance(payload[field], bool)

    assert payload["ready"] is True
    assert payload["consistency_verified"] is True
    assert payload["has_candidates"] is True
    assert payload["ranking_available"] is True
    assert payload["summary_available"] is True
    assert payload["separation_metadata_available"] is True
    assert (
        payload["readiness_source"] == READINESS_SOURCE_DIFFERENTIAL_DECISION_TASK_030
    )


def test_api_differential_readiness_empty_session() -> None:
    session_id = _create_session("Task 030 empty readiness test")

    response = client.get(f"/sessions/{session_id}/differential-readiness")
    assert response.status_code == 200
    payload = response.json()

    assert payload["ready"] is False
    assert payload["consistency_verified"] is True
    assert payload["has_candidates"] is False
    assert payload["summary_available"] is True
    assert payload["separation_metadata_available"] is True


def test_api_differential_readiness_missing_session_returns_404() -> None:
    response = client.get(f"/sessions/{uuid4()}/differential-readiness")
    assert response.status_code == 404


def test_api_differential_readiness_is_read_only() -> None:
    session_id = _seed_session("Task 030 read-only test")

    differential_before = client.get(f"/sessions/{session_id}/differential").json()
    summary_before = client.get(f"/sessions/{session_id}/differential-summary").json()
    consistency_before = client.get(
        f"/sessions/{session_id}/differential-consistency"
    ).json()

    response = client.get(f"/sessions/{session_id}/differential-readiness")
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


def test_api_differential_readiness_is_deterministic() -> None:
    session_id = _seed_session("Task 030 determinism test")

    first = client.get(f"/sessions/{session_id}/differential-readiness").json()
    second = client.get(f"/sessions/{session_id}/differential-readiness").json()

    assert first == second


def test_api_readiness_agrees_with_the_live_consistency_endpoint() -> None:
    session_id = _seed_session("Task 030 agreement test")

    consistency = client.get(f"/sessions/{session_id}/differential-consistency").json()
    readiness = client.get(f"/sessions/{session_id}/differential-readiness").json()

    assert readiness["consistency_verified"] == consistency["consistent"]
