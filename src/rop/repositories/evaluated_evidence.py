from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.evidence_evaluation.models import EvidenceEvaluationResult
from rop.models import EvaluatedEvidence


class EvaluatedEvidenceRepository:
    """Database operations for evaluated evidence records.

    None of these methods commit. Evaluating a whole session (delete the
    previous evidence, then persist the new evidence for every candidate)
    must happen as one atomic operation, so the caller — currently
    ``EvidenceEvaluationService.evaluate_session`` — owns the transaction
    boundary and commits once at the end, rolling back everything if any
    step fails. Committing after each step here would leave old evidence
    deleted and new evidence only partially written if a later candidate
    failed to evaluate.
    """

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

            contributing_observations = list(result.contributing_observation_ids) or (
                [str(observation_id)] if observation_id else []
            )
            contributing_entities = list(result.contributing_entity_ids) or (
                [str(entity_id)] if entity_id else []
            )

            # The rule's weight is a fixed, declared property of the rule.
            # `contribution` is what should actually feed a future scoring
            # engine: it scales that weight by how much of the rule's
            # configured findings were present in this session, so a rule
            # that matched on every finding counts for more than one that
            # barely cleared the bar.
            contribution = (
                result.rule.weight * result.match_strength
                if result.total_finding_count
                else result.rule.weight
            )

            record = EvaluatedEvidence(
                session_id=session_id,
                hypothesis_id=hypothesis_id,
                observation_id=(
                    UUID(contributing_observations[0])
                    if contributing_observations
                    else observation_id
                ),
                entity_id=(
                    UUID(contributing_entities[0])
                    if contributing_entities
                    else entity_id
                ),
                rule_id=result.rule.rule_id,
                relationship=result.relationship.value,
                weight=result.rule.weight,
                confidence=result.rule.confidence,
                matched_finding_count=result.matched_finding_count,
                total_finding_count=result.total_finding_count,
                match_strength=result.match_strength,
                contribution=round(contribution, 4),
                contributing_observation_ids=contributing_observations,
                contributing_entity_ids=contributing_entities,
                reason=result.reason,
                source=result.rule.source,
            )
            db.add(record)
            records.append(record)

        if records:
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
    ) -> list[EvaluatedEvidence]:
        statement = (
            select(EvaluatedEvidence)
            .where(EvaluatedEvidence.session_id == session_id)
            .order_by(EvaluatedEvidence.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def list_all_by_session(
        self, db: Session, session_id: UUID
    ) -> list[EvaluatedEvidence]:
        """Return every evaluated evidence record for a session, unpaginated.

        For callers that must see the complete set (e.g. aggregating a
        deterministic summary) rather than a page of it — ``list_by_session``
        defaults to 100 rows, which is the wrong contract when every record
        has to be counted.
        """
        statement = select(EvaluatedEvidence).where(
            EvaluatedEvidence.session_id == session_id
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

    def get(self, db: Session, evidence_id: UUID) -> EvaluatedEvidence | None:
        return db.get(EvaluatedEvidence, evidence_id)
