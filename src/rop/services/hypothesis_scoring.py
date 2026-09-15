from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import CandidateHypothesis
from rop.services.evidence_aggregation import (
    CONSISTENCY_CONTRADICTION_ONLY,
    CONSISTENCY_MIXED,
    CONSISTENCY_NEUTRAL_ONLY,
    CONSISTENCY_NO_EVIDENCE,
    CONSISTENCY_SUPPORT_ONLY,
    EvidenceAggregationService,
)

_SCORE_PRECISION = 4

SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION = "NET_EVIDENCE_CONTRIBUTION"

# Task 024: score direction values.
SCORE_DIRECTION_POSITIVE = "POSITIVE"
SCORE_DIRECTION_NEGATIVE = "NEGATIVE"
SCORE_DIRECTION_ZERO = "ZERO"

# Task 024: evidence-position values (score-facing interpretation layer).
# Deliberately separate from Task 022's ``evidence_consistency`` — see
# ``_determine_evidence_position`` for why the two are allowed to map
# closely without being the same field.
EVIDENCE_POSITION_UNSUPPORTED = "UNSUPPORTED"
EVIDENCE_POSITION_SUPPORTING = "SUPPORTING"
EVIDENCE_POSITION_CONTRADICTED = "CONTRADICTED"
EVIDENCE_POSITION_MIXED = "MIXED"
EVIDENCE_POSITION_NEUTRAL = "NEUTRAL"

_CONSISTENCY_TO_EVIDENCE_POSITION = {
    CONSISTENCY_NO_EVIDENCE: EVIDENCE_POSITION_UNSUPPORTED,
    CONSISTENCY_SUPPORT_ONLY: EVIDENCE_POSITION_SUPPORTING,
    CONSISTENCY_CONTRADICTION_ONLY: EVIDENCE_POSITION_CONTRADICTED,
    CONSISTENCY_MIXED: EVIDENCE_POSITION_MIXED,
    CONSISTENCY_NEUTRAL_ONLY: EVIDENCE_POSITION_NEUTRAL,
}


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

    Task 024 extends this with a structural interpretation layer around
    the same unchanged score: score direction, evidence coverage,
    informative-evidence ratio, support-to-contradiction ratio, and an
    evidence-position classification. None of this changes
    ``hypothesis_score`` (still ``net_contribution``) or Task 022's
    ``evidence_consistency`` — it only derives additional read-only
    fields from the same per-candidate analysis. Each derivation lives
    in its own isolated private method (``_determine_score_direction``,
    ``_calculate_evidence_coverage``, ``_calculate_informative_ratio``,
    ``_calculate_support_to_contradiction_ratio``,
    ``_determine_evidence_position``) so a later task can replace any
    one of them — most notably the TEMPORARY evidence-coverage
    definition below — without touching the others or the API.
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
    def _determine_score_direction(hypothesis_score: float) -> str:
        """Task 024: structural sign of the unchanged score.

        POSITIVE when hypothesis_score > 0, NEGATIVE when < 0, otherwise
        ZERO. This is not a true/false diagnosis state: ZERO can mean no
        evidence at all, exactly balanced support and contradiction, or
        any other structural reason the net contribution lands on zero.
        Callers must consult ``evidence_consistency``/``has_evidence`` to
        tell those cases apart — this field alone does not.
        """
        if hypothesis_score > 0:
            return SCORE_DIRECTION_POSITIVE
        if hypothesis_score < 0:
            return SCORE_DIRECTION_NEGATIVE
        return SCORE_DIRECTION_ZERO

    @staticmethod
    def _calculate_evidence_coverage(total_evidence_items: int) -> float:
        """Task 024 TEMPORARY evidence coverage definition.

        ROP has no formally defined "maximum possible evidence items"
        for a hypothesis yet, so this deliberately does NOT compute a
        true coverage ratio. It only answers a much narrower structural
        question: "has this candidate received any evaluated evidence
        at all?" — 0.0 when ``total_evidence_items == 0``, else 1.0.

        This is NOT a measure of clinical completeness, investigation
        adequacy, or evidence quality, and must be replaced once ROP
        defines a real evidence-requirement model. Isolated here so that
        replacement only touches this one method.
        """
        return 1.0 if total_evidence_items > 0 else 0.0

    @staticmethod
    def _calculate_informative_ratio(analysis: dict[str, Any]) -> float:
        """Task 024: share of persisted evidence that is informative.

        Informative evidence is supporting + strongly-supporting +
        contradicting + strongly-contradicting evidence — i.e. every
        row that actually moved ``net_contribution``. Neutral/unknown
        evidence is persisted but uninformative, so it lowers this
        ratio. 0.0 when there is no evidence at all.
        """
        total = analysis["total_evidence_items"]
        if total == 0:
            return 0.0

        informative_evidence = (
            analysis["supporting_evidence_count"]
            + analysis["strongly_supporting_evidence_count"]
            + analysis["contradicting_evidence_count"]
            + analysis["strongly_contradicting_evidence_count"]
        )
        return round(informative_evidence / total, _SCORE_PRECISION)

    @staticmethod
    def _calculate_support_to_contradiction_ratio(
        total_support_contribution: float,
        total_contradiction_contribution: float,
    ) -> float | None:
        """Task 024: support/contradiction ratio from contributions.

        Deliberately uses Task 021's contribution totals, not raw
        evidence counts — a single strong piece of evidence should not
        be treated the same as a single weak one. Never returns
        infinity: contradiction contribution of 0 always yields None,
        whether or not there is support contribution, and both being
        zero also yields None.
        """
        if total_contradiction_contribution > 0:
            return round(
                total_support_contribution / total_contradiction_contribution,
                _SCORE_PRECISION,
            )
        if total_contradiction_contribution == 0 and total_support_contribution > 0:
            return None
        return None

    @staticmethod
    def _determine_evidence_position(evidence_consistency: str) -> str:
        """Task 024: score-facing interpretation of the evidence.

        Mirrors Task 022's ``evidence_consistency`` classification by
        design (UNSUPPORTED/SUPPORTING/CONTRADICTED/MIXED/NEUTRAL vs.
        NO_EVIDENCE/SUPPORT_ONLY/CONTRADICTION_ONLY/MIXED/NEUTRAL_ONLY)
        but is kept as its own field rather than reusing or renaming
        ``evidence_consistency``, since Task 022's value remains the
        structural consistency signal and this is the Task 024 scoring
        layer's own interpretation of it. The two are allowed to map
        closely without being merged.
        """
        return _CONSISTENCY_TO_EVIDENCE_POSITION.get(
            evidence_consistency, EVIDENCE_POSITION_UNSUPPORTED
        )

    @staticmethod
    def _score_hypothesis(analysis: dict[str, Any]) -> dict[str, Any]:
        hypothesis_score = HypothesisScoringService._calculate_score(
            analysis["net_contribution"]
        )
        total_support_contribution = analysis["total_support_contribution"]
        total_contradiction_contribution = analysis["total_contradiction_contribution"]
        evidence_consistency = analysis["evidence_consistency"]

        return {
            "hypothesis_id": analysis["hypothesis_id"],
            "hypothesis_name": analysis["hypothesis_name"],
            "hypothesis_score": hypothesis_score,
            "score_source": SCORE_SOURCE_NET_EVIDENCE_CONTRIBUTION,
            "evidence_consistency": evidence_consistency,
            "total_evidence_items": analysis["total_evidence_items"],
            "total_support_contribution": total_support_contribution,
            "total_contradiction_contribution": total_contradiction_contribution,
            "net_contribution": analysis["net_contribution"],
            "has_evidence": analysis["has_evidence"],
            "has_mixed_evidence": analysis["has_mixed_evidence"],
            "score_direction": HypothesisScoringService._determine_score_direction(
                hypothesis_score
            ),
            "evidence_coverage_ratio": (
                HypothesisScoringService._calculate_evidence_coverage(
                    analysis["total_evidence_items"]
                )
            ),
            "informative_evidence_ratio": (
                HypothesisScoringService._calculate_informative_ratio(analysis)
            ),
            "support_to_contradiction_ratio": (
                HypothesisScoringService._calculate_support_to_contradiction_ratio(
                    total_support_contribution, total_contradiction_contribution
                )
            ),
            "evidence_position": HypothesisScoringService._determine_evidence_position(
                evidence_consistency
            ),
        }
