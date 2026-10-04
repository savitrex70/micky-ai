"""Tests for the Task 023 hypothesis-scoring foundation.

Task 023 does not evaluate evidence, does not aggregate it from scratch,
and does not rank hypotheses — it consumes Task 022's per-candidate
consistency analysis (which itself already carries Task 021's
contribution totals over Task 020's persisted ``EvaluatedEvidence`` rows)
and derives one deterministic score per candidate:
``hypothesis_score = net_contribution``. These tests persist
``EvaluatedEvidence`` rows directly, bypassing the evaluator entirely,
plus end-to-end API tests through the real
generate-candidates -> evaluate-evidence -> hypothesis-scores pipeline.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import UUID, uuid4

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
    """Build an EvaluatedEvidence row with the fields scoring reads.

    Bypasses the evaluator/repository.create_many entirely — scoring
    only consumes already-persisted rows via Task 022's analysis, so
    tests can set exactly the relationship/contribution combination
    they need.
    """
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


# ---------------------------------------------------------------------------
# 1. Positive score
# ---------------------------------------------------------------------------


def test_positive_score_when_support_exceeds_contradiction() -> None:
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

    assert entry["total_support_contribution"] == 0.8
    assert entry["total_contradiction_contribution"] == 0.3
    assert entry["net_contribution"] == 0.5
    assert entry["hypothesis_score"] == 0.5
    assert entry["score_source"] == SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION


# ---------------------------------------------------------------------------
# 2. Negative score
# ---------------------------------------------------------------------------


def test_negative_score_when_contradiction_exceeds_support() -> None:
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

    assert entry["net_contribution"] == -0.5
    assert entry["hypothesis_score"] == -0.5


# ---------------------------------------------------------------------------
# 3. Zero score from no evidence
# ---------------------------------------------------------------------------


def test_zero_score_from_no_evidence() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["hypothesis_score"] == 0.0
    assert entry["has_evidence"] is False
    assert entry["evidence_consistency"] == "NO_EVIDENCE"
    assert entry["total_evidence_items"] == 0


# ---------------------------------------------------------------------------
# 4. Zero score from mixed evidence (support == contradiction)
# ---------------------------------------------------------------------------


def test_zero_score_from_mixed_evidence_that_cancels_out() -> None:
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
    assert entry["evidence_consistency"] == "MIXED"
    assert entry["has_mixed_evidence"] is True


# ---------------------------------------------------------------------------
# 5. Precision: score rounded to 4 decimal places
# ---------------------------------------------------------------------------


def test_score_rounded_to_four_decimal_places() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.723456,
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    # total_support_contribution is already rounded to 4dp by Task 021,
    # and the score formula rounds again defensively.
    assert entry["total_support_contribution"] == 0.7235
    assert entry["hypothesis_score"] == 0.7235


# ---------------------------------------------------------------------------
# 6. Multiple hypotheses get independent scores
# ---------------------------------------------------------------------------


def test_multiple_hypotheses_get_independent_scores() -> None:
    service = _service()
    session_id = uuid4()
    supported = _Candidate(uuid4(), "Supported Hypothesis")
    contradicted = _Candidate(uuid4(), "Contradicted Hypothesis")
    untouched = _Candidate(uuid4(), "Untouched Hypothesis")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                supported.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.6,
            )
        )
        db.add(
            _evidence(
                session_id,
                contradicted.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.6,
                rule_id="rule_2",
            )
        )
        db.commit()

        results = service.score_session(
            db, session_id, [supported, contradicted, untouched]
        )

    by_id = {entry["hypothesis_id"]: entry for entry in results}
    assert len(results) == 3
    assert by_id[supported.id]["hypothesis_score"] == 0.6
    assert by_id[contradicted.id]["hypothesis_score"] == -0.6
    assert by_id[untouched.id]["hypothesis_score"] == 0.0
    assert by_id[untouched.id]["evidence_consistency"] == "NO_EVIDENCE"

    # Candidate order is preserved as passed in — this is not a ranked list.
    assert [entry["hypothesis_id"] for entry in results] == [
        supported.id,
        contradicted.id,
        untouched.id,
    ]


# ---------------------------------------------------------------------------
# 7. Evidence consistency propagation
# ---------------------------------------------------------------------------


def test_evidence_consistency_propagated_from_task_022() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.STRONGLY_SUPPORTS,
                contribution=0.9,
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["evidence_consistency"] == "SUPPORT_ONLY"


# ---------------------------------------------------------------------------
# 8. Contribution propagation
# ---------------------------------------------------------------------------


def test_contribution_values_preserved_accurately() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.4,
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.STRONGLY_SUPPORTS,
                contribution=0.2,
                rule_id="rule_2",
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.1,
                rule_id="rule_3",
            )
        )
        db.commit()

        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["total_support_contribution"] == 0.6
    assert entry["total_contradiction_contribution"] == 0.1
    assert entry["net_contribution"] == 0.5
    assert entry["hypothesis_score"] == 0.5
    # Score must come from stored contribution values, never derived
    # from raw evidence counts (2 supporting vs 1 contradicting here
    # must NOT produce a score of 2 - 1 = 1).
    assert entry["hypothesis_score"] != 1.0


# ---------------------------------------------------------------------------
# 9. Zero-evidence candidate still receives a result
# ---------------------------------------------------------------------------


def test_zero_evidence_candidate_still_receives_a_result() -> None:
    service = _service()
    session_id = uuid4()
    with_evidence = _Candidate(uuid4(), "Has Evidence")
    without_evidence = _Candidate(uuid4(), "No Evidence")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                with_evidence.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.5,
            )
        )
        db.commit()

        results = service.score_session(
            db, session_id, [with_evidence, without_evidence]
        )

    assert len(results) == 2
    by_id = {entry["hypothesis_id"]: entry for entry in results}
    zero_entry = by_id[without_evidence.id]
    assert zero_entry["hypothesis_score"] == 0.0
    assert zero_entry["has_evidence"] is False
    assert zero_entry["evidence_consistency"] == "NO_EVIDENCE"


def test_session_with_no_candidates_returns_empty_scores() -> None:
    service = _service()
    session_id = uuid4()

    with TestingSessionLocal() as db:
        results = service.score_session(db, session_id, [])
        assert results == []


# ---------------------------------------------------------------------------
# Edge cases A-D from the task spec
# ---------------------------------------------------------------------------


def test_edge_case_a_support_08_contradiction_03() -> None:
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


def test_edge_case_b_support_02_contradiction_07() -> None:
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


def test_edge_case_c_support_05_contradiction_05_is_mixed() -> None:
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
    assert entry["evidence_consistency"] == "MIXED"


def test_edge_case_d_no_evidence() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["hypothesis_score"] == 0.0
    assert entry["evidence_consistency"] == "NO_EVIDENCE"


# ---------------------------------------------------------------------------
# API: read-only, includes every candidate, 404 handling
# ---------------------------------------------------------------------------


def _create_session() -> str:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Hypothesis scoring test",
            "current_stage": "initial",
            "metadata": {"source": "hypothesis-scoring-test"},
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


def test_hypothesis_scores_endpoint_404_for_unknown_session() -> None:
    response = client.get(f"/sessions/{uuid4()}/hypothesis-scores")
    assert response.status_code == 404


def test_hypothesis_scores_endpoint_empty_list_before_generate_candidates() -> None:
    session_id = _create_session()

    response = client.get(f"/sessions/{session_id}/hypothesis-scores")
    assert response.status_code == 200
    assert response.json() == []


def test_hypothesis_scores_endpoint_full_pipeline() -> None:
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

    # Every generated candidate gets exactly one score — including any
    # that ended up with no matching evidence.
    assert len(scores) == candidate_count

    for entry in scores:
        assert entry["score_source"] == SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION
        assert entry["hypothesis_score"] == entry["net_contribution"]
        if entry["total_evidence_items"] == 0:
            assert entry["has_evidence"] is False
            assert entry["evidence_consistency"] == "NO_EVIDENCE"
            assert entry["hypothesis_score"] == 0.0
        else:
            assert entry["has_evidence"] is True

    # Candidate order matches the generate-candidates order, not a
    # ranking by score.
    candidate_ids_in_order = [c["id"] for c in generate_response.json()]
    score_ids_in_order = [entry["hypothesis_id"] for entry in scores]
    assert score_ids_in_order == candidate_ids_in_order

    # Read-only: calling it again must not change anything or re-evaluate.
    second_response = client.get(f"/sessions/{session_id}/hypothesis-scores")
    assert second_response.status_code == 200
    assert second_response.json() == scores


def test_hypothesis_scores_endpoint_does_not_write_to_database() -> None:
    """Calling the scores endpoint repeatedly must not create or modify
    any EvaluatedEvidence records."""
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

    for _ in range(3):
        response = client.get(f"/sessions/{session_id}/hypothesis-scores")
        assert response.status_code == 200

    with TestingSessionLocal() as db:
        after_count = (
            db.query(EvaluatedEvidence)
            .filter(EvaluatedEvidence.session_id == UUID(session_id))
            .count()
        )

    assert before_count == after_count
