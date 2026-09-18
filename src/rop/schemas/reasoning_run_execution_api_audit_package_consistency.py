from pydantic import BaseModel, ConfigDict


class ReasoningRunExecutionApiAuditPackageConsistencyRead(BaseModel):
    """Task 052: independent audit of a Task 051 API audit package.

    Audits whether the supplied ReasoningRunExecutionApiAuditPackageRead
    is internally consistent: verifies its top-level HTTP metadata,
    validates the nested Task 048 response package and Task 050 API
    consistency result via their own validators, and independently
    re-derives the Task 050 response fingerprint to prove that the
    audit's provenance binds to the supplied response.

    Note: Task 052's ``package_consistent`` means "is the Task 051
    package internally consistent?". That is distinct from Task 051's
    ``package_consistent`` (does the Task 051 package correctly bind
    the response and its audit?) and from Task 048's
    ``response.package_consistent`` (was the underlying audited
    execution package internally consistent?). A valid Task 051
    package can legitimately carry ``response.package_consistent
    = False`` alongside ``api_consistency.api_consistent = True`` and
    still produce a Task 052 audit with ``package_consistent = True``.

    No decision, winner, recommendation, diagnosis, treatment, action,
    probability, confidence, utility, or expected-outcome field
    appears anywhere in this schema.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_consistent: bool
    method_consistent: bool
    path_consistent: bool
    status_consistent: bool
    nested_response_consistent: bool
    nested_api_consistency_consistent: bool
    provenance_consistent: bool
    package_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    package_consistency_source: str
