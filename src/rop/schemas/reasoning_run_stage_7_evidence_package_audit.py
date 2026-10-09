"""Task 169: independent Stage 7 evidence-package audit contract.

Strict read-only audit verdict for one published Task 168 evidence package.
The audit independently derives the expected package state (the complete
aggregate findings and the package status) from the published Task 162-167
evidence supplied alongside the package, then compares the independently
derived state against the published Task 168 package.

The audit is a pure, provider-neutral boundary: it never calls Task 168,
never calls Tasks 162-167 services, never recomputes fingerprints, never
invokes a provider, and never accesses a database. It only reads
already-published evidence surfaces.
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

    ``package_audit_status`` is the single audit verdict:

    * ``CONSISTENT`` -- the package and the supplied evidence were readable,
      the independently derived state matches the published package exactly,
      and the audit has no finding. A correctly assembled package that is
      itself ``UNAVAILABLE`` or ``BLOCKED`` is ``CONSISTENT``.
    * ``INCONSISTENT`` -- everything was readable but the published package
      contradicts the independently derived state. Both package statuses are
      named, and at least one finding says what disagrees.
    * ``UNAVAILABLE`` -- the package or the supplied evidence was too
      malformed to audit (not the expected model, a missing or wrongly shaped
      nested object, an unreadable identity, or a published status outside
      the permitted set). Nothing was verified, so no package status is
      named, no session is claimed, and the findings only diagnose why the
      audit could not be performed.

    ``published_package_status`` is the status the Task 168 package claims
    and ``expected_package_status`` is the status independently derived from
    the evidence; both are ``None`` exactly when the audit is ``UNAVAILABLE``,
    so a published status that cannot be read is never invented.
    ``findings`` are deterministic, sorted, and deduplicated;
    ``finding_count`` always equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    package_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    published_package_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    expected_package_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_audit(self) -> ReasoningRunStage7EvidencePackageAuditRead:
        if self.audit_source != (
            REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169
        ):
            raise ValueError("audit_source must be the canonical Task 169 source")
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
            if (
                self.published_package_status is not None
                or self.expected_package_status is not None
            ):
                raise ValueError("UNAVAILABLE must not name a package status")
            if self.session_id != "":
                raise ValueError("UNAVAILABLE must not claim a session identity")
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            return self
        if (
            self.published_package_status is None
            or self.expected_package_status is None
        ):
            raise ValueError("a compared audit requires both package statuses")
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
