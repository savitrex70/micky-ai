from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DifferentialRankRead(BaseModel):
    """Task 026: one ranked entry in a session's differential ranking.

    A derived view over Task 025's hypothesis-score contract
    (``HypothesisScoreRead``), plus a ``rank`` assigned by
    ``DifferentialRankingService``. Ranking is purely a relative
    ordering of already-computed, unchanged ``hypothesis_score``
    values — descending, with competition ranking for ties (e.g.
    1, 1, 3 — never dense 1, 1, 2). This is differential ranking only:
    not diagnosis selection, not a winner, not a probability, not a
    confidence, not a treatment recommendation. Every candidate passed
    to the ranking service remains present; none are dropped or
    reordered independently of score.

    All non-``rank`` fields are preserved exactly from the Task 025
    contract — ranking never alters a score or any of its supporting
    fields.
    """

    model_config = ConfigDict(from_attributes=True)

    rank: int
    hypothesis_id: UUID
    hypothesis_name: str
    hypothesis_score: float
    score_direction: str
    evidence_consistency: str
    evidence_position: str
    has_evidence: bool
    has_mixed_evidence: bool
    total_evidence_items: int
    total_support_contribution: float
    total_contradiction_contribution: float
    net_contribution: float
    evidence_coverage_ratio: float
    informative_evidence_ratio: float
    support_to_contradiction_ratio: float | None
