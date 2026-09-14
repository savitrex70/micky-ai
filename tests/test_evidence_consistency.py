"""Tests for the Task 022 evidence consistency/quality analysis.

Task 022 does not evaluate evidence and does not aggregate it from scratch
— it consumes the same persisted ``EvaluatedEvidence`` rows Task 020 wrote
and Task 021 already knows how to count, and derives deterministic
structural signals (support-only, contradiction-only, mixed, neutral-only,
or no evidence) plus ratios. These tests persist ``EvaluatedEvidence`` rows
directly, bypassing the evaluator entirely, plus one end-to-end API test
through the real generate-candidates -> evaluate-evidence -> evidence-
analysis pipeline.
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
    """Build an EvaluatedEvidence row with the fields analysis reads.

    Bypasses the evaluator/repository.create_many entirely — the analysis
    only consumes already-persisted rows, so tests can set exactly the
    relationship/contribution combination they need.
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


# ---------------------------------------------------------------------------
# 1. No evidence
# ---------------------------------------------------------------------------


def test_candidate_with_no_evidence_gets_zero_valued_no_evidence_analysis() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        results = service.analyze_session_consistency(
            db, session_id, candidates=[candidate]
        )

    assert len(results) == 1
    entry = results[0]
    assert entry["hypothesis_id"] == candidate.id
    assert entry["hypothesis_name"] == "Hypothesis A"
    assert entry["total_evidence_items"] == 0
    assert entry["has_evidence"] is False
    assert entry["has_supporting_evidence"] is False
    assert entry["has_contradicting_evidence"] is False
    assert entry["has_mixed_evidence"] is False
    assert entry["support_evidence_ratio"] == 0.0
    assert entry["contradiction_evidence_ratio"] == 0.0
    assert entry["neutral_or_unknown_evidence_ratio"] == 0.0
    assert entry["evidence_consistency"] == "NO_EVIDENCE"


def test_session_with_no_candidates_returns_empty_analysis() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()

    with TestingSessionLocal() as db:
        results = service.analyze_session_consistency(db, session_id, candidates=[])
        assert results == []


# ---------------------------------------------------------------------------
# 2. Support only
# ---------------------------------------------------------------------------


def test_support_only_evidence() -> None:
    service = EvidenceAggregationService()
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
                relationship=EvidenceRelationship.STRONGLY_SUPPORTS,
                contribution=0.9,
                rule_id="rule_2",
            )
        )
        db.commit()

        entry = service.analyze_session_consistency(
            db, session_id, candidates=[candidate]
        )[0]

    assert entry["has_supporting_evidence"] is True
    assert entry["has_contradicting_evidence"] is False
    assert entry["has_mixed_evidence"] is False
    assert entry["evidence_consistency"] == "SUPPORT_ONLY"


# ---------------------------------------------------------------------------
# 3. Contradiction only
# ---------------------------------------------------------------------------


def test_contradiction_only_evidence() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.4,
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.STRONGLY_CONTRADICTS,
                contribution=0.8,
                rule_id="rule_2",
            )
        )
        db.commit()

        entry = service.analyze_session_consistency(
            db, session_id, candidates=[candidate]
        )[0]

    assert entry["has_supporting_evidence"] is False
    assert entry["has_contradicting_evidence"] is True
    assert entry["has_mixed_evidence"] is False
    assert entry["evidence_consistency"] == "CONTRADICTION_ONLY"


# ---------------------------------------------------------------------------
# 4. Mixed evidence
# ---------------------------------------------------------------------------


def test_mixed_evidence_one_support_one_contradiction() -> None:
    service = EvidenceAggregationService()
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

        entry = service.analyze_session_consistency(
            db, session_id, candidates=[candidate]
        )[0]

    assert entry["has_mixed_evidence"] is True
    assert entry["evidence_consistency"] == "MIXED"


def test_mixed_evidence_net_zero_is_still_mixed_not_neutral() -> None:
    """net_contribution == 0.0 must never be used to decide consistency —
    equal support and contradiction is a structural conflict (MIXED), not
    the absence of a signal (NEUTRAL_ONLY)."""
    service = EvidenceAggregationService()
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

        entry = service.analyze_session_consistency(
            db, session_id, candidates=[candidate]
        )[0]

    assert entry["net_contribution"] == 0.0
    assert entry["evidence_consistency"] == "MIXED"


# ---------------------------------------------------------------------------
# 5. Neutral only
# ---------------------------------------------------------------------------


def test_neutral_only_evidence() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.NEUTRAL,
                contribution=0.3,
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.UNKNOWN,
                contribution=0.2,
                rule_id="rule_2",
            )
        )
        db.commit()

        entry = service.analyze_session_consistency(
            db, session_id, candidates=[candidate]
        )[0]

    assert entry["has_supporting_evidence"] is False
    assert entry["has_contradicting_evidence"] is False
    assert entry["has_evidence"] is True
    assert entry["evidence_consistency"] == "NEUTRAL_ONLY"
    assert entry["neutral_or_unknown_evidence_ratio"] == 1.0


# ---------------------------------------------------------------------------
# 6. Ratio calculation and rounding
# ---------------------------------------------------------------------------


def test_ratio_calculation_and_four_decimal_rounding() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    # 3 items total: 1 support, 1 contradiction, 1 neutral.
    # Each ratio should be 1/3 == 0.3333 (rounded to 4 decimals).
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
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.NEUTRAL,
                contribution=0.1,
                rule_id="rule_3",
            )
        )
        db.commit()

        entry = service.analyze_session_consistency(
            db, session_id, candidates=[candidate]
        )[0]

    assert entry["support_evidence_ratio"] == 0.3333
    assert entry["contradiction_evidence_ratio"] == 0.3333
    assert entry["neutral_or_unknown_evidence_ratio"] == 0.3333
    assert entry["total_evidence_items"] == 3


def test_ratios_use_total_evidence_items_as_denominator_including_strong() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    # 4 items: 2 supports (1 regular, 1 strong), 1 contradiction, 1 neutral.
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
                contribution=0.9,
                rule_id="rule_2",
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.3,
                rule_id="rule_3",
            )
        )
        db.add(
            _evidence(
                session_id,
                candidate.id,
                relationship=EvidenceRelationship.UNKNOWN,
                contribution=0.1,
                rule_id="rule_4",
            )
        )
        db.commit()

        entry = service.analyze_session_consistency(
            db, session_id, candidates=[candidate]
        )[0]

    assert entry["support_evidence_ratio"] == 0.5  # 2/4
    assert entry["contradiction_evidence_ratio"] == 0.25  # 1/4
    assert entry["neutral_or_unknown_evidence_ratio"] == 0.25  # 1/4


# ---------------------------------------------------------------------------
# 7. Multiple hypotheses get independent analyses
# ---------------------------------------------------------------------------


def test_multiple_hypotheses_get_independent_analyses() -> None:
    service = EvidenceAggregationService()
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

        results = service.analyze_session_consistency(
            db, session_id, candidates=[supported, contradicted, untouched]
        )

    by_id = {entry["hypothesis_id"]: entry for entry in results}
    assert len(results) == 3
    assert by_id[supported.id]["evidence_consistency"] == "SUPPORT_ONLY"
    assert by_id[contradicted.id]["evidence_consistency"] == "CONTRADICTION_ONLY"
    assert by_id[untouched.id]["evidence_consistency"] == "NO_EVIDENCE"
    assert by_id[untouched.id]["total_evidence_items"] == 0


# ---------------------------------------------------------------------------
# 8. Zero-evidence candidates still appear (duplicated persisted evidence
#    also must not distort counts)
# ---------------------------------------------------------------------------


def test_duplicate_persisted_evidence_records_are_each_counted() -> None:
    """Duplicate rows (same rule matched twice, or persisted twice) are
    counted as separate evidence items — the analysis reflects what is
    actually stored, it does not deduplicate."""
    service = EvidenceAggregationService()
    session_id = uuid4()
    candidate = _Candidate(uuid4(), "Hypothesis A")

    with TestingSessionLocal() as db:
        for _ in range(3):
            db.add(
                _evidence(
                    session_id,
                    candidate.id,
                    relationship=EvidenceRelationship.SUPPORTS,
                    contribution=0.5,
                    rule_id="duplicate_rule",
                )
            )
        db.commit()

        entry = service.analyze_session_consistency(
            db, session_id, candidates=[candidate]
        )[0]

    assert entry["total_evidence_items"] == 3
    assert entry["supporting_evidence_count"] == 3
    assert entry["evidence_consistency"] == "SUPPORT_ONLY"


# ---------------------------------------------------------------------------
# 9. API: read-only, includes every candidate, 404 handling
# ---------------------------------------------------------------------------


def _create_session() -> str:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Evidence consistency test",
            "current_stage": "initial",
            "metadata": {"source": "evidence-consistency-test"},
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


def test_evidence_analysis_endpoint_404_for_unknown_session() -> None:
    response = client.get(f"/sessions/{uuid4()}/evidence-analysis")
    assert response.status_code == 404


def test_evidence_analysis_endpoint_empty_list_before_generate_candidates() -> None:
    session_id = _create_session()

    response = client.get(f"/sessions/{session_id}/evidence-analysis")
    assert response.status_code == 200
    assert response.json() == []


def test_evidence_analysis_endpoint_full_pipeline() -> None:
    session_id = _create_session()
    _add_observation(session_id, "Patient reports chest pain")
    _add_observation(session_id, "Pain radiates to left arm")

    generate_response = client.post(f"/sessions/{session_id}/generate-candidates")
    assert generate_response.status_code == 201
    candidate_count = len(generate_response.json())
    assert candidate_count > 0

    evaluate_response = client.post(f"/sessions/{session_id}/evaluate-evidence")
    assert evaluate_response.status_code == 200

    response = client.get(f"/sessions/{session_id}/evidence-analysis")
    assert response.status_code == 200
    analyses = response.json()

    # Every generated candidate gets exactly one analysis entry — including
    # any that ended up with no matching evidence.
    assert len(analyses) == candidate_count

    for entry in analyses:
        total = entry["total_evidence_items"]
        assert total == (
            entry["supporting_evidence_count"]
            + entry["strongly_supporting_evidence_count"]
            + entry["contradicting_evidence_count"]
            + entry["strongly_contradicting_evidence_count"]
            + entry["neutral_or_unknown_count"]
        )
        if total == 0:
            assert entry["has_evidence"] is False
            assert entry["evidence_consistency"] == "NO_EVIDENCE"
            assert entry["support_evidence_ratio"] == 0.0
            assert entry["contradiction_evidence_ratio"] == 0.0
            assert entry["neutral_or_unknown_evidence_ratio"] == 0.0
        else:
            assert entry["has_evidence"] is True
            assert entry["evidence_consistency"] in {
                "SUPPORT_ONLY",
                "CONTRADICTION_ONLY",
                "MIXED",
                "NEUTRAL_ONLY",
            }
            ratio_sum = round(
                entry["support_evidence_ratio"]
                + entry["contradiction_evidence_ratio"]
                + entry["neutral_or_unknown_evidence_ratio"],
                4,
            )
            assert ratio_sum == 1.0
        assert entry["has_mixed_evidence"] == (
            entry["has_supporting_evidence"] and entry["has_contradicting_evidence"]
        )

    # Read-only: calling it again must not change anything or re-evaluate.
    second_response = client.get(f"/sessions/{session_id}/evidence-analysis")
    assert second_response.status_code == 200
    assert second_response.json() == analyses


def test_evidence_analysis_endpoint_does_not_write_to_database() -> None:
    """Calling the analysis endpoint repeatedly must not create or modify
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
        response = client.get(f"/sessions/{session_id}/evidence-analysis")
        assert response.status_code == 200

    with TestingSessionLocal() as db:
        after_count = (
            db.query(EvaluatedEvidence)
            .filter(EvaluatedEvidence.session_id == UUID(session_id))
            .count()
        )

    assert before_count == after_count
