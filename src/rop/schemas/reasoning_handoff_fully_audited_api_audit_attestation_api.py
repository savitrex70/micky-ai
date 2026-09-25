"""Task 075: fully audited reasoning handoff attestation API.

Exposes the final Task 073 attestation package and its Task 074
consistency audit as a session-level read-only API bundle. This is a
composition and provenance boundary only, not a new reasoning engine.

``api_consistent`` means the Task 073 package and Task 074 audit form a
coherent, correctly-provenanced API response. It does not mean the
underlying attestation is defect-free. A legitimate Task 071 attestation
may contain ``attestation_consistent = False`` provided Task 072
truthfully audits that state and Task 073/074 faithfully package and
audit it, and in that case Task 075 may still produce
``api_consistent = True`` because the API response itself is coherent.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyRead,
)


class ReasoningHandoffFullyAuditedApiAuditAttestationApiRead(BaseModel):
    """Task 075: final fully audited attestation API bundle."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    api_consistent: bool
    session_id: UUID
    attestation_package: ReasoningHandoffFullyAuditedApiAuditAttestationPackageRead
    attestation_package_consistency: (
        ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyRead
    )
    api_source: str
    audited_api_fingerprint: str
