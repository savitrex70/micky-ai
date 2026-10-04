"""Task 073: fully audited attestation package schema."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation import (
    ReasoningHandoffFullyAuditedApiAuditAttestationRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyRead,
)


class ReasoningHandoffFullyAuditedApiAuditAttestationPackageRead(BaseModel):
    """Task 073: fully audited API audit attestation package."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_id: UUID
    attestation: ReasoningHandoffFullyAuditedApiAuditAttestationRead
    attestation_consistency: (
        ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyRead
    )
    package_source: str
    package_fingerprint: str
    # Self-authenticating provenance: mandatory, a lowercase 64-char
    # SHA-256 hex string, and exactly equal to package_fingerprint.
    audited_package_fingerprint: str
