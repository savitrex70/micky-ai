from pydantic import BaseModel, ConfigDict


class DifferentialRankingConsistencyRead(BaseModel):
    """Task 029: structural completeness/consistency contract.

    A derived view that cross-checks Task 027's ranked differential
    (``DifferentialRankRead`` entries) against Task 028's structural
    summary (``DifferentialRankingSummaryRead``) and reports whether
    they describe the same differential state. It never recalculates
    evidence or scores, never introduces a second ranking algorithm,
    and never mutates either input — it only independently re-derives
    each summary/separation value from the ranked entries and compares
    it against what Tasks 027/028 already produced.

    This is still purely structural: no winner selection, no
    diagnosis selection, no probability, no confidence, no treatment
    recommendation, and no decision-making. ``consistency_source`` is
    a fixed structural-contract identifier, never a confidence score.

    An empty differential (a session with no candidates) is a valid
    state: every boolean field is ``True`` because two empty
    structures trivially agree.
    """

    model_config = ConfigDict(from_attributes=True)

    consistent: bool
    candidate_count_matches: bool
    score_groups_match: bool
    tie_statistics_match: bool
    score_range_matches: bool
    rank_structure_matches: bool
    separation_metadata_matches: bool
    summary_consistent: bool
    consistency_source: str
