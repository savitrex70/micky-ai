from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_run_execution_audit_package import (
    ReasoningRunExecutionAuditPackageRead,
)
from rop.schemas.reasoning_run_execution_audit_package_api_consistency import (
    ReasoningRunExecutionAuditPackageApiConsistencyRead,
)


class ReasoningRunExecutionApiAuditPackageRead(BaseModel):
    """Task 051: fully audited API response package.

    Packages the canonical Task 049 API response metadata and body
    (``response``, a Task 048 ``ReasoningRunExecutionAuditPackageRead``)
    with the Task 050 audit of that response (``api_consistency``).

    ``package_consistent`` derives exclusively from Task 050's
    ``api_consistent`` -- which answers "did the API response
    faithfully represent the Task 048 package contract?" -- never from
    Task 048's own ``package_consistent``, which answers a different
    question (whether the underlying reasoning package was internally
    consistent).

    No decision, winner, recommendation, diagnosis, treatment, action,
    probability, confidence, utility, or expected-outcome field
    appears anywhere in this schema. ``package_source`` is a fixed
    structural identifier.
    """

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_id: UUID
    method: str
    path: str
    status_code: int
    response: ReasoningRunExecutionAuditPackageRead
    api_consistency: ReasoningRunExecutionAuditPackageApiConsistencyRead
    package_source: str
