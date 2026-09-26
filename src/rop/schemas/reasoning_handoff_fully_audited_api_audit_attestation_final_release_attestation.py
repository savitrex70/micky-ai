"""Task 097: final release attestation over the Task 095/096 bundle and audit.

Binds the Task 095 response audit bundle with its Task 096 independent
consistency audit into a single deterministic, self-authenticating terminal
release attestation. Pure composition boundary; no new reasoning is
introduced here, and any legitimate underlying defect is preserved
unchanged. This is the final emitted artifact consumers should rely on
after verification.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleRead,  # noqa: E501
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyRead,  # noqa: E501
)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationRead(  # noqa: E501
    BaseModel
):
    """Task 097: terminal release attestation of the audited bundle chain."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    final_attestation_consistent: bool
    session_id: UUID
    response_bundle: ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleRead  # noqa: E501
    response_bundle_consistency: ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyRead  # noqa: E501
    final_attestation_source: str
    final_attestation_fingerprint: str
    audited_final_attestation_fingerprint: str
