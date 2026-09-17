from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DecisionCandidateSelectionRead(BaseModel):
    """Task 035: the set of candidates forwarded into the decision layer.

    A deterministic, read-only selection boundary. When Task 034's
    decision input is eligible, every already-established candidate is
    forwarded in the exact order supplied by the Task 031 decision
    context's differential; when it is not eligible, no candidate is
    forwarded. This contract never selects a preferred candidate,
    ranks, scores, breaks ties, or produces a winner, diagnosis,
    recommendation, probability, or confidence. ``selection_source``
    is a fixed structural-contract identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    selection_available: bool
    eligible_candidate_count: int
    eligible_candidate_ids: list[UUID]
    eligible_candidate_names: list[str]
    all_candidates_forwarded: bool
    candidate_order_preserved: bool
    selection_source: str
