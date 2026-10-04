"""Task 147: Stage 6 release readiness consistency audit contract.

The strict read-only audit response for the Task 146 release
readiness report itself. Verifies that the published readiness state
agrees with the deterministic evidence from Tasks 144 and 145. An
audit of the report, not another release gate: no validation logic is
reimplemented here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunStage6ReadinessConsistencyAuditRead(BaseModel):
    """Strict consistency audit of the Task 146 readiness report.

    ``expected_readiness_status`` is the audit's independent
    expectation derived from the Task 144 gate verdict and Task 145
    gate consistency; ``actual_readiness_status`` is the published Task
    146 report state. ``readiness_consistent`` is true exactly when the
    two agree. A mismatch produces the deterministic
    ``READINESS_STATUS_MISMATCH`` finding; underlying evidence findings
    are preserved verbatim. ``release_ready`` echoes the Task 146
    report value. The architectural Task 140 ``original_result`` gap
    (``NOT_PERSISTED``) is not an issue code and never drives this
    audit. ``audit_source`` is the canonical identifier of this audit
    contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    available: bool
    readiness_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    expected_readiness_status: Literal[
        "READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"
    ]
    actual_readiness_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    readiness_consistent: bool
    release_ready: bool
    finding_count: int
    findings: list[str]
    audit_source: str
