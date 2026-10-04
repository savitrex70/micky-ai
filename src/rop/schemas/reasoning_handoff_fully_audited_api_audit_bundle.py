"""Task 069: fully audited reasoning handoff API audit bundle.

Composes the complete Task 067 audited API package with the complete Task
068 consistency audit of that exact package, plus the session identity
and a fixed Task 069 source identifier.

``bundle_consistent`` derives exclusively from Task 068's
``package_consistent`` -- which answers "is the Task 067 package
internally consistent?" -- never from Task 067's own
``package_consistent``, which answers a different question (does the Task
067 package correctly bind the API response and its audit?). A valid Task
067 package whose underlying audit legitimately reports a defect can
still produce a Task 068 audit with ``package_consistent = True``, and
therefore a Task 069 bundle with ``bundle_consistent = True``.

This is a composition boundary, not a new reasoning engine. No decision,
diagnosis, treatment, probability, utility, or confidence semantics, and
no external vendor or model client dependency, appears anywhere in this
schema. ``bundle_source`` is a fixed structural identifier.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_package import (
    ReasoningHandoffFullyAuditedApiAuditPackageRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_package_consistency import (
    ReasoningHandoffFullyAuditedApiAuditPackageConsistencyRead,
)


class ReasoningHandoffFullyAuditedApiAuditBundleRead(BaseModel):
    """Task 069: fully audited reasoning handoff API audit bundle."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    bundle_consistent: bool
    session_id: UUID
    api_audit_package: ReasoningHandoffFullyAuditedApiAuditPackageRead
    api_audit_package_consistency: (
        ReasoningHandoffFullyAuditedApiAuditPackageConsistencyRead
    )
    bundle_source: str
    audited_bundle_fingerprint: str
