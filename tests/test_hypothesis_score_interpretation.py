"""Tests for the Task 024 hypothesis score interpretation and evidence
coverage layer.

Task 024 does not change ``hypothesis_score`` (still Task 023's
``net_contribution``) or Task 022's ``evidence_consistency`` — it only
derives additional structural fields from the same per-candidate
analysis: ``score_direction``, ``evidence_coverage_ratio`` (TEMPORARY),
``informative_evidence_ratio``, ``support_to_contradiction_ratio``, and
``evidence_position``. These tests persist ``EvaluatedEvidence`` rows
directly, bypassing the evaluator entirely, plus end-to-end API tests
through the real hypothesis-scores endpoint.
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
from rop.services.hypothesis_scoring import HypothesisScoringService

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


# ---------------------------------------------------------------------------
# 1 & 2. Score direction: positive and negative
# ---------------------------------------------------------------------------


def test_score_direction_positive_when_support_exceeds_contradiction() -> None:
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


def test_score_direction_negative_when_contradiction_exceeds_support() -> None:
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


# ---------------------------------------------------------------------------
# 3. Zero score, no evidence
# ---------------------------------------------------------------------------


def test_zero_direction_no_evidence() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["hypothesis_score"] == 0.0
    assert entry["score_direction"] == "ZERO"
    assert entry["evidence_position"] == "UNSUPPORTED"
    assert entry["evidence_coverage_ratio"] == 0.0
    assert entry["informative_evidence_ratio"] == 0.0
    assert entry["support_to_contradiction_ratio"] is None


# ---------------------------------------------------------------------------
# 4. Zero score, mixed evidence (support == contradiction)
# ---------------------------------------------------------------------------


def test_zero_direction_mixed_evidence_is_not_unsupported_or_neutral() -> None:
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
    assert entry["evidence_position"] == "MIXED"
    assert entry["evidence_consistency"] == "MIXED"
    assert entry["evidence_coverage_ratio"] == 1.0
    assert entry["informative_evidence_ratio"] == 1.0
    assert entry["support_to_contradiction_ratio"] == 1.0


# ---------------------------------------------------------------------------
# 5. Support-only
# ---------------------------------------------------------------------------


def test_support_only_evidence_position() -> None:
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
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["evidence_position"] == "SUPPORTING"
    assert entry["evidence_coverage_ratio"] == 1.0
    assert entry["support_to_contradiction_ratio"] is None


# ---------------------------------------------------------------------------
# 6. Contradiction-only
# ---------------------------------------------------------------------------


def test_contradiction_only_evidence_position() -> None:
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

    assert entry["evidence_position"] == "CONTRADICTED"
    assert entry["evidence_coverage_ratio"] == 1.0
    # contradiction contribution > 0, support contribution == 0 -> 0.0,
    # not null.
    assert entry["support_to_contradiction_ratio"] == 0.0


# ---------------------------------------------------------------------------
# 7. Neutral-only
# ---------------------------------------------------------------------------


def test_neutral_only_evidence_position_and_informative_ratio() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.NEUTRAL,
                contribution=0.0,
            )
        )
        db.commit()
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["evidence_position"] == "NEUTRAL"
    assert entry["evidence_consistency"] == "NEUTRAL_ONLY"
    assert entry["informative_evidence_ratio"] == 0.0
    assert entry["evidence_coverage_ratio"] == 1.0


# ---------------------------------------------------------------------------
# 8. Informative evidence ratio: 4 informative, 1 neutral -> 0.8
# ---------------------------------------------------------------------------


def test_informative_evidence_ratio_with_mixed_and_neutral_rows() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.3,
                rule_id="r1",
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.STRONGLY_SUPPORTS,
                contribution=0.3,
                rule_id="r2",
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.2,
                rule_id="r3",
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.STRONGLY_CONTRADICTS,
                contribution=0.1,
                rule_id="r4",
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.NEUTRAL,
                contribution=0.0,
                rule_id="r5",
            )
        )
        db.commit()
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["total_evidence_items"] == 5
    assert entry["informative_evidence_ratio"] == 0.8


# ---------------------------------------------------------------------------
# 9 & 10 & 11. Support-to-contradiction ratio, including division-by-zero
# ---------------------------------------------------------------------------


def test_support_to_contradiction_ratio_normal_case() -> None:
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
                contribution=0.4,
                rule_id="rule_2",
            )
        )
        db.commit()
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["support_to_contradiction_ratio"] == 2.0


def test_support_to_contradiction_ratio_null_when_no_contradiction() -> None:
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
        db.commit()
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["support_to_contradiction_ratio"] is None


def test_support_to_contradiction_ratio_null_when_both_contributions_zero() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.NEUTRAL,
                contribution=0.0,
            )
        )
        db.commit()
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["support_to_contradiction_ratio"] is None
    assert entry["total_support_contribution"] == 0.0
    assert entry["total_contradiction_contribution"] == 0.0


def test_support_to_contradiction_ratio_never_infinity() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.STRONGLY_SUPPORTS,
                contribution=1.0,
            )
        )
        db.commit()
        entry = service.score_session(db, session_id, [candidate])[0]

    ratio = entry["support_to_contradiction_ratio"]
    assert ratio is None
    assert ratio != float("inf")


# ---------------------------------------------------------------------------
# 12. Multiple hypotheses each get independent interpretation
# ---------------------------------------------------------------------------


def test_multiple_hypotheses_get_independent_interpretation() -> None:
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
    assert by_id[supported.id]["score_direction"] == "POSITIVE"
    assert by_id[supported.id]["evidence_position"] == "SUPPORTING"
    assert by_id[contradicted.id]["score_direction"] == "NEGATIVE"
    assert by_id[contradicted.id]["evidence_position"] == "CONTRADICTED"
    assert by_id[untouched.id]["score_direction"] == "ZERO"
    assert by_id[untouched.id]["evidence_position"] == "UNSUPPORTED"
    assert by_id[untouched.id]["evidence_coverage_ratio"] == 0.0


# ---------------------------------------------------------------------------
# 13. Candidate with zero evidence still receives a complete score result
# ---------------------------------------------------------------------------


def test_zero_evidence_candidate_receives_complete_task_024_fields() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        entry = service.score_session(db, session_id, [candidate])[0]

    for field in (
        "score_direction",
        "evidence_coverage_ratio",
        "informative_evidence_ratio",
        "support_to_contradiction_ratio",
        "evidence_position",
    ):
        assert field in entry


# ---------------------------------------------------------------------------
# 14 & 15. Task 023/022 values remain unchanged
# ---------------------------------------------------------------------------


def test_existing_hypothesis_score_still_equals_net_contribution() -> None:
    service = _service()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.7,
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.2,
                rule_id="rule_2",
            )
        )
        db.commit()
        entry = service.score_session(db, session_id, [candidate])[0]

    assert entry["hypothesis_score"] == entry["net_contribution"]


def test_existing_evidence_consistency_not_overwritten_by_task_024() -> None:
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

    # Task 022's original value, untouched by the new evidence_position field.
    assert entry["evidence_consistency"] == "SUPPORT_ONLY"
    assert entry["evidence_position"] == "SUPPORTING"


# ---------------------------------------------------------------------------
# Required edge case: support == contradiction proves MIXED is not
# mistaken for NEUTRAL or UNSUPPORTED.
# ---------------------------------------------------------------------------


def test_balanced_conflict_edge_case() -> None:
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
    assert entry["evidence_position"] == "MIXED"
    assert entry["evidence_consistency"] == "MIXED"


# ---------------------------------------------------------------------------
# 16 & 17. API: returns typed fields, read-only
# ---------------------------------------------------------------------------


def _create_session() -> str:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Hypothesis score interpretation test",
            "current_stage": "initial",
            "metadata": {"source": "hypothesis-score-interpretation-test"},
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


def test_api_returns_task_024_typed_fields() -> None:
    session_id = _create_session()
    _add_observation(session_id, "Patient reports chest pain")
    _add_observation(session_id, "Pain radiates to left arm")

    generate_response = client.post(f"/sessions/{session_id}/generate-candidates")
    assert generate_response.status_code == 201

    evaluate_response = client.post(f"/sessions/{session_id}/evaluate-evidence")
    assert evaluate_response.status_code == 200

    response = client.get(f"/sessions/{session_id}/hypothesis-scores")
    assert response.status_code == 200
    scores = response.json()
    assert len(scores) > 0

    for entry in scores:
        assert entry["score_direction"] in ("POSITIVE", "NEGATIVE", "ZERO")
        assert entry["evidence_coverage_ratio"] in (0.0, 1.0)
        assert 0.0 <= entry["informative_evidence_ratio"] <= 1.0
        assert entry["evidence_position"] in (
            "UNSUPPORTED",
            "SUPPORTING",
            "CONTRADICTED",
            "MIXED",
            "NEUTRAL",
        )
        if entry["support_to_contradiction_ratio"] is not None:
            assert entry["support_to_contradiction_ratio"] >= 0.0
        # Task 023 fields must remain present and unchanged in meaning.
        assert entry["hypothesis_score"] == entry["net_contribution"]


def test_api_does_not_write_to_database_task_024() -> None:
    """Requesting the interpretation fields repeatedly must not create
    or modify any EvaluatedEvidence records."""
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
