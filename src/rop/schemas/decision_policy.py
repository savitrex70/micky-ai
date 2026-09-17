from pydantic import BaseModel, ConfigDict


class DecisionPolicyRead(BaseModel):
    """Task 038: the explicit decision policy contract.

    Defines the rules a future decision-execution layer is permitted to
    apply to a Task 037 ``DecisionInputBundleRead``. This is a contract
    only -- it does not execute the policy, select a candidate, rank
    candidates, break ties, or produce a decision. There is no winner,
    best candidate, diagnosis, recommendation, probability, confidence,
    or utility anywhere in this schema. ``policy_source`` is a fixed
    structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    policy_id: str
    policy_version: str
    policy_name: str
    required_candidate_count: int | None
    allowed_selection_mode: str
    required_criteria_behavior: str
    tie_behavior: str
    insufficient_input_behavior: str
    incomplete_input_behavior: str
    policy_source: str
