from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models import ReasoningStep
from rop.schemas import ReasoningStepCreate


class ReasoningStepRepository:
    """Database operations for reasoning step records."""

    def create(
        self, db: Session, data: ReasoningStepCreate, step_number: int
    ) -> ReasoningStep:
        step = ReasoningStep(
            session_id=data.session_id,
            step_number=step_number,
            step_type=data.step_type,
            input_data=data.input_data,
            output_data=data.output_data,
            confidence=data.confidence,
            duration_ms=data.duration_ms,
            status=data.status,
        )
        db.add(step)
        db.commit()
        db.refresh(step)
        return step

    def get(self, db: Session, step_id: UUID) -> ReasoningStep | None:
        return db.get(ReasoningStep, step_id)

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ReasoningStep]:
        statement = (
            select(ReasoningStep)
            .where(ReasoningStep.session_id == session_id)
            .order_by(ReasoningStep.step_number.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def next_step_number(self, db: Session, session_id: UUID) -> int:
        statement = (
            select(ReasoningStep)
            .where(ReasoningStep.session_id == session_id)
            .order_by(ReasoningStep.step_number.desc())
            .limit(1)
        )
        last_step = db.scalars(statement).first()
        return (last_step.step_number + 1) if last_step else 1
