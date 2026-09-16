"""Tests for the Task 027 differential ranking structure/separation layer.

Task 027 extends Task 026's ranked entries with derived separation
metadata (``is_tied``, ``tie_group_size``, ``score_gap_to_next_higher``,
``score_gap_to_next_lower``) describing how candidates are separated
from one another by score. It changes nothing about Task 025's scores
or Task 026's ranking/tie-ordering rules — these tests build directly
on the Task 026 test helpers and only add coverage for the new fields.
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
from rop.services.differential_ranking import (
    DifferentialRankingContractError,
    DifferentialRankingService,
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


def _service() -> DifferentialRankingService:
    return DifferentialRankingService(
        HypothesisScoringService(EvidenceAggregationService())
    )


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
    """Build a well-formed Task 025 score-result dict for ranking tests.

    Same shape as the Task 026 test helper — Task 027 consumes ranked
    Task 026 output, not raw evidence, so these tests build directly
    on hand-built Task 025-shaped dicts.
    """
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


def _by_name(ranked: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {entry["hypothesis_name"]: entry for entry in ranked}


_TASK_025_FIELDS = {
    "hypothesis_id",
    "hypothesis_name",
    "hypothesis_score",
    "score_source",
    "score_direction",
    "evidence_consistency",
    "evidence_position",
    "has_evidence",
    "has_mixed_evidence",
    "total_evidence_items",
    "total_support_contribution",
    "total_contradiction_contribution",
    "net_contribution",
    "evidence_coverage_ratio",
    "informative_evidence_ratio",
    "support_to_contradiction_ratio",
}


# ---------------------------------------------------------------------------
# Basic separation: 10, 8, 5
# ---------------------------------------------------------------------------


def test_basic_separation_gaps() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="A", hypothesis_score=10.0),
        _score_result(hypothesis_name="B", hypothesis_score=8.0),
        _score_result(hypothesis_name="C", hypothesis_score=5.0),
    ]

    by_name = _by_name(service.rank_score_results(entries))

    assert by_name["A"]["score_gap_to_next_higher"] is None
    assert by_name["A"]["score_gap_to_next_lower"] == 2.0

    assert by_name["B"]["score_gap_to_next_higher"] == 2.0
    assert by_name["B"]["score_gap_to_next_lower"] == 3.0

    assert by_name["C"]["score_gap_to_next_higher"] == 3.0
    assert by_name["C"]["score_gap_to_next_lower"] is None

    for entry in by_name.values():
        assert entry["is_tied"] is False
        assert entry["tie_group_size"] == 1


# ---------------------------------------------------------------------------
# Highest / lowest candidate boundaries
# ---------------------------------------------------------------------------


def test_highest_candidate_has_no_higher_gap() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="A", hypothesis_score=10.0),
        _score_result(hypothesis_name="B", hypothesis_score=1.0),
    ]
    by_name = _by_name(service.rank_score_results(entries))
    assert by_name["A"]["score_gap_to_next_higher"] is None


def test_lowest_candidate_has_no_lower_gap() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="A", hypothesis_score=10.0),
        _score_result(hypothesis_name="B", hypothesis_score=1.0),
    ]
    by_name = _by_name(service.rank_score_results(entries))
    assert by_name["B"]["score_gap_to_next_lower"] is None


# ---------------------------------------------------------------------------
# Single candidate
# ---------------------------------------------------------------------------


def test_single_candidate_separation_metadata() -> None:
    service = _service()
    ranked = service.rank_score_results(
        [_score_result(hypothesis_name="Solo", hypothesis_score=0.5)]
    )
    entry = ranked[0]
    assert entry["rank"] == 1
    assert entry["is_tied"] is False
    assert entry["tie_group_size"] == 1
    assert entry["score_gap_to_next_higher"] is None
    assert entry["score_gap_to_next_lower"] is None


# ---------------------------------------------------------------------------
# Exact tie: 10, 10, 5
# ---------------------------------------------------------------------------


def test_exact_tie_ranks_and_tie_metadata() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="A", hypothesis_score=10.0),
        _score_result(hypothesis_name="B", hypothesis_score=10.0),
        _score_result(hypothesis_name="C", hypothesis_score=5.0),
    ]
    ranked = service.rank_score_results(entries)
    by_name = _by_name(ranked)

    assert by_name["A"]["rank"] == 1
    assert by_name["B"]["rank"] == 1
    assert by_name["C"]["rank"] == 3

    assert by_name["A"]["tie_group_size"] == 2
    assert by_name["B"]["tie_group_size"] == 2
    assert by_name["C"]["tie_group_size"] == 1

    assert by_name["A"]["is_tied"] is True
    assert by_name["B"]["is_tied"] is True
    assert by_name["C"]["is_tied"] is False


# ---------------------------------------------------------------------------
# Multiple tie groups: 10, 10, 7, 7, 3
# ---------------------------------------------------------------------------


def test_multiple_tie_groups() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="A", hypothesis_score=10.0),
        _score_result(hypothesis_name="B", hypothesis_score=10.0),
        _score_result(hypothesis_name="C", hypothesis_score=7.0),
        _score_result(hypothesis_name="D", hypothesis_score=7.0),
        _score_result(hypothesis_name="E", hypothesis_score=3.0),
    ]
    ranked = service.rank_score_results(entries)
    by_name = _by_name(ranked)

    assert by_name["A"]["rank"] == 1
    assert by_name["B"]["rank"] == 1
    assert by_name["C"]["rank"] == 3
    assert by_name["D"]["rank"] == 3
    assert by_name["E"]["rank"] == 5

    assert by_name["A"]["tie_group_size"] == 2
    assert by_name["C"]["tie_group_size"] == 2
    assert by_name["E"]["tie_group_size"] == 1

    # 10-group: no higher gap, lower gap skips to 7.
    assert by_name["A"]["score_gap_to_next_higher"] is None
    assert by_name["A"]["score_gap_to_next_lower"] == 3.0
    # 7-group: higher gap skips to 10, lower gap skips to 3.
    assert by_name["C"]["score_gap_to_next_higher"] == 3.0
    assert by_name["C"]["score_gap_to_next_lower"] == 4.0
    # 3: higher gap skips to 7, no lower gap.
    assert by_name["E"]["score_gap_to_next_higher"] == 4.0
    assert by_name["E"]["score_gap_to_next_lower"] is None


# ---------------------------------------------------------------------------
# Tie-gap skipping: 10, 10, 7 — both 10s must see gap 3, never 0
# ---------------------------------------------------------------------------


def test_tied_candidates_skip_own_tie_group_for_gap() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="A", hypothesis_score=10.0),
        _score_result(hypothesis_name="B", hypothesis_score=10.0),
        _score_result(hypothesis_name="C", hypothesis_score=7.0),
    ]
    by_name = _by_name(service.rank_score_results(entries))

    assert by_name["A"]["score_gap_to_next_lower"] == 3.0
    assert by_name["B"]["score_gap_to_next_lower"] == 3.0
    assert by_name["A"]["score_gap_to_next_higher"] is None
    assert by_name["B"]["score_gap_to_next_higher"] is None


# ---------------------------------------------------------------------------
# Negative scores: 2, -1, -4
# ---------------------------------------------------------------------------


def test_negative_scores_separation() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="A", hypothesis_score=2.0),
        _score_result(hypothesis_name="B", hypothesis_score=-1.0),
        _score_result(hypothesis_name="C", hypothesis_score=-4.0),
    ]
    by_name = _by_name(service.rank_score_results(entries))

    assert by_name["A"]["score_gap_to_next_lower"] == 3.0
    assert by_name["B"]["score_gap_to_next_higher"] == 3.0
    assert by_name["B"]["score_gap_to_next_lower"] == 3.0
    assert by_name["C"]["score_gap_to_next_higher"] == 3.0
    assert by_name["C"]["score_gap_to_next_lower"] is None
    assert by_name["A"]["score_gap_to_next_higher"] is None


# ---------------------------------------------------------------------------
# Zero scores: 5, 0, 0, -2
# ---------------------------------------------------------------------------


def test_zero_scores_separation() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="A", hypothesis_score=5.0),
        _score_result(
            hypothesis_name="B",
            hypothesis_score=0.0,
            evidence_consistency="MIXED",
            evidence_position="MIXED",
            has_mixed_evidence=True,
        ),
        _score_result(
            hypothesis_name="C",
            hypothesis_score=0.0,
            total_evidence_items=0,
            total_support_contribution=0.0,
            total_contradiction_contribution=0.0,
            evidence_consistency="NO_EVIDENCE",
            has_evidence=False,
            evidence_coverage_ratio=0.0,
            informative_evidence_ratio=0.0,
            evidence_position="UNSUPPORTED",
        ),
        _score_result(hypothesis_name="D", hypothesis_score=-2.0),
    ]
    by_name = _by_name(service.rank_score_results(entries))

    assert by_name["B"]["is_tied"] is True
    assert by_name["C"]["is_tied"] is True
    assert by_name["B"]["tie_group_size"] == 2
    assert by_name["B"]["score_gap_to_next_higher"] == 5.0
    assert by_name["B"]["score_gap_to_next_lower"] == 2.0
    assert by_name["C"]["score_gap_to_next_higher"] == 5.0
    assert by_name["C"]["score_gap_to_next_lower"] == 2.0
    assert by_name["A"]["score_gap_to_next_higher"] is None
    assert by_name["D"]["score_gap_to_next_lower"] is None


# ---------------------------------------------------------------------------
# Equal-score all candidates: 5, 5, 5
# ---------------------------------------------------------------------------


def test_all_candidates_tied() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="A", hypothesis_score=5.0),
        _score_result(hypothesis_name="B", hypothesis_score=5.0),
        _score_result(hypothesis_name="C", hypothesis_score=5.0),
    ]
    ranked = service.rank_score_results(entries)

    assert [entry["rank"] for entry in ranked] == [1, 1, 1]
    for entry in ranked:
        assert entry["is_tied"] is True
        assert entry["tie_group_size"] == 3
        assert entry["score_gap_to_next_higher"] is None
        assert entry["score_gap_to_next_lower"] is None


# ---------------------------------------------------------------------------
# Deterministic tie ordering is unchanged from Task 026
# ---------------------------------------------------------------------------


def test_deterministic_tie_ordering_matches_task_026() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="pneumonia", hypothesis_score=0.5),
        _score_result(hypothesis_name="ACS", hypothesis_score=0.5),
        _score_result(hypothesis_name="aortic dissection", hypothesis_score=0.5),
    ]

    ranked_once = service.rank_score_results(entries)
    ranked_again = service.rank_score_results(list(reversed(entries)))

    names_once = [entry["hypothesis_name"] for entry in ranked_once]
    names_again = [entry["hypothesis_name"] for entry in ranked_again]
    assert names_once == ["ACS", "aortic dissection", "pneumonia"]
    assert names_again == names_once


# ---------------------------------------------------------------------------
# Precision: avoid floating-point artifacts
# ---------------------------------------------------------------------------


def test_score_gap_precision_has_no_floating_point_artifacts() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="A", hypothesis_score=0.1),
        _score_result(hypothesis_name="B", hypothesis_score=-2.9),
    ]
    by_name = _by_name(service.rank_score_results(entries))

    gap = by_name["A"]["score_gap_to_next_lower"]
    assert gap == 3.0
    assert round(gap, 4) == gap


def test_four_decimal_precision_scores() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="A", hypothesis_score=0.5678),
        _score_result(hypothesis_name="B", hypothesis_score=0.1234),
    ]
    by_name = _by_name(service.rank_score_results(entries))

    gap = by_name["A"]["score_gap_to_next_lower"]
    assert gap == 0.4444
    assert round(gap, 4) == gap


# ---------------------------------------------------------------------------
# Empty session
# ---------------------------------------------------------------------------


def test_empty_session_returns_empty_list() -> None:
    service = _service()
    assert service.rank_score_results([]) == []


# ---------------------------------------------------------------------------
# Zero-evidence hypotheses remain present with separation metadata
# ---------------------------------------------------------------------------


def test_zero_evidence_hypothesis_gets_separation_metadata() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="ACS", hypothesis_score=0.5),
        _score_result(
            hypothesis_name="Pneumonia",
            hypothesis_score=0.0,
            total_evidence_items=0,
            total_support_contribution=0.0,
            total_contradiction_contribution=0.0,
            evidence_consistency="NO_EVIDENCE",
            has_evidence=False,
            evidence_coverage_ratio=0.0,
            informative_evidence_ratio=0.0,
            evidence_position="UNSUPPORTED",
        ),
    ]
    by_name = _by_name(service.rank_score_results(entries))

    pneumonia = by_name["Pneumonia"]
    assert pneumonia["total_evidence_items"] == 0
    assert pneumonia["is_tied"] is False
    assert pneumonia["tie_group_size"] == 1
    assert pneumonia["score_gap_to_next_higher"] == 0.5
    assert pneumonia["score_gap_to_next_lower"] is None


# ---------------------------------------------------------------------------
# Task 025/026 fields remain present and unchanged
# ---------------------------------------------------------------------------


def test_task_025_and_026_fields_preserved() -> None:
    service = _service()
    original = _score_result(
        hypothesis_name="ACS",
        hypothesis_score=0.5678,
        total_evidence_items=3,
        total_support_contribution=0.9,
        total_contradiction_contribution=0.3322,
        evidence_consistency="MIXED",
        has_evidence=True,
        has_mixed_evidence=True,
        informative_evidence_ratio=0.75,
        support_to_contradiction_ratio=2.7108,
        evidence_position="MIXED",
    )

    ranked = service.rank_score_results([original])
    entry = ranked[0]

    for field in _TASK_025_FIELDS:
        assert entry[field] == original[field]
    assert entry["rank"] == 1
    assert set(entry.keys()) == _TASK_025_FIELDS | {
        "rank",
        "is_tied",
        "tie_group_size",
        "score_gap_to_next_higher",
        "score_gap_to_next_lower",
    }


# ---------------------------------------------------------------------------
# Contract validation: internally inconsistent separation metadata raises
# ---------------------------------------------------------------------------


def test_validator_raises_on_is_tied_type_mismatch() -> None:
    ranked = [
        {
            "hypothesis_id": uuid4(),
            "hypothesis_name": "A",
            "hypothesis_score": 1.0,
            "rank": 1,
            "is_tied": "yes",  # deliberately not a bool
            "tie_group_size": 1,
            "score_gap_to_next_higher": None,
            "score_gap_to_next_lower": None,
        }
    ]
    with pytest.raises(DifferentialRankingContractError) as exc_info:
        DifferentialRankingService._validate_separation_metadata(ranked)
    assert exc_info.value.invariant == "IS_TIED_TYPE"


def test_validator_raises_on_tie_group_size_below_one() -> None:
    ranked = [
        {
            "hypothesis_id": uuid4(),
            "hypothesis_name": "A",
            "hypothesis_score": 1.0,
            "rank": 1,
            "is_tied": False,
            "tie_group_size": 0,
            "score_gap_to_next_higher": None,
            "score_gap_to_next_lower": None,
        }
    ]
    with pytest.raises(DifferentialRankingContractError) as exc_info:
        DifferentialRankingService._validate_separation_metadata(ranked)
    assert exc_info.value.invariant == "TIE_GROUP_SIZE_BOUNDS"


def test_validator_raises_when_is_tied_true_but_group_size_one() -> None:
    ranked = [
        {
            "hypothesis_id": uuid4(),
            "hypothesis_name": "A",
            "hypothesis_score": 1.0,
            "rank": 1,
            "is_tied": True,
            "tie_group_size": 1,
            "score_gap_to_next_higher": None,
            "score_gap_to_next_lower": None,
        }
    ]
    with pytest.raises(DifferentialRankingContractError) as exc_info:
        DifferentialRankingService._validate_separation_metadata(ranked)
    assert exc_info.value.invariant == "TIE_GROUP_SIZE_CONSISTENCY"


def test_validator_raises_on_boundary_violation_for_highest_score() -> None:
    ranked = [
        {
            "hypothesis_id": uuid4(),
            "hypothesis_name": "A",
            "hypothesis_score": 1.0,
            "rank": 1,
            "is_tied": False,
            "tie_group_size": 1,
            # Deliberately non-None at the highest distinct score.
            "score_gap_to_next_higher": 5.0,
            "score_gap_to_next_lower": None,
        }
    ]
    with pytest.raises(DifferentialRankingContractError) as exc_info:
        DifferentialRankingService._validate_separation_metadata(ranked)
    assert exc_info.value.invariant == "SCORE_GAP_BOUNDARY"


def test_validator_raises_on_negative_gap() -> None:
    ranked = [
        {
            "hypothesis_id": uuid4(),
            "hypothesis_name": "A",
            "hypothesis_score": 5.0,
            "rank": 1,
            "is_tied": False,
            "tie_group_size": 1,
            "score_gap_to_next_higher": None,
            "score_gap_to_next_lower": -1.0,
        },
        {
            "hypothesis_id": uuid4(),
            "hypothesis_name": "B",
            "hypothesis_score": 1.0,
            "rank": 2,
            "is_tied": False,
            "tie_group_size": 1,
            "score_gap_to_next_higher": 4.0,
            "score_gap_to_next_lower": None,
        },
    ]
    with pytest.raises(DifferentialRankingContractError) as exc_info:
        DifferentialRankingService._validate_separation_metadata(ranked)
    assert exc_info.value.invariant == "SCORE_GAP_NEGATIVE"


def test_validator_accepts_well_formed_separation_metadata() -> None:
    service = _service()
    ranked = service.rank_score_results(
        [
            _score_result(hypothesis_name="A", hypothesis_score=5.0),
            _score_result(hypothesis_name="B", hypothesis_score=1.0),
        ]
    )
    # Must not raise.
    DifferentialRankingService._validate_separation_metadata(ranked)


# ---------------------------------------------------------------------------
# API: /differential now exposes separation metadata
# ---------------------------------------------------------------------------


def test_api_differential_response_includes_separation_metadata() -> None:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Task 027 structure test",
            "current_stage": "initial",
            "metadata": {"source": "differential-structure-test"},
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

    response = client.get(f"/sessions/{session_id}/differential")
    assert response.status_code == 200
    ranked = response.json()
    assert len(ranked) == candidate_count

    for entry in ranked:
        assert isinstance(entry["is_tied"], bool)
        assert entry["tie_group_size"] >= 1
        assert entry["score_gap_to_next_higher"] is None or isinstance(
            entry["score_gap_to_next_higher"], (int, float)
        )
        assert entry["score_gap_to_next_lower"] is None or isinstance(
            entry["score_gap_to_next_lower"], (int, float)
        )
