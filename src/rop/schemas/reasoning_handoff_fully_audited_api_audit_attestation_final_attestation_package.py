"""Task 083: final attestation package schema.

Binds the Task 081 final attestation with its Task 082 independent
consistency audit into a deterministic, self-authenticating package. Pure
composition boundary only -- no new reasoning. ``package_consistent``
derives from the Task 082 audit's own ``final_attestation_consistent``;
a legitimate underlying defect at any nested layer is preserved unchanged
and never promoted to a false success.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyRead,  # noqa: E501
)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageRead(
    BaseModel
):
    """Task 083: final attestation package."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_id: UUID
    final_attestation: (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationRead
    )
    final_attestation_consistency: (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyRead
    )
    package_source: str
    package_fingerprint: str
    audited_package_fingerprint: str
