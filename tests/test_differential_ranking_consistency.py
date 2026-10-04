"""Tests for the Task 029 differential ranking consistency layer.

Task 029 cross-checks Task 027's ranked differential against Task 028's
structural summary and reports whether they describe the same
differential state. It changes nothing about Tasks 025-028's scores,
ranks, separation metadata, or summary aggregates -- these tests build
on the same helpers used by the Task 026/027/028 suites and cover only
the new consistency contract.

Two outcomes are deliberately kept apart and tested apart:

* a *wrong but well-typed* value is an inconsistency
  (``consistent is False``), never an exception;
* a *structurally unusable* value raises
  ``DifferentialRankingConsistencyContractError``.
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
from rop.services.differential_ranking import DifferentialRankingService
from rop.services.differential_ranking_consistency import (
    CONSISTENCY_SOURCE_DIFFERENTIAL_RANKING_TASK_029,
    DifferentialRankingConsistencyContractError,
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


CONSISTENCY_FIELDS = (
    "consistent",
    "candidate_count_matches",
    "score_groups_match",
    "tie_statistics_match",
    "score_range_matches",
    "rank_structure_matches",
    "separation_metadata_matches",
    "summary_consistent",
)


def _ranking_service() -> DifferentialRankingService:
    return DifferentialRankingService(
        HypothesisScoringService(EvidenceAggregationService())
    )


def _summary_service() -> DifferentialRankingSummaryService:
    return DifferentialRankingSummaryService(_ranking_service())


def _consistency_service() -> DifferentialRankingConsistencyService:
    return DifferentialRankingConsistencyService(_summary_service())


def _score_result(
    *,
    hypothesis_name: str,
    hypothesis_score: float,
    hypothesis_id: UUID | None = None,
) -> dict[str, Any]:
    """Build a well-formed Task 025 score-result dict for these tests."""
    if hypothesis_score > 0:
        score_direction = "POSITIVE"
    elif hypothesis_score < 0:
        score_direction = "NEGATIVE"
    else:
        score_direction = "ZERO"

    return {
        "hypothesis_id": hypothesis_id or uuid4(),
        "hypothesis_name": hypothesis_name,
        "hypothesis_score": hypothesis_score,
        "score_source": SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
        "evidence_consistency": "SUPPORT_ONLY",
        "total_evidence_items": 1,
        "total_support_contribution": 0.0,
        "total_contradiction_contribution": 0.0,
        "net_contribution": hypothesis_score,
        "has_evidence": True,
        "has_mixed_evidence": False,
        "score_direction": score_direction,
        "evidence_coverage_ratio": 1.0,
        "informative_evidence_ratio": 1.0,
        "support_to_contradiction_ratio": None,
        "evidence_position": "SUPPORTING",
    }


def _build(scores: list[float]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Produce a genuine (ranked, summary) pair through Tasks 026-028.

    Tests then corrupt a copy of one side and assert Task 029 notices.
    """
    ranking_service = _ranking_service()
    summary_service = DifferentialRankingSummaryService(ranking_service)
    entries = [
        _score_result(hypothesis_name=f"H{index}", hypothesis_score=score)
        for index, score in enumerate(scores)
    ]
    ranked = ranking_service.rank_score_results(entries)
    summary = summary_service.summarize_ranked(ranked)
    return ranked, summary


def _check(scores: list[float]) -> dict[str, Any]:
    ranked, summary = _build(scores)
    return _consistency_service().check_consistency(ranked, summary)


def _assert_fully_consistent(result: dict[str, Any]) -> None:
    for field in CONSISTENCY_FIELDS:
        assert result[field] is True, f"{field} should be True"
    assert (
        result["consistency_source"] == CONSISTENCY_SOURCE_DIFFERENTIAL_RANKING_TASK_029
    )


# ---------------------------------------------------------------------------
# Consistent states
# ---------------------------------------------------------------------------


def test_empty_differential_is_consistent() -> None:
    """Two empty structures agree -- absence of candidates is not an error."""
    _assert_fully_consistent(_check([]))


def test_single_candidate_is_consistent() -> None:
    _assert_fully_consistent(_check([10.0]))


def test_no_ties_is_consistent() -> None:
    _assert_fully_consistent(_check([10.0, 8.0, 5.0]))


def test_one_tie_is_consistent() -> None:
    _assert_fully_consistent(_check([10.0, 10.0, 5.0]))


def test_multiple_tie_groups_is_consistent() -> None:
    _assert_fully_consistent(_check([10.0, 10.0, 7.0, 7.0, 3.0]))


def test_all_candidates_tied_is_consistent() -> None:
    _assert_fully_consistent(_check([4.0, 4.0, 4.0]))


def test_negative_scores_are_consistent() -> None:
    """Score-range consistency must hold across the sign boundary."""
    ranked, summary = _build([2.0, -1.0, -4.0])
    result = _consistency_service().check_consistency(ranked, summary)

    _assert_fully_consistent(result)
    assert summary["highest_score"] == 2.0
    assert summary["lowest_score"] == -4.0
    assert summary["score_range"] == 6.0


def test_consistency_source_is_fixed() -> None:
    assert (
        CONSISTENCY_SOURCE_DIFFERENTIAL_RANKING_TASK_029
        == "DIFFERENTIAL_RANKING_TASK_029"
    )
    for scores in ([], [1.0], [3.0, 3.0, 1.0]):
        result = _check(scores)
        assert (
            result["consistency_source"]
            == CONSISTENCY_SOURCE_DIFFERENTIAL_RANKING_TASK_029
        )


def test_identical_input_is_deterministic() -> None:
    ranked, summary = _build([10.0, 10.0, 7.0, 5.0, 5.0, 3.0])
    service = _consistency_service()
    first = service.check_consistency(ranked, summary)
    second = service.check_consistency(ranked, summary)
    assert first == second


def test_competition_ranking_sequence_is_accepted() -> None:
    """The Task 029 spec's worked example: 1, 1, 3, 4, 4, 6."""
    ranked, summary = _build([10.0, 10.0, 7.0, 5.0, 5.0, 3.0])
    assert [entry["rank"] for entry in ranked] == [1, 1, 3, 4, 4, 6]
    _assert_fully_consistent(_consistency_service().check_consistency(ranked, summary))


# ---------------------------------------------------------------------------
# Candidate-count corruption
# ---------------------------------------------------------------------------


def test_candidate_count_corruption_is_detected() -> None:
    ranked, summary = _build([10.0, 8.0, 5.0])
    corrupted = dict(summary)
    corrupted["total_candidates"] = 4

    result = _consistency_service().check_consistency(ranked, corrupted)

    assert result["candidate_count_matches"] is False
    assert result["consistent"] is False
    assert result["summary_consistent"] is False
    # Unrelated checks stay green -- the failure is reported precisely.
    assert result["rank_structure_matches"] is True
    assert result["separation_metadata_matches"] is True


# ---------------------------------------------------------------------------
# Score-group corruption
# ---------------------------------------------------------------------------


def test_score_group_corruption_is_detected() -> None:
    ranked, summary = _build([10.0, 10.0, 5.0])
    corrupted = dict(summary)
    corrupted["distinct_score_groups"] = 3

    result = _consistency_service().check_consistency(ranked, corrupted)

    assert result["score_groups_match"] is False
    assert result["consistent"] is False


# ---------------------------------------------------------------------------
# Tie-statistic corruption
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tied_candidate_count", 0),
        ("tie_group_count", 0),
        ("largest_tie_group_size", 1),
        ("has_any_ties", False),
    ],
)
def test_tie_statistic_corruption_is_detected(field: str, value: Any) -> None:
    ranked, summary = _build([10.0, 10.0, 7.0])
    corrupted = dict(summary)
    corrupted[field] = value

    result = _consistency_service().check_consistency(ranked, corrupted)

    assert result["tie_statistics_match"] is False
    assert result["consistent"] is False


def test_tie_statistics_claiming_no_ties_for_a_tied_differential() -> None:
    """The spec's worked example: actual 10, 10, 7 vs a claim of 0 ties."""
    ranked, summary = _build([10.0, 10.0, 7.0])
    corrupted = dict(summary)
    corrupted["tied_candidate_count"] = 0
    corrupted["tie_group_count"] = 0
    corrupted["largest_tie_group_size"] = 1
    corrupted["has_any_ties"] = False

    result = _consistency_service().check_consistency(ranked, corrupted)

    assert result["tie_statistics_match"] is False
    assert result["consistent"] is False


# ---------------------------------------------------------------------------
# Range corruption
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("highest_score", 99.0),
        ("lowest_score", -99.0),
        ("score_range", 999.0),
    ],
)
def test_range_corruption_is_detected(field: str, value: float) -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = dict(summary)
    corrupted[field] = value

    result = _consistency_service().check_consistency(ranked, corrupted)

    assert result["score_range_matches"] is False
    assert result["consistent"] is False


# ---------------------------------------------------------------------------
# Rank corruption
# ---------------------------------------------------------------------------


def test_dense_ranking_corruption_is_detected() -> None:
    """Actual competition ranks 1, 1, 3 rewritten as dense 1, 2, 3."""
    ranked, summary = _build([10.0, 10.0, 7.0])
    assert [entry["rank"] for entry in ranked] == [1, 1, 3]

    corrupted = copy.deepcopy(ranked)
    corrupted[1]["rank"] = 2
    corrupted[2]["rank"] = 3

    result = _consistency_service().check_consistency(corrupted, summary)

    assert result["rank_structure_matches"] is False
    assert result["consistent"] is False


def test_first_rank_not_one_is_detected() -> None:
    ranked, summary = _build([10.0, 8.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["rank"] = 2

    result = _consistency_service().check_consistency(corrupted, summary)

    assert result["rank_structure_matches"] is False
    assert result["consistent"] is False


def test_rank_exceeding_total_candidates_is_detected() -> None:
    ranked, summary = _build([10.0, 8.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[2]["rank"] = 99

    result = _consistency_service().check_consistency(corrupted, summary)

    assert result["rank_structure_matches"] is False
    assert result["consistent"] is False


def test_out_of_order_scores_are_detected() -> None:
    """A rank is only meaningful relative to a score-descending order."""
    ranked, summary = _build([10.0, 8.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted.reverse()

    result = _consistency_service().check_consistency(corrupted, summary)

    assert result["rank_structure_matches"] is False
    assert result["consistent"] is False


# ---------------------------------------------------------------------------
# Separation-metadata corruption (the second integrity boundary on Task 027)
# ---------------------------------------------------------------------------


def test_is_tied_corruption_is_detected() -> None:
    ranked, summary = _build([10.0, 10.0, 7.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["is_tied"] = False

    result = _consistency_service().check_consistency(corrupted, summary)

    assert result["separation_metadata_matches"] is False
    assert result["consistent"] is False


def test_tie_group_size_corruption_is_detected() -> None:
    ranked, summary = _build([10.0, 10.0, 7.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["tie_group_size"] = 3

    result = _consistency_service().check_consistency(corrupted, summary)

    assert result["separation_metadata_matches"] is False
    assert result["consistent"] is False


def test_score_gap_to_next_higher_corruption_is_detected() -> None:
    ranked, summary = _build([10.0, 7.0, 3.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[1]["score_gap_to_next_higher"] = 0.0

    result = _consistency_service().check_consistency(corrupted, summary)

    assert result["separation_metadata_matches"] is False
    assert result["consistent"] is False


def test_score_gap_to_next_lower_corruption_is_detected() -> None:
    """The spec's worked example: a tied candidate claiming a 0 gap down."""
    ranked, summary = _build([10.0, 10.0, 7.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["score_gap_to_next_lower"] = 0.0

    result = _consistency_service().check_consistency(corrupted, summary)

    assert result["separation_metadata_matches"] is False
    assert result["consistent"] is False


def test_boundary_gap_corruption_is_detected() -> None:
    """The top entry must report ``None`` upward, the bottom ``None`` down."""
    ranked, summary = _build([10.0, 7.0])

    top_corrupted = copy.deepcopy(ranked)
    top_corrupted[0]["score_gap_to_next_higher"] = 3.0
    top_result = _consistency_service().check_consistency(top_corrupted, summary)
    assert top_result["separation_metadata_matches"] is False

    bottom_corrupted = copy.deepcopy(ranked)
    bottom_corrupted[-1]["score_gap_to_next_lower"] = 3.0
    bottom_result = _consistency_service().check_consistency(bottom_corrupted, summary)
    assert bottom_result["separation_metadata_matches"] is False


# ---------------------------------------------------------------------------
# Never silently repair, never mutate
# ---------------------------------------------------------------------------


def test_service_does_not_mutate_its_inputs() -> None:
    ranked, summary = _build([10.0, 10.0, 7.0, 5.0])
    ranked_before = copy.deepcopy(ranked)
    summary_before = copy.deepcopy(summary)

    _consistency_service().check_consistency(ranked, summary)

    assert ranked == ranked_before
    assert summary == summary_before


def test_service_does_not_repair_corrupted_input() -> None:
    ranked, summary = _build([10.0, 10.0, 7.0])
    corrupted_ranked = copy.deepcopy(ranked)
    corrupted_ranked[1]["rank"] = 2
    corrupted_summary = dict(summary)
    corrupted_summary["total_candidates"] = 99

    result = _consistency_service().check_consistency(
        corrupted_ranked, corrupted_summary
    )

    assert result["consistent"] is False
    # The corrupted values survive untouched -- reporting only.
    assert corrupted_ranked[1]["rank"] == 2
    assert corrupted_summary["total_candidates"] == 99


def test_multiple_simultaneous_corruptions_are_all_reported() -> None:
    ranked, summary = _build([10.0, 10.0, 7.0])
    corrupted_ranked = copy.deepcopy(ranked)
    corrupted_ranked[0]["is_tied"] = False
    corrupted_summary = dict(summary)
    corrupted_summary["total_candidates"] = 2
    corrupted_summary["score_range"] = 999.0

    result = _consistency_service().check_consistency(
        corrupted_ranked, corrupted_summary
    )

    assert result["candidate_count_matches"] is False
    assert result["score_range_matches"] is False
    assert result["separation_metadata_matches"] is False
    assert result["score_groups_match"] is True
    assert result["consistent"] is False


def test_consistent_always_equals_summary_consistent() -> None:
    ranked, summary = _build([10.0, 10.0, 7.0])
    service = _consistency_service()

    good = service.check_consistency(ranked, summary)
    assert good["consistent"] is True
    assert good["summary_consistent"] is True

    corrupted = dict(summary)
    corrupted["tie_group_count"] = 0
    bad = service.check_consistency(ranked, corrupted)
    assert bad["consistent"] is False
    assert bad["summary_consistent"] is False


# ---------------------------------------------------------------------------
# Structurally unusable input -> dedicated contract error
# ---------------------------------------------------------------------------


def test_non_numeric_score_raises_contract_error() -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["hypothesis_score"] = "ten"

    with pytest.raises(DifferentialRankingConsistencyContractError):
        _consistency_service().check_consistency(corrupted, summary)


def test_missing_hypothesis_score_raises_contract_error() -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    del corrupted[0]["hypothesis_score"]

    with pytest.raises(DifferentialRankingConsistencyContractError):
        _consistency_service().check_consistency(corrupted, summary)


def test_non_integer_rank_raises_contract_error() -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["rank"] = "first"

    with pytest.raises(DifferentialRankingConsistencyContractError):
        _consistency_service().check_consistency(corrupted, summary)


def test_missing_rank_raises_contract_error() -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    del corrupted[1]["rank"]

    with pytest.raises(DifferentialRankingConsistencyContractError):
        _consistency_service().check_consistency(corrupted, summary)


def test_invalid_is_tied_type_raises_contract_error() -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["is_tied"] = "yes"

    with pytest.raises(DifferentialRankingConsistencyContractError):
        _consistency_service().check_consistency(corrupted, summary)


def test_invalid_tie_group_size_type_raises_contract_error() -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["tie_group_size"] = "one"

    with pytest.raises(DifferentialRankingConsistencyContractError):
        _consistency_service().check_consistency(corrupted, summary)


def test_invalid_score_gap_type_raises_contract_error() -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["score_gap_to_next_lower"] = "five"

    with pytest.raises(DifferentialRankingConsistencyContractError):
        _consistency_service().check_consistency(corrupted, summary)


def test_missing_score_gap_field_raises_contract_error() -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    del corrupted[0]["score_gap_to_next_higher"]

    with pytest.raises(DifferentialRankingConsistencyContractError):
        _consistency_service().check_consistency(corrupted, summary)


@pytest.mark.parametrize(
    "field",
    [
        "total_candidates",
        "distinct_score_groups",
        "tied_candidate_count",
        "tie_group_count",
        "largest_tie_group_size",
        "has_any_ties",
        "highest_score",
        "lowest_score",
        "score_range",
    ],
)
def test_missing_summary_field_raises_contract_error(field: str) -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = dict(summary)
    del corrupted[field]

    with pytest.raises(DifferentialRankingConsistencyContractError):
        _consistency_service().check_consistency(ranked, corrupted)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total_candidates", "two"),
        ("distinct_score_groups", 2.5),
        ("has_any_ties", "no"),
        ("highest_score", "ten"),
        ("score_range", "five"),
    ],
)
def test_invalid_summary_field_type_raises_contract_error(
    field: str, value: Any
) -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = dict(summary)
    corrupted[field] = value

    with pytest.raises(DifferentialRankingConsistencyContractError):
        _consistency_service().check_consistency(ranked, corrupted)


def test_contract_error_carries_invariant_name() -> None:
    ranked, summary = _build([10.0, 5.0])
    corrupted = copy.deepcopy(ranked)
    corrupted[0]["hypothesis_score"] = "ten"

    with pytest.raises(DifferentialRankingConsistencyContractError) as exc_info:
        _consistency_service().check_consistency(corrupted, summary)

    assert exc_info.value.invariant == "NON_NUMERIC_SCORE"


def test_normal_inconsistency_is_not_an_exception() -> None:
    """The boundary between the two failure modes, stated directly."""
    ranked, summary = _build([10.0, 5.0])
    corrupted = dict(summary)
    corrupted["total_candidates"] = 4

    result = _consistency_service().check_consistency(ranked, corrupted)

    assert result["consistent"] is False
    assert (
        result["consistency_source"] == CONSISTENCY_SOURCE_DIFFERENTIAL_RANKING_TASK_029
    )


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
            "metadata": {"source": "differential-consistency-test"},
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


def test_api_differential_consistency_endpoint() -> None:
    session_id = _seed_session("Task 029 consistency test")

    response = client.get(f"/sessions/{session_id}/differential-consistency")
    assert response.status_code == 200
    payload = response.json()

    assert set(payload) == set(CONSISTENCY_FIELDS) | {"consistency_source"}
    for field in CONSISTENCY_FIELDS:
        assert isinstance(payload[field], bool)
        assert payload[field] is True
    assert (
        payload["consistency_source"]
        == CONSISTENCY_SOURCE_DIFFERENTIAL_RANKING_TASK_029
    )


def test_api_differential_consistency_agrees_with_the_live_pipeline() -> None:
    session_id = _seed_session("Task 029 pipeline agreement test")

    ranked = client.get(f"/sessions/{session_id}/differential").json()
    summary = client.get(f"/sessions/{session_id}/differential-summary").json()
    payload = client.get(f"/sessions/{session_id}/differential-consistency").json()

    assert payload["consistent"] is True
    assert summary["total_candidates"] == len(ranked)


def test_api_differential_consistency_empty_session() -> None:
    session_id = _create_session("Task 029 empty consistency test")

    response = client.get(f"/sessions/{session_id}/differential-consistency")
    assert response.status_code == 200
    payload = response.json()

    for field in CONSISTENCY_FIELDS:
        assert payload[field] is True


def test_api_differential_consistency_missing_session_returns_404() -> None:
    response = client.get(f"/sessions/{uuid4()}/differential-consistency")
    assert response.status_code == 404


def test_api_differential_consistency_is_read_only() -> None:
    session_id = _seed_session("Task 029 read-only test")

    differential_before = client.get(f"/sessions/{session_id}/differential").json()
    summary_before = client.get(f"/sessions/{session_id}/differential-summary").json()

    response = client.get(f"/sessions/{session_id}/differential-consistency")
    assert response.status_code == 200

    differential_after = client.get(f"/sessions/{session_id}/differential").json()
    summary_after = client.get(f"/sessions/{session_id}/differential-summary").json()

    assert differential_after == differential_before
    assert summary_after == summary_before


def test_api_differential_consistency_is_deterministic() -> None:
    session_id = _seed_session("Task 029 determinism test")

    first = client.get(f"/sessions/{session_id}/differential-consistency").json()
    second = client.get(f"/sessions/{session_id}/differential-consistency").json()

    assert first == second


def test_check_session_walks_the_full_dependency_chain() -> None:
    """``check_session`` must consume Tasks 025-028, not reimplement them.

    Task 029 must not duplicate ranking or scoring logic, so the only
    way it may obtain a ranked differential is
    ``DifferentialRankingService.rank_session``, and the only way it may
    obtain a summary is ``DifferentialRankingSummaryService``. This
    records those calls rather than asserting on their results, so the
    architectural dependency is pinned independently of the data.
    """
    calls: list[str] = []

    class RecordingRankingService(DifferentialRankingService):
        def rank_session(
            self,
            db: Session,
            session_id: UUID,
            candidates: list[Any],
        ) -> list[dict[str, Any]]:
            calls.append("rank_session")
            return super().rank_session(db, session_id, candidates)

    class RecordingSummaryService(DifferentialRankingSummaryService):
        def summarize_ranked(self, ranked: list[dict[str, Any]]) -> dict[str, Any]:
            calls.append("summarize_ranked")
            return super().summarize_ranked(ranked)

    ranking_service = RecordingRankingService(
        HypothesisScoringService(EvidenceAggregationService())
    )
    service = DifferentialRankingConsistencyService(
        RecordingSummaryService(ranking_service)
    )

    with TestingSessionLocal() as db:
        result = service.check_session(db, uuid4(), [])

    assert calls == ["rank_session", "summarize_ranked"]
    _assert_fully_consistent(result)


def test_check_session_with_no_candidates_is_consistent() -> None:
    """A session with no candidates is a valid, fully consistent state."""
    with TestingSessionLocal() as db:
        result = _consistency_service().check_session(db, uuid4(), [])

    _assert_fully_consistent(result)
