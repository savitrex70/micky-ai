from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DecisionSelectedCandidateRead(BaseModel):
    """Task 039: the candidate selected by executing the decision policy.

    A verbatim projection of the corresponding Task 035/036 candidate
    metadata (identity, name, rank, score). No probability, confidence,
    utility, recommendation, diagnosis, or action appears here. ``rank``
    and ``score`` are the existing upstream values, never recomputed.
    """

    model_config = ConfigDict(from_attributes=True)

    hypothesis_id: UUID
    hypothesis_name: str
    rank: int
    score: float


class DecisionExecutionRead(BaseModel):
    """Task 039: the deterministic outcome of executing the Task 038 policy.

    The first boundary at which a candidate may be selected. Outcome is
    one of a fixed set of machine-readable identifiers; every field is
    derived only from the Task 037 decision-input bundle and the Task
    038 policy, with no new scoring, ranking, evidence interpretation,
    or domain-specific reasoning. There is no probability, confidence,
    utility, recommendation, diagnosis, treatment, action, or
    expected-outcome field anywhere in this schema.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    outcome: str
    selected_candidate: DecisionSelectedCandidateRead | None
    eligible_candidate_count: int
    eligible_candidate_ids: list[UUID]
    policy_id: str
    policy_version: str
    decision_execution_source: str
