"""Task 087: fully audited final-attestation bundle API response.

Composes the complete Task 085 final attestation bundle (which itself
binds the Task 083 final attestation package with the Task 084
independent consistency audit) with the complete Task 086 independent
consistency audit of that exact bundle, plus the session identity and a
fixed Task 087 source identifier.

``response_consistent`` derives exclusively from Task 086's
``bundle_consistent`` -- which answers "is the Task 085 bundle
internally consistent?" -- never from Task 085's own
``bundle_consistent``, which answers a different question (does the
package and its consistency audit form a coherent bundle?). A
legitimate underlying defect reported anywhere in Tasks 083-086 is
preserved unchanged and never converted into a false success.

This is a thin, additive, read-only API boundary only, not a new
reasoning engine. No decision, diagnosis, treatment, probability,
utility, or confidence semantics, and no external vendor or model
dependency, appears anywhere in this schema. ``response_source`` is a
fixed structural identifier.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyRead,  # noqa: E501
)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseRead(
    BaseModel
):
    """Task 087: fully audited final-attestation bundle API response."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    response_consistent: bool
    session_id: UUID
    final_attestation_bundle: (
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleRead
    )
    final_attestation_bundle_consistency: ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyRead  # noqa: E501
    response_source: str
