from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.evidence_evaluation.models import EvidenceRelationship
from rop.models import CandidateHypothesis, EvaluatedEvidence
from rop.repositories import EvaluatedEvidenceRepository

_CONTRIBUTION_PRECISION = 4

_SUPPORTING_RELATIONSHIPS = {
    EvidenceRelationship.SUPPORTS.value,
    EvidenceRelationship.STRONGLY_SUPPORTS.value,
}
_CONTRADICTING_RELATIONSHIPS = {
    EvidenceRelationship.CONTRADICTS.value,
    EvidenceRelationship.STRONGLY_CONTRADICTS.value,
}

_RATIO_PRECISION = 4

CONSISTENCY_NO_EVIDENCE = "NO_EVIDENCE"
CONSISTENCY_SUPPORT_ONLY = "SUPPORT_ONLY"
CONSISTENCY_CONTRADICTION_ONLY = "CONTRADICTION_ONLY"
CONSISTENCY_MIXED = "MIXED"
CONSISTENCY_NEUTRAL_ONLY = "NEUTRAL_ONLY"


class EvidenceAggregationService:
    """Summarize a session's persisted evidence, per candidate hypothesis.

    This is Task 021: a read-only aggregation layer over the
    ``EvaluatedEvidence`` records Task 020's ``EvidenceEvaluationService``
    already evaluated and persisted. It does not re-evaluate evidence,
    rank hypotheses, or produce a diagnosis — it only reduces each
    hypothesis's evidence rows to deterministic counts and contribution
    totals, so a later hypothesis-scoring engine can consume one summary
    per hypothesis instead of raw evidence records.

    Only hypotheses with at least one persisted evidence record produce a
    summary, matching how ``EvidenceEvaluationService.group_by_hypothesis``
    already groups by observed evidence rather than by the full candidate
    list — a hypothesis with zero evidence has nothing yet to summarize.
    """

    def __init__(self, repository: EvaluatedEvidenceRepository | None = None) -> None:
        self.repository = repository or EvaluatedEvidenceRepository()

    def summarize_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> list[dict[str, Any]]:
        all_evidence = self.repository.list_all_by_session(db, session_id)

        grouped: dict[UUID, list[EvaluatedEvidence]] = defaultdict(list)
        for evidence in all_evidence:
            grouped[evidence.hypothesis_id].append(evidence)

        candidate_map = {candidate.id: candidate for candidate in candidates}

        return [
            self._summarize_hypothesis(
                hypothesis_id=hypothesis_id,
                hypothesis_name=(
                    candidate_map[hypothesis_id].name
                    if hypothesis_id in candidate_map
                    else "unknown"
                ),
                evidence_list=evidence_list,
            )
            for hypothesis_id, evidence_list in grouped.items()
        ]

    def analyze_session_consistency(
        self,
        db: Session,
        session_id: UUID,
        *,
        candidates: list[CandidateHypothesis],
    ) -> list[dict[str, Any]]:
        """Task 022: structural evidence-consistency signal per candidate.

        Unlike ``summarize_session`` (Task 021), this always returns exactly
        one entry per candidate passed in — including candidates with zero
        persisted evidence — since "no evidence yet" is itself a signal a
        caller needs to see. Read-only: consumes the same persisted
        ``EvaluatedEvidence`` rows and does not evaluate or write anything.
        """
        all_evidence = self.repository.list_all_by_session(db, session_id)

        grouped: dict[UUID, list[EvaluatedEvidence]] = defaultdict(list)
        for evidence in all_evidence:
            grouped[evidence.hypothesis_id].append(evidence)

        return [
            self._analyze_hypothesis(
                hypothesis_id=candidate.id,
                hypothesis_name=candidate.name,
                evidence_list=grouped.get(candidate.id, []),
            )
            for candidate in candidates
        ]

    @staticmethod
    def _analyze_hypothesis(
        hypothesis_id: UUID,
        hypothesis_name: str,
        evidence_list: list[EvaluatedEvidence],
    ) -> dict[str, Any]:
        summary = EvidenceAggregationService._summarize_hypothesis(
            hypothesis_id=hypothesis_id,
            hypothesis_name=hypothesis_name,
            evidence_list=evidence_list,
        )

        total = summary["total_evidence_items"]
        support_count = (
            summary["supporting_evidence_count"]
            + summary["strongly_supporting_evidence_count"]
        )
        contradiction_count = (
            summary["contradicting_evidence_count"]
            + summary["strongly_contradicting_evidence_count"]
        )
        neutral_count = summary["neutral_or_unknown_count"]

        has_supporting = support_count > 0
        has_contradicting = contradiction_count > 0
        has_mixed = has_supporting and has_contradicting
        has_evidence = total > 0

        if total == 0:
            consistency = CONSISTENCY_NO_EVIDENCE
        elif has_mixed:
            # Checked before net_contribution ever enters the picture:
            # equal support and contradiction is a structural conflict,
            # not a signal that cancels out to neutral.
            consistency = CONSISTENCY_MIXED
        elif has_supporting:
            consistency = CONSISTENCY_SUPPORT_ONLY
        elif has_contradicting:
            consistency = CONSISTENCY_CONTRADICTION_ONLY
        else:
            consistency = CONSISTENCY_NEUTRAL_ONLY

        if total > 0:
            support_ratio = round(support_count / total, _RATIO_PRECISION)
            contradiction_ratio = round(contradiction_count / total, _RATIO_PRECISION)
            neutral_ratio = round(neutral_count / total, _RATIO_PRECISION)
        else:
            support_ratio = 0.0
            contradiction_ratio = 0.0
            neutral_ratio = 0.0

        return {
            **summary,
            "has_evidence": has_evidence,
            "has_supporting_evidence": has_supporting,
            "has_contradicting_evidence": has_contradicting,
            "has_mixed_evidence": has_mixed,
            "support_evidence_ratio": support_ratio,
            "contradiction_evidence_ratio": contradiction_ratio,
            "neutral_or_unknown_evidence_ratio": neutral_ratio,
            "evidence_consistency": consistency,
        }

    @staticmethod
    def _summarize_hypothesis(
        hypothesis_id: UUID,
        hypothesis_name: str,
        evidence_list: list[EvaluatedEvidence],
    ) -> dict[str, Any]:
        supporting_count = 0
        strongly_supporting_count = 0
        contradicting_count = 0
        strongly_contradicting_count = 0
        neutral_or_unknown_count = 0
        total_support_contribution = 0.0
        total_contradiction_contribution = 0.0

        for evidence in evidence_list:
            relationship = evidence.relationship
            if relationship == EvidenceRelationship.SUPPORTS.value:
                supporting_count += 1
                total_support_contribution += evidence.contribution
            elif relationship == EvidenceRelationship.STRONGLY_SUPPORTS.value:
                strongly_supporting_count += 1
                total_support_contribution += evidence.contribution
            elif relationship == EvidenceRelationship.CONTRADICTS.value:
                contradicting_count += 1
                total_contradiction_contribution += evidence.contribution
            elif relationship == EvidenceRelationship.STRONGLY_CONTRADICTS.value:
                strongly_contradicting_count += 1
                total_contradiction_contribution += evidence.contribution
            else:
                # NEUTRAL and UNKNOWN (and any relationship value this
                # service doesn't recognize) are counted but never
                # contribute to either side of the net.
                neutral_or_unknown_count += 1

        total_support_contribution = round(
            total_support_contribution, _CONTRIBUTION_PRECISION
        )
        total_contradiction_contribution = round(
            total_contradiction_contribution, _CONTRIBUTION_PRECISION
        )
        net_contribution = round(
            total_support_contribution - total_contradiction_contribution,
            _CONTRIBUTION_PRECISION,
        )

        return {
            "hypothesis_id": hypothesis_id,
            "hypothesis_name": hypothesis_name,
            "total_evidence_items": len(evidence_list),
            "supporting_evidence_count": supporting_count,
            "strongly_supporting_evidence_count": strongly_supporting_count,
            "contradicting_evidence_count": contradicting_count,
            "strongly_contradicting_evidence_count": strongly_contradicting_count,
            "neutral_or_unknown_count": neutral_or_unknown_count,
            "total_support_contribution": total_support_contribution,
            "total_contradiction_contribution": total_contradiction_contribution,
            "net_contribution": net_contribution,
        }
