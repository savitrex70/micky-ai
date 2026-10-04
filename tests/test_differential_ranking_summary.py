"""Tests for the Task 028 differential ranking summary layer.

Task 028 derives a compact, session-level structural summary from
Task 027's ranked differential. It changes nothing about Task
025/026/027's scores, ranks, or separation metadata — these tests
build directly on the Task 026/027 test helpers and only cover the
new summary aggregation.
"""

from __future__ import annotations

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
from rop.services.differential_ranking_summary import (
    DifferentialRankingSummaryContractError,
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


def _ranking_service() -> DifferentialRankingService:
    return DifferentialRankingService(
        HypothesisScoringService(EvidenceAggregationService())
    )


def _summary_service() -> DifferentialRankingSummaryService:
    return DifferentialRankingSummaryService(_ranking_service())


def _score_result(
    *,
    hypothesis_name: str,
    hypothesis_score: float,
    hypothesis_id: UUID | None = None,
    total_evidence_items: int = 1,
    total_support_contribution: float = 0.0,
    total_contradiction_contribution: float = 0.0,
    evidence_consistency: str = "SUPPORT_ONLY",
    has_evidence: bool = True,
    has_mixed_evidence: bool = False,
    evidence_coverage_ratio: float = 1.0,
    informative_evidence_ratio: float = 1.0,
    support_to_contradiction_ratio: float | None = None,
    evidence_position: str = "SUPPORTING",
) -> dict[str, Any]:
    """Build a well-formed Task 025 score-result dict for summary tests."""
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
        "evidence_consistency": evidence_consistency,
        "total_evidence_items": total_evidence_items,
        "total_support_contribution": total_support_contribution,
        "total_contradiction_contribution": total_contradiction_contribution,
        "net_contribution": hypothesis_score,
        "has_evidence": has_evidence,
        "has_mixed_evidence": has_mixed_evidence,
        "score_direction": score_direction,
        "evidence_coverage_ratio": evidence_coverage_ratio,
        "informative_evidence_ratio": informative_evidence_ratio,
        "support_to_contradiction_ratio": support_to_contradiction_ratio,
        "evidence_position": evidence_position,
    }


def _summarize(scores: list[float]) -> dict[str, Any]:
    ranking_service = _ranking_service()
    summary_service = DifferentialRankingSummaryService(ranking_service)
    entries = [
        _score_result(hypothesis_name=f"H{i}", hypothesis_score=score)
        for i, score in enumerate(scores)
    ]
    ranked = ranking_service.rank_score_results(entries)
    return summary_service.summarize_ranked(ranked)


# ---------------------------------------------------------------------------
# No candidates
# ---------------------------------------------------------------------------


def test_empty_differential_summary() -> None:
    summary = _summarize([])
    assert summary == {
        "total_candidates": 0,
        "distinct_score_groups": 0,
        "top_rank": None,
        "highest_score": None,
        "lowest_score": None,
        "score_range": None,
        "tied_candidate_count": 0,
        "tie_group_count": 0,
        "largest_tie_group_size": 0,
        "has_any_ties": False,
    }


# ---------------------------------------------------------------------------
# One candidate
# ---------------------------------------------------------------------------


def test_single_candidate_summary() -> None:
    summary = _summarize([10.0])
    assert summary["total_candidates"] == 1
    assert summary["distinct_score_groups"] == 1
    assert summary["top_rank"] == 1
    assert summary["highest_score"] == 10.0
    assert summary["lowest_score"] == 10.0
    assert summary["score_range"] == 0.0
    assert summary["tied_candidate_count"] == 0
    assert summary["tie_group_count"] == 0
    assert summary["largest_tie_group_size"] == 1
    assert summary["has_any_ties"] is False


# ---------------------------------------------------------------------------
# No ties: 10, 8, 5
# ---------------------------------------------------------------------------


def test_no_ties_summary() -> None:
    summary = _summarize([10.0, 8.0, 5.0])
    assert summary["total_candidates"] == 3
    assert summary["distinct_score_groups"] == 3
    assert summary["tied_candidate_count"] == 0
    assert summary["tie_group_count"] == 0
    assert summary["largest_tie_group_size"] == 1
    assert summary["has_any_ties"] is False
    assert summary["score_range"] == 5.0
    assert summary["highest_score"] == 10.0
    assert summary["lowest_score"] == 5.0
    assert summary["top_rank"] == 1


# ---------------------------------------------------------------------------
# One tie group: 10, 10, 5
# ---------------------------------------------------------------------------


def test_one_tie_group_summary() -> None:
    summary = _summarize([10.0, 10.0, 5.0])
    assert summary["total_candidates"] == 3
    assert summary["distinct_score_groups"] == 2
    assert summary["tied_candidate_count"] == 2
    assert summary["tie_group_count"] == 1
    assert summary["largest_tie_group_size"] == 2
    assert summary["has_any_ties"] is True


# ---------------------------------------------------------------------------
# Multiple tie groups: 10, 10, 7, 7, 3
# ---------------------------------------------------------------------------


def test_multiple_tie_groups_summary() -> None:
    summary = _summarize([10.0, 10.0, 7.0, 7.0, 3.0])
    assert summary["total_candidates"] == 5
    assert summary["distinct_score_groups"] == 3
    assert summary["tied_candidate_count"] == 4
    assert summary["tie_group_count"] == 2
    assert summary["largest_tie_group_size"] == 2
    assert summary["has_any_ties"] is True


# ---------------------------------------------------------------------------
# Unequal tie sizes: 10, 10, 10, 7, 7, 3
# ---------------------------------------------------------------------------


def test_unequal_tie_sizes_summary() -> None:
    summary = _summarize([10.0, 10.0, 10.0, 7.0, 7.0, 3.0])
    assert summary["tied_candidate_count"] == 5
    assert summary["tie_group_count"] == 2
    assert summary["largest_tie_group_size"] == 3


# ---------------------------------------------------------------------------
# distinct_score_groups vs tie_group_count are different things
# ---------------------------------------------------------------------------


def test_distinct_score_groups_vs_tie_group_count() -> None:
    summary = _summarize([10.0, 10.0, 7.0, 5.0, 5.0, 3.0])
    assert summary["distinct_score_groups"] == 4
    assert summary["tie_group_count"] == 2


# ---------------------------------------------------------------------------
# Negative scores: 2, -1, -4
# ---------------------------------------------------------------------------


def test_negative_scores_summary() -> None:
    summary = _summarize([2.0, -1.0, -4.0])
    assert summary["highest_score"] == 2.0
    assert summary["lowest_score"] == -4.0
    assert summary["score_range"] == 6.0


# ---------------------------------------------------------------------------
# Mixed positive/zero/negative: 5, 0, 0, -2
# ---------------------------------------------------------------------------


def test_mixed_positive_zero_negative_summary() -> None:
    summary = _summarize([5.0, 0.0, 0.0, -2.0])
    assert summary["total_candidates"] == 4
    assert summary["distinct_score_groups"] == 3
    assert summary["highest_score"] == 5.0
    assert summary["lowest_score"] == -2.0
    assert summary["score_range"] == 7.0
    assert summary["tied_candidate_count"] == 2
    assert summary["tie_group_count"] == 1
    assert summary["largest_tie_group_size"] == 2
    assert summary["has_any_ties"] is True


# ---------------------------------------------------------------------------
# Precision: four-decimal scores must not produce floating-point artifacts
# ---------------------------------------------------------------------------


def test_score_range_precision_has_no_floating_point_artifacts() -> None:
    summary = _summarize([0.5678, 0.1234])
    score_range = summary["score_range"]
    assert score_range == 0.4444
    assert round(score_range, 4) == score_range


# ---------------------------------------------------------------------------
# Validator: contract enforcement
# ---------------------------------------------------------------------------


def test_validator_accepts_well_formed_summary() -> None:
    summary = _summarize([10.0, 10.0, 5.0])
    # Must not raise.
    DifferentialRankingSummaryService._validate_summary(summary)


def test_validator_rejects_negative_count() -> None:
    summary = {
        "total_candidates": -1,
        "distinct_score_groups": 0,
        "top_rank": None,
        "highest_score": None,
        "lowest_score": None,
        "score_range": None,
        "tied_candidate_count": 0,
        "tie_group_count": 0,
        "largest_tie_group_size": 0,
        "has_any_ties": False,
    }
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "TOTAL_CANDIDATES_BOUNDS"


def test_validator_rejects_has_any_ties_mismatch() -> None:
    summary = {
        "total_candidates": 2,
        "distinct_score_groups": 1,
        "top_rank": 1,
        "highest_score": 5.0,
        "lowest_score": 5.0,
        "score_range": 0.0,
        "tied_candidate_count": 2,
        "tie_group_count": 1,
        "largest_tie_group_size": 2,
        "has_any_ties": False,  # deliberately wrong
    }
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "HAS_ANY_TIES_MISMATCH"


def test_validator_rejects_non_empty_with_none_fields() -> None:
    summary = {
        "total_candidates": 1,
        "distinct_score_groups": 1,
        "top_rank": None,  # deliberately missing
        "highest_score": 5.0,
        "lowest_score": 5.0,
        "score_range": 0.0,
        "tied_candidate_count": 0,
        "tie_group_count": 0,
        "largest_tie_group_size": 1,
        "has_any_ties": False,
    }
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "NON_EMPTY_FIELD_MISSING"


def test_validator_rejects_empty_with_non_none_field() -> None:
    summary = {
        "total_candidates": 0,
        "distinct_score_groups": 0,
        "top_rank": 1,  # deliberately present
        "highest_score": None,
        "lowest_score": None,
        "score_range": None,
        "tied_candidate_count": 0,
        "tie_group_count": 0,
        "largest_tie_group_size": 0,
        "has_any_ties": False,
    }
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "EMPTY_FIELD_NOT_NONE"


def test_validator_rejects_top_rank_not_one() -> None:
    summary = _summarize([10.0, 8.0, 5.0])
    summary["top_rank"] = 2  # deliberately wrong
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "TOP_RANK_INVALID"


def test_validator_rejects_tied_candidate_count_exceeding_total() -> None:
    summary = _summarize([10.0, 8.0, 5.0])
    summary["tied_candidate_count"] = 4  # deliberately > total_candidates (3)
    summary["has_any_ties"] = (
        True  # keep this check isolated from HAS_ANY_TIES_MISMATCH
    )
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "TIED_CANDIDATE_COUNT_BOUNDS"


def test_validator_rejects_tie_group_count_exceeding_distinct_groups() -> None:
    summary = _summarize([10.0, 10.0, 7.0, 7.0, 3.0])
    summary["tie_group_count"] = 99  # deliberately absurd
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "TIE_GROUP_COUNT_BOUNDS"


def test_validator_rejects_distinct_score_groups_inconsistent_with_ties() -> None:
    # Reviewer-flagged case: tie_group_count says 99 tie groups exist,
    # but largest_tie_group_size says the biggest group has only 1
    # member (i.e. no group is actually tied). Even bounding
    # tie_group_count by distinct_score_groups alone would not catch
    # every such inconsistency, so this checks the exact structural
    # identity between tie_group_count, tied_candidate_count, and
    # distinct_score_groups.
    summary = _summarize([10.0, 10.0, 7.0])
    summary["tie_group_count"] = 1  # still <= distinct_score_groups (2)
    summary["tied_candidate_count"] = 0  # but now inconsistent with it
    summary["has_any_ties"] = False  # keep isolated from HAS_ANY_TIES_MISMATCH
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "DISTINCT_SCORE_GROUPS_MISMATCH"


def test_validator_rejects_largest_tie_group_size_when_no_tie_groups() -> None:
    summary = _summarize([10.0, 8.0, 5.0])
    summary["largest_tie_group_size"] = 2  # no tie groups, so must be 1
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "LARGEST_TIE_GROUP_SIZE_MISMATCH"


def test_validator_rejects_largest_tie_group_size_below_two_with_ties() -> None:
    summary = _summarize([10.0, 10.0, 5.0])
    summary["largest_tie_group_size"] = 1  # a tie group exists but size < 2
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "LARGEST_TIE_GROUP_SIZE_MISMATCH"


def test_validator_rejects_largest_tie_group_size_exceeding_tied_count() -> None:
    summary = _summarize([10.0, 10.0, 7.0, 7.0, 3.0])
    summary["largest_tie_group_size"] = 5  # exceeds tied_candidate_count (4)
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "LARGEST_TIE_GROUP_SIZE_MISMATCH"


def test_validator_accepts_unequal_tie_sizes_summary() -> None:
    summary = _summarize([10.0, 10.0, 10.0, 7.0, 7.0, 3.0])
    # Must not raise — exercises the new checks against a real,
    # correctly-derived multi-tie-group summary.
    DifferentialRankingSummaryService._validate_summary(summary)


def test_validator_rejects_score_range_mismatch() -> None:
    summary = {
        "total_candidates": 2,
        "distinct_score_groups": 2,
        "top_rank": 1,
        "highest_score": 10.0,
        "lowest_score": 5.0,
        "score_range": 999.0,  # deliberately wrong
        "tied_candidate_count": 0,
        "tie_group_count": 0,
        "largest_tie_group_size": 1,
        "has_any_ties": False,
    }
    with pytest.raises(DifferentialRankingSummaryContractError) as exc_info:
        DifferentialRankingSummaryService._validate_summary(summary)
    assert exc_info.value.invariant == "SCORE_RANGE_MISMATCH"


# ---------------------------------------------------------------------------
# API integration
# ---------------------------------------------------------------------------


def test_api_differential_summary_endpoint() -> None:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Task 028 summary test",
            "current_stage": "initial",
            "metadata": {"source": "differential-summary-test"},
        },
    )
    assert response.status_code == 201
    session_id = response.json()["id"]

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
    candidate_count = len(generate_response.json())
    assert candidate_count > 0

    evaluate_response = client.post(f"/sessions/{session_id}/evaluate-evidence")
    assert evaluate_response.status_code == 200

    differential_response = client.get(f"/sessions/{session_id}/differential")
    assert differential_response.status_code == 200
    ranked = differential_response.json()

    response = client.get(f"/sessions/{session_id}/differential-summary")
    assert response.status_code == 200
    summary = response.json()

    assert summary["total_candidates"] == candidate_count
    assert summary["top_rank"] == ranked[0]["rank"]
    assert isinstance(summary["distinct_score_groups"], int)
    assert isinstance(summary["tied_candidate_count"], int)
    assert isinstance(summary["tie_group_count"], int)
    assert isinstance(summary["largest_tie_group_size"], int)
    assert isinstance(summary["has_any_ties"], bool)


def test_api_differential_summary_missing_session_returns_404() -> None:
    response = client.get(f"/sessions/{uuid4()}/differential-summary")
    assert response.status_code == 404


def test_api_differential_summary_is_read_only() -> None:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Task 028 read-only test",
            "current_stage": "initial",
            "metadata": {"source": "differential-summary-readonly-test"},
        },
    )
    assert response.status_code == 201
    session_id = response.json()["id"]

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

    evaluate_response = client.post(f"/sessions/{session_id}/evaluate-evidence")
    assert evaluate_response.status_code == 200

    before = client.get(f"/sessions/{session_id}/differential").json()

    response = client.get(f"/sessions/{session_id}/differential-summary")
    assert response.status_code == 200

    after = client.get(f"/sessions/{session_id}/differential").json()
    assert before == after


def test_api_differential_summary_empty_session() -> None:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Task 028 empty session test",
            "current_stage": "initial",
            "metadata": {"source": "differential-summary-empty-test"},
        },
    )
    assert response.status_code == 201
    session_id = response.json()["id"]

    response = client.get(f"/sessions/{session_id}/differential-summary")
    assert response.status_code == 200
    summary = response.json()
    assert summary == {
        "total_candidates": 0,
        "distinct_score_groups": 0,
        "top_rank": None,
        "highest_score": None,
        "lowest_score": None,
        "score_range": None,
        "tied_candidate_count": 0,
        "tie_group_count": 0,
        "largest_tie_group_size": 0,
        "has_any_ties": False,
    }
