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
        self, db: Session, session_id: UUID, text: str, *, commit: bool = True
    ) -> list[Observation]:
        """Extract observations and stage them.

        With ``commit=True`` (default, preserving endpoint behavior) the
        extraction commits once on success and rolls back on failure.
        Pass ``commit=False`` when running inside a larger transaction
        (e.g. reasoning-run execution): writes are flushed and the
        caller owns commit/rollback.
        """
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
        if not records:
            return []
        try:
            staged = self.repository.create_many(db, records)
            if commit:
                db.commit()
            else:
                db.flush()
            return staged
        except Exception:
            db.rollback()
            raise
