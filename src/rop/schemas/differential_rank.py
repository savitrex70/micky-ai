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

    All Task 025/026 fields are preserved exactly — ranking never
    alters a score or any of its supporting fields.

    Task 027 adds derived separation metadata describing how this
    candidate's score relates to the others in the same ranking:
    ``is_tied``/``tie_group_size`` (whether and how many candidates
    share this exact normalized score) and
    ``score_gap_to_next_higher``/``score_gap_to_next_lower`` (the
    distance to the nearest strictly higher/lower *distinct* score,
    skipping over tied peers; ``None`` at the top/bottom of the
    ranking respectively). This is still structural only — not a
    winner, a probability, or a decision.
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
    is_tied: bool
    tie_group_size: int
    score_gap_to_next_higher: float | None
    score_gap_to_next_lower: float | None
