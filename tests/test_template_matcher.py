from uuid import uuid4

from rop.models import Entity, Observation
from rop.templates import (
    ClinicalTemplate,
    TemplateRule,
    match_template,
)


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


def _simple_template(name: str, priority: int = 1) -> ClinicalTemplate:
    return ClinicalTemplate(
        name=name,
        category="Test",
        description="Test template",
        priority=priority,
        trigger_rules=(
            TemplateRule(category="Symptom", terms=("chest pain",)),
            TemplateRule(category="Body Location", terms=("left arm",)),
        ),
        required_information=(),
    )


def test_single_template_match() -> None:
    templates = (_simple_template("acs"),)
    observations = [
        _observation("Symptom = Chest pain", "Symptom"),
        _observation("Radiation = Left arm", "Body Location"),
    ]

    result = match_template(templates, observations, [])

    assert result.selected_template.name == "acs"
    assert result.confidence > 0.0
    assert len(result.matched_observations) == 2
    assert result.reason.startswith("Selected 'acs'")


def test_multiple_matches_selects_highest_score() -> None:
    templates = (
        _simple_template("acs", priority=1),
        _simple_template("generic", priority=99),
    )
    observations = [
        _observation("Symptom = Chest pain", "Symptom"),
        _observation("Radiation = Left arm", "Body Location"),
    ]

    result = match_template(templates, observations, [])

    assert result.selected_template.name == "acs"
    assert result.confidence > 0.0


def test_no_matches_falls_back_to_general_assessment() -> None:
    templates = (
        _simple_template("acs", priority=1),
        ClinicalTemplate(
            name="general_assessment",
            category="General",
            description="Default template",
            priority=99,
            trigger_rules=(),
            required_information=("age", "sex"),
        ),
    )
    observations = [
        _observation("Symptom = Headache", "Symptom"),
    ]

    result = match_template(templates, observations, [])

    assert result.selected_template.name == "general_assessment"
    assert result.confidence == 0.1
    assert "general_assessment" in result.reason


def test_entities_contribute_to_match_score() -> None:
    templates = (_simple_template("acs"),)
    observations = [_observation("Symptom = Chest pain", "Symptom")]
    entities = [_entity("Left arm", "Body Location")]

    result = match_template(templates, observations, entities)

    assert result.selected_template.name == "acs"
    assert "Left arm" in result.matched_entities


def test_confidence_calculation() -> None:
    template = ClinicalTemplate(
        name="full_match",
        category="Test",
        description="Test",
        priority=1,
        trigger_rules=(
            TemplateRule(category="Symptom", terms=("chest pain",)),
            TemplateRule(category="Body Location", terms=("left arm",)),
        ),
        required_information=(),
    )
    templates = (template,)
    observations = [
        _observation("Symptom = Chest pain", "Symptom"),
        _observation("Radiation = Left arm", "Body Location"),
    ]

    result = match_template(templates, observations, [])

    assert result.selected_template.name == "full_match"
    assert 0.0 < result.confidence <= 1.0


def test_candidates_are_stored() -> None:
    templates = (
        _simple_template("acs", priority=1),
        _simple_template("generic", priority=99),
    )
    observations = [
        _observation("Symptom = Chest pain", "Symptom"),
    ]

    result = match_template(templates, observations, [])

    assert len(result.candidates) == 2
    candidate_names = {c.template.name for c in result.candidates}
    assert candidate_names == {"acs", "generic"}


def test_priority_lower_is_better() -> None:
    low_priority = ClinicalTemplate(
        name="low",
        category="Test",
        description="Test",
        priority=10,
        trigger_rules=(TemplateRule(category="Symptom", terms=("chest pain",)),),
        required_information=(),
    )
    high_priority = ClinicalTemplate(
        name="high",
        category="Test",
        description="Test",
        priority=1,
        trigger_rules=(TemplateRule(category="Symptom", terms=("headache",)),),
        required_information=(),
    )
    templates = (low_priority, high_priority)
    observations = [_observation("Symptom = Chest pain", "Symptom")]

    result = match_template(templates, observations, [])

    assert result.selected_template.name == "low"
