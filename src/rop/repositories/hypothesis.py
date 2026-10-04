from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models import Hypothesis
from rop.schemas import HypothesisCreate, HypothesisUpdate


class HypothesisRepository:
    """Database operations for hypothesis records."""

    def create(self, db: Session, data: HypothesisCreate) -> Hypothesis:
        hypothesis = Hypothesis(
            session_id=data.session_id,
            title=data.title,
            description=data.description,
            category=data.category,
            status=data.status,
            likelihood_score=data.likelihood_score,
            rank=data.rank,
            reason=data.reason,
        )
        db.add(hypothesis)
        db.commit()
        db.refresh(hypothesis)
        return hypothesis

    def get(self, db: Session, hypothesis_id: UUID) -> Hypothesis | None:
        return db.get(Hypothesis, hypothesis_id)

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Hypothesis]:
        statement = (
            select(Hypothesis)
            .where(Hypothesis.session_id == session_id)
            .order_by(Hypothesis.rank.asc(), Hypothesis.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def list_by_status(
        self,
        db: Session,
        session_id: UUID,
        status: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Hypothesis]:
        statement = (
            select(Hypothesis)
            .where(Hypothesis.session_id == session_id, Hypothesis.status == status)
            .order_by(Hypothesis.rank.asc(), Hypothesis.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def update(
        self, db: Session, hypothesis: Hypothesis, data: HypothesisUpdate
    ) -> Hypothesis:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(hypothesis, field, value)

        db.add(hypothesis)
        db.commit()
        db.refresh(hypothesis)
        return hypothesis

    def delete(self, db: Session, hypothesis: Hypothesis) -> None:
        db.delete(hypothesis)
        db.commit()
