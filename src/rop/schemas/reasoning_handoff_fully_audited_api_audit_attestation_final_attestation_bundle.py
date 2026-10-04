"""Task 085: fully audited final attestation package bundle schema.

Binds the Task 083 final attestation package with its Task 084
independent consistency audit into a single deterministic,
self-authenticating audit bundle. Pure composition boundary; no new
reasoning is introduced here, and any legitimate underlying defect is
preserved unchanged.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyRead,  # noqa: E501
)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleRead(
    BaseModel
):
    """Task 085: fully audited final attestation package audit bundle."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    bundle_consistent: bool
    session_id: UUID
    final_attestation_package: (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageRead
    )
    final_attestation_package_consistency: ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyRead  # noqa: E501
    bundle_source: str
    bundle_fingerprint: str
    audited_bundle_fingerprint: str
