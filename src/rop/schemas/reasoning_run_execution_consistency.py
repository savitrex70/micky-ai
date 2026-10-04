from pydantic import BaseModel, ConfigDict


class ReasoningRunExecutionConsistencyRead(BaseModel):
    """Task 045: independent audit of a Task 044 execution result.

    Audits a supplied ReasoningRunExecutionRead against the Task 044
    execution contract, using Task 042's and Task 043's own validators
    for the nested results. It does not execute the reasoning workflow,
    touch the database, or supply the result -- the caller supplies the
    execution. ``execution_consistency_source`` is a fixed structural
    identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    execution_consistent: bool
    session_consistent: bool
    outcome_consistent: bool
    availability_consistent: bool
    stage_structure_consistent: bool
    stage_status_consistent: bool
    stage_count_consistent: bool
    completed_stage_count_consistent: bool
    nested_reasoning_run_consistent: bool
    nested_reasoning_run_audit_consistent: bool
    metadata_consistent: bool
    source_consistency: bool
    consistency_issues: list[str]
    execution_consistency_source: str
