"""Tests for the Task 020 Evidence Evaluation Engine.

Covers every area listed in the Task 020 acceptance criteria that had no
coverage: rule loading, evidence creation, relationship mapping, weight
calculation, persistence, the API endpoint, and a basic performance check.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.evidence_evaluation import EvidenceEvaluator, load_evidence_rules
from rop.evidence_evaluation.models import EvidenceRelationship, EvidenceRule
from rop.main import app
from rop.models import Entity, Observation
from rop.repositories import EvaluatedEvidenceRepository
from rop.services.evidence_evaluation import EvidenceEvaluationService

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


def _observation(text: str, type_: str = "symptom") -> Observation:
    return Observation(
        session_id=uuid4(),
        text=text,
        type=type_,
        confidence=0.9,
        source="rule_based",
    )


def _entity(name: str, category: str = "anatomical_location") -> Entity:
    return Entity(
        session_id=uuid4(),
        name=name,
        category=category,
        confidence=0.9,
        source="rule_based",
    )


def _rule(**overrides: object) -> EvidenceRule:
    defaults: dict[str, object] = {
        "rule_id": "test_rule_001",
        "hypothesis": "acute_coronary_syndrome",
        "target": "observation",
        "required_findings": (),
        "supporting_findings": ("chest pain", "diaphoresis"),
        "contradicting_findings": ("sharp", "pleuritic"),
        "weight": 0.75,
        "confidence": 0.8,
        "reason": "Test rule",
        "source": "unit_test",
    }
    defaults.update(overrides)
    return EvidenceRule(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------


def test_load_evidence_rules_from_real_knowledge_directory() -> None:
    rules = load_evidence_rules()

    assert len(rules) > 0
    hypotheses = {rule.hypothesis for rule in rules}
    assert "acute_coronary_syndrome" in hypotheses
    for rule in rules:
        assert rule.rule_id
        assert 0.0 <= rule.confidence <= 1.0


def test_load_evidence_rules_missing_directory_returns_empty_tuple() -> None:
    rules = load_evidence_rules("/nonexistent/evidence/rules/path")
    assert rules == ()


# ---------------------------------------------------------------------------
# Evidence creation and relationship mapping
# ---------------------------------------------------------------------------


def test_evaluator_maps_single_supporting_finding_to_supports() -> None:
    evaluator = EvidenceEvaluator(rules=(_rule(),))
    results = evaluator.evaluate_observation(
        "acute_coronary_syndrome", _observation("Patient reports chest pain")
    )

    assert len(results) == 1
    assert results[0].relationship == EvidenceRelationship.SUPPORTS
    assert results[0].passed is True


def test_evaluator_maps_multiple_supporting_findings_to_strongly_supports() -> None:
    evaluator = EvidenceEvaluator(rules=(_rule(),))
    results = evaluator.evaluate_observation(
        "acute_coronary_syndrome",
        _observation("Patient has chest pain and diaphoresis"),
    )

    assert len(results) == 1
    assert results[0].relationship == EvidenceRelationship.STRONGLY_SUPPORTS


def test_evaluator_maps_single_contradicting_finding_to_contradicts() -> None:
    evaluator = EvidenceEvaluator(rules=(_rule(),))
    results = evaluator.evaluate_observation(
        "acute_coronary_syndrome", _observation("Patient reports sharp pain")
    )

    assert len(results) == 1
    assert results[0].relationship == EvidenceRelationship.CONTRADICTS


def test_evaluator_maps_multiple_contradicting_findings_to_strongly_contradicts() -> (
    None
):
    evaluator = EvidenceEvaluator(rules=(_rule(),))
    results = evaluator.evaluate_observation(
        "acute_coronary_syndrome",
        _observation("Pain is sharp and pleuritic in nature"),
    )

    assert len(results) == 1
    assert results[0].relationship == EvidenceRelationship.STRONGLY_CONTRADICTS


def test_evaluator_skips_rule_when_required_finding_is_absent() -> None:
    rule = _rule(required_findings=("troponin",))
    evaluator = EvidenceEvaluator(rules=(rule,))

    results = evaluator.evaluate_observation(
        "acute_coronary_syndrome", _observation("Patient reports chest pain")
    )

    assert results == []


def test_evaluator_reports_neutral_and_unpassed_when_nothing_matches() -> None:
    evaluator = EvidenceEvaluator(rules=(_rule(),))
    results = evaluator.evaluate_observation(
        "acute_coronary_syndrome", _observation("Patient is well and asymptomatic")
    )

    assert len(results) == 1
    assert results[0].relationship == EvidenceRelationship.NEUTRAL
    assert results[0].passed is False


def test_evaluator_evaluate_entity_uses_same_relationship_rules() -> None:
    rule = _rule(target="entity", supporting_findings=("left arm",))
    evaluator = EvidenceEvaluator(rules=(rule,))

    results = evaluator.evaluate_entity(
        "acute_coronary_syndrome", _entity("left arm radiation")
    )

    assert len(results) == 1
    assert results[0].relationship == EvidenceRelationship.SUPPORTS


def test_evaluator_only_matches_rules_for_the_requested_hypothesis() -> None:
    rule = _rule(hypothesis="stroke")
    evaluator = EvidenceEvaluator(rules=(rule,))

    results = evaluator.evaluate_observation(
        "acute_coronary_syndrome", _observation("Patient reports chest pain")
    )

    assert results == []


# ---------------------------------------------------------------------------
# Weight and confidence calculation
# ---------------------------------------------------------------------------


def test_persisted_evidence_carries_the_rules_weight_and_confidence() -> None:
    rule = _rule(weight=0.42, confidence=0.61)
    evaluator = EvidenceEvaluator(rules=(rule,))
    results = evaluator.evaluate_observation(
        "acute_coronary_syndrome", _observation("Patient reports chest pain")
    )

    repository = EvaluatedEvidenceRepository()
    session_id = uuid4()
    hypothesis_id = uuid4()
    observation_id = uuid4()

    with TestingSessionLocal() as db:
        records = repository.create_many(
            db, session_id, hypothesis_id, results, observation_id=observation_id
        )

        assert len(records) == 1
        record = records[0]
        assert record.weight == 0.42
        assert record.confidence == 0.61
        assert record.rule_id == rule.rule_id
        assert record.relationship == EvidenceRelationship.SUPPORTS.value
        assert record.observation_id == observation_id
        assert record.entity_id is None

        repository.delete_by_session(db, session_id)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_repository_does_not_persist_unpassed_neutral_results() -> None:
    evaluator = EvidenceEvaluator(rules=(_rule(),))
    results = evaluator.evaluate_observation(
        "acute_coronary_syndrome", _observation("Patient is well and asymptomatic")
    )
    assert results[0].passed is False

    repository = EvaluatedEvidenceRepository()
    session_id = uuid4()

    with TestingSessionLocal() as db:
        records = repository.create_many(db, session_id, uuid4(), results)
        assert records == []
        assert repository.list_by_session(db, session_id) == []


def test_repository_list_and_delete_by_session() -> None:
    evaluator = EvidenceEvaluator(rules=(_rule(),))
    results = evaluator.evaluate_observation(
        "acute_coronary_syndrome", _observation("Patient reports chest pain")
    )

    repository = EvaluatedEvidenceRepository()
    session_id = uuid4()

    with TestingSessionLocal() as db:
        repository.create_many(db, session_id, uuid4(), results)
        stored = repository.list_by_session(db, session_id)
        assert len(stored) == 1

        repository.delete_by_session(db, session_id)
        assert repository.list_by_session(db, session_id) == []


def test_service_rerun_replaces_previous_evidence_for_the_session() -> None:
    rule = _rule()
    service = EvidenceEvaluationService(rules=(rule,))
    session_id = uuid4()

    class _Candidate:
        id = uuid4()
        name = "acute_coronary_syndrome"

    candidate = _Candidate()

    with TestingSessionLocal() as db:
        first_pass = service.evaluate_session(
            db,
            session_id,
            candidates=[candidate],  # type: ignore[list-item]
            observations=[_observation("Patient reports chest pain")],
            entities=[],
        )
        assert len(first_pass) == 1

        second_pass = service.evaluate_session(
            db,
            session_id,
            candidates=[candidate],  # type: ignore[list-item]
            observations=[_observation("Patient is well and asymptomatic")],
            entities=[],
        )
        assert second_pass == []
        assert service.list_by_session(db, session_id) == []


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------


def _create_session() -> str:
    response = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": "Evidence evaluation test",
            "current_stage": "initial",
            "metadata": {"source": "evidence-evaluation-test"},
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


def test_evaluate_evidence_endpoint_returns_evidence_grouped_by_hypothesis() -> None:
    session_id = _create_session()
    _add_observation(session_id, "Patient reports chest pain")
    _add_observation(session_id, "Pain radiates to left arm")

    generate_response = client.post(f"/sessions/{session_id}/generate-candidates")
    assert generate_response.status_code == 201
    candidates = generate_response.json()
    assert len(candidates) > 0

    response = client.post(f"/sessions/{session_id}/evaluate-evidence")
    assert response.status_code == 200

    grouped = response.json()
    assert isinstance(grouped, list)
    assert len(grouped) > 0

    acs_group = next(
        (g for g in grouped if g["hypothesis_name"] == "acute_coronary_syndrome"),
        None,
    )
    assert acs_group is not None
    assert len(acs_group["evidence"]) > 0
    for item in acs_group["evidence"]:
        assert item["rule_id"]
        assert item["relationship"] in {r.value for r in EvidenceRelationship}
        assert 0.0 <= item["confidence"] <= 1.0


def test_evaluate_evidence_endpoint_404_for_unknown_session() -> None:
    response = client.post(f"/sessions/{uuid4()}/evaluate-evidence")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


def test_evaluator_handles_large_observation_batch_quickly() -> None:
    rules = load_evidence_rules()
    evaluator = EvidenceEvaluator(rules=rules)
    observations = [
        _observation(f"Patient reports chest pain, episode {i}") for i in range(500)
    ]

    started = time.perf_counter()
    for observation in observations:
        evaluator.evaluate_observation("acute_coronary_syndrome", observation)
    elapsed = time.perf_counter() - started

    assert (
        elapsed < 2.0
    ), f"Evaluating 500 observations took {elapsed:.2f}s, expected under 2s"
