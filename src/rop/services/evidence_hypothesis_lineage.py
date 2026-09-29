"""Task 130: deterministic evidence-hypothesis lineage contract.

Builds one traceability record per hypothesis/candidate from source
data only: candidate records, evaluated evidence rows, the Task 025
score contract, and the differential rank contract. Every referenced ID
must exist in its source collection; no evidence may silently belong to
another hypothesis; every score and rank must trace back to the exact
contract row that produced it. Tie behavior is preserved exactly as
defined -- this task traces, never rescores, reranks, or recommends.
No probabilities, no winners, no new formulas. Read-only.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.evidence_evaluation.models import EvidenceRelationship
from rop.schemas.evidence_hypothesis_lineage import EvidenceHypothesisLineageRead
from rop.services.candidate_generation import CandidateGenerationService
from rop.services.differential_ranking import DifferentialRankingService
from rop.services.entity import EntityService
from rop.services.evidence_evaluation import EvidenceEvaluationService
from rop.services.hypothesis_scoring import HypothesisScoringService
from rop.services.observation import ObservationService
from rop.services.reasoning_session import ReasoningSessionService

EVIDENCE_HYPOTHESIS_LINEAGE_SOURCE_TASK_130 = "EVIDENCE_HYPOTHESIS_LINEAGE_TASK_130"

_SUPPORTING = {
    EvidenceRelationship.STRONGLY_SUPPORTS.value,
    EvidenceRelationship.SUPPORTS.value,
}
_CONTRADICTING = {
    EvidenceRelationship.CONTRADICTS.value,
    EvidenceRelationship.STRONGLY_CONTRADICTS.value,
}


class EvidenceHypothesisLineageContractError(Exception):
    """Task 130: lineage could not be established."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class EvidenceHypothesisLineageService:
    """Builds per-hypothesis traceability from source contracts."""

    def __init__(
        self,
        reasoning_session_service: ReasoningSessionService | None = None,
        observation_service: ObservationService | None = None,
        entity_service: EntityService | None = None,
        candidate_generation_service: CandidateGenerationService | None = None,
        evidence_evaluation_service: EvidenceEvaluationService | None = None,
        hypothesis_scoring_service: HypothesisScoringService | None = None,
        differential_ranking_service: DifferentialRankingService | None = None,
    ) -> None:
        self.reasoning_session_service = (
            reasoning_session_service or ReasoningSessionService()
        )
        self.observation_service = observation_service or ObservationService()
        self.entity_service = entity_service or EntityService()
        self.candidate_generation_service = (
            candidate_generation_service or CandidateGenerationService()
        )
        self.evidence_evaluation_service = (
            evidence_evaluation_service or EvidenceEvaluationService()
        )
        self.hypothesis_scoring_service = (
            hypothesis_scoring_service or HypothesisScoringService()
        )
        self.differential_ranking_service = (
            differential_ranking_service or DifferentialRankingService()
        )

    def build_for_session(self, db: Session, session_id: UUID) -> dict[str, Any]:
        """Build the session lineage contract, read-only."""
        session = self.reasoning_session_service.get(db, session_id)
        if session is None:
            raise EvidenceHypothesisLineageContractError(
                "SESSION_NOT_FOUND", "session does not exist"
            )
        issues: list[str] = []
        sid = str(session_id)

        observations = self.observation_service.list_by_session(db, session_id)
        entities = self.entity_service.list_by_session(db, session_id)
        candidates = self.candidate_generation_service.list_by_session(db, session_id)
        evidence = self.evidence_evaluation_service.list_by_session(db, session_id)
        observation_ids = {str(o.id) for o in observations}
        entity_ids = {str(e.id) for e in entities}
        candidate_ids = {str(c.id) for c in candidates}

        try:
            scores = self.hypothesis_scoring_service.score_session(
                db, session_id, candidates
            )
            scores_by_id = {
                str(s.get("hypothesis_id")): s for s in scores if isinstance(s, dict)
            }
        except Exception:
            scores_by_id = {}
            issues.append("score_contract_unavailable")
        try:
            ranked = self.differential_ranking_service.rank_session(
                db, session_id, candidates
            )
            ranks_by_id = {
                str(r.get("hypothesis_id")): r for r in ranked if isinstance(r, dict)
            }
        except Exception:
            ranks_by_id = {}
            issues.append("rank_contract_unavailable")

        if set(scores_by_id) != candidate_ids and candidates:
            issues.append("score_coverage_mismatch")
        if set(ranks_by_id) != candidate_ids and candidates:
            issues.append("rank_coverage_mismatch")

        evidence_by_hypothesis: dict[str, list[Any]] = {}
        for row in evidence:
            hid = str(getattr(row, "hypothesis_id", ""))
            if hid not in candidate_ids:
                issues.append(f"unknown_hypothesis_evidence:{getattr(row, 'id', '?')}")
                continue
            evidence_by_hypothesis.setdefault(hid, []).append(row)

        lineages: list[dict[str, Any]] = []
        for candidate in candidates:
            cid = str(candidate.id)
            rows = evidence_by_hypothesis.get(cid, [])
            supporting: list[dict[str, Any]] = []
            contradicting: list[dict[str, Any]] = []
            support_total = 0.0
            contradiction_total = 0.0
            originating_observations: set[str] = set(
                str(oid)
                for oid in list(
                    getattr(candidate, "supporting_observations", None) or []
                )
                + list(getattr(candidate, "contradicting_observations", None) or [])
            )
            originating_entities: set[str] = set()
            complete = True
            for row in rows:
                relationship = str(getattr(row, "relationship", ""))
                entry = {
                    "evidence_id": str(getattr(row, "id", "")),
                    "rule_id": str(getattr(row, "rule_id", "")),
                    "relationship": relationship,
                    "weight": float(getattr(row, "weight", 0.0)),
                    "contribution": float(getattr(row, "contribution", 0.0)),
                    "observation_id": (
                        str(row.observation_id)
                        if row.observation_id is not None
                        else None
                    ),
                    "entity_id": (
                        str(row.entity_id) if row.entity_id is not None else None
                    ),
                }
                if entry["observation_id"] is not None:
                    if entry["observation_id"] not in observation_ids:
                        issues.append(
                            f"unknown_lineage_observation:{entry['evidence_id']}"
                        )
                        complete = False
                    else:
                        originating_observations.add(entry["observation_id"])
                if entry["entity_id"] is not None:
                    if entry["entity_id"] not in entity_ids:
                        issues.append(f"unknown_lineage_entity:{entry['evidence_id']}")
                        complete = False
                    else:
                        originating_entities.add(entry["entity_id"])
                if relationship in _SUPPORTING:
                    supporting.append(entry)
                    support_total += entry["contribution"]
                elif relationship in _CONTRADICTING:
                    contradicting.append(entry)
                    contradiction_total += entry["contribution"]
            for oid in originating_observations:
                if oid not in observation_ids:
                    issues.append(f"unknown_lineage_observation:{cid}:{oid}")
                    complete = False
            score = scores_by_id.get(cid, {})
            rank_row = ranks_by_id.get(cid, {})
            lineages.append(
                {
                    "hypothesis_id": cid,
                    "hypothesis_name": str(getattr(candidate, "name", "")),
                    "originating_observation_ids": sorted(originating_observations),
                    "originating_entity_ids": sorted(originating_entities),
                    "supporting_evidence": supporting,
                    "contradicting_evidence": contradicting,
                    "total_support_contribution": round(support_total, 4),
                    "total_contradiction_contribution": round(contradiction_total, 4),
                    "hypothesis_score": float(score.get("hypothesis_score", 0.0)),
                    "score_source": str(score.get("score_source", "")),
                    "rank": rank_row.get("rank"),
                    "is_tied": rank_row.get("is_tied"),
                    "unresolved_information": list(
                        getattr(candidate, "missing_information", None) or []
                    ),
                    "lineage_complete": bool(complete),
                }
            )

        lineage_consistent = not issues
        result = {
            "available": True,
            "lineage_consistent": lineage_consistent,
            "session_id": sid,
            "lineages": lineages,
            "consistency_issues": sorted(set(issues)),
            "lineage_source": EVIDENCE_HYPOTHESIS_LINEAGE_SOURCE_TASK_130,
        }
        return EvidenceHypothesisLineageRead.model_validate(result).model_dump()
