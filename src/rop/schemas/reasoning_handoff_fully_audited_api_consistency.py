"""Task 066: independent audit of a Task 065 fully audited API response.

Audits the HTTP response produced by the Task 065
``GET /sessions/{session_id}/reasoning-handoff/fully-audited`` route: its
transport metadata (method, route shape, status), its session identity,
its exact response shape, the nested Task 063 audit bundle, the nested
Task 062 package audit carried inside that bundle, the fixed source
identifiers, and the provenance binding between the nested Task 062
audit and the nested Task 061 package.

Provenance note: the Task 065 response body contains no Task 064 audit.
Task 063's own validator -- reused here, never reimplemented -- is what
proves the nested Task 061 package / Task 062 audit / bundle relationship.
The nested *audit* that the body does carry is Task 062's audit of the
Task 061 package, which is validated independently here and whose
``audited_package_fingerprint`` is bound to the nested package by an
independently recomputed fingerprint. A body that reports
``bundle_consistent = False`` because the underlying handoff was
legitimately inconsistent is still a faithful API response, so this
audit reports ``api_consistent = True`` for it.

No decision, diagnosis, treatment, probability, utility, or confidence
semantics, and no external vendor or model client dependency, appears
anywhere in this schema. ``api_consistency_source`` is a fixed
structural identifier.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiConsistencyRead(BaseModel):
    """Task 066: independent audit of a Task 065 API response."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    api_consistent: bool
    method_consistent: bool
    path_consistent: bool
    status_consistent: bool
    session_consistent: bool
    response_shape_consistent: bool
    nested_bundle_consistent: bool
    nested_package_audit_consistent: bool
    provenance_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    api_consistency_source: str

    # Provenance: binds the audit to the exact HTTP metadata and response
    # body it inspected. Enables downstream composition layers (e.g.
    # Task 067) to verify that a supplied audit corresponds to the
    # supplied response without re-invoking Task 066.
    audited_session_id: str | None
    audited_method: str | None
    audited_path: str | None
    audited_status_code: int | None
    audited_response_fingerprint: str | None
