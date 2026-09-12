from uuid import UUID

from sqlalchemy.orm import Session

from rop.extraction import ObservationExtractor
from rop.models import Observation
from rop.repositories import ObservationRepository
from rop.schemas import ObservationCreate


class ObservationExtractionService:
    """Extract and persist observations for one active session."""

    def __init__(
        self,
        extractor: ObservationExtractor | None = None,
        repository: ObservationRepository | None = None,
    ) -> None:
        self.extractor = extractor or ObservationExtractor()
        self.repository = repository or ObservationRepository()

    def extract_and_store(
        self, db: Session, session_id: UUID, text: str
    ) -> list[Observation]:
        extracted = self.extractor.extract(text)
        records = [
            ObservationCreate(
                session_id=session_id,
                text=item.text,
                type=item.type,
                confidence=item.confidence,
                source=item.source,
            )
            for item in extracted
        ]
        return self.repository.create_many(db, records) if records else []
