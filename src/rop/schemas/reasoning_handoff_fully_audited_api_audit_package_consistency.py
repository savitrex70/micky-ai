"""Task 068: independent audit of a Task 067 fully audited API package.

Audits whether the supplied
ReasoningHandoffFullyAuditedApiAuditPackageRead is internally consistent:
verifies its structure and availability, its top-level HTTP metadata, its
session identity, the nested Task 063 bundle and Task 066 audit via their
own validators, the response-fingerprint provenance binding the Task 066
audit to the exact response it inspected, and the package/audit
relationship.

Note: Task 068's ``package_consistent`` means "is the Task 067 package
internally consistent?". A valid Task 067 package that faithfully carries
a defect-reporting Task 066 audit (``api_consistent = False``, and
therefore ``package_consistent = False``) is still internally consistent,
so Task 068 reports ``package_consistent = True`` for it.

No decision, diagnosis, treatment, probability, utility, or confidence
semantics, and no external vendor or model client dependency, appears
anywhere in this schema.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiAuditPackageConsistencyRead(BaseModel):
    """Task 068: independent audit of a Task 067 package."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_consistent: bool
    method_consistent: bool
    path_consistent: bool
    status_consistent: bool
    nested_response_consistent: bool
    nested_api_audit_consistent: bool
    provenance_consistent: bool
    package_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    package_consistency_source: str

    # Provenance: SHA-256 hex digest of the canonicalized Task 067 package
    # this audit inspected. Enables downstream composition layers (e.g.
    # Tasks 069/070) to verify that a supplied audit corresponds to the
    # supplied package without re-invoking Task 068's build().
    audited_package_fingerprint: str
