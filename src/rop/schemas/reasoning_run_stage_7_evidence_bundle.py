"""Task 165: Stage 7 canonical vertical-slice evidence bundle contract.

Strict read-only projection of the canonical Stage 7 vertical-slice
evidence bundle: the Task 163 verdict, the Task 164 audit, and the
Task 162 attribution packaged into one deterministic, provider-neutral
evidence surface. The bundle answers the question of what the Stage 7
vertical-slice decision concluded, whether the Task 164 audit
independently confirmed it, and what the Stage 7 boundary currently
has evidence for.

The bundle is an evidence aggregation boundary, not a gate. It
consumes only already-published material from Tasks 162, 163, and 164
and never redoes their reasoning. Raw provider text, raw provider
response objects, raw request payloads, and raw proposal objects can
never appear.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ReasoningRunStage7EvidenceBundleRead(BaseModel):
    """Strict read model for one canonical Stage 7 evidence bundle.

    ``bundle_status`` is the single aggregate verdict: ``READY`` only
    when all three child inputs agree and every READY condition holds,
    ``BLOCKED`` when the validated evidence carries an approved blocking
    state, and ``UNAVAILABLE`` for everything else. ``bundle_findings``
    contains only Task 165 structural finding codes, never copies of
    child findings. ``session_id`` is the common session shared by all
    three child inputs; it is empty when any mismatch is detected.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    # Identity
    session_id: str

    # Task 163 evidence (verbatim from the validated verdict)
    slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    admission_status: Literal["ADMITTED", "BLOCKED", "UNAVAILABLE"] | None
    diagnostics_status: (
        Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL"] | None
    )
    provider_name: str | None
    model_name: str | None
    finding_count: int
    findings: list[str]
    certification_source: str

    # Task 164 audit evidence (verbatim from the validated audit)
    slice_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    audit_available: bool
    audit_consistent: bool
    published_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    expected_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    audit_finding_count: int
    audit_findings: list[str]
    audit_source: str  # Task 164 audit_source value

    # Task 162 attribution (verbatim from the validated package)
    request_fingerprint: str | None
    request_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    proposal_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    t162_audit_source: str  # Task 162 audit_source value (renamed to avoid collision)

    # Aggregate
    bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    bundle_finding_count: int
    bundle_findings: list[str]
    bundle_source: str  # Task 165 source constant

    @model_validator(mode="after")
    def _coherent_bundle(self) -> ReasoningRunStage7EvidenceBundleRead:
        # Task 163 surface: finding_count == len(findings), sorted, deduplicated
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        # Task 164 surface: audit_finding_count == len(audit_findings)
        if self.audit_finding_count != len(self.audit_findings):
            raise ValueError("audit_finding_count must equal len(audit_findings)")
        if len(set(self.audit_findings)) != len(self.audit_findings):
            raise ValueError("audit_findings must not contain duplicates")
        if self.audit_findings != sorted(self.audit_findings):
            raise ValueError("audit_findings must be sorted")
        # Bundle-level: bundle_finding_count == len(bundle_findings)
        if self.bundle_finding_count != len(self.bundle_findings):
            raise ValueError("bundle_finding_count must equal len(bundle_findings)")
        if len(set(self.bundle_findings)) != len(self.bundle_findings):
            raise ValueError("bundle_findings must not contain duplicates")
        if self.bundle_findings != sorted(self.bundle_findings):
            raise ValueError("bundle_findings must be sorted")
        # audit_available must equal (slice_audit_status != "UNAVAILABLE")
        if self.audit_available != (self.slice_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "audit_available must equal (slice_audit_status != 'UNAVAILABLE')"
            )
        # audit_consistent must equal (slice_audit_status == "CONSISTENT")
        if self.audit_consistent != (self.slice_audit_status == "CONSISTENT"):
            raise ValueError(
                "audit_consistent must equal (slice_audit_status == 'CONSISTENT')"
            )
        # provider_name and model_name must be set together
        if (self.provider_name is None) != (self.model_name is None):
            raise ValueError("provider_name and model_name must be set together")
        # READY bundle structural coherence
        if self.bundle_status == "READY":
            if self.session_id == "":
                raise ValueError("READY bundle requires a session identity")
            if self.bundle_findings:
                raise ValueError("READY bundle requires no bundle findings")
        return self
