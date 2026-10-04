from uuid import UUID

from pydantic import BaseModel, ConfigDict


class HypothesisScoreRead(BaseModel):
    """Task 023: deterministic hypothesis score for one candidate.

    A derived view over Task 022's evidence consistency/quality analysis
    (which itself derives from Task 021's evidence summary over Task
    020's persisted ``EvaluatedEvidence`` records). ``hypothesis_score``
    is currently ``net_contribution`` unchanged — a transparent,
    reproducible number, not a probability, percentage, or diagnostic
    confidence. This is a scoring foundation, not a ranked differential:
    candidates are not compared or ordered against one another here.

    Task 024 adds a structural interpretation layer around that same
    unchanged score: ``score_direction`` (sign of the score),
    ``evidence_coverage_ratio`` (TEMPORARY — 1.0 means only "has any
    evaluated evidence", not clinical completeness; see
    ``HypothesisScoringService._calculate_evidence_coverage``),
    ``informative_evidence_ratio`` (share of persisted evidence that is
    supporting/contradicting rather than neutral/unknown), and
    ``support_to_contradiction_ratio`` (contribution-based, ``None``
    when contradiction contribution is 0 to avoid division by zero —
    never infinity). ``evidence_position`` mirrors
    ``evidence_consistency`` by design but is kept as its own
    score-facing field rather than replacing it.
    """

    model_config = ConfigDict(from_attributes=True)

    hypothesis_id: UUID
    hypothesis_name: str
    hypothesis_score: float
    score_source: str
    evidence_consistency: str
    total_evidence_items: int
    total_support_contribution: float
    total_contradiction_contribution: float
    net_contribution: float
    has_evidence: bool
    has_mixed_evidence: bool
    score_direction: str
    evidence_coverage_ratio: float
    informative_evidence_ratio: float
    support_to_contradiction_ratio: float | None
    evidence_position: str
