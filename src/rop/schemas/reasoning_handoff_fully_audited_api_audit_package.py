"""Task 067: fully audited reasoning handoff API audit package.

Packages the canonical Task 065 API response metadata and body
(``response``, a Task 063 ``ReasoningHandoffApiAuditBundleRead``) with the
Task 066 audit of that exact response (``api_consistency``), plus a
fingerprint binding the package to the exact response representation that
was audited.

``package_consistent`` derives exclusively from Task 066's
``api_consistent`` -- which answers "did the API response faithfully
represent the Task 063 bundle contract?" -- never from Task 063's own
``bundle_consistent``, which answers a different question (whether the
Task 062 audit found the Task 061 package internally consistent). A
valid response whose bundle legitimately reports
``bundle_consistent = False`` still yields ``package_consistent = True``.

No decision, diagnosis, treatment, probability, utility, or confidence
semantics, and no external vendor or model client dependency, appears
anywhere in this schema. ``package_source`` is a fixed structural
identifier.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.reasoning_handoff_api_audit_bundle import (
    ReasoningHandoffApiAuditBundleRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_consistency import (
    ReasoningHandoffFullyAuditedApiConsistencyRead,
)


class ReasoningHandoffFullyAuditedApiAuditPackageRead(BaseModel):
    """Task 067: fully audited reasoning handoff API audit package."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_id: UUID
    method: str
    path: str
    status_code: int
    response: ReasoningHandoffApiAuditBundleRead
    api_consistency: ReasoningHandoffFullyAuditedApiConsistencyRead
    package_source: str

    # Provenance: SHA-256 hex digest of the canonicalized Task 065
    # response body this package binds. Computed with the repository's
    # established canonical JSON approach and required to equal the
    # Task 066 audit's own fingerprint, so the package cannot be silently
    # rebound to a different response representation.
    audited_response_fingerprint: str
