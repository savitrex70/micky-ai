"""Task 170: Stage 7 evidence-package audit consistency contract.

Strict read-only consistency verdict for the binding between Task 168
Evidence Package and Task 169 Evidence-Package Audit. The consistency check
verifies that the audit actually belongs to the exact package being
represented, and that the audit's findings are correctly bound to the
package's published evidence.

The consistency boundary is independent: it never calls Task 168 or
Task 169 services, never recomputes fingerprints, never invokes a
provider, and never accesses a database. It only reads the already-
published validated Pydantic objects.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

# The Task 170 source constant lives here, next to the contract that enforces
# it, so the schema never has to import the service that imports the schema.
# The service re-exports the same name.
REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170 = (
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_TASK_170"
)


class ReasoningRunStage7EvidencePackageAuditConsistencyRead(BaseModel):
    """Strict consistency verdict for package-audit binding.

    ``consistency_status`` is the single canonical verdict: ``CONSISTENT``
    when the audit is canonically bound to the exact Task 168 package
    represented, ``INCONSISTENT`` when the audit is detached or contradicts
    the package, and ``UNAVAILABLE`` when either input is missing or fails
    its own contract. ``available`` is always exactly
    ``consistency_status != "UNAVAILABLE"`` and ``consistent`` is always
    exactly ``consistency_status == "CONSISTENT"``. ``findings`` are
    deterministic, sorted, and deduplicated; ``finding_count`` always
    equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    consistency_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    finding_count: int
    findings: list[str]
    consistency_source: str

    @model_validator(mode="after")
    def _coherent_consistency(
        self,
    ) -> ReasoningRunStage7EvidencePackageAuditConsistencyRead:
        if self.available != (self.consistency_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (consistency_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.consistency_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (consistency_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.consistency_status == "UNAVAILABLE":
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            return self
        if self.consistency_status == "CONSISTENT":
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free consistency check")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self
