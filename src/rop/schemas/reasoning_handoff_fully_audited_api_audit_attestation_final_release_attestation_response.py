"""Task 099: fully audited final release attestation API response.

Composes the complete Task 097 final release attestation (which itself
binds the Task 095 response bundle with the Task 096 independent
consistency audit) with the complete Task 098 independent consistency
audit of that exact attestation, plus the session identity and a fixed
Task 099 source identifier.

``response_consistent`` derives exclusively from Task 098's
``final_attestation_consistent`` -- which answers "is the Task 097
release attestation internally consistent?" -- never from Task 097's own
``final_attestation_consistent``, which answers a different question
(does the bundle and its consistency audit form a coherent release
attestation?). A legitimate underlying defect reported anywhere in Tasks
055-098 is preserved unchanged and never converted into a false success.

This is a thin, additive, read-only API boundary only, not a new
reasoning engine. No decision, diagnosis, treatment, probability,
utility, or confidence semantics, and no external vendor or model
dependency, appears anywhere in this schema. ``response_source`` is a
fixed structural identifier.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyRead,  # noqa: E501
)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseRead(  # noqa: E501
    BaseModel
):
    """Task 099: fully audited final release attestation API response."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    response_consistent: bool
    session_id: UUID
    final_release_attestation: (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationRead
    )
    final_release_attestation_consistency: ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyRead  # noqa: E501
    response_source: str
