"""Task 062: independent audit of a Task 061 API audit package.

Audits whether the supplied ReasoningHandoffApiAuditPackageRead is
internally consistent: verifies its top-level HTTP metadata, validates
the nested Task 057 response and Task 060 API consistency result via
their own validators, and independently re-derives the Task 060
response fingerprint to prove that the audit's provenance binds to the
supplied response.

Note: Task 062's ``package_consistent`` means "is the Task 061 package
internally consistent?". That is distinct from Task 061's
``package_consistent`` (does the Task 061 package correctly bind the
response and its audit?) and from Task 057's
``response.handoff_consistent`` (was the underlying reasoning context
internally consistent?). A valid Task 061 package can legitimately
carry ``response.handoff_consistent = False`` alongside
``api_consistency.api_consistent = True`` and still produce a Task 062
audit with ``package_consistent = True``.

No decision, winner, recommendation, diagnosis, treatment, action,
probability, confidence, utility, or expected-outcome field appears
anywhere in this schema.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffApiAuditPackageConsistencyRead(BaseModel):
    """Task 062: independent audit of a Task 061 API audit package."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_consistent: bool
    method_consistent: bool
    path_consistent: bool
    status_consistent: bool
    nested_response_consistent: bool
    nested_api_consistency_consistent: bool
    provenance_consistent: bool
    package_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    package_consistency_source: str

    # Provenance: SHA-256 hex digest of the canonicalized Task 061
    # package this audit inspected. Enables downstream composition
    # layers (e.g. Task 063) to verify that a supplied audit
    # corresponds to the supplied package without re-invoking Task
    # 062's build(). Provenance only -- not a correctness score.
    audited_package_fingerprint: str
