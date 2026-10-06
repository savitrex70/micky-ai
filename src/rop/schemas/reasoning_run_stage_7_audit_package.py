"""Task 162: Stage 7 deterministic audit package contract.

Strict read-only projection of the assembled Stage 7 audit package for
one session: the Task 154 admission verdict, the Task 155 request
package fingerprint, the Task 156 request audit, the Task 158 proposal
metadata, the Task 159 proposal audit, and the Task 161 diagnostics
health combined into one deterministic, provider-neutral summary.
Only canonical statuses, provider metadata, and deterministic findings
are exposed -- never raw provider text, never the raw provider
response object.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ReasoningRunStage7AuditPackageRead(BaseModel):
    """Strict deterministic Stage 7 audit package summary.

    ``admission_status`` carries the canonical Task 154 verdict verbatim
    and is ``None`` exactly when the admission material is absent or
    unreadable. ``diagnostics_status`` carries the canonical Task 161
    health state; a missing or unreadable diagnostics verdict folds to
    ``NO_MATERIAL`` so the package always exposes one canonical health
    state. ``request_fingerprint`` and the two audit statuses are
    ``None`` exactly when the corresponding material is unusable; no
    status is ever fabricated. ``session_id`` is empty when no material
    claims one or when the claims contradict. ``provider_name`` and
    ``model_name`` appear only together, and only from a validated
    proposal. ``findings`` are deterministic, sorted, and deduplicated;
    ``finding_count`` always equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    admission_status: Literal["ADMITTED", "BLOCKED", "UNAVAILABLE"] | None
    request_fingerprint: str | None
    request_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    proposal_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    diagnostics_status: Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL"]
    provider_name: str | None
    model_name: str | None
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_package(self) -> ReasoningRunStage7AuditPackageRead:
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if (self.provider_name is None) != (self.model_name is None):
            raise ValueError("provider_name and model_name must be set together")
        return self
