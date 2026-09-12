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
    ) -> list[MissingInformation]:
        items = self.detector.detect(observations, profile_name)
        return self.repository.replace_for_session(
            db, session_id, items, template_name=profile_name
        )

    def list_by_session(
        self, db: Session, session_id: UUID
    ) -> list[MissingInformation]:
        return self.repository.list_by_session(db, session_id)
