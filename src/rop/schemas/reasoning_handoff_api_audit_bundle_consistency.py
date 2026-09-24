"""Task 064: independent audit of a Task 063 API audit bundle.

Audits whether the supplied ReasoningHandoffApiAuditBundleRead is
internally consistent: verifies its structure and availability,
validates the nested Task 061 package and Task 062 audit via their own
validators, independently re-derives the Task 061 package fingerprint
to bind the Task 062 audit's ``audited_package_fingerprint`` to the
exact package being bundled, and reports every disagreement through
``consistency_issues``.

Note: Task 064's ``package_consistent`` means "is the Task 063 bundle
internally consistent?" -- distinct from Task 063's
``bundle_consistent`` and Task 062's ``package_consistent``. A valid
Task 063 bundle legitimately carrying ``bundle_consistent = False``
(because Task 062 reported ``package_consistent = False``) still
produces a Task 064 audit with ``package_consistent = True`` when the
bundle faithfully represents the Task 062 result.

No decision, winner, recommendation, diagnosis, treatment, action,
probability, confidence, utility, or expected-outcome field appears
anywhere in this schema.
"""

from pydantic import BaseModel, ConfigDict


class ReasoningHandoffApiAuditBundleConsistencyRead(BaseModel):
    """Task 064: independent audit of a Task 063 API audit bundle."""

    model_config = ConfigDict(from_attributes=True)

    available: bool
    package_consistent: bool
    session_consistent: bool
    nested_package_consistent: bool
    nested_package_audit_consistent: bool
    provenance_consistent: bool
    bundle_relationship_consistent: bool
    source_consistency: bool
    metadata_consistent: bool
    consistency_issues: list[str]
    package_consistency_source: str
    audited_bundle_fingerprint: str
