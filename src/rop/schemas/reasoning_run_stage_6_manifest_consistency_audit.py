"""Task 151: Stage 6 release package manifest consistency audit contract.

The strict read-only audit response for the Task 150 release package
manifest itself. Verifies that the manifest accurately represents the
canonical upstream chain from Task 142 inspection through Task 149
evidence consistency. An audit of the manifest, not another gate: no
validation logic is reimplemented here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunStage6ManifestConsistencyAuditRead(BaseModel):
    """Strict consistency audit of the Task 150 release manifest.

    ``expected_manifest_status`` is the audit's independent expectation
    derived from the canonical upstream evidence (Tasks 144-149);
    ``actual_manifest_status`` is the published Task 150 manifest
    state. ``manifest_consistent`` is true exactly when the two agree,
    every required component is present in canonical order with a
    status matching upstream evidence, and the manifest's release-ready
    value is correct. Any deviation produces deterministic findings
    (status, release-ready, missing/contradictory/misordered
    components). ``release_ready`` echoes the Task 150 manifest value.
    The architectural Task 140 ``original_result`` gap
    (``NOT_PERSISTED``) is not an issue code and never drives this
    audit. ``audit_source`` is the canonical identifier of this audit
    contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    available: bool
    manifest_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    expected_manifest_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    actual_manifest_status: Literal["READY", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL"]
    manifest_consistent: bool
    release_ready: bool
    finding_count: int
    findings: list[str]
    audit_source: str
