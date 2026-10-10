"""Task 180: Stage 7 release-readiness final attestation contract.

Strict read-only attestation over the published Task 177 release-readiness
evidence bundle, its Task 178 independent audit, and the Task 179 bundle
audit-consistency verdict. The attestation answers only: "Does the
published release-readiness evidence have complete, mutually consistent,
canonically attributable bindings?"

The attestation does NOT perform new reasoning, execute a release, invoke
a provider, or access a database. It only verifies the already-published
records.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180 = (
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_TASK_180"
)


class ReasoningRunStage7ReleaseReadinessFinalAttestationRead(BaseModel):
    """Strict read model for one release-readiness final attestation.

    ``attestation_status`` is the single canonical verdict: ``CERTIFIED``
    when the published Task 177 bundle is READY, the Task 178 audit is
    CONSISTENT over that exact bundle, and the Task 179 consistency
    verdict is CONSISTENT over that exact binding, with every session,
    status and finding invariant agreeing; ``BLOCKED`` when readable,
    contract-valid blocking evidence exists; ``UNAVAILABLE`` when evidence
    is insufficient and no blocking state is readable. ``certified``,
    ``blocked`` and ``available`` are coherent boolean projections of the
    status, while ``bundle_status``, ``bundle_audit_status`` and
    ``bundle_audit_consistency_status`` echo the upstream Task 177/178/179
    verdicts the attestation was derived from (``None`` when the input was
    invalid and no verdict could be read). ``findings`` are
    deterministic, sorted, and deduplicated; ``finding_count`` always
    equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    attestation_status: Literal["CERTIFIED", "BLOCKED", "UNAVAILABLE"]
    certified: bool
    blocked: bool
    available: bool
    bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None = None
    bundle_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None = (
        None
    )
    bundle_audit_consistency_status: (
        Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    ) = None
    finding_count: int
    findings: list[str]
    attestation_source: str

    @model_validator(mode="after")
    def _coherent_attestation(
        self,
    ) -> ReasoningRunStage7ReleaseReadinessFinalAttestationRead:
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        # Boolean projections must cohere with the status.
        if self.certified != (self.attestation_status == "CERTIFIED"):
            raise ValueError("certified must equal (attestation_status == 'CERTIFIED')")
        if self.blocked != (self.attestation_status == "BLOCKED"):
            raise ValueError("blocked must equal (attestation_status == 'BLOCKED')")
        if self.available != (self.attestation_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (attestation_status != 'UNAVAILABLE')"
            )
        if self.attestation_source != (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180
        ):
            raise ValueError("attestation_source must be the canonical Task 180 source")
        # Readable blocking evidence, derived from the echoed upstream
        # verdicts, must surface as BLOCKED and must never be hidden by
        # CERTIFIED or UNAVAILABLE.
        blocking_evidence = (
            self.bundle_status == "BLOCKED"
            or self.bundle_audit_status == "INCONSISTENT"
            or self.bundle_audit_consistency_status == "INCONSISTENT"
        )
        if self.attestation_status == "CERTIFIED":
            if self.finding_count != 0:
                raise ValueError("CERTIFIED requires a finding-free attestation")
            if not self.session_id:
                raise ValueError("CERTIFIED requires a valid session_id")
            if (
                self.bundle_status != "READY"
                or self.bundle_audit_status != "CONSISTENT"
                or self.bundle_audit_consistency_status != "CONSISTENT"
            ):
                raise ValueError(
                    "CERTIFIED requires READY, CONSISTENT bundle and audit evidence"
                )
        elif self.attestation_status == "BLOCKED":
            if self.finding_count == 0:
                raise ValueError("BLOCKED requires at least one finding")
            if not blocking_evidence:
                raise ValueError("BLOCKED requires readable blocking evidence")
        else:  # UNAVAILABLE
            if self.finding_count == 0:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            if blocking_evidence:
                raise ValueError("UNAVAILABLE must not hide readable blocking evidence")
        return self
