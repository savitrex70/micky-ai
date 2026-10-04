"""Task 081: final attestation of the fully audited response chain.

Binds the Task 079 response audit bundle with its Task 080 independent
consistency audit into a single deterministic, self-authenticating terminal
attestation. Pure composition boundary; no new reasoning is introduced
here, and any legitimate underlying defect is preserved unchanged. This is
the final emitted artifact consumers should rely on after verification.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyRead,
)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationRead(BaseModel):
    """Task 081: terminal fully-audited attestation of the response chain."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    final_attestation_consistent: bool
    session_id: UUID
    response_bundle: ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleRead
    response_bundle_consistency: (
        ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyRead
    )
    final_attestation_source: str
    final_attestation_fingerprint: str
    audited_final_attestation_fingerprint: str
