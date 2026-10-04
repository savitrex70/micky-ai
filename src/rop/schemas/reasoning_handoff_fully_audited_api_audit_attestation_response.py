"""Task 075: fully audited reasoning handoff attestation API response.

Composes the complete Task 073 attestation package (which itself nests
the Task 071 attestation and Task 072 consistency audit) with the
complete Task 074 independent consistency audit of that exact package,
plus the session identity and a fixed Task 075 source identifier.

``response_consistent`` derives exclusively from Task 074's
``package_consistent`` -- which answers "is the Task 073 package
internally consistent?" -- never from Task 073's own
``package_consistent``, which answers a different question (does the
attestation and its consistency audit form a coherent package?). A
legitimate underlying defect reported anywhere in Tasks 071-074 is
preserved unchanged and never converted into a false success.

This is a thin, additive, read-only API boundary only, not a new
reasoning engine. No decision, diagnosis, treatment, probability,
utility, or confidence semantics, and no external vendor or model client
dependency, appears anywhere in this schema. ``response_source`` is a
fixed structural identifier.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyRead,
)


class ReasoningHandoffFullyAuditedApiAuditAttestationResponseRead(BaseModel):
    """Task 075: fully audited attestation API response."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    response_consistent: bool
    session_id: UUID
    attestation_package: ReasoningHandoffFullyAuditedApiAuditAttestationPackageRead
    attestation_package_consistency: (
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyRead
    )
    response_source: str
