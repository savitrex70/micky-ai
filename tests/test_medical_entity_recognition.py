from uuid import uuid4

from rop.models import Observation
from rop.recognition import MedicalEntityRecognizer
from rop.services import MedicalEntityRecognitionService


def observation(text: str, type_: str, confidence: float = 0.9) -> Observation:
    return Observation(
        session_id=uuid4(),
        text=text,
        type=type_,
        confidence=confidence,
        source="rule_based",
    )


def test_recognizer_maps_supported_observation_categories() -> None:
    observations = [
        observation("Symptom = Chest pain", "symptom"),
        observation("Sign = Fever", "sign"),
        observation("Radiation = Left arm", "radiation"),
        observation("Duration = 30 minutes", "duration"),
        observation("Blood pressure = 120/80 mmHg", "measurement"),
        observation("Smoking", "risk_factor"),
    ]

    entities = MedicalEntityRecognizer().recognize(observations)

    assert [(entity.category, entity.value) for entity in entities] == [
        ("symptom", "Chest pain"),
        ("sign", "Fever"),
        ("anatomical_location", "Left arm"),
        ("duration", "30 minutes"),
        ("measurement", "120/80 mmHg"),
        ("risk_factor", "Smoking"),
    ]
    assert all(
        entity.source_observation is source
        for entity, source in zip(entities, observations, strict=True)
    )
    assert [entity.confidence for entity in entities] == [0.9] * 6


def test_recognizer_supports_label_based_observations() -> None:
    entities = MedicalEntityRecognizer().recognize(
        [observation("Anatomical location = Left arm", "fact")]
    )

    assert len(entities) == 1
    assert entities[0].category == "anatomical_location"
    assert entities[0].value == "Left arm"


def test_recognizer_ignores_unsupported_observations() -> None:
    assert (
        MedicalEntityRecognizer().recognize(
            [observation("Sex = Male", "sex"), observation("Unstructured fact", "fact")]
        )
        == []
    )


def test_service_delegates_to_rule_based_recognizer() -> None:
    source = observation("Age = 56", "age", confidence=0.99)

    entities = MedicalEntityRecognitionService().recognize([source])

    assert [(entity.category, entity.value) for entity in entities] == [
        ("measurement", "56")
    ]
    assert entities[0].source_observation is source
