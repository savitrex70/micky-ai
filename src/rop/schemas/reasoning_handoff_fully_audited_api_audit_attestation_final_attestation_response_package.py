"""Task 093: fully audited final-attestation response package schema.

Binds the Task 087 final-attestation API response with its Task 088
independent consistency audit into a deterministic, self-authenticating
package. Pure composition boundary only -- no new reasoning.
``package_consistent`` derives from the Task 088 audit's own
``response_consistent`` AND the Task 087 response's own
``response_consistent``; a legitimate underlying defect at any nested
layer is preserved unchanged and never promoted to a false success.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyRead,  # noqa: E501
)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageRead(  # noqa: E501
    BaseModel
):
    """Task 093: fully audited final-attestation response package."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_id: UUID
    response: ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseRead  # noqa: E501
    response_consistency: ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyRead  # noqa: E501
    package_source: str
    package_fingerprint: str
    audited_package_fingerprint: str
