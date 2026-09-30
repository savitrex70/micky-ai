from uuid import UUID

from sqlalchemy.orm import Session

from rop.missing_information import MissingInformationDetector
from rop.models import MissingInformation, Observation
from rop.repositories import MissingInformationRepository


class MissingInformationService:
    """Detect and persist missing information for one reasoning session."""

    def __init__(
        self,
        detector: MissingInformationDetector | None = None,
        repository: MissingInformationRepository | None = None,
    ) -> None:
        self.detector = detector or MissingInformationDetector()
        self.repository = repository or MissingInformationRepository()

    def detect_and_store(
        self,
        db: Session,
        session_id: UUID,
        observations: list[Observation],
        profile_name: str | None = None,
        *,
        commit: bool = True,
    ) -> list[MissingInformation]:
        """Detect and persist missing information for one session.

        Commit ownership follows the Task 126 correction: ``commit=True``
        preserves standalone behavior; ``commit=False`` stages inside
        the caller's transaction.
        """
        items = self.detector.detect(observations, profile_name)
        try:
            staged = self.repository.replace_for_session(
                db, session_id, items, template_name=profile_name
            )
            if commit:
                db.commit()
            else:
                db.flush()
            return staged
        except Exception:
            db.rollback()
            raise

    def list_by_session(
        self, db: Session, session_id: UUID
    ) -> list[MissingInformation]:
        return self.repository.list_by_session(db, session_id)
