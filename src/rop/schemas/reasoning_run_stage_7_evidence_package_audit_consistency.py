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

    ``consistency_status`` is the single canonical verdict:

    * ``CONSISTENT`` -- both inputs are readable, satisfy their own
      contracts, and the audit is canonically bound to the exact Task 168
      package represented.
    * ``INCONSISTENT`` -- both inputs are *readable* but contradict each
      other or fail their own contract: a non-canonical source, a detached
      session, conflicting package/audit statuses, a published-versus-expected
      status mismatch, wrong flags, or a finding count that does not match its
      findings. The findings name what disagrees; a schema contract failure
      alone never downgrades a readable input to ``UNAVAILABLE``.
    * ``UNAVAILABLE`` -- the comparison cannot be evaluated safely. Either an
      input is *unreadable* (missing, the wrong model type, a missing
      attribute, a wrongly typed field, a status or identity value outside
      its permitted set, or malformed nested evidence), reported as
      ``PACKAGE_OR_AUDIT_INVALID`` with ``PACKAGE_UNREADABLE`` and/or
      ``AUDIT_UNREADABLE``; or the Task 169 audit is a structurally valid
      ``UNAVAILABLE`` audit that verified nothing and so names no package
      status or session, reported as ``AUDIT_UNAVAILABLE`` alone. That second
      case is a readable, honest audit and is distinct from a malformed one.

    ``available`` is always exactly ``consistency_status != "UNAVAILABLE"``
    and ``consistent`` is always exactly ``consistency_status ==
    "CONSISTENT"``. ``UNAVAILABLE`` names no session and carries at least one
    diagnostic finding. ``findings`` are deterministic, sorted, and
    deduplicated; ``finding_count`` always equals ``len(findings)``.
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
            if self.session_id != "":
                raise ValueError("UNAVAILABLE must not claim a session identity")
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
        elif self.consistency_status == "CONSISTENT":
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free consistency check")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        if (
            self.consistency_source
            != REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170
        ):
            raise ValueError("consistency_source must be the canonical Task 170 source")
        return self
