from rop.models import Observation
from rop.recognition import MedicalEntityRecognizer, RecognizedMedicalEntity


class MedicalEntityRecognitionService:
    """Application service for deterministic medical entity recognition."""

    def __init__(self, recognizer: MedicalEntityRecognizer | None = None) -> None:
        self.recognizer = recognizer or MedicalEntityRecognizer()

    def recognize(
        self, observations: list[Observation]
    ) -> list[RecognizedMedicalEntity]:
        return self.recognizer.recognize(observations)
