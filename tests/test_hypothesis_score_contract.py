"""Tests for the Task 025 hypothesis-score contract.

Task 025 introduces no new scoring formula: it formalizes the Task
023/024 fields into a single stable "hypothesis-score contract" and
adds ``HypothesisScoringService._validate_score_result`` to catch
architectural regressions before a result ever leaves the service.
These tests exercise the contract invariants directly (via
``score_session``/``_validate_score_result``) and end-to-end through
the read-only ``/hypothesis-scores`` API.
"""

from __future__ import annotations

from collections.abc import Generator
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
from rop.services.evidence_aggregation import EvidenceAggregationService
from rop.services.hypothesis_scoring import (
    SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
    HypothesisScoreContractError,
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


def _service() -> HypothesisScoringService:
    return HypothesisScoringService(EvidenceAggregationService())


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
    "support_to_contradiction_ratio",
    "evidence_coverage_ratio",
    "informative_evidence_ratio",
}


# ---------------------------------------------------------------------------
# 1. Score equals net contribution
# ---------------------------------------------------------------------------


def test_hypothesis_score_equals_net_contribution() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.8,
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.3,
                rule_id="rule_2",
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["hypothesis_score"] == entry["net_contribution"]


# ---------------------------------------------------------------------------
# 2. Score source constant
# ---------------------------------------------------------------------------


def test_score_source_constant_is_correct() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["score_source"] == "NET_EVIDENCE_CONTRIBUTION"
    assert entry["score_source"] == SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION


# ---------------------------------------------------------------------------
# 3-5. Score direction
# ---------------------------------------------------------------------------


def test_positive_score_direction() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.8,
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.3,
                rule_id="rule_2",
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["hypothesis_score"] == 0.5
    assert entry["score_direction"] == "POSITIVE"


def test_negative_score_direction() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.2,
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.7,
                rule_id="rule_2",
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["hypothesis_score"] == -0.5
    assert entry["score_direction"] == "NEGATIVE"


def test_zero_score_direction() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["hypothesis_score"] == 0.0
    assert entry["score_direction"] == "ZERO"


# ---------------------------------------------------------------------------
# 6. Support/contradiction relationship consistency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("support", "contradiction", "expected_direction"),
    [
        (0.9, 0.1, "POSITIVE"),
        (0.1, 0.9, "NEGATIVE"),
        (0.4, 0.4, "ZERO"),
    ],
)
def test_support_contradiction_relationship_is_consistent(
    support: float, contradiction: float, expected_direction: str
) -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=support,
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=contradiction,
                rule_id="rule_2",
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["score_direction"] == expected_direction
    if support > contradiction:
        assert entry["hypothesis_score"] > 0
    elif support < contradiction:
        assert entry["hypothesis_score"] < 0
    else:
        assert entry["hypothesis_score"] == 0


# ---------------------------------------------------------------------------
# 7. Evidence consistency preserved from Task 022
# ---------------------------------------------------------------------------


def test_evidence_consistency_preserved_from_task_022() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.6,
            )
        )
        db.commit()

        analysis = EvidenceAggregationService().analyze_session_consistency(
            db, session_id, candidates=[candidate]
        )[0]
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["evidence_consistency"] == analysis["evidence_consistency"]
    assert entry["evidence_consistency"] == "SUPPORT_ONLY"


# ---------------------------------------------------------------------------
# 8. Evidence position preserved from Task 024
# ---------------------------------------------------------------------------


def test_evidence_position_preserved_from_task_024() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.6,
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    # evidence_position derives from evidence_consistency, never from
    # the score itself.
    assert entry["evidence_consistency"] == "CONTRADICTION_ONLY"
    assert entry["evidence_position"] == "CONTRADICTED"


# ---------------------------------------------------------------------------
# 9. Complete zero-evidence contract
# ---------------------------------------------------------------------------


def test_complete_zero_evidence_contract() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["hypothesis_score"] == 0.0
    assert entry["net_contribution"] == 0.0
    assert entry["score_direction"] == "ZERO"
    assert entry["evidence_consistency"] == "NO_EVIDENCE"
    assert entry["evidence_position"] == "UNSUPPORTED"
    assert entry["has_evidence"] is False
    assert entry["has_mixed_evidence"] is False
    assert entry["evidence_coverage_ratio"] == 0.0
    assert entry["informative_evidence_ratio"] == 0.0
    assert entry["support_to_contradiction_ratio"] is None


# ---------------------------------------------------------------------------
# 10. Complete mixed-zero-score contract
# ---------------------------------------------------------------------------


def test_complete_mixed_zero_score_contract() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.5,
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.5,
                rule_id="rule_2",
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["hypothesis_score"] == 0.0
    assert entry["score_direction"] == "ZERO"
    assert entry["evidence_consistency"] == "MIXED"
    assert entry["evidence_position"] == "MIXED"
    assert entry["has_evidence"] is True
    assert entry["has_mixed_evidence"] is True
    assert entry["evidence_coverage_ratio"] == 1.0
    assert entry["informative_evidence_ratio"] > 0
    assert entry["support_to_contradiction_ratio"] == 1.0


# ---------------------------------------------------------------------------
# 11. Ratio bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("relationship", "contribution"),
    [
        (EvidenceRelationship.SUPPORTS, 0.9),
        (EvidenceRelationship.CONTRADICTS, 0.9),
        (EvidenceRelationship.NEUTRAL, 0.0),
    ],
)
def test_ratio_bounds_hold_across_evidence_shapes(
    relationship: EvidenceRelationship, contribution: float
) -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=relationship,
                contribution=contribution,
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    assert 0.0 <= entry["evidence_coverage_ratio"] <= 1.0
    assert 0.0 <= entry["informative_evidence_ratio"] <= 1.0
    if entry["support_to_contradiction_ratio"] is not None:
        assert entry["support_to_contradiction_ratio"] >= 0.0


# ---------------------------------------------------------------------------
# 12. Support-to-contradiction ratio null behavior
# ---------------------------------------------------------------------------


def test_support_to_contradiction_ratio_is_null_with_zero_contradiction() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.5,
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["total_contradiction_contribution"] == 0.0
    assert entry["support_to_contradiction_ratio"] is None


# ---------------------------------------------------------------------------
# 13. Four-decimal precision
# ---------------------------------------------------------------------------


def test_four_decimal_precision_on_all_numeric_fields() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.123456789,
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.098765432,
                rule_id="rule_2",
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    for field_name in (
        "hypothesis_score",
        "net_contribution",
        "total_support_contribution",
        "total_contradiction_contribution",
        "evidence_coverage_ratio",
        "informative_evidence_ratio",
    ):
        value = entry[field_name]
        assert round(value, 4) == value, field_name

    ratio = entry["support_to_contradiction_ratio"]
    if ratio is not None:
        assert round(ratio, 4) == ratio


# ---------------------------------------------------------------------------
# 14. Candidate order is preserved
# ---------------------------------------------------------------------------


def test_candidate_order_is_preserved_not_sorted_by_score() -> None:
    service = _service()
    session_id = uuid4()
    low_scoring = _Candidate(uuid4(), "Low scoring, listed first")
    high_scoring = _Candidate(uuid4(), "High scoring, listed second")
    candidates = [low_scoring, high_scoring]

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

        entries = service.score_session(db, session_id, candidates)

    assert [entry["hypothesis_id"] for entry in entries] == [
        low_scoring.id,
        high_scoring.id,
    ]
    assert entries[0]["hypothesis_score"] < entries[1]["hypothesis_score"]
    for entry in entries:
        assert "rank" not in entry


# ---------------------------------------------------------------------------
# 15. Multiple hypotheses remain independent
# ---------------------------------------------------------------------------


def test_multiple_hypotheses_remain_independent() -> None:
    service = _service()
    session_id = uuid4()
    candidate_a = _Candidate(uuid4(), "Hypothesis A")
    candidate_b = _Candidate(uuid4(), "Hypothesis B")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate_a.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.7,
            )
        )
        db.commit()

        entries = service.score_session(db, session_id, [candidate_a, candidate_b])

    entry_a, entry_b = entries
    assert entry_a["hypothesis_score"] == 0.7
    assert entry_a["has_evidence"] is True
    assert entry_b["hypothesis_score"] == 0.0
    assert entry_b["has_evidence"] is False


# ---------------------------------------------------------------------------
# Validator: deliberately inconsistent input must raise, not correct
# ---------------------------------------------------------------------------


def test_validator_raises_on_internally_inconsistent_result() -> None:
    inconsistent_result = {
        "hypothesis_id": uuid4(),
        "hypothesis_name": "Broken Hypothesis",
        "hypothesis_score": 0.5,
        "score_source": SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
        "evidence_consistency": "SUPPORT_ONLY",
        "total_evidence_items": 1,
        "total_support_contribution": 0.5,
        "total_contradiction_contribution": 0.5,
        # net_contribution deliberately disagrees with hypothesis_score.
        "net_contribution": 0.0,
        "has_evidence": True,
        "has_mixed_evidence": False,
        "score_direction": "POSITIVE",
        "evidence_coverage_ratio": 1.0,
        "informative_evidence_ratio": 1.0,
        "support_to_contradiction_ratio": 1.0,
        "evidence_position": "SUPPORTING",
    }

    with pytest.raises(HypothesisScoreContractError) as exc_info:
        HypothesisScoringService._validate_score_result(inconsistent_result)

    assert exc_info.value.invariant == "SCORE_IDENTITY"
    # The validator must not have mutated the value to "fix" it.
    assert inconsistent_result["hypothesis_score"] == 0.5
    assert inconsistent_result["net_contribution"] == 0.0


def test_validator_raises_on_direction_mismatch() -> None:
    result = {
        "hypothesis_id": uuid4(),
        "hypothesis_name": "Broken Hypothesis",
        "hypothesis_score": 0.5,
        "score_source": SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
        "evidence_consistency": "SUPPORT_ONLY",
        "total_evidence_items": 1,
        "total_support_contribution": 0.5,
        "total_contradiction_contribution": 0.0,
        "net_contribution": 0.5,
        "has_evidence": True,
        "has_mixed_evidence": False,
        # Direction deliberately wrong for a positive score.
        "score_direction": "NEGATIVE",
        "evidence_coverage_ratio": 1.0,
        "informative_evidence_ratio": 1.0,
        "support_to_contradiction_ratio": None,
        "evidence_position": "SUPPORTING",
    }

    with pytest.raises(HypothesisScoreContractError) as exc_info:
        HypothesisScoringService._validate_score_result(result)

    assert exc_info.value.invariant == "SCORE_DIRECTION"


def test_validator_accepts_a_well_formed_result() -> None:
    result = {
        "hypothesis_id": uuid4(),
        "hypothesis_name": "Healthy Hypothesis",
        "hypothesis_score": 0.5,
        "score_source": SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
        "evidence_consistency": "SUPPORT_ONLY",
        "total_evidence_items": 1,
        "total_support_contribution": 0.5,
        "total_contradiction_contribution": 0.0,
        "net_contribution": 0.5,
        "has_evidence": True,
        "has_mixed_evidence": False,
        "score_direction": "POSITIVE",
        "evidence_coverage_ratio": 1.0,
        "informative_evidence_ratio": 1.0,
        "support_to_contradiction_ratio": None,
        "evidence_position": "SUPPORTING",
    }

    # Must not raise.
    HypothesisScoringService._validate_score_result(result)


# ---------------------------------------------------------------------------
# 16-17. API returns the complete contract and stays read-only
# ---------------------------------------------------------------------------


def _create_session() -> str:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Hypothesis score contract test",
            "current_stage": "initial",
            "metadata": {"source": "hypothesis-score-contract-test"},
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


def test_api_returns_the_complete_task_025_contract() -> None:
    session_id = _create_session()
    _add_observation(session_id, "Patient reports chest pain")
    _add_observation(session_id, "Pain radiates to left arm")

    generate_response = client.post(f"/sessions/{session_id}/generate-candidates")
    assert generate_response.status_code == 201
    candidate_count = len(generate_response.json())
    assert candidate_count > 0

    evaluate_response = client.post(f"/sessions/{session_id}/evaluate-evidence")
    assert evaluate_response.status_code == 200

    response = client.get(f"/sessions/{session_id}/hypothesis-scores")
    assert response.status_code == 200
    scores = response.json()
    assert len(scores) == candidate_count

    for entry in scores:
        assert _CONTRACT_FIELDS.issubset(entry.keys())
        assert entry["hypothesis_score"] == entry["net_contribution"]

    # Candidate order preserved, never sorted/ranked.
    candidate_ids_in_order = [c["id"] for c in generate_response.json()]
    score_ids_in_order = [entry["hypothesis_id"] for entry in scores]
    assert score_ids_in_order == candidate_ids_in_order


def test_api_hypothesis_scores_endpoint_is_read_only() -> None:
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

    first = client.get(f"/sessions/{session_id}/hypothesis-scores")
    second = client.get(f"/sessions/{session_id}/hypothesis-scores")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    with TestingSessionLocal() as db:
        after_count = (
            db.query(EvaluatedEvidence)
            .filter(EvaluatedEvidence.session_id == UUID(session_id))
            .count()
        )

    assert before_count == after_count


# ---------------------------------------------------------------------------
# 18. Regression — Task 020-024 suites still pass alongside this file.
# ---------------------------------------------------------------------------
#
# Enforced by running the full suite (see the task report), not by a
# single test here: this file only adds Task 025-specific coverage
# without modifying any Task 020-024 test file.
