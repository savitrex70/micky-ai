from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models import TemplateMatch


class TemplateMatchRepository:
    """Database operations for template match records."""

    def create(self, db: Session, data: TemplateMatch) -> TemplateMatch:
        db.add(data)
        db.commit()
        db.refresh(data)
        return data

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[TemplateMatch]:
        statement = (
            select(TemplateMatch)
            .where(TemplateMatch.session_id == session_id)
            .order_by(TemplateMatch.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())
