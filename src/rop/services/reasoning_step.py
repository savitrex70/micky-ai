from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import ReasoningStep
from rop.repositories import ReasoningStepRepository
from rop.schemas import ReasoningStepCreate


class ReasoningStepService:
    """Service for managing immutable reasoning step records."""

    def __init__(self, repository: ReasoningStepRepository | None = None) -> None:
        self.repository = repository or ReasoningStepRepository()

    def create(self, db: Session, data: ReasoningStepCreate) -> ReasoningStep:
        step_number = self.repository.next_step_number(db, data.session_id)
        return self.repository.create(db, data, step_number)

    def get(self, db: Session, step_id: UUID) -> ReasoningStep | None:
        return self.repository.get(db, step_id)

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ReasoningStep]:
        return self.repository.list_by_session(
            db, session_id, offset=offset, limit=limit
        )

    def replay(self, db: Session, session_id: UUID) -> list[ReasoningStep]:
        return self.repository.list_by_session(db, session_id)
