"""Tests for the Task 021 Evidence Aggregation Service.

Task 021 does not evaluate evidence — it summarizes ``EvaluatedEvidence``
records already persisted by Task 020's ``EvidenceEvaluationService``. These
tests persist ``EvaluatedEvidence`` rows directly (bypassing the evaluator
entirely) so aggregation is exercised independently of how the evidence was
produced, plus one end-to-end API test that goes through the real
generate-candidates -> evaluate-evidence -> evidence-summary pipeline.
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
    """Build an EvaluatedEvidence row with the fields aggregation reads.

    Bypasses the evaluator/repository.create_many entirely — aggregation
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
# Empty evidence
# ---------------------------------------------------------------------------


def test_session_with_no_evaluated_evidence_returns_empty_summary() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()

    with TestingSessionLocal() as db:
        summaries = service.summarize_session(db, session_id, candidates=[])
        assert summaries == []


def test_hypothesis_with_no_evidence_produces_no_summary_entry() -> None:
    """A candidate with zero evaluated evidence has nothing to summarize
    yet, so it must not appear in the results (matching how
    ``group_by_hypothesis`` already groups by observed evidence, not by
    the full candidate list).
    """
    service = EvidenceAggregationService()
    session_id = uuid4()
    hypothesis_with_evidence = uuid4()
    hypothesis_without_evidence = uuid4()

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                hypothesis_with_evidence,
                relationship=EvidenceRelationship.SUPPORTS,
            )
        )
        db.commit()

        summaries = service.summarize_session(
            db,
            session_id,
            candidates=[
                _Candidate(hypothesis_with_evidence, "acute_coronary_syndrome"),
                _Candidate(hypothesis_without_evidence, "pulmonary_embolism"),
            ],
        )

        assert len(summaries) == 1
        assert summaries[0]["hypothesis_id"] == hypothesis_with_evidence


# ---------------------------------------------------------------------------
# Support aggregation
# ---------------------------------------------------------------------------


def test_multiple_supports_records_sum_correctly() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    hypothesis_id = uuid4()

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.3,
                rule_id="rule_a",
            )
        )
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.2,
                rule_id="rule_b",
            )
        )
        db.commit()

        summary = service.summarize_session(
            db,
            session_id,
            candidates=[_Candidate(hypothesis_id, "acute_coronary_syndrome")],
        )[0]

        assert summary["supporting_evidence_count"] == 2
        assert summary["strongly_supporting_evidence_count"] == 0
        assert summary["total_support_contribution"] == 0.5
        assert summary["total_evidence_items"] == 2


def test_strongly_supports_is_counted_separately_and_still_supports() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    hypothesis_id = uuid4()

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.STRONGLY_SUPPORTS,
                contribution=0.7,
                rule_id="rule_a",
            )
        )
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.2,
                rule_id="rule_b",
            )
        )
        db.commit()

        summary = service.summarize_session(
            db,
            session_id,
            candidates=[_Candidate(hypothesis_id, "acute_coronary_syndrome")],
        )[0]

        assert summary["strongly_supporting_evidence_count"] == 1
        assert summary["supporting_evidence_count"] == 1
        # Both SUPPORTS and STRONGLY_SUPPORTS feed the same support total.
        assert summary["total_support_contribution"] == 0.9


# ---------------------------------------------------------------------------
# Contradiction aggregation
# ---------------------------------------------------------------------------


def test_contradicts_and_strongly_contradicts_counted_correctly() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    hypothesis_id = uuid4()

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.1,
                rule_id="rule_a",
            )
        )
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.STRONGLY_CONTRADICTS,
                contribution=0.4,
                rule_id="rule_b",
            )
        )
        db.commit()

        summary = service.summarize_session(
            db,
            session_id,
            candidates=[_Candidate(hypothesis_id, "acute_coronary_syndrome")],
        )[0]

        assert summary["contradicting_evidence_count"] == 1
        assert summary["strongly_contradicting_evidence_count"] == 1
        assert summary["total_contradiction_contribution"] == 0.5


# ---------------------------------------------------------------------------
# Neutral / unknown
# ---------------------------------------------------------------------------


def test_neutral_and_unknown_are_counted_but_contribute_zero() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    hypothesis_id = uuid4()

    with TestingSessionLocal() as db:
        # Nonzero contribution values on purpose: they must still be
        # excluded from both totals purely by relationship type.
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.NEUTRAL,
                contribution=0.9,
                rule_id="rule_a",
            )
        )
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.UNKNOWN,
                contribution=0.9,
                rule_id="rule_b",
            )
        )
        db.commit()

        summary = service.summarize_session(
            db,
            session_id,
            candidates=[_Candidate(hypothesis_id, "acute_coronary_syndrome")],
        )[0]

        assert summary["neutral_or_unknown_count"] == 2
        assert summary["total_support_contribution"] == 0.0
        assert summary["total_contradiction_contribution"] == 0.0
        assert summary["net_contribution"] == 0.0
        assert summary["total_evidence_items"] == 2


# ---------------------------------------------------------------------------
# Net contribution
# ---------------------------------------------------------------------------


def test_net_contribution_is_support_minus_contradiction() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    hypothesis_id = uuid4()

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.STRONGLY_SUPPORTS,
                contribution=0.8,
                rule_id="rule_a",
            )
        )
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.3,
                rule_id="rule_b",
            )
        )
        db.commit()

        summary = service.summarize_session(
            db,
            session_id,
            candidates=[_Candidate(hypothesis_id, "acute_coronary_syndrome")],
        )[0]

        assert summary["total_support_contribution"] == 0.8
        assert summary["total_contradiction_contribution"] == 0.3
        assert summary["net_contribution"] == 0.5


# ---------------------------------------------------------------------------
# Multiple hypotheses
# ---------------------------------------------------------------------------


def test_evidence_is_grouped_correctly_by_hypothesis() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    acs_id = uuid4()
    pe_id = uuid4()

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                acs_id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.4,
                rule_id="acs_rule",
            )
        )
        db.add(
            _evidence(
                session_id,
                pe_id,
                relationship=EvidenceRelationship.CONTRADICTS,
                contribution=0.6,
                rule_id="pe_rule",
            )
        )
        db.commit()

        summaries = service.summarize_session(
            db,
            session_id,
            candidates=[
                _Candidate(acs_id, "acute_coronary_syndrome"),
                _Candidate(pe_id, "pulmonary_embolism"),
            ],
        )

        by_id = {summary["hypothesis_id"]: summary for summary in summaries}
        assert len(summaries) == 2
        assert by_id[acs_id]["hypothesis_name"] == "acute_coronary_syndrome"
        assert by_id[acs_id]["total_support_contribution"] == 0.4
        assert by_id[pe_id]["hypothesis_name"] == "pulmonary_embolism"
        assert by_id[pe_id]["total_contradiction_contribution"] == 0.6


# ---------------------------------------------------------------------------
# Precision
# ---------------------------------------------------------------------------


def test_totals_are_rounded_to_four_decimal_places() -> None:
    service = EvidenceAggregationService()
    session_id = uuid4()
    hypothesis_id = uuid4()

    with TestingSessionLocal() as db:
        # 0.1 + 0.2 is 0.30000000000000004 in raw floating point.
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.1,
                rule_id="rule_a",
            )
        )
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.2,
                rule_id="rule_b",
            )
        )
        db.commit()

        summary = service.summarize_session(
            db,
            session_id,
            candidates=[_Candidate(hypothesis_id, "acute_coronary_syndrome")],
        )[0]

        assert summary["total_support_contribution"] == 0.3
        assert summary["net_contribution"] == 0.3


# ---------------------------------------------------------------------------
# Duplicate evidence is not silently deduplicated
# ---------------------------------------------------------------------------


def test_duplicate_evidence_records_are_aggregated_as_persisted() -> None:
    """Two records with the same rule and contribution must both count —
    aggregation reflects what was persisted, it does not deduplicate.
    """
    service = EvidenceAggregationService()
    session_id = uuid4()
    hypothesis_id = uuid4()

    with TestingSessionLocal() as db:
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.25,
                rule_id="same_rule",
            )
        )
        db.add(
            _evidence(
                session_id,
                hypothesis_id,
                relationship=EvidenceRelationship.SUPPORTS,
                contribution=0.25,
                rule_id="same_rule",
            )
        )
        db.commit()

        summary = service.summarize_session(
            db,
            session_id,
            candidates=[_Candidate(hypothesis_id, "acute_coronary_syndrome")],
        )[0]

        assert summary["supporting_evidence_count"] == 2
        assert summary["total_evidence_items"] == 2
        assert summary["total_support_contribution"] == 0.5


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------


def _create_session() -> str:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Evidence aggregation test",
            "current_stage": "initial",
            "metadata": {"source": "evidence-aggregation-test"},
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


def test_evidence_summary_endpoint_returns_expected_structure() -> None:
    session_id = _create_session()
    _add_observation(session_id, "Patient reports chest pain")
    _add_observation(session_id, "Pain radiates to left arm")

    generate_response = client.post(f"/sessions/{session_id}/generate-candidates")
    assert generate_response.status_code == 201
    assert len(generate_response.json()) > 0

    evaluate_response = client.post(f"/sessions/{session_id}/evaluate-evidence")
    assert evaluate_response.status_code == 200

    summary_response = client.get(f"/sessions/{session_id}/evidence-summary")
    assert summary_response.status_code == 200

    summaries = summary_response.json()
    assert isinstance(summaries, list)
    assert len(summaries) > 0

    acs_summary = next(
        (
            summary
            for summary in summaries
            if summary["hypothesis_name"] == "acute_coronary_syndrome"
        ),
        None,
    )
    assert acs_summary is not None
    assert acs_summary["total_evidence_items"] > 0
    assert acs_summary["total_evidence_items"] == (
        acs_summary["supporting_evidence_count"]
        + acs_summary["strongly_supporting_evidence_count"]
        + acs_summary["contradicting_evidence_count"]
        + acs_summary["strongly_contradicting_evidence_count"]
        + acs_summary["neutral_or_unknown_count"]
    )
    expected_net = round(
        acs_summary["total_support_contribution"]
        - acs_summary["total_contradiction_contribution"],
        4,
    )
    assert acs_summary["net_contribution"] == expected_net

    # Read-only: calling it again must not change anything or evaluate.
    second_response = client.get(f"/sessions/{session_id}/evidence-summary")
    assert second_response.status_code == 200
    assert second_response.json() == summaries


def test_evidence_summary_endpoint_404_for_unknown_session() -> None:
    response = client.get(f"/sessions/{uuid4()}/evidence-summary")
    assert response.status_code == 404


def test_evidence_summary_endpoint_empty_list_before_evaluation() -> None:
    """A session with candidates generated but evidence never evaluated
    has no EvaluatedEvidence records yet, so the summary is empty.
    """
    session_id = _create_session()
    _add_observation(session_id, "Patient reports chest pain")

    generate_response = client.post(f"/sessions/{session_id}/generate-candidates")
    assert generate_response.status_code == 201

    response = client.get(f"/sessions/{session_id}/evidence-summary")
    assert response.status_code == 200
    assert response.json() == []
