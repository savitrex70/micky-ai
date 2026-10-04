"""Task 079: fully audited attestation response bundle schema.

Binds the Task 077 response package with its Task 078 independent consistency
audit into a single deterministic, self-authenticating audit bundle. Pure
composition boundary; no new reasoning is introduced here, and any
legitimate underlying defect is preserved unchanged.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_package_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageConsistencyRead,
)


class ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleRead(BaseModel):
    """Task 079: fully audited attestation response audit bundle."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    bundle_consistent: bool
    session_id: UUID
    response_package: ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageRead
    response_package_consistency: (
        ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageConsistencyRead
    )
    bundle_source: str
    bundle_fingerprint: str
    audited_bundle_fingerprint: str
