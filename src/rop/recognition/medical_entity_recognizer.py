import re
from dataclasses import dataclass

from rop.models import Observation


@dataclass(frozen=True, slots=True)
class RecognizedMedicalEntity:
    """A medical entity recognized from one persisted observation."""

    category: str
    value: str
    confidence: float
    source_observation: Observation


class MedicalEntityRecognizer:
    """Recognize medical entities from observations without model inference."""

    _VALUE_PATTERN = re.compile(r"^\s*[^=]+\s*=\s*(?P<value>.+?)\s*$")
    _CATEGORY_BY_TYPE = {
        "symptom": "symptom",
        "sign": "sign",
        "anatomical_location": "anatomical_location",
        "radiation": "anatomical_location",
        "duration": "duration",
        "measurement": "measurement",
        "age": "measurement",
        "risk_factor": "risk_factor",
    }
    _CATEGORY_BY_LABEL = {
        "symptom": "symptom",
        "sign": "sign",
        "anatomical location": "anatomical_location",
        "location": "anatomical_location",
        "radiation": "anatomical_location",
        "duration": "duration",
        "measurement": "measurement",
        "age": "measurement",
        "risk factor": "risk_factor",
    }

    def recognize(
        self, observations: list[Observation]
    ) -> list[RecognizedMedicalEntity]:
        """Return one entity for each observation with a supported category."""
        entities: list[RecognizedMedicalEntity] = []
        for observation in observations:
            category, value = self._classify(observation)
            if category is None or value is None:
                continue
            entities.append(
                RecognizedMedicalEntity(
                    category=category,
                    value=value,
                    confidence=observation.confidence,
                    source_observation=observation,
                )
            )
        return entities

    def _classify(self, observation: Observation) -> tuple[str | None, str | None]:
        category = self._CATEGORY_BY_TYPE.get(observation.type.lower().strip())
        value_match = self._VALUE_PATTERN.match(observation.text)
        value = value_match.group("value") if value_match else observation.text.strip()

        if category is not None:
            return category, value

        if value_match is None:
            return None, None
        label = observation.text.split("=", 1)[0].strip().lower()
        return self._CATEGORY_BY_LABEL.get(label), value
