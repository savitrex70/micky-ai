from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import ReasoningSession
from rop.repositories import ReasoningSessionRepository
from rop.schemas import ReasoningSessionCreate, ReasoningSessionUpdate


class ReasoningSessionService:
    """CRUD service for reasoning session records."""

    def __init__(self, repository: ReasoningSessionRepository | None = None) -> None:
        self.repository = repository or ReasoningSessionRepository()

    def create(self, db: Session, data: ReasoningSessionCreate) -> ReasoningSession:
        return self.repository.create(db, data)

    def get(self, db: Session, session_id: UUID) -> ReasoningSession | None:
        return self.repository.get(db, session_id)

    def list(
        self, db: Session, *, offset: int = 0, limit: int = 100
    ) -> list[ReasoningSession]:
        return self.repository.list(db, offset=offset, limit=limit)

    def update(
        self,
        db: Session,
        session_id: UUID,
        data: ReasoningSessionUpdate,
    ) -> ReasoningSession | None:
        session = self.repository.get(db, session_id)
        if session is None:
            return None
        return self.repository.update(db, session, data)

    def delete(self, db: Session, session_id: UUID) -> bool:
        session = self.repository.get(db, session_id)
        if session is None:
            return False
        self.repository.delete(db, session)
        return True
