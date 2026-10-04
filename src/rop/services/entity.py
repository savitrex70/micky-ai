from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import Entity
from rop.repositories import EntityRepository
from rop.schemas import EntityCreate, EntityUpdate


class EntityService:
    """CRUD service for entity records."""

    def __init__(self, repository: EntityRepository | None = None) -> None:
        self.repository = repository or EntityRepository()

    def create(self, db: Session, data: EntityCreate) -> Entity:
        return self.repository.create(db, data)

    def get(self, db: Session, entity_id: UUID) -> Entity | None:
        return self.repository.get(db, entity_id)

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Entity]:
        return self.repository.list_by_session(
            db, session_id, offset=offset, limit=limit
        )

    def update(
        self,
        db: Session,
        entity_id: UUID,
        data: EntityUpdate,
    ) -> Entity | None:
        entity = self.repository.get(db, entity_id)
        if entity is None:
            return None
        return self.repository.update(db, entity, data)

    def delete(self, db: Session, entity_id: UUID) -> bool:
        entity = self.repository.get(db, entity_id)
        if entity is None:
            return False
        self.repository.delete(db, entity)
        return True
