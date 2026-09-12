from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.evidence_evaluation import EvidenceEvaluator, load_evidence_rules
from rop.evidence_evaluation.models import EvidenceRule
from rop.models import CandidateHypothesis, Entity, Observation
from rop.models.evaluated_evidence import EvaluatedEvidence
from rop.repositories import EvaluatedEvidenceRepository


class EvidenceEvaluationService:
    """Evaluate observations and entities against evidence rules.

    A session's evidence is evaluated against its *combined* observations
    and entities (see ``EvidenceEvaluator.evaluate_hypothesis``), not one
    observation at a time — a rule that requires two findings recorded as
    separate observations can still match.
    """

    def __init__(
        self,
        rules: tuple[EvidenceRule, ...] | None = None,
        repository: EvaluatedEvidenceRepository | None = None,
    ) -> None:
        self.rules = rules or load_evidence_rules()
        self.repository = repository or EvaluatedEvidenceRepository()
        self.evaluator = EvidenceEvaluator(rules=self.rules)

    def evaluate_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
        observations: list[Observation],
        entities: list[Entity],
    ) -> list[EvaluatedEvidence]:
        """Re-evaluate a session's evidence as a single atomic operation.

        Replacing the previous evidence and writing the new evidence for
        every candidate happens in one transaction: if evaluating any
        candidate fails, everything (including the delete of the old
        evidence) is rolled back, so the session is never left with a
        partially-evaluated or missing evidence set.
        """
        try:
            self.repository.delete_by_session(db, session_id)

            all_evidence: list[EvaluatedEvidence] = []
            for candidate in candidates:
                evidence_items = self._evaluate_candidate(
                    db, session_id, candidate, observations, entities
                )
                all_evidence.extend(evidence_items)

            db.commit()
            for record in all_evidence:
                db.refresh(record)
            return all_evidence
        except Exception:
            db.rollback()
            raise

    def _evaluate_candidate(
        self,
        db: Session,
        session_id: UUID,
        candidate: CandidateHypothesis,
        observations: list[Observation],
        entities: list[Entity],
    ) -> list[EvaluatedEvidence]:
        results = self.evaluator.evaluate_hypothesis(
            candidate.name, observations, entities
        )
        if not results:
            return []

        return self.repository.create_many(db, session_id, candidate.id, results)

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[EvaluatedEvidence]:
        return self.repository.list_by_session(
            db, session_id, offset=offset, limit=limit
        )

    def group_by_hypothesis(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> list[dict[str, Any]]:
        all_evidence = self.repository.list_by_session(db, session_id)
        grouped: dict[Any, list[EvaluatedEvidence]] = defaultdict(list)
        for evidence in all_evidence:
            grouped[evidence.hypothesis_id].append(evidence)

        result = []
        candidate_map = {c.id: c for c in candidates}
        for hypothesis_id, evidence_list in grouped.items():
            candidate = candidate_map.get(hypothesis_id)
            result.append(
                {
                    "hypothesis_id": str(hypothesis_id),
                    "hypothesis_name": (candidate.name if candidate else "unknown"),
                    "evidence": [
                        {
                            "id": str(e.id),
                            "rule_id": e.rule_id,
                            "relationship": e.relationship,
                            "weight": e.weight,
                            "confidence": e.confidence,
                            "matched_finding_count": e.matched_finding_count,
                            "total_finding_count": e.total_finding_count,
                            "match_strength": e.match_strength,
                            "contribution": e.contribution,
                            "reason": e.reason,
                            "source": e.source,
                            "observation_id": (
                                str(e.observation_id) if e.observation_id else None
                            ),
                            "entity_id": (str(e.entity_id) if e.entity_id else None),
                            "contributing_observation_ids": (
                                e.contributing_observation_ids
                            ),
                            "contributing_entity_ids": e.contributing_entity_ids,
                            "created_at": e.created_at.isoformat(),
                        }
                        for e in evidence_list
                    ],
                }
            )
        return result
