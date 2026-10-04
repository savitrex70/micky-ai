from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DecisionCandidateRead(BaseModel):
    """Task 035: one candidate in the decision candidate-set handoff.

    A verbatim projection of the corresponding entry in the Task 031
    ``DecisionContextRead.differential``. ``score`` is the upstream
    ``hypothesis_score`` copied unchanged; every other field is copied
    unchanged as well. This is a package boundary, not a
    re-interpretation: no scoring, ranking, tie-breaking, or selection
    happens here, and no candidate is preferred over another.
    """

    model_config = ConfigDict(from_attributes=True)

    hypothesis_id: UUID
    hypothesis_name: str
    rank: int
    score: float
    is_tied: bool
    tie_group_size: int
    score_gap_to_next_higher: float | None
    score_gap_to_next_lower: float | None


class DecisionCandidateSetRead(BaseModel):
    """Task 035: the stable candidate-set handoff contract.

    Packages the already-validated Task 031 candidate set into one
    deterministic downstream contract. When Task 034's decision input
    is eligible AND the Task 031 context is available AND decision
    ready, every candidate from the differential is forwarded in the
    exact original order; otherwise the set is empty and ``available``
    is ``False``. There is no winner, best candidate, diagnosis,
    recommendation, probability, confidence, utility, weighted score,
    expected outcome, or treatment anywhere in this contract.
    ``candidate_set_source`` is a fixed structural-contract identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    candidate_count: int
    candidates: list[DecisionCandidateRead]
    candidate_order_preserved: bool
    candidate_set_complete: bool
    candidate_set_source: str
