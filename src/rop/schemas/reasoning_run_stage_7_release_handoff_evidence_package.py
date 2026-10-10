"""Task 186: strict Stage 7 release-handoff evidence package contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from rop.schemas.reasoning_run_stage_7_final_release_gate_audit import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_audit_consistency import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_projection import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183,
)

REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186 = (
    "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_TASK_186"
)

_GATE_STATUSES = ("READY", "BLOCKED", "UNAVAILABLE")
_AUDIT_STATUSES = ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE")
_CHILD_SOURCES = {
    "t183_projection_source": (
        REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
    ),
    "t184_audit_source": REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    "t185_consistency_source": (
        REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185
    ),
}


class ReasoningRunStage7ReleaseHandoffEvidencePackageRead(BaseModel):
    """Verbatim child evidence and a strict aggregate handoff verdict.

    A READY package requires a canonical, finding-free, consistently-bound
    Task 183/184/185 chain. BLOCKED requires readable explicit BLOCKED gate
    evidence. All other evidence is UNAVAILABLE. Child evidence remains
    separately visible even when the aggregate package is unavailable.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str

    t183_session_id: str
    t183_gate_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t183_attestation_status: Literal["CERTIFIED", "BLOCKED", "UNAVAILABLE"] | None
    t183_attestation_audit_status: (
        Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    )
    t183_consistency_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    t183_finding_count: int
    t183_findings: list[str]
    t183_projection_source: str
    t183_valid: bool

    t184_session_id: str
    t184_gate_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    t184_available: bool | None
    t184_consistent: bool | None
    t184_published_gate_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t184_expected_gate_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t184_finding_count: int
    t184_findings: list[str]
    t184_audit_source: str
    t184_valid: bool

    t185_session_id: str
    t185_gate_consistency_status: (
        Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    )
    t185_available: bool | None
    t185_consistent: bool | None
    t185_published_gate_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t185_expected_gate_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t185_finding_count: int
    t185_findings: list[str]
    t185_consistency_source: str
    t185_valid: bool

    package_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    package_source: str

    @model_validator(mode="after")
    def _coherent_package(self) -> ReasoningRunStage7ReleaseHandoffEvidencePackageRead:
        for prefix in ("t183", "t184", "t185"):
            child_findings = getattr(self, f"{prefix}_findings")
            child_count = getattr(self, f"{prefix}_finding_count")
            if child_count != len(child_findings):
                raise ValueError(
                    f"{prefix}_finding_count must equal len({prefix}_findings)"
                )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.package_source != (
            REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186
        ):
            raise ValueError("package_source must be the canonical Task 186 source")

        for prefix, source_field in (
            ("t183", "t183_projection_source"),
            ("t184", "t184_audit_source"),
            ("t185", "t185_consistency_source"),
        ):
            child_findings = getattr(self, f"{prefix}_findings")
            if getattr(self, f"{prefix}_valid"):
                if getattr(self, source_field) != _CHILD_SOURCES[source_field]:
                    raise ValueError(f"{source_field} must be canonical when valid")
                if child_findings != sorted(set(child_findings)):
                    raise ValueError(f"{prefix}_findings must be sorted and unique")
        if self.t183_valid:
            if self.t183_gate_status is None:
                raise ValueError("valid Task 183 evidence requires a gate status")
            if (
                self.t183_attestation_status is None
                or self.t183_attestation_audit_status is None
                or self.t183_consistency_status is None
            ):
                raise ValueError(
                    "valid Task 183 evidence requires all component statuses"
                )
            if self.t183_gate_status == "READY" and (
                not self.t183_session_id
                or self.t183_attestation_status != "CERTIFIED"
                or self.t183_attestation_audit_status != "CONSISTENT"
                or self.t183_consistency_status != "CONSISTENT"
                or self.t183_findings
            ):
                raise ValueError(
                    "valid READY Task 183 evidence must be certified, consistent, "
                    "bound, and finding-free"
                )
            if self.t183_gate_status == "BLOCKED" and not (
                self.t183_attestation_status == "BLOCKED"
                or self.t183_attestation_audit_status == "INCONSISTENT"
                or self.t183_consistency_status == "INCONSISTENT"
            ):
                raise ValueError(
                    "valid BLOCKED Task 183 evidence requires blocking evidence"
                )
            if self.t183_gate_status == "UNAVAILABLE" and not self.t183_findings:
                raise ValueError(
                    "valid UNAVAILABLE Task 183 evidence requires findings"
                )
            if self.t183_gate_status == "UNAVAILABLE" and (
                self.t183_attestation_status == "BLOCKED"
                or self.t183_attestation_audit_status == "INCONSISTENT"
                or self.t183_consistency_status == "INCONSISTENT"
            ):
                raise ValueError(
                    "valid UNAVAILABLE Task 183 evidence must not hide "
                    "blocking evidence"
                )

        for prefix, verdict, published, expected in (
            (
                "t184",
                self.t184_gate_audit_status,
                self.t184_published_gate_status,
                self.t184_expected_gate_status,
            ),
            (
                "t185",
                self.t185_gate_consistency_status,
                self.t185_published_gate_status,
                self.t185_expected_gate_status,
            ),
        ):
            if getattr(self, f"{prefix}_valid"):
                available = getattr(self, f"{prefix}_available")
                consistent = getattr(self, f"{prefix}_consistent")
                child_session_id = getattr(self, f"{prefix}_session_id")
                child_findings = getattr(self, f"{prefix}_findings")
                if verdict is None or available is None or consistent is None:
                    raise ValueError(f"valid {prefix} evidence is incomplete")
                if available != (verdict != "UNAVAILABLE"):
                    raise ValueError(f"{prefix}_available contradicts its status")
                if consistent != (verdict == "CONSISTENT"):
                    raise ValueError(f"{prefix}_consistent contradicts its status")
                if published is None and (
                    verdict != "UNAVAILABLE"
                    or "PROJECTION_INVALID" not in child_findings
                ):
                    raise ValueError(
                        f"{prefix} unknown published status requires "
                        "UNAVAILABLE and PROJECTION_INVALID"
                    )
                if verdict == "UNAVAILABLE":
                    if child_session_id or not child_findings:
                        raise ValueError(
                            f"valid UNAVAILABLE {prefix} evidence requires "
                            "findings and a blank identity"
                        )
                elif verdict == "CONSISTENT":
                    if not child_session_id or published != expected or child_findings:
                        raise ValueError(
                            f"valid CONSISTENT {prefix} evidence must be bound "
                            "and finding-free"
                        )
                elif not child_findings:
                    raise ValueError(
                        f"valid INCONSISTENT {prefix} evidence requires findings"
                    )

        blocking = (
            (self.t183_valid and self.t183_gate_status == "BLOCKED")
            or (
                self.t184_valid
                and "BLOCKED"
                in (
                    self.t184_published_gate_status,
                    self.t184_expected_gate_status,
                )
            )
            or (
                self.t185_valid
                and "BLOCKED"
                in (
                    self.t185_published_gate_status,
                    self.t185_expected_gate_status,
                )
            )
        )
        child_identities_match = (
            bool(self.t183_session_id)
            and self.t183_session_id == self.t184_session_id
            and self.t183_session_id == self.t185_session_id
        )
        expected_session_id = self.t183_session_id if child_identities_match else ""
        if self.session_id != expected_session_id:
            raise ValueError("session_id must preserve the common child session")
        identity_matches = child_identities_match and self.session_id != ""

        ready = (
            self.t183_valid
            and self.t184_valid
            and self.t185_valid
            and identity_matches
            and all(
                getattr(self, field_name) == source
                for field_name, source in _CHILD_SOURCES.items()
            )
            and self.t183_gate_status == "READY"
            and self.t183_finding_count == 0
            and not self.t183_findings
            and self.t184_gate_audit_status == "CONSISTENT"
            and self.t184_available is True
            and self.t184_consistent is True
            and self.t184_published_gate_status == "READY"
            and self.t184_expected_gate_status == "READY"
            and self.t184_finding_count == 0
            and not self.t184_findings
            and self.t185_gate_consistency_status == "CONSISTENT"
            and self.t185_available is True
            and self.t185_consistent is True
            and self.t185_published_gate_status == "READY"
            and self.t185_expected_gate_status == "READY"
            and self.t185_finding_count == 0
            and not self.t185_findings
        )
        expected_status = (
            "BLOCKED" if blocking else ("READY" if ready else "UNAVAILABLE")
        )
        if self.package_status != expected_status:
            raise ValueError(
                "package_status must reflect explicit blocking evidence or a "
                "fully bound READY chain"
            )
        if self.package_status == "READY":
            if self.findings:
                raise ValueError("READY requires a finding-free package")
        elif not self.findings:
            raise ValueError(f"{self.package_status} requires at least one finding")
        return self
