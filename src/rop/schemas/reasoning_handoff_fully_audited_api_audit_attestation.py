"""Task 071: fully audited reasoning handoff API audit attestation.

Binds the Task 069 audited API audit bundle with its Task 070
consistency audit into a final deterministic attestation. This is a
composition and provenance boundary only, not a new reasoning engine.

``attestation_consistent`` means the Task 069 bundle and Task 070
consistency audit form a coherent, correctly-provenanced attestation.
It does not mean the underlying API audit package is defect-free. A
legitimate Task 069 bundle may contain ``bundle_consistent = False``
provided Task 070 truthfully and coherently audits that state, and in
that case Task 071 may still produce ``attestation_consistent = True``
because the attestation itself is coherent.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_bundle import (
    ReasoningHandoffFullyAuditedApiAuditBundleRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_bundle_consistency import (
    ReasoningHandoffFullyAuditedApiAuditBundleConsistencyRead,
)


class ReasoningHandoffFullyAuditedApiAuditAttestationRead(BaseModel):
    """Task 071: final attestation over Task 069 bundle and Task 070 audit."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    attestation_consistent: bool
    session_id: UUID
    api_audit_bundle: ReasoningHandoffFullyAuditedApiAuditBundleRead
    api_audit_bundle_consistency: (
        ReasoningHandoffFullyAuditedApiAuditBundleConsistencyRead
    )
    attestation_source: str
    audited_attestation_fingerprint: str
