"""Task 169: independent Stage 7 evidence-package audit contract.

Strict read-only audit verdict for one published Task 168 evidence package.
The audit independently derives the expected package state from the
published Task 162-167 surfaces already present inside the package, then
compares the independently derived state against the published Task 168
package status.

The audit is a pure, provider-neutral boundary: it never calls Task 168,
never calls Tasks 162-167 services, never recomputes fingerprints, never
invokes a provider, and never accesses a database. It only reads the
already-published evidence surfaces contained in the validated Task 168
package.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

# The Task 169 source constant lives here, next to the contract that enforces
# it, so the schema never has to import the service that imports the schema.
# The service re-exports the same name.
REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169 = (
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_TASK_169"
)


class ReasoningRunStage7EvidencePackageAuditRead(BaseModel):
    """Strict read model for one independent Stage 7 evidence-package audit.

    ``package_audit_status`` is the single audit verdict: ``CONSISTENT`` when
    the independently derived expected state matches the published Task 168
    package, ``INCONSISTENT`` when the published evidence contradicts the
    independently derived result, and ``UNAVAILABLE`` for missing or malformed
    Task 168 input. ``published_package_status`` is the status the Task 168
    package claims, and ``expected_package_status`` is the status independently
    derived from the published evidence surfaces. ``findings`` are
    deterministic, sorted, and deduplicated; ``finding_count`` always
    equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    package_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    published_package_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    expected_package_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_audit(self) -> ReasoningRunStage7EvidencePackageAuditRead:
        if self.available != (self.package_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (package_audit_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.package_audit_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (package_audit_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.package_audit_status == "UNAVAILABLE":
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            return self
        if self.package_audit_status == "CONSISTENT":
            if self.published_package_status != self.expected_package_status:
                raise ValueError(
                    "CONSISTENT requires published and expected package status to match"
                )
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free audit")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self
