from pydantic import BaseModel, ConfigDict


class DifferentialRankingSummaryRead(BaseModel):
    """Task 028: session-level structural summary of the ranked differential.

    A derived view over Task 027's ranked differential
    (``DifferentialRankRead`` entries) — it describes the *shape* of
    the differential as a whole (how many candidates, how many
    distinct scores, how spread out and how tied they are), never
    which hypothesis is correct. This is still purely structural: no
    winner, no probability, no confidence, no clinical decision.

    An empty differential (a session with no candidates) still
    produces a fully defined summary: counts are ``0``/``False`` and
    every score-derived field is ``None``.
    """

    model_config = ConfigDict(from_attributes=True)

    total_candidates: int
    distinct_score_groups: int
    top_rank: int | None
    highest_score: float | None
    lowest_score: float | None
    score_range: float | None
    tied_candidate_count: int
    tie_group_count: int
    largest_tie_group_size: int
    has_any_ties: bool
