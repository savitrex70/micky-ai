from uuid import uuid4

from rop.candidates import CandidateGenerator, load_hypothesis_rules
from rop.candidates.models import HypothesisRule
from rop.models import Entity, Observation
from rop.templates import ClinicalTemplate, TemplateRule


def _observation(text: str, type_: str) -> Observation:
    return Observation(
        session_id=uuid4(),
        text=text,
        type=type_,
        confidence=0.9,
        source="rule_based",
    )


def _entity(name: str, category: str) -> Entity:
    return Entity(
        session_id=uuid4(),
        name=name,
        category=category,
        confidence=0.9,
        source="rule_based",
    )


def test_knowledge_loading_from_directory() -> None:
    rules = load_hypothesis_rules()

    assert len(rules) > 0
    rule_names = {rule.name for rule in rules}
    assert "acute_coronary_syndrome" in rule_names
    assert "stroke" in rule_names or "migraine" in rule_names


def test_knowledge_loading_handles_missing_directory() -> None:
    rules = load_hypothesis_rules("/nonexistent/rules/path")
    assert rules == ()


def test_candidate_generation_generates_candidates() -> None:
    rules = load_hypothesis_rules()
    generator = CandidateGenerator(rules=rules)

    observations = [
        _observation("Patient reports chest pain", "symptom"),
        _observation("Pain radiates to left arm", "radiation"),
    ]

    candidates = generator.generate(
        session_id=uuid4(),
        observations=observations,
        entities=[],
    )

    assert len(candidates) > 0
    candidate_names = {c.rule.name for c in candidates}
    assert "acute_coronary_syndrome" in candidate_names
    assert "aortic_dissection" not in candidate_names


def test_candidate_generation_no_matches_returns_empty() -> None:
    rules = load_hypothesis_rules()
    generator = CandidateGenerator(rules=rules)

    observations = [_observation("Patient reports fatigue", "symptom")]
    candidates = generator.generate(
        session_id=uuid4(),
        observations=observations,
        entities=[],
    )
    assert candidates == ()


def test_candidate_generation_orders_by_score() -> None:
    rules = load_hypothesis_rules()
    generator = CandidateGenerator(rules=rules)

    observations = [
        _observation("Patient reports shortness of breath", "symptom"),
        _observation("Patient has tachycardia", "sign"),
        _observation("Oxygen saturation is low", "measurement"),
    ]

    candidates = generator.generate(
        session_id=uuid4(),
        observations=observations,
        entities=[],
    )

    if len(candidates) > 1:
        scores = [c.initial_score for c in candidates]
        assert scores == sorted(scores, reverse=True)


def test_candidate_generation_includes_supporting_and_contradicting() -> None:
    custom_rules = (
        HypothesisRule(
            name="test_condition",
            category="Test",
            description="Test hypothesis",
            required_findings=("chest pain",),
            supporting_findings=("pressure", "diaphoresis"),
            contradicting_findings=("sharp", "wheezing"),
            risk_factors=("smoking",),
            urgency="high",
            base_score=0.8,
        ),
    )
    generator = CandidateGenerator(rules=custom_rules)

    observations = [
        _observation("Chest pain with pressure", "symptom"),
        _observation("Patient has diaphoresis", "sign"),
    ]

    candidates = generator.generate(
        session_id=uuid4(),
        observations=observations,
        entities=[],
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert len(candidate.supporting_observations) == 2
    assert len(candidate.contradicting_observations) == 0
    assert candidate.trigger_reason


def test_candidate_generation_includes_contradicting() -> None:
    custom_rules = (
        HypothesisRule(
            name="test_condition",
            category="Test",
            description="Test hypothesis",
            required_findings=("headache",),
            supporting_findings=("throbbing",),
            contradicting_findings=("fever",),
            risk_factors=(),
            urgency="low",
            base_score=0.5,
        ),
    )
    generator = CandidateGenerator(rules=custom_rules)

    observations = [
        _observation("Severe headache", "symptom"),
        _observation("Patient has fever", "symptom"),
    ]

    candidates = generator.generate(
        session_id=uuid4(),
        observations=observations,
        entities=[],
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.confidence < candidate.rule.base_score


def test_candidate_generation_includes_missing_information() -> None:
    from datetime import datetime
    from typing import Any
    from uuid import UUID

    from rop.schemas import MissingInformationRead

    custom_rules = (
        HypothesisRule(
            name="test_condition",
            category="Test",
            description="Test hypothesis",
            required_findings=("chest pain", "troponin"),
            supporting_findings=("pressure",),
            contradicting_findings=(),
            risk_factors=(),
            urgency="high",
            base_score=0.8,
        ),
    )
    generator = CandidateGenerator(rules=custom_rules)

    missing_info: list[Any] = [
        MissingInformationRead(
            id=UUID("12345678-1234-5678-1234-567812345678"),
            session_id=UUID("12345678-1234-5678-1234-567812345678"),
            template="test",
            item="troponin",
            created_at=datetime.now(),
        )
    ]

    observations = [_observation("Chest pain", "symptom")]

    candidates = generator.generate(
        session_id=uuid4(),
        observations=observations,
        entities=[],
        missing_information=missing_info,
    )

    assert len(candidates) == 1
    assert "troponin" in candidates[0].missing_information


def test_candidate_generation_with_template_filtering() -> None:
    rules = load_hypothesis_rules()
    generator = CandidateGenerator(rules=rules)

    template = ClinicalTemplate(
        name="acute_coronary_syndrome",
        category="Cardiology",
        description="ACS template",
        priority=1,
        trigger_rules=(
            TemplateRule(category="symptom", terms=("chest pain",)),
        ),
        required_information=("age", "sex"),
    )

    observations = [_observation("Chest pain", "symptom")]

    candidates = generator.generate(
        session_id=uuid4(),
        observations=observations,
        entities=[],
        template=template,
    )

    assert len(candidates) > 0
    for candidate in candidates:
        assert candidate.rule.category in ("Cardiology", "Pulmonology")


def test_candidate_generation_confidence_capped() -> None:
    custom_rules = (
        HypothesisRule(
            name="test_condition",
            category="Test",
            description="Test",
            required_findings=("fever",),
            supporting_findings=("fever", "fever2", "fever3"),
            contradicting_findings=(),
            risk_factors=(),
            urgency="low",
            base_score=0.9,
        ),
    )
    generator = CandidateGenerator(rules=custom_rules)

    observations = [
        _observation("Patient has fever", "symptom"),
        _observation("Patient has fever2", "symptom"),
        _observation("Patient has fever3", "symptom"),
    ]

    candidates = generator.generate(
        session_id=uuid4(),
        observations=observations,
        entities=[],
    )

    assert len(candidates) == 1
    assert candidates[0].confidence <= 1.0
