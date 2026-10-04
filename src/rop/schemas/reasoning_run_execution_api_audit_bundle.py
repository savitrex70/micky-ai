from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_run_execution_api_audit_package import (
    ReasoningRunExecutionApiAuditPackageRead,
)
from rop.schemas.reasoning_run_execution_api_audit_package_consistency import (
    ReasoningRunExecutionApiAuditPackageConsistencyRead,
)


class ReasoningRunExecutionApiAuditBundleRead(BaseModel):
    """Task 053: Task 051 package plus its Task 052 audit, in one bundle.

    Bundles a Task 051 ``ReasoningRunExecutionApiAuditPackageRead``
    with the Task 052 ``ReasoningRunExecutionApiAuditPackageConsistencyRead``
    that audits it. Both nested results are the exact canonical outputs
    of their owners, untouched.

    ``bundle_consistent`` derives exclusively from Task 052's
    ``package_consistent`` -- which answers "is the supplied Task 051
    package internally consistent?" -- never from Task 051's own
    ``package_consistent``, which answers a different question
    (whether Task 051 correctly bound the API response to its Task 050
    audit).

    No decision, winner, recommendation, diagnosis, treatment, action,
    probability, confidence, utility, or expected-outcome field
    appears anywhere in this schema. ``bundle_source`` is a fixed
    structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    bundle_consistent: bool
    session_id: UUID
    method: str
    path: str
    status_code: int
    api_audit_package: ReasoningRunExecutionApiAuditPackageRead
    api_audit_package_consistency: ReasoningRunExecutionApiAuditPackageConsistencyRead
    bundle_source: str
