from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models import Entity
from rop.schemas import EntityCreate, EntityUpdate


class EntityRepository:
    """Database operations for entity records."""

    def create(self, db: Session, data: EntityCreate) -> Entity:
        entity = Entity(
            session_id=data.session_id,
            name=data.name,
            category=data.category,
            confidence=data.confidence,
            source=data.source,
        )
        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity

    def get(self, db: Session, entity_id: UUID) -> Entity | None:
        return db.get(Entity, entity_id)

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Entity]:
        statement = (
            select(Entity)
            .where(Entity.session_id == session_id)
            .order_by(Entity.name.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def update(self, db: Session, entity: Entity, data: EntityUpdate) -> Entity:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(entity, field, value)

        db.add(entity)
        db.commit()
        db.refresh(entity)
        return entity

    def delete(self, db: Session, entity: Entity) -> None:
        db.delete(entity)
        db.commit()
