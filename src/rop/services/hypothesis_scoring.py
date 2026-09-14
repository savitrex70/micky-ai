from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.evidence_aggregation import EvidenceAggregationService

_SCORE_PRECISION = 4

SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION = "NET_EVIDENCE_CONTRIBUTION"


class HypothesisScoringService:
    """Task 023: deterministic hypothesis-scoring foundation.

    Converts the Task 021/022 evidence-derived information into a
    transparent, deterministic score per candidate hypothesis. This is
    the beginning of hypothesis scoring, not differential ranking: it
    does not rank hypotheses against one another, select a winner, or
    produce a diagnosis. The score is simply a computational
    representation of the evidence currently stored for a hypothesis.

    This service does not re-evaluate evidence, does not recompute
    Task 021/022 aggregation, and does not query observations/entities.
    It obtains Task 022's per-candidate analysis (which already carries
    Task 021's contribution totals) and derives a score from it, so
    ``_summarize_hypothesis``/``_analyze_hypothesis`` logic is never
    duplicated here.

    The scoring formula itself lives in ``_calculate_score``, kept
    isolated so a later task can replace it with a more sophisticated
    strategy without rewriting the API, evidence evaluation, or
    evidence aggregation layers.
    """

    def __init__(
        self, aggregation_service: EvidenceAggregationService | None = None
    ) -> None:
        self.aggregation_service = aggregation_service or EvidenceAggregationService()

    def score_session(
        self,
        db: Session,
        session_id: UUID,
        candidates: list[CandidateHypothesis],
    ) -> list[dict[str, Any]]:
        """Return one deterministic score per candidate, in candidate order.

        Every candidate passed in receives a result — including
        candidates with no persisted evidence, which score 0.0 with
        ``evidence_consistency == "NO_EVIDENCE"`` — because Task 022's
        ``analyze_session_consistency`` already guarantees exactly one
        entry per candidate. Read-only: never writes to the database.
        """
        analyses = self.aggregation_service.analyze_session_consistency(
            db, session_id, candidates=candidates
        )
        return [self._score_hypothesis(analysis) for analysis in analyses]

    @staticmethod
    def _calculate_score(net_contribution: float) -> float:
        """Task 023 scoring formula.

        hypothesis_score = net_contribution

        Task 021 already defines
        ``net_contribution = total_support_contribution -
        total_contradiction_contribution``, so this is intentionally the
        simplest possible scoring strategy: it establishes the scoring
        architecture rather than optimizing the formula. A positive
        score means stored support currently outweighs contradiction; a
        negative score means the reverse; zero means they cancel out or
        there is no evidence yet. It is not a probability, a percentage,
        or a diagnostic confidence, and it is not clamped to any range.
        """
        return round(net_contribution, _SCORE_PRECISION)

    @staticmethod
    def _score_hypothesis(analysis: dict[str, Any]) -> dict[str, Any]:
        hypothesis_score = HypothesisScoringService._calculate_score(
            analysis["net_contribution"]
        )

        return {
            "hypothesis_id": analysis["hypothesis_id"],
            "hypothesis_name": analysis["hypothesis_name"],
            "hypothesis_score": hypothesis_score,
            "score_source": SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
            "evidence_consistency": analysis["evidence_consistency"],
            "total_evidence_items": analysis["total_evidence_items"],
            "total_support_contribution": analysis["total_support_contribution"],
            "total_contradiction_contribution": analysis[
                "total_contradiction_contribution"
            ],
            "net_contribution": analysis["net_contribution"],
            "has_evidence": analysis["has_evidence"],
            "has_mixed_evidence": analysis["has_mixed_evidence"],
        }
