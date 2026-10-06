"""Task 156: Stage 7 request provenance and integrity audit contract.

The strict read-only audit verdict for one Task 155 request package.
The audit independently re-derives every provenance dimension instead of
trusting the builder's own flags: session identity, admission status,
Task 152 certification status, request source, payload field set,
canonical serialization, and a recomputed fingerprint. Nothing else:
no provider call, no mutation, no persistence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

_DIMENSIONS = (
    "session_consistent",
    "admission_consistent",
    "certification_consistent",
    "source_consistent",
    "payload_consistent",
    "fingerprint_consistent",
)


class ReasoningRunStage7RequestAuditRead(BaseModel):
    """Strict provenance audit verdict for one request package.

    ``request_audit_status`` is the canonical verdict: ``CONSISTENT``
    (every dimension was independently re-derived and matched),
    ``INCONSISTENT`` (the package was readable but at least one
    dimension mismatched), or ``UNAVAILABLE`` (the package or a
    verification input could not be read, so no dimension is
    certified -- all dimension flags are ``False`` in that case).
    ``available`` is always exactly
    ``request_audit_status != "UNAVAILABLE"``. ``findings`` are
    deterministic, sorted, and deduplicated.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    request_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    session_consistent: bool
    admission_consistent: bool
    certification_consistent: bool
    source_consistent: bool
    payload_consistent: bool
    fingerprint_consistent: bool
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_audit(self) -> ReasoningRunStage7RequestAuditRead:
        if self.available != (self.request_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (request_audit_status != 'UNAVAILABLE')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        dimensions = [getattr(self, name) for name in _DIMENSIONS]
        if self.request_audit_status == "CONSISTENT":
            if not all(dimensions):
                raise ValueError("CONSISTENT requires every dimension to be True")
        elif self.request_audit_status == "INCONSISTENT":
            if all(dimensions):
                raise ValueError("INCONSISTENT requires at least one False dimension")
        elif any(dimensions):
            raise ValueError("UNAVAILABLE requires every dimension to be False")
        return self
