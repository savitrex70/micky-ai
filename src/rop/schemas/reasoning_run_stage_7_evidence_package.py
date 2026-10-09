"""Task 168: canonical Stage 7 evidence package contract.

Strict read-only aggregation of already-published and already-validated
Stage 7 evidence: Task 162 Audit Package, Task 163 Vertical-Slice Verdict,
Task 164 Vertical-Slice Audit, Task 165 Evidence Bundle, Task 166
Evidence-Bundle Audit, and Task 167 Evidence-Bundle Audit Consistency.

The package is an aggregation boundary, not a new reasoning engine. It
preserves exact session identity only when all inputs agree, preserves
canonical sources, preserves all evidence verbatim, and maintains
sorted/deduplicated findings. The package adds an aggregate package status
(READY/BLOCKED/UNAVAILABLE) with BLOCKED precedence over READY and
UNAVAILABLE.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

# The Task 168 source constant lives here, next to the contract that enforces
# it, so the schema never has to import the service that imports the schema.
# The service re-exports the same name.
REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168 = (
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_TASK_168"
)


class ReasoningRunStage7EvidencePackageRead(BaseModel):
    """Strict read model for one canonical Stage 7 evidence package.

    ``package_status`` is the single aggregate verdict: ``READY`` only when
    all six inputs agree and every READY condition holds, ``BLOCKED`` when
    the validated evidence carries an approved blocking state, and
    ``UNAVAILABLE`` for everything else. ``session_id`` is the common
    session shared by all inputs; it is empty when any mismatch is detected.
    ``findings`` are deterministic, sorted, and deduplicated;
    ``finding_count`` always equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    # Identity
    session_id: str

    # Task 162 evidence (verbatim)
    t162_session_id: str
    t162_admission_status: Literal["ADMITTED", "BLOCKED", "UNAVAILABLE"] | None
    t162_diagnostics_status: Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL"]
    t162_request_fingerprint: str | None
    t162_request_audit_status: (
        Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    )
    t162_proposal_audit_status: (
        Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    )
    t162_provider_name: str | None
    t162_model_name: str | None
    t162_finding_count: int
    t162_findings: list[str]
    t162_audit_source: str

    # Task 163 evidence (verbatim)
    t163_session_id: str
    t163_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    t163_admission_status: Literal["ADMITTED", "BLOCKED", "UNAVAILABLE"] | None
    t163_diagnostics_status: (
        Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL"] | None
    )
    t163_provider_name: str | None
    t163_model_name: str | None
    t163_finding_count: int
    t163_findings: list[str]
    t163_certification_source: str

    # Task 164 evidence (verbatim)
    t164_session_id: str
    t164_slice_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    t164_available: bool
    t164_consistent: bool
    t164_published_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t164_expected_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t164_finding_count: int
    t164_findings: list[str]
    t164_audit_source: str

    # Task 165 evidence (verbatim)
    t165_session_id: str
    t165_bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    t165_bundle_finding_count: int
    t165_bundle_findings: list[str]
    t165_bundle_source: str

    # Task 166 evidence (verbatim)
    t166_session_id: str
    t166_bundle_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    t166_available: bool
    t166_consistent: bool
    t166_published_bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t166_expected_bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t166_finding_count: int
    t166_findings: list[str]
    t166_audit_source: str

    # Task 167 evidence (verbatim)
    t167_session_id: str
    t167_consistency_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    t167_available: bool
    t167_consistent: bool
    t167_finding_count: int
    t167_findings: list[str]
    t167_consistency_source: str

    # Aggregate
    package_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    package_source: str

    @model_validator(mode="after")
    def _coherent_package(self) -> ReasoningRunStage7EvidencePackageRead:
        # All finding counts must match their findings lists
        if self.t162_finding_count != len(self.t162_findings):
            raise ValueError("t162_finding_count must equal len(t162_findings)")
        if self.t163_finding_count != len(self.t163_findings):
            raise ValueError("t163_finding_count must equal len(t163_findings)")
        if self.t164_finding_count != len(self.t164_findings):
            raise ValueError("t164_finding_count must equal len(t164_findings)")
        if self.t165_bundle_finding_count != len(self.t165_bundle_findings):
            raise ValueError(
                "t165_bundle_finding_count must equal len(t165_bundle_findings)"
            )
        if self.t166_finding_count != len(self.t166_findings):
            raise ValueError("t166_finding_count must equal len(t166_findings)")
        if self.t167_finding_count != len(self.t167_findings):
            raise ValueError("t167_finding_count must equal len(t167_findings)")
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")

        # All findings must be sorted and deduplicated
        if len(set(self.t162_findings)) != len(self.t162_findings):
            raise ValueError("t162_findings must not contain duplicates")
        if self.t162_findings != sorted(self.t162_findings):
            raise ValueError("t162_findings must be sorted")
        if len(set(self.t163_findings)) != len(self.t163_findings):
            raise ValueError("t163_findings must not contain duplicates")
        if self.t163_findings != sorted(self.t163_findings):
            raise ValueError("t163_findings must be sorted")
        if len(set(self.t164_findings)) != len(self.t164_findings):
            raise ValueError("t164_findings must not contain duplicates")
        if self.t164_findings != sorted(self.t164_findings):
            raise ValueError("t164_findings must be sorted")
        if len(set(self.t165_bundle_findings)) != len(self.t165_bundle_findings):
            raise ValueError("t165_bundle_findings must not contain duplicates")
        if self.t165_bundle_findings != sorted(self.t165_bundle_findings):
            raise ValueError("t165_bundle_findings must be sorted")
        if len(set(self.t166_findings)) != len(self.t166_findings):
            raise ValueError("t166_findings must not contain duplicates")
        if self.t166_findings != sorted(self.t166_findings):
            raise ValueError("t166_findings must be sorted")
        if len(set(self.t167_findings)) != len(self.t167_findings):
            raise ValueError("t167_findings must not contain duplicates")
        if self.t167_findings != sorted(self.t167_findings):
            raise ValueError("t167_findings must be sorted")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")

        # Task 164 coherence
        if self.t164_available != (self.t164_slice_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "t164_available must equal (t164_slice_audit_status != 'UNAVAILABLE')"
            )
        if self.t164_consistent != (self.t164_slice_audit_status == "CONSISTENT"):
            raise ValueError(
                "t164_consistent must equal (t164_slice_audit_status == 'CONSISTENT')"
            )

        # Task 166 coherence
        if self.t166_available != (self.t166_bundle_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "t166_available must equal (t166_bundle_audit_status != 'UNAVAILABLE')"
            )
        if self.t166_consistent != (self.t166_bundle_audit_status == "CONSISTENT"):
            raise ValueError(
                "t166_consistent must equal (t166_bundle_audit_status == 'CONSISTENT')"
            )

        # Task 167 coherence
        if self.t167_available != (self.t167_consistency_status != "UNAVAILABLE"):
            raise ValueError(
                "t167_available must equal (t167_consistency_status != 'UNAVAILABLE')"
            )
        if self.t167_consistent != (self.t167_consistency_status == "CONSISTENT"):
            raise ValueError(
                "t167_consistent must equal (t167_consistency_status == 'CONSISTENT')"
            )

        # Task 168 source is always the canonical constant
        expected_source = REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168
        if self.package_source != expected_source:
            raise ValueError("package_source must be the canonical Task 168 source")

        # Precedence: BLOCKED > READY > UNAVAILABLE
        if self.package_status == "BLOCKED":
            # BLOCKED requires at least one blocking state in the evidence
            blocking = (
                self.t162_admission_status == "BLOCKED"
                or self.t162_diagnostics_status == "UNHEALTHY"
                or self.t163_slice_status == "BLOCKED"
                or self.t163_admission_status == "BLOCKED"
                or self.t163_diagnostics_status == "UNHEALTHY"
                or self.t165_bundle_status == "BLOCKED"
            )
            if not blocking:
                raise ValueError("BLOCKED package requires a published blocking state")
        elif self.package_status == "READY":
            # READY requires all child inputs to be READY/CONSISTENT
            ready = (
                self.t162_admission_status == "ADMITTED"
                and self.t162_diagnostics_status == "HEALTHY"
                and self.t162_request_audit_status == "CONSISTENT"
                and self.t162_proposal_audit_status == "CONSISTENT"
                and self.t163_slice_status == "READY"
                and self.t163_admission_status == "ADMITTED"
                and self.t163_diagnostics_status == "HEALTHY"
                and self.t164_slice_audit_status == "CONSISTENT"
                and self.t165_bundle_status == "READY"
                and self.t166_bundle_audit_status == "CONSISTENT"
                and self.t167_consistency_status == "CONSISTENT"
                and self.t162_finding_count == 0
                and self.t163_finding_count == 0
                and self.t164_finding_count == 0
                and self.t165_bundle_finding_count == 0
                and self.t166_finding_count == 0
                and self.t167_finding_count == 0
                and self.finding_count == 0
            )
            if not ready:
                raise ValueError("READY package requires complete READY evidence")
        return self
