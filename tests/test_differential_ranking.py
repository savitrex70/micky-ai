"""Tests for the Task 026 differential ranking layer.

Task 026 is the first ROP layer allowed to compare hypotheses against
one another — but only their already-computed, unchanged Task 025
``hypothesis_score`` values. These tests exercise the ranking
invariants directly against hand-built Task 025 score-result dicts
(``DifferentialRankingService.rank_score_results``), through the
service's end-to-end path over real persisted evidence
(``rank_session``), and through the read-only ``/differential`` API.
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
from rop.evidence_evaluation.models import EvidenceRelationship
from rop.main import app
from rop.models import EvaluatedEvidence
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


class _Candidate:
    """Minimal stand-in for a CandidateHypothesis: just id and name."""

    def __init__(self, id_: UUID, name: str) -> None:
        self.id = id_
        self.name = name


def _evidence(
    session_id: UUID,
    hypothesis_id: UUID,
    *,
    relationship: EvidenceRelationship,
    contribution: float = 0.5,
    rule_id: str = "test_rule",
) -> EvaluatedEvidence:
    return EvaluatedEvidence(
        session_id=session_id,
        hypothesis_id=hypothesis_id,
        rule_id=rule_id,
        relationship=relationship.value,
        weight=0.5,
        confidence=0.8,
        matched_finding_count=1,
        total_finding_count=2,
        match_strength=0.5,
        contribution=contribution,
        contributing_observation_ids=[],
        contributing_entity_ids=[],
        reason="test",
        source="unit_test",
    )


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

    Ranking consumes already-produced Task 025 results, so these tests
    exercise ``DifferentialRankingService`` directly against hand-built
    dicts in this same shape rather than re-deriving them from evidence
    every time.
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


_CONTRACT_FIELDS = {
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
# 1. Single candidate
# ---------------------------------------------------------------------------


def test_single_candidate_gets_rank_one() -> None:
    service = _service()
    result = service.rank_score_results(
        [_score_result(hypothesis_name="Solo", hypothesis_score=0.3)]
    )

    assert len(result) == 1
    assert result[0]["rank"] == 1


# ---------------------------------------------------------------------------
# 2-3. Multiple candidates, descending score order
# ---------------------------------------------------------------------------


def test_highest_score_gets_rank_one_and_order_is_descending() -> None:
    service = _service()
    acs = _score_result(hypothesis_name="ACS", hypothesis_score=0.8)
    pe = _score_result(hypothesis_name="PE", hypothesis_score=0.4)
    pneumonia = _score_result(hypothesis_name="Pneumonia", hypothesis_score=-0.1)

    ranked = service.rank_score_results([pneumonia, acs, pe])

    assert [entry["hypothesis_name"] for entry in ranked] == ["ACS", "PE", "Pneumonia"]
    assert [entry["rank"] for entry in ranked] == [1, 2, 3]
    scores = [entry["hypothesis_score"] for entry in ranked]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 4-5. Negative and zero scores are allowed
# ---------------------------------------------------------------------------


def test_negative_score_is_allowed_and_ranked() -> None:
    service = _service()
    ranked = service.rank_score_results(
        [
            _score_result(hypothesis_name="Positive", hypothesis_score=0.2),
            _score_result(hypothesis_name="Negative", hypothesis_score=-0.5),
        ]
    )
    negative_entry = next(e for e in ranked if e["hypothesis_name"] == "Negative")
    assert negative_entry["hypothesis_score"] == -0.5
    assert negative_entry["rank"] == 2


def test_zero_score_is_allowed_and_ranked() -> None:
    service = _service()
    ranked = service.rank_score_results(
        [
            _score_result(hypothesis_name="Positive", hypothesis_score=0.2),
            _score_result(hypothesis_name="Zero", hypothesis_score=0.0),
        ]
    )
    zero_entry = next(e for e in ranked if e["hypothesis_name"] == "Zero")
    assert zero_entry["hypothesis_score"] == 0.0
    assert zero_entry["rank"] == 2


# ---------------------------------------------------------------------------
# 6. Zero-evidence candidates remain present and are ranked by score
# ---------------------------------------------------------------------------


def test_zero_evidence_candidate_remains_in_ranking() -> None:
    service = _service()
    acs = _score_result(
        hypothesis_name="ACS", hypothesis_score=0.5, total_evidence_items=1
    )
    pe = _score_result(
        hypothesis_name="PE",
        hypothesis_score=0.0,
        total_evidence_items=1,
        evidence_consistency="MIXED",
        evidence_position="MIXED",
        has_evidence=True,
        has_mixed_evidence=True,
    )
    pneumonia = _score_result(
        hypothesis_name="Pneumonia",
        hypothesis_score=0.0,
        total_evidence_items=0,
        total_support_contribution=0.0,
        total_contradiction_contribution=0.0,
        evidence_consistency="NO_EVIDENCE",
        has_evidence=False,
        has_mixed_evidence=False,
        evidence_coverage_ratio=0.0,
        informative_evidence_ratio=0.0,
        support_to_contradiction_ratio=None,
        evidence_position="UNSUPPORTED",
    )
    tb = _score_result(hypothesis_name="TB", hypothesis_score=-0.2)

    ranked = service.rank_score_results([acs, pe, pneumonia, tb])

    names_in_order = [entry["hypothesis_name"] for entry in ranked]
    assert set(names_in_order) == {"ACS", "PE", "Pneumonia", "TB"}

    pneumonia_entry = next(e for e in ranked if e["hypothesis_name"] == "Pneumonia")
    assert pneumonia_entry["total_evidence_items"] == 0
    assert pneumonia_entry["evidence_consistency"] == "NO_EVIDENCE"

    by_name = {entry["hypothesis_name"]: entry["rank"] for entry in ranked}
    assert by_name["ACS"] == 1
    assert by_name["PE"] == 2
    assert by_name["Pneumonia"] == 2
    assert by_name["TB"] == 4


# ---------------------------------------------------------------------------
# 7-8. Equal-score ties share a rank; competition ranking, not dense
# ---------------------------------------------------------------------------


def test_tied_scores_receive_competition_ranking_not_dense() -> None:
    service = _service()
    acs = _score_result(hypothesis_name="ACS", hypothesis_score=0.8)
    pe = _score_result(hypothesis_name="PE", hypothesis_score=0.5)
    dissection = _score_result(
        hypothesis_name="Aortic Dissection", hypothesis_score=0.5
    )
    pneumonia = _score_result(hypothesis_name="Pneumonia", hypothesis_score=0.1)

    ranked = service.rank_score_results([acs, pe, dissection, pneumonia])
    by_name = {entry["hypothesis_name"]: entry["rank"] for entry in ranked}

    assert by_name["ACS"] == 1
    assert by_name["PE"] == 2
    assert by_name["Aortic Dissection"] == 2
    assert (
        by_name["Pneumonia"] == 4
    )  # competition ranking: 1, 2, 2, 4 — never 1, 2, 2, 3


# ---------------------------------------------------------------------------
# 9-10. Deterministic, case-insensitive secondary ordering for ties
# ---------------------------------------------------------------------------


def test_tied_scores_are_ordered_alphabetically_case_insensitive() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name="pneumonia", hypothesis_score=0.5),
        _score_result(hypothesis_name="ACS", hypothesis_score=0.5),
        _score_result(hypothesis_name="aortic dissection", hypothesis_score=0.5),
    ]

    ranked = service.rank_score_results(entries)

    assert [entry["hypothesis_name"] for entry in ranked] == [
        "ACS",
        "aortic dissection",
        "pneumonia",
    ]
    assert [entry["rank"] for entry in ranked] == [1, 1, 1]

    # Deterministic across repeated calls, not dependent on input order.
    reordered = service.rank_score_results(list(reversed(entries)))
    assert [entry["hypothesis_name"] for entry in reordered] == [
        "ACS",
        "aortic dissection",
        "pneumonia",
    ]


# ---------------------------------------------------------------------------
# 11. ID-based tie-break when names are identical (case-insensitively)
# ---------------------------------------------------------------------------


def test_identical_names_fall_back_to_hypothesis_id_ordering() -> None:
    service = _service()
    id_low = UUID("00000000-0000-0000-0000-000000000001")
    id_high = UUID("00000000-0000-0000-0000-000000000002")
    entry_high_id = _score_result(
        hypothesis_name="ACS", hypothesis_score=0.5, hypothesis_id=id_high
    )
    entry_low_id = _score_result(
        hypothesis_name="acs", hypothesis_score=0.5, hypothesis_id=id_low
    )

    ranked = service.rank_score_results([entry_high_id, entry_low_id])

    assert [entry["hypothesis_id"] for entry in ranked] == [id_low, id_high]
    assert [entry["rank"] for entry in ranked] == [1, 1]


# ---------------------------------------------------------------------------
# 12-13. Score fields preserved exactly; candidate count preserved
# ---------------------------------------------------------------------------


def test_task_025_fields_preserved_exactly() -> None:
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
        evidence_coverage_ratio=1.0,
        informative_evidence_ratio=0.75,
        support_to_contradiction_ratio=2.7108,
        evidence_position="MIXED",
    )

    ranked = service.rank_score_results([original])
    entry = ranked[0]

    for field in _CONTRACT_FIELDS:
        assert entry[field] == original[field]
    assert entry["rank"] == 1
    # The original dict must not have been mutated in place.
    assert "rank" not in original


def test_candidate_count_and_unique_ids_preserved() -> None:
    service = _service()
    entries = [
        _score_result(hypothesis_name=f"Hypothesis {i}", hypothesis_score=float(i))
        for i in range(5)
    ]
    original_ids = {entry["hypothesis_id"] for entry in entries}

    ranked = service.rank_score_results(entries)

    assert len(ranked) == 5
    assert {entry["hypothesis_id"] for entry in ranked} == original_ids


# ---------------------------------------------------------------------------
# 14. No candidates returns []
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_list() -> None:
    service = _service()
    assert service.rank_score_results([]) == []


# ---------------------------------------------------------------------------
# 17. Invalid ranking input raises an internal contract error
# ---------------------------------------------------------------------------


def test_duplicate_hypothesis_id_raises_contract_error() -> None:
    service = _service()
    shared_id = uuid4()
    entries = [
        _score_result(
            hypothesis_name="ACS", hypothesis_score=0.5, hypothesis_id=shared_id
        ),
        _score_result(
            hypothesis_name="PE", hypothesis_score=0.3, hypothesis_id=shared_id
        ),
    ]

    with pytest.raises(DifferentialRankingContractError) as exc_info:
        service.rank_score_results(entries)

    assert exc_info.value.invariant == "DUPLICATE_HYPOTHESIS_ID"


def test_non_numeric_score_raises_contract_error() -> None:
    service = _service()
    broken = _score_result(hypothesis_name="ACS", hypothesis_score=0.5)
    broken["hypothesis_score"] = "not-a-number"

    with pytest.raises(DifferentialRankingContractError) as exc_info:
        service.rank_score_results([broken])

    assert exc_info.value.invariant == "NON_NUMERIC_SCORE"


def test_unrounded_score_raises_contract_error() -> None:
    service = _service()
    broken = _score_result(hypothesis_name="ACS", hypothesis_score=0.5)
    broken["hypothesis_score"] = 0.123456789

    with pytest.raises(DifferentialRankingContractError) as exc_info:
        service.rank_score_results([broken])

    assert exc_info.value.invariant == "ROUNDING_PRECISION"


def test_missing_hypothesis_id_raises_contract_error() -> None:
    service = _service()
    broken = _score_result(hypothesis_name="ACS", hypothesis_score=0.5)
    broken["hypothesis_id"] = None

    with pytest.raises(DifferentialRankingContractError) as exc_info:
        service.rank_score_results([broken])

    assert exc_info.value.invariant == "MISSING_HYPOTHESIS_ID"


# ---------------------------------------------------------------------------
# End-to-end service test over real persisted evidence (no API layer)
# ---------------------------------------------------------------------------


def test_rank_session_consumes_task_025_scores_without_recomputation() -> None:
    service = _service()
    session_id = uuid4()
    low_scoring = _Candidate(uuid4(), "Low scoring")
    high_scoring = _Candidate(uuid4(), "High scoring")
    no_evidence = _Candidate(uuid4(), "No evidence")
    candidates = [low_scoring, high_scoring, no_evidence]

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                low_scoring.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.9,
            )
        )
        db.add(
            _evidence(
                session_id,
                high_scoring.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.9,
                rule_id="rule_2",
            )
        )
        db.commit()

        ranked = service.rank_session(db, session_id, candidates)

    assert [entry["hypothesis_id"] for entry in ranked] == [
        high_scoring.id,
        no_evidence.id,
        low_scoring.id,
    ]
    assert [entry["rank"] for entry in ranked] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 15-16, 18. API: unknown session 404s, ranking is read-only
# ---------------------------------------------------------------------------


def _create_session() -> str:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Differential ranking test",
            "current_stage": "initial",
            "metadata": {"source": "differential-ranking-test"},
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _add_observation(session_id: str, text: str, type_: str = "symptom") -> None:
    response = client.post(
        f"/sessions/{session_id}/observations",
        json={
            "text": text,
            "type": type_,
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert response.status_code == 201


def test_api_returns_ranked_differential_with_contract_fields() -> None:
    session_id = _create_session()
    _add_observation(session_id, "Patient reports chest pain")
    _add_observation(session_id, "Pain radiates to left arm")

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
        assert _CONTRACT_FIELDS.issubset(entry.keys())
        assert "rank" in entry

    scores = [entry["hypothesis_score"] for entry in ranked]
    assert scores == sorted(scores, reverse=True)

    # Every candidate hypothesis from generation is still present.
    candidate_ids = {c["id"] for c in generate_response.json()}
    ranked_ids = {entry["hypothesis_id"] for entry in ranked}
    assert ranked_ids == candidate_ids


def test_api_differential_response_exposes_score_source() -> None:
    """Regression: ``score_source`` was carried internally by the
    ranking service since Task 026 but was missing from
    ``DifferentialRankRead``, so it never reached the actual HTTP
    response despite ``_CONTRACT_FIELDS`` claiming full preservation.
    This asserts the live response, not just the service-level dict.
    """
    session_id = _create_session()
    _add_observation(session_id, "Patient reports chest pain")

    generate_response = client.post(f"/sessions/{session_id}/generate-candidates")
    assert generate_response.status_code == 201

    evaluate_response = client.post(f"/sessions/{session_id}/evaluate-evidence")
    assert evaluate_response.status_code == 200

    response = client.get(f"/sessions/{session_id}/differential")
    assert response.status_code == 200
    ranked = response.json()
    assert len(ranked) > 0

    for entry in ranked:
        assert entry["score_source"] == SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION


def test_api_differential_endpoint_is_read_only() -> None:
    session_id = _create_session()
    _add_observation(session_id, "Patient reports chest pain")
    client.post(f"/sessions/{session_id}/generate-candidates")
    client.post(f"/sessions/{session_id}/evaluate-evidence")

    with TestingSessionLocal() as db:
        before_count = (
            db.query(EvaluatedEvidence)
            .filter(EvaluatedEvidence.session_id == UUID(session_id))
            .count()
        )

    first = client.get(f"/sessions/{session_id}/differential")
    second = client.get(f"/sessions/{session_id}/differential")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    with TestingSessionLocal() as db:
        after_count = (
            db.query(EvaluatedEvidence)
            .filter(EvaluatedEvidence.session_id == UUID(session_id))
            .count()
        )
    assert after_count == before_count


def test_api_differential_unknown_session_returns_404() -> None:
    response = client.get(f"/sessions/{uuid4()}/differential")
    assert response.status_code == 404


def test_api_differential_no_candidates_returns_empty_list() -> None:
    session_id = _create_session()
    response = client.get(f"/sessions/{session_id}/differential")
    assert response.status_code == 200
    assert response.json() == []
