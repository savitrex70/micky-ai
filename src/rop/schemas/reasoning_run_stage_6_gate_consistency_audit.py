"""Task 145: Stage 6 completion gate consistency audit contract.

The strict read-only audit response for the Task 144 completion-gate
result itself. Verifies that the published gate status agrees with the
deterministic evidence from Tasks 142 and 143. An audit of the gate,
not a replacement for it: no validation logic is reimplemented here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunStage6GateConsistencyAuditRead(BaseModel):
    """Strict consistency audit of the Task 144 gate result.

    ``expected_gate_status`` is the audit's independent expectation
    derived from the Task 143 diagnostics component statuses;
    ``actual_gate_status`` is the published Task 144 verdict (also
    echoed as ``gate_status``). ``gate_consistent`` is true exactly
    when the two agree. A mismatch produces the deterministic
    ``GATE_STATUS_MISMATCH`` finding; underlying evidence findings are
    preserved verbatim. The architectural Task 140 ``original_result``
    gap (``NOT_PERSISTED``) is not an issue code and never drives this
    audit. ``audit_source`` is the canonical identifier of this audit
    contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    available: bool
    gate_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    gate_consistent: bool
    expected_gate_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    actual_gate_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    finding_count: int
    findings: list[str]
    audit_source: str
