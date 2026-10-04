from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models import Evidence
from rop.schemas import EvidenceCreate, EvidenceUpdate


class EvidenceRepository:
    """Database operations for evidence records."""

    def create(self, db: Session, data: EvidenceCreate) -> Evidence:
        evidence = Evidence(
            hypothesis_id=data.hypothesis_id,
            session_id=data.session_id,
            type=data.type,
            source=data.source,
            text=data.text,
            confidence=data.confidence,
            strength=data.strength,
        )
        db.add(evidence)
        db.commit()
        db.refresh(evidence)
        return evidence

    def get(self, db: Session, evidence_id: UUID) -> Evidence | None:
        return db.get(Evidence, evidence_id)

    def list_by_hypothesis(
        self,
        db: Session,
        hypothesis_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Evidence]:
        statement = (
            select(Evidence)
            .where(Evidence.hypothesis_id == hypothesis_id)
            .order_by(Evidence.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Evidence]:
        statement = (
            select(Evidence)
            .where(Evidence.session_id == session_id)
            .order_by(Evidence.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def update(self, db: Session, evidence: Evidence, data: EvidenceUpdate) -> Evidence:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(evidence, field, value)

        db.add(evidence)
        db.commit()
        db.refresh(evidence)
        return evidence

    def delete(self, db: Session, evidence: Evidence) -> None:
        db.delete(evidence)
        db.commit()
