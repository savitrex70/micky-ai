"""Task 063: reasoning handoff API audit bundle.

Composes the complete Task 061 audited API package with the complete
Task 062 consistency audit of that exact package, plus the session
identity and a fixed Task 063 source identifier.

``bundle_consistent`` derives exclusively from Task 062's
``package_consistent`` -- which answers "is the Task 061 package
internally consistent?" -- never from Task 061's own
``package_consistent``, which answers a different question (does the
Task 061 package correctly bind the response and its audit?). A valid
Task 061 package whose underlying handoff legitimately reports
``handoff_consistent = False`` can still produce a Task 062 audit with
``package_consistent = True``, and therefore a Task 063 bundle with
``bundle_consistent = True``.

No decision, winner, recommendation, diagnosis, treatment, action,
probability, confidence, utility, or expected-outcome field appears
anywhere in this schema. ``bundle_source`` is a fixed structural
identifier.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_api_audit_package import (
    ReasoningHandoffApiAuditPackageRead,
)
from rop.schemas.reasoning_handoff_api_audit_package_consistency import (
    ReasoningHandoffApiAuditPackageConsistencyRead,
)


class ReasoningHandoffApiAuditBundleRead(BaseModel):
    """Task 063: reasoning handoff API audit bundle."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    bundle_consistent: bool
    session_id: UUID
    api_audit_package: ReasoningHandoffApiAuditPackageRead
    api_audit_package_consistency: ReasoningHandoffApiAuditPackageConsistencyRead
    bundle_source: str
