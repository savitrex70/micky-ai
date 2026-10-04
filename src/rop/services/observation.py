from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import Observation
from rop.repositories import ObservationRepository
from rop.schemas import ObservationCreate, ObservationUpdate


class ObservationService:
    """CRUD service for observation records."""

    def __init__(self, repository: ObservationRepository | None = None) -> None:
        self.repository = repository or ObservationRepository()

    def create(self, db: Session, data: ObservationCreate) -> Observation:
        return self.repository.create(db, data)

    def get(self, db: Session, observation_id: UUID) -> Observation | None:
        return self.repository.get(db, observation_id)

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Observation]:
        return self.repository.list_by_session(
            db, session_id, offset=offset, limit=limit
        )

    def update(
        self,
        db: Session,
        observation_id: UUID,
        data: ObservationUpdate,
    ) -> Observation | None:
        observation = self.repository.get(db, observation_id)
        if observation is None:
            return None
        return self.repository.update(db, observation, data)

    def delete(self, db: Session, observation_id: UUID) -> bool:
        observation = self.repository.get(db, observation_id)
        if observation is None:
            return False
        self.repository.delete(db, observation)
        return True
