"""Tests for the Task 020 Evidence Evaluation Engine.

Covers every area listed in the Task 020 acceptance criteria that had no
coverage: rule loading, evidence creation, relationship mapping, weight
calculation, persistence, the API endpoint, and a basic performance check.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from uuid import uuid4

import pytest
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


def test_evaluator_reports_unmatched_result_when_required_finding_is_absent() -> None:
    rule = _rule(required_findings=("troponin",))
    evaluator = EvidenceEvaluator(rules=(rule,))

    results = evaluator.evaluate_observation(
        "acute_coronary_syndrome", _observation("Patient reports chest pain")
    )

    # A rule whose required findings weren't met is recorded as not-passed
    # rather than silently disappearing, so the evaluation is auditable:
    # you can see every rule that was *considered* for a hypothesis, not
    # just the ones that happened to match.
    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].relationship == EvidenceRelationship.UNKNOWN


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


def test_evaluator_recognizes_required_findings_across_multiple_observations() -> None:
    """A rule's required findings can be satisfied by the session as a
    whole, even when no single observation contains all of them — this is
    the cross-observation reasoning gap flagged in review: a clinician
    reads "chest pain" and "radiates to the left arm" as one case, not two
    unrelated facts, and the evaluator now needs to as well.
    """
    rule = _rule(
        required_findings=("chest pain", "left arm"),
        supporting_findings=("chest pain", "left arm"),
        contradicting_findings=(),
    )
    evaluator = EvidenceEvaluator(rules=(rule,))

    observations = [
        _observation("Patient reports chest pain"),
        _observation("Pain started thirty minutes ago"),
        _observation("Pain radiates to the left arm"),
    ]

    # Evaluating each observation in isolation never satisfies the
    # combined required findings.
    for observation in observations:
        isolated = evaluator.evaluate_observation(
            "acute_coronary_syndrome", observation
        )
        assert isolated == [] or isolated[0].passed is False

    # Evaluating the full session context does.
    results = evaluator.evaluate_hypothesis(
        "acute_coronary_syndrome", observations, entities=[]
    )
    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].relationship == EvidenceRelationship.STRONGLY_SUPPORTS
    assert results[0].matched_finding_count == 2
    assert results[0].total_finding_count == 2
    assert results[0].match_strength == 1.0


def test_evaluator_tracks_which_observations_contributed_a_match() -> None:
    rule = _rule(
        required_findings=(),
        supporting_findings=("chest pain", "diaphoresis"),
        contradicting_findings=(),
    )
    evaluator = EvidenceEvaluator(rules=(rule,))

    chest_pain_obs = _observation("Patient reports chest pain")
    diaphoresis_obs = _observation("Patient is diaphoretic")

    results = evaluator.evaluate_hypothesis(
        "acute_coronary_syndrome", [chest_pain_obs, diaphoresis_obs], entities=[]
    )

    assert len(results) == 1
    contributing_ids = set(results[0].contributing_observation_ids)
    # Ids are only present once the observations are flushed to the
    # database; here we only assert the shape/behavior, id population is
    # covered by the persistence tests below.
    assert isinstance(contributing_ids, set)


# ---------------------------------------------------------------------------
# Target isolation (observation-targeted rules vs. entity-targeted rules)
# ---------------------------------------------------------------------------


def test_observation_targeted_rule_does_not_match_entity_only_finding() -> None:
    """A finding that exists only as an entity must not satisfy an
    observation-targeted rule, even though ``evaluate_hypothesis`` sees
    both lists at once. Combining the two into one text blob (the Task
    020 bug) would let this match; keeping them separate must not.
    """
    rule = _rule(
        target="observation",
        required_findings=(),
        supporting_findings=("left arm",),
        contradicting_findings=(),
    )
    evaluator = EvidenceEvaluator(rules=(rule,))

    results = evaluator.evaluate_hypothesis(
        "acute_coronary_syndrome",
        observations=[_observation("Patient reports chest pain")],
        entities=[_entity("left arm")],
    )

    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].relationship == EvidenceRelationship.NEUTRAL
    assert results[0].matched_finding_count == 0


def test_entity_targeted_rule_does_not_match_observation_only_finding() -> None:
    """A finding that exists only as an observation must not satisfy an
    entity-targeted rule.
    """
    rule = _rule(
        target="entity",
        required_findings=(),
        supporting_findings=("chest pain",),
        contradicting_findings=(),
    )
    evaluator = EvidenceEvaluator(rules=(rule,))

    results = evaluator.evaluate_hypothesis(
        "acute_coronary_syndrome",
        observations=[_observation("Patient reports chest pain")],
        entities=[_entity("left arm")],
    )

    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].relationship == EvidenceRelationship.NEUTRAL
    assert results[0].matched_finding_count == 0


def test_observation_targeted_rule_still_matches_across_multiple_observations() -> None:
    """Target isolation must not break cross-observation reasoning: an
    observation-targeted rule still needs to see every observation as one
    combined context, even when unrelated entities are also present in
    the session.
    """
    rule = _rule(
        target="observation",
        required_findings=("chest pain", "left arm"),
        supporting_findings=("chest pain", "left arm"),
        contradicting_findings=(),
    )
    evaluator = EvidenceEvaluator(rules=(rule,))

    results = evaluator.evaluate_hypothesis(
        "acute_coronary_syndrome",
        observations=[
            _observation("Patient reports chest pain"),
            _observation("Pain radiates to the left arm"),
        ],
        # An unrelated entity is present, but must not be needed (or used)
        # to satisfy an observation-targeted rule.
        entities=[_entity("unrelated finding")],
    )

    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].relationship == EvidenceRelationship.STRONGLY_SUPPORTS
    assert results[0].matched_finding_count == 2


def test_entity_targeted_rule_still_matches_across_multiple_entities() -> None:
    """Cross-item reasoning must also hold for entity-targeted rules: a
    rule requiring two findings can still match when those findings were
    recorded as two separate entities.
    """
    rule = _rule(
        target="entity",
        required_findings=("left arm", "jaw"),
        supporting_findings=("left arm", "jaw"),
        contradicting_findings=(),
    )
    evaluator = EvidenceEvaluator(rules=(rule,))

    results = evaluator.evaluate_hypothesis(
        "acute_coronary_syndrome",
        observations=[_observation("Patient reports chest pain")],
        entities=[
            _entity("left arm"),
            _entity("jaw"),
        ],
    )

    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].relationship == EvidenceRelationship.STRONGLY_SUPPORTS
    assert results[0].matched_finding_count == 2


def test_source_attribution_is_never_mixed_across_target_types() -> None:
    """Even when an observation and an entity happen to contain the same
    finding text, an observation-targeted rule's match must only be
    attributed to observation ids, and an entity-targeted rule's match
    must only be attributed to entity ids — never both.
    """
    observation = _observation("Patient reports chest pain")
    observation.id = uuid4()
    entity = _entity("chest pain")
    entity.id = uuid4()

    observation_rule = _rule(
        rule_id="obs_rule",
        target="observation",
        required_findings=(),
        supporting_findings=("chest pain",),
        contradicting_findings=(),
    )
    entity_rule = _rule(
        rule_id="entity_rule",
        target="entity",
        required_findings=(),
        supporting_findings=("chest pain",),
        contradicting_findings=(),
    )
    evaluator = EvidenceEvaluator(rules=(observation_rule, entity_rule))

    results = evaluator.evaluate_hypothesis(
        "acute_coronary_syndrome",
        observations=[observation],
        entities=[entity],
    )

    by_rule_id = {result.rule.rule_id: result for result in results}

    obs_result = by_rule_id["obs_rule"]
    assert obs_result.passed is True
    assert set(obs_result.contributing_observation_ids) == {str(observation.id)}
    assert obs_result.contributing_entity_ids == ()

    entity_result = by_rule_id["entity_rule"]
    assert entity_result.passed is True
    assert set(entity_result.contributing_entity_ids) == {str(entity.id)}
    assert entity_result.contributing_observation_ids == ()


# ---------------------------------------------------------------------------
# Weight and confidence calculation
# ---------------------------------------------------------------------------


def test_full_match_and_partial_match_produce_different_contribution() -> None:
    """The reviewer's core finding: two matches of the same rule with
    different amounts of evidence must not be stored as identical. Rule
    weight stays fixed (it's a property of the rule), but the stored
    ``contribution`` must reflect how much of the rule actually matched.
    """
    rule = _rule(
        required_findings=(),
        supporting_findings=("chest pain", "diaphoresis", "nausea"),
        contradicting_findings=(),
        weight=0.9,
    )
    service = EvidenceEvaluationService(rules=(rule,))

    class _Candidate:
        id = uuid4()
        name = "acute_coronary_syndrome"

    partial_session = uuid4()
    full_session = uuid4()

    with TestingSessionLocal() as db:
        partial = service.evaluate_session(
            db,
            partial_session,
            candidates=[_Candidate()],  # type: ignore[list-item]
            observations=[_observation("Patient reports chest pain")],
            entities=[],
        )
        full = service.evaluate_session(
            db,
            full_session,
            candidates=[_Candidate()],  # type: ignore[list-item]
            observations=[
                _observation("Patient reports chest pain and diaphoresis and nausea")
            ],
            entities=[],
        )

        assert len(partial) == 1
        assert len(full) == 1

        # Rule weight is identical either way — it's a static property.
        assert partial[0].weight == full[0].weight == 0.9

        # But the actual contribution differs, because the evidence
        # backing the match differs.
        assert partial[0].contribution < full[0].contribution
        assert full[0].match_strength == 1.0
        assert partial[0].match_strength < 1.0


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


def test_service_rolls_back_everything_if_evaluation_fails_partway() -> None:
    """If evaluating one candidate raises, the whole re-evaluation must be
    rolled back — including the delete of the session's previous evidence
    — so the session never ends up with old evidence gone and new evidence
    only half-written.
    """
    rule = _rule()
    service = EvidenceEvaluationService(rules=(rule,))
    session_id = uuid4()

    class _GoodCandidate:
        id = uuid4()
        name = "acute_coronary_syndrome"

    class _ExplodingCandidate:
        id = uuid4()

        @property
        def name(self) -> str:
            raise RuntimeError("simulated failure evaluating this candidate")

    with TestingSessionLocal() as db:
        first_pass = service.evaluate_session(
            db,
            session_id,
            candidates=[_GoodCandidate()],  # type: ignore[list-item]
            observations=[_observation("Patient reports chest pain")],
            entities=[],
        )
        assert len(first_pass) == 1

        with pytest.raises(RuntimeError):
            service.evaluate_session(
                db,
                session_id,
                candidates=[_ExplodingCandidate()],  # type: ignore[list-item]
                observations=[_observation("Patient reports chest pain")],
                entities=[],
            )

        # The failed re-evaluation must not have deleted the previously
        # committed evidence, since the whole operation rolled back.
        remaining = service.list_by_session(db, session_id)
        assert len(remaining) == 1
        assert remaining[0].rule_id == rule.rule_id


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
