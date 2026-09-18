from pydantic import BaseModel, ConfigDict


class ReasoningRunExecutionBundleConsistencyRead(BaseModel):
    """Task 047: independent audit of a Task 046 execution + audit bundle.

    Audits the Task 046 bundle contract itself: verifies the nested
    Task 044 execution and Task 045 audit are each structurally valid,
    their session metadata agrees, the bundle's own
    ``bundle_consistent`` field mirrors the Task 045 audit verdict,
    and all three fixed source identifiers are correct.

    Note: Task 047's ``bundle_consistent`` means "is the Task 046
    bundle contract internally consistent?" -- NOT "did the reasoning
    succeed?". A bundle whose Task 046 ``bundle_consistent`` field is
    legitimately ``False`` can still produce a Task 047
    ``bundle_consistent = True``.

    No decision, winner, recommendation, diagnosis, treatment, action,
    probability, confidence, utility, or expected-outcome field
    appears anywhere in this schema. ``bundle_consistency_source`` is
    a fixed structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    bundle_consistent: bool
    session_consistent: bool
    nested_execution_consistent: bool
    nested_execution_audit_consistent: bool
    bundle_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    bundle_consistency_source: str
