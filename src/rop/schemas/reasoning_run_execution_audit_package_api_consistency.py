from pydantic import BaseModel, ConfigDict


class ReasoningRunExecutionAuditPackageApiConsistencyRead(BaseModel):
    """Task 050: independent audit of a Task 049 API response.

    Verifies that a successful Task 049 HTTP response faithfully
    represents the canonical Task 048 fully audited execution package.

    Note: Task 050's ``api_consistent`` means "did the API response
    faithfully represent the Task 048 package contract?" -- NOT "was
    the underlying reasoning or package consistent?". A valid API
    response whose Task 048 ``package_consistent`` is legitimately
    ``False`` still produces ``api_consistent = True``.

    No decision, winner, recommendation, diagnosis, treatment, action,
    probability, confidence, utility, or expected-outcome field
    appears anywhere in this schema. ``api_consistency_source`` is a
    fixed structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    api_consistent: bool
    method_consistent: bool
    path_consistent: bool
    status_consistent: bool
    session_consistent: bool
    response_shape_consistent: bool
    nested_package_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    api_consistency_source: str
