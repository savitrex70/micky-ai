"""Task 164: Stage 7 vertical-slice consistency audit contract.

Strict read-only audit verdict for one published Task 163 vertical-slice
verdict, audited against the Task 162 audit package it claims to
certify. The audit is a comparison of two already-published,
independently validated pieces of material -- never a second
certification, never a re-derivation of provenance -- so the verdict
only states whether the two agree.

``findings`` are the Task 164 audit codes that explain the verdict:
empty exactly when the verdict is ``CONSISTENT``, the cross-contract
disagreements when ``INCONSISTENT``, and the unreadable-material
diagnostics when ``UNAVAILABLE``. Provider names, model names, raw
provider text, and the raw provider response object can never appear.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ReasoningRunStage7VerticalSliceAuditRead(BaseModel):
    """Strict consistency verdict for one published vertical-slice result.

    ``slice_audit_status`` is the single canonical verdict:
    ``CONSISTENT`` (every required cross-contract relationship agrees),
    ``INCONSISTENT`` (both inputs are structurally valid and contradict
    one another), or ``UNAVAILABLE`` (an input is missing or fails its
    own contract, so nothing is compared). ``available`` is always
    exactly ``slice_audit_status != "UNAVAILABLE"`` and ``consistent``
    is always exactly ``slice_audit_status == "CONSISTENT"``.
    ``published_slice_status`` is the validated Task 163 verdict and
    ``expected_slice_status`` is the verdict the validated Task 162
    package supports; both are ``None`` exactly when the audit is
    ``UNAVAILABLE``. ``session_id`` names the session only when both
    inputs agree on it and is empty otherwise. ``findings`` are
    deterministic, sorted, and deduplicated; ``finding_count`` always
    equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    slice_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    published_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    expected_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_audit(self) -> ReasoningRunStage7VerticalSliceAuditRead:
        if self.available != (self.slice_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (slice_audit_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.slice_audit_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (slice_audit_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.slice_audit_status == "UNAVAILABLE":
            if (
                self.published_slice_status is not None
                or self.expected_slice_status is not None
            ):
                raise ValueError("UNAVAILABLE must not name a slice status")
            if self.session_id != "":
                raise ValueError("UNAVAILABLE must not claim a session identity")
            if not self.findings:
                raise ValueError("UNAVAILABLE requires a diagnostic finding")
            return self
        if self.published_slice_status is None or self.expected_slice_status is None:
            raise ValueError("a compared audit requires both slice statuses")
        if self.slice_audit_status == "CONSISTENT":
            if self.published_slice_status != self.expected_slice_status:
                raise ValueError("CONSISTENT requires matching slice statuses")
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free audit")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self
