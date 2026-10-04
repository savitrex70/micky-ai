"""Task 149: Stage 6 release evidence consistency audit contract.

The strict read-only audit response for the Task 148 release evidence
bundle itself. Verifies that the evidence bundle faithfully represents
the canonical chain from Task 142 inspection through Task 147
readiness consistency. An audit of the bundle, not a new release gate:
no validation logic is reimplemented here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunStage6EvidenceConsistencyAuditRead(BaseModel):
    """Strict consistency audit of the Task 148 evidence bundle.

    ``expected_evidence_status`` is the audit's independent expectation
    derived from the Task 144 gate, Task 145 gate consistency, Task 146
    readiness, and Task 147 readiness consistency outputs;
    ``actual_evidence_status`` is the published Task 148 bundle state.
    ``evidence_consistent`` is true exactly when the two agree and the
    bundle's release-ready value is correct. A mismatch produces
    deterministic findings; underlying evidence findings are preserved
    verbatim. ``release_ready`` echoes the Task 148 bundle value. The
    architectural Task 140 ``original_result`` gap
    (``NOT_PERSISTED``) is not an issue code and never drives this
    audit. ``audit_source`` is the canonical identifier of this audit
    contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    available: bool
    evidence_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    expected_evidence_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    actual_evidence_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    evidence_consistent: bool
    release_ready: bool
    finding_count: int
    findings: list[str]
    audit_source: str
