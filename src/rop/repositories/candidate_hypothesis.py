from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.candidates.models import GeneratedCandidate
from rop.models import CandidateHypothesis


class CandidateHypothesisRepository:
    """Database operations for candidate hypothesis records."""

    def create_many(
        self, db: Session, session_id: UUID, candidates: tuple[GeneratedCandidate, ...]
    ) -> list[CandidateHypothesis]:
        """Stage candidate records without committing.

        Task 126: the owning service commits exactly once after the full
        delete+generate+create sequence succeeds, so a mid-sequence
        failure rolls everything back instead of stranding a partial
        candidate set.
        """
        records = []
        for candidate in candidates:
            record = CandidateHypothesis(
                session_id=session_id,
                name=candidate.rule.name,
                category=candidate.rule.category,
                trigger_reason=candidate.trigger_reason,
                initial_score=candidate.initial_score,
                confidence=candidate.confidence,
                supporting_observations=list(candidate.supporting_observations),
                contradicting_observations=list(candidate.contradicting_observations),
                missing_information=list(candidate.missing_information),
            )
            db.add(record)
            records.append(record)

        db.flush()
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
    ) -> list[CandidateHypothesis]:
        statement = (
            select(CandidateHypothesis)
            .where(CandidateHypothesis.session_id == session_id)
            .order_by(CandidateHypothesis.initial_score.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def get(self, db: Session, candidate_id: UUID) -> CandidateHypothesis | None:
        return db.get(CandidateHypothesis, candidate_id)

    def delete_by_session(self, db: Session, session_id: UUID) -> None:
        """Delete staged candidates without committing.

        Task 126: pairs with :meth:`create_many` -- the owning service
        commits once after regeneration succeeds.
        """
        statement = CandidateHypothesis.__table__.delete().where(
            CandidateHypothesis.session_id == session_id
        )
        db.execute(statement)
        db.flush()
