"""Task 077: fully audited attestation API response package schema.

Binds the Task 075 attestation API response with its Task 076 independent
consistency audit into a deterministic, self-authenticating package. Pure
composition boundary only -- no new reasoning. ``package_consistent``
derives from the Task 076 audit's own ``response_consistent`` AND the
Task 075 response's own ``response_consistent``; a legitimate underlying
defect at any nested layer is preserved unchanged and never promoted to
a false success.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyRead,
)


class ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageRead(BaseModel):
    """Task 077: fully audited attestation API response package."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_id: UUID
    attestation_response: ReasoningHandoffFullyAuditedApiAuditAttestationResponseRead
    attestation_response_consistency: (
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyRead
    )
    package_source: str
    package_fingerprint: str
    audited_package_fingerprint: str
