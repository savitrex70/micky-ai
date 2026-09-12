from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import Hypothesis
from rop.repositories import HypothesisRepository
from rop.schemas import HypothesisCreate, HypothesisUpdate


class HypothesisService:
    """CRUD service for hypothesis records."""

    def __init__(self, repository: HypothesisRepository | None = None) -> None:
        self.repository = repository or HypothesisRepository()

    def create(self, db: Session, data: HypothesisCreate) -> Hypothesis:
        return self.repository.create(db, data)

    def get(self, db: Session, hypothesis_id: UUID) -> Hypothesis | None:
        return self.repository.get(db, hypothesis_id)

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Hypothesis]:
        return self.repository.list_by_session(
            db, session_id, offset=offset, limit=limit
        )

    def list_by_status(
        self,
        db: Session,
        session_id: UUID,
        status: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Hypothesis]:
        return self.repository.list_by_status(
            db, session_id, status, offset=offset, limit=limit
        )

    def update(
        self,
        db: Session,
        hypothesis_id: UUID,
        data: HypothesisUpdate,
    ) -> Hypothesis | None:
        hypothesis = self.repository.get(db, hypothesis_id)
        if hypothesis is None:
            return None
        return self.repository.update(db, hypothesis, data)

    def delete(self, db: Session, hypothesis_id: UUID) -> bool:
        hypothesis = self.repository.get(db, hypothesis_id)
        if hypothesis is None:
            return False
        self.repository.delete(db, hypothesis)
        return True
