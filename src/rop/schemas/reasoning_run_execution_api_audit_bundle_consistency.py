from pydantic import BaseModel, ConfigDict


class ReasoningRunExecutionApiAuditBundleConsistencyRead(BaseModel):
    """Task 054: independent audit of a Task 053 API audit bundle.

    Audits whether the supplied ReasoningRunExecutionApiAuditBundleRead
    is internally consistent: verifies its top-level HTTP metadata,
    validates the nested Task 051 package and Task 052 audit through
    their own validators, and independently recomputes the Task 051
    package fingerprint to prove that the Task 052 audit's provenance
    binds to the exact package embedded in the bundle.

    Note: Task 054's ``bundle_consistent`` means "is the supplied
    Task 053 bundle internally consistent as a bundle?". That is
    distinct from Task 053's ``bundle_consistent`` (which mirrors
    Task 052's verdict on the Task 051 package). A valid Task 053
    bundle can legitimately carry ``bundle_consistent = False`` while
    still being internally consistent and producing a Task 054 audit
    with ``bundle_consistent = True``.

    No decision, winner, recommendation, diagnosis, treatment, action,
    probability, confidence, utility, or expected-outcome field
    appears anywhere in this schema.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    bundle_consistent: bool
    session_consistent: bool
    method_consistent: bool
    path_consistent: bool
    status_consistent: bool
    nested_package_consistent: bool
    nested_package_audit_consistent: bool
    package_audit_provenance_consistent: bool
    bundle_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    bundle_consistency_source: str
