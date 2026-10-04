from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models import ReasoningSession
from rop.schemas import ReasoningSessionCreate, ReasoningSessionUpdate


class ReasoningSessionRepository:
    """Database operations for reasoning session records."""

    def create(self, db: Session, data: ReasoningSessionCreate) -> ReasoningSession:
        session = ReasoningSession(
            status=data.status,
            domain=data.domain,
            user_input=data.user_input,
            current_stage=data.current_stage,
            notes=data.notes,
            metadata_=data.metadata,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def get(self, db: Session, session_id: UUID) -> ReasoningSession | None:
        return db.get(ReasoningSession, session_id)

    def list(
        self, db: Session, *, offset: int = 0, limit: int = 100
    ) -> list[ReasoningSession]:
        statement = (
            select(ReasoningSession)
            .order_by(ReasoningSession.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def update(
        self,
        db: Session,
        session: ReasoningSession,
        data: ReasoningSessionUpdate,
    ) -> ReasoningSession:
        values = data.model_dump(exclude_unset=True)
        if "metadata" in values:
            values["metadata_"] = values.pop("metadata")

        for field, value in values.items():
            setattr(session, field, value)

        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def delete(self, db: Session, session: ReasoningSession) -> None:
        db.delete(session)
        db.commit()
