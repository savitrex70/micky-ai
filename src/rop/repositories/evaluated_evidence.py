from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.evidence_evaluation.models import EvidenceEvaluationResult
from rop.models import EvaluatedEvidence


class EvaluatedEvidenceRepository:
    """Database operations for evaluated evidence records."""

    def create_many(
        self,
        db: Session,
        session_id: UUID,
        hypothesis_id: UUID,
        results: list[EvidenceEvaluationResult],
        observation_id: UUID | None = None,
        entity_id: UUID | None = None,
    ) -> list[EvaluatedEvidence]:
        records = []
        for result in results:
            if not result.passed:
                continue

            record = EvaluatedEvidence(
                session_id=session_id,
                hypothesis_id=hypothesis_id,
                observation_id=observation_id,
                entity_id=entity_id,
                rule_id=result.rule.rule_id,
                relationship=result.relationship.value,
                weight=result.rule.weight,
                confidence=result.rule.confidence,
                reason=result.reason,
                source=result.rule.source,
            )
            db.add(record)
            records.append(record)

        db.commit()
        for record in records:
            db.refresh(record)

        return records

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[EvaluatedEvidence]:
        statement = (
            select(EvaluatedEvidence)
            .where(EvaluatedEvidence.session_id == session_id)
            .order_by(EvaluatedEvidence.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def list_by_hypothesis(
        self,
        db: Session,
        hypothesis_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[EvaluatedEvidence]:
        statement = (
            select(EvaluatedEvidence)
            .where(EvaluatedEvidence.hypothesis_id == hypothesis_id)
            .order_by(EvaluatedEvidence.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def delete_by_session(self, db: Session, session_id: UUID) -> None:
        db.execute(
            EvaluatedEvidence.__table__.delete().where(
                EvaluatedEvidence.session_id == session_id
            )
        )
        db.commit()

    def get(
        self, db: Session, evidence_id: UUID
    ) -> EvaluatedEvidence | None:
        return db.get(EvaluatedEvidence, evidence_id)
