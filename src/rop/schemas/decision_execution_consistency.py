from pydantic import BaseModel, ConfigDict


class DecisionExecutionConsistencyRead(BaseModel):
    """Task 040: independent consistency/audit of a Task 039 execution result.

    Verifies that the Task 039 decision-execution outcome is structurally
    and semantically consistent with the Task 037 decision-input bundle
    and the Task 038 decision policy. This is an audit contract only --
    it does not select a candidate, rerank, rescore, or alter the
    execution result. There is no winner, recommendation, diagnosis,
    treatment, action, probability, confidence, utility, or
    expected-outcome field anywhere in this schema. ``execution_source``
    is a fixed structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    execution_consistent: bool
    outcome_consistent: bool
    eligibility_consistent: bool
    selection_consistent: bool
    metadata_consistent: bool
    source_consistent: bool
    consistency_issues: list[str]
    execution_source: str
