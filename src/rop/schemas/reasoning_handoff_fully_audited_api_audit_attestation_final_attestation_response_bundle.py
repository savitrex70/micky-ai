"""Task 095: fully audited final attestation response bundle schema.

Binds the Task 093 response package with its Task 094 independent consistency
audit into a single deterministic, self-authenticating audit bundle. Pure
composition boundary; no new reasoning is introduced here, and any
legitimate underlying defect is preserved unchanged.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageRead,  # noqa: E501
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyRead,  # noqa: E501
)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleRead(  # noqa: E501
    BaseModel
):
    """Task 095: fully audited final attestation response audit bundle."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    bundle_consistent: bool
    session_id: UUID
    response_package: ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageRead  # noqa: E501
    response_package_consistency: ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyRead  # noqa: E501
    bundle_source: str
    bundle_fingerprint: str
    audited_bundle_fingerprint: str
