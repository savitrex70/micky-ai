"""Task 070: independent audit of a Task 069 fully audited API audit bundle.

Audits whether the supplied ReasoningHandoffFullyAuditedApiAuditBundleRead
is internally consistent: verifies its structure, availability, session
identity, validates the nested Task 067 package and Task 068 audit via
their own validators, independently re-derives the Task 067 package
fingerprint to bind the Task 068 audit's audited_package_fingerprint to
the exact package being bundled, and reports every disagreement through
consistency_issues.

Note: this audit's ``bundle_consistent`` means "is the Task 069 bundle
internally consistent?" -- distinct from Task 069's ``bundle_consistent``
and Task 068's ``package_consistent``.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffFullyAuditedApiAuditBundleConsistencyRead(BaseModel):
    """Task 070: independent audit of a Task 069 audit bundle."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    bundle_consistent: bool
    session_consistent: bool
    nested_package_consistent: bool
    nested_package_consistency_consistent: bool
    provenance_consistent: bool
    bundle_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    bundle_consistency_source: str
    audited_bundle_fingerprint: str
