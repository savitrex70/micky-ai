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
    """Evaluate observations and entities against evidence rules."""

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
        self.repository.delete_by_session(db, session_id)

        all_evidence: list[EvaluatedEvidence] = []
        for candidate in candidates:
            evidence_items = self._evaluate_candidate(
                db, session_id, candidate, observations, entities
            )
            all_evidence.extend(evidence_items)

        return all_evidence

    def _evaluate_candidate(
        self,
        db: Session,
        session_id: UUID,
        candidate: CandidateHypothesis,
        observations: list[Observation],
        entities: list[Entity],
    ) -> list[EvaluatedEvidence]:
        evidence_items: list[EvaluatedEvidence] = []

        for observation in observations:
            results = self.evaluator.evaluate_observation(candidate.name, observation)
            if results:
                records = self.repository.create_many(
                    db,
                    session_id,
                    candidate.id,
                    results,
                    observation_id=observation.id,
                )
                evidence_items.extend(records)

        for entity in entities:
            results = self.evaluator.evaluate_entity(candidate.name, entity)
            if results:
                records = self.repository.create_many(
                    db,
                    session_id,
                    candidate.id,
                    results,
                    entity_id=entity.id,
                )
                evidence_items.extend(records)

        return evidence_items

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
                            "reason": e.reason,
                            "source": e.source,
                            "observation_id": (
                                str(e.observation_id) if e.observation_id else None
                            ),
                            "entity_id": (str(e.entity_id) if e.entity_id else None),
                            "created_at": e.created_at.isoformat(),
                        }
                        for e in evidence_list
                    ],
                }
            )
        return result
