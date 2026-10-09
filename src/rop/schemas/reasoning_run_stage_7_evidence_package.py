"""Task 168: canonical Stage 7 evidence package contract.

Strict read-only aggregation of already-published and already-validated
Stage 7 evidence: Task 162 Audit Package, Task 163 Vertical-Slice Verdict,
Task 164 Vertical-Slice Audit, Task 165 Evidence Bundle, Task 166
Evidence-Bundle Audit, and Task 167 Evidence-Bundle Audit Consistency.

The package is an aggregation boundary, not a new reasoning engine. It
preserves exact session identity only when all inputs agree, preserves
canonical sources, preserves all evidence verbatim, and maintains
sorted/deduplicated findings. The package adds an aggregate package status
(READY/BLOCKED/UNAVAILABLE) with BLOCKED precedence over READY and
UNAVAILABLE.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
    ReasoningRunStage7EvidenceBundleSnapshot,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167,
)

# The Task 168 source constant lives here, next to the contract that enforces
# it, so the schema never has to import the service that imports the schema.
# The service re-exports the same name.
REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168 = (
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_TASK_168"
)


def _canonical_upstream_sources() -> dict[str, str]:
    """Load upstream source constants without a schema/service import cycle."""
    from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
        REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    )
    from rop.services.reasoning_run_stage_7_audit_package import (
        REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
    )
    from rop.services.reasoning_run_stage_7_vertical_slice import (
        REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
    )
    from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
        REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
    )

    return {
        "t162_audit_source": REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        "t163_certification_source": (
            REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163
        ),
        "t164_audit_source": (
            REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164
        ),
        "t165_bundle_source": REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
        "t166_audit_source": (
            REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166
        ),
        "t167_consistency_source": (
            REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167
        ),
    }


def _bundle_status_is_valid(field_name: str, value: object) -> bool:
    allowed: dict[str, tuple[object, ...]] = {
        "bundle_status": ("READY", "BLOCKED", "UNAVAILABLE"),
        "slice_status": ("READY", "BLOCKED", "UNAVAILABLE"),
        "admission_status": ("ADMITTED", "BLOCKED", "UNAVAILABLE", None),
        "diagnostics_status": (
            "HEALTHY",
            "DEGRADED",
            "UNHEALTHY",
            "NO_MATERIAL",
            None,
        ),
        "slice_audit_status": ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE"),
        "published_slice_status": ("READY", "BLOCKED", "UNAVAILABLE", None),
        "expected_slice_status": ("READY", "BLOCKED", "UNAVAILABLE", None),
        "request_audit_status": ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE", None),
        "proposal_audit_status": (
            "CONSISTENT",
            "INCONSISTENT",
            "UNAVAILABLE",
            None,
        ),
    }
    return value in allowed[field_name]


def _snapshot_values_match(
    left: ReasoningRunStage7EvidenceBundleSnapshot,
    right: ReasoningRunStage7EvidenceBundleSnapshot,
) -> bool:
    def values_match(a: object, b: object) -> bool:
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(
                values_match(item_a, item_b)
                for item_a, item_b in zip(a, b, strict=True)
            )
        return type(a) is type(b) and a == b

    left_values = left.model_dump()
    right_values = right.model_dump()
    return left_values.keys() == right_values.keys() and all(
        values_match(left_values[name], right_values[name]) for name in left_values
    )


def _expected_task167(
    bundle: ReasoningRunStage7EvidenceBundleSnapshot,
    audit_snapshot: ReasoningRunStage7EvidenceBundleSnapshot | None,
    audit_session_id: str,
    audit_status: str,
    audit_available: bool,
    audit_consistent: bool,
    audit_published_status: str | None,
    audit_expected_status: str | None,
    audit_finding_count: int,
    audit_findings: list[str],
    audit_source: str,
) -> tuple[str, list[str]]:
    """Independently derive Task 167's published result from Tasks 165/166."""
    status_fields = (
        "bundle_status",
        "slice_status",
        "admission_status",
        "diagnostics_status",
        "slice_audit_status",
        "published_slice_status",
        "expected_slice_status",
        "request_audit_status",
        "proposal_audit_status",
    )
    for field_name in status_fields:
        value = getattr(bundle, field_name)
        if not _bundle_status_is_valid(field_name, value):
            return (
                "UNAVAILABLE",
                [f"TASK_165_BUNDLE_INVALID:{field_name}:not_a_permitted_status"],
            )
    if audit_status == "UNAVAILABLE":
        return "UNAVAILABLE", ["TASK_166_AUDIT_UNAVAILABLE"]
    if audit_snapshot is None:
        return "UNAVAILABLE", ["TASK_166_AUDITED_BUNDLE_MISSING"]

    findings: set[str] = set()
    if bundle.bundle_source != _canonical_upstream_sources()["t165_bundle_source"]:
        findings.add("BUNDLE_SOURCE_MISMATCH")
    if audit_source != REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166:
        findings.add("AUDIT_SOURCE_MISMATCH")
    if not _snapshot_values_match(bundle, audit_snapshot):
        findings.add("BUNDLE_SNAPSHOT_MISMATCH")
    if bundle.session_id != audit_snapshot.session_id:
        findings.add("SESSION_MISMATCH")
    if bundle.bundle_status != audit_published_status:
        findings.add("PUBLISHED_STATUS_MISMATCH")
    if (
        audit_available is not True
        or audit_consistent is not (audit_status == "CONSISTENT")
        or audit_finding_count != len(audit_findings)
        or len(set(audit_findings)) != len(audit_findings)
        or audit_findings != sorted(audit_findings)
        or (
            audit_status == "CONSISTENT"
            and (audit_findings or audit_published_status != audit_expected_status)
        )
        or (audit_status == "INCONSISTENT" and not audit_findings)
        or audit_snapshot.session_id != audit_session_id
        or audit_snapshot.bundle_status != audit_published_status
    ):
        findings.add("AUDIT_INTERNAL_MISMATCH")
    if audit_status == "CONSISTENT":
        if bundle.bundle_status != audit_expected_status:
            findings.add("EXPECTED_STATUS_CONTRADICTION")
    else:
        findings.add("AUDIT_REPORTS_BUNDLE_INCONSISTENT")

    ordered = sorted(findings)
    return ("INCONSISTENT" if ordered else "CONSISTENT"), ordered


class ReasoningRunStage7EvidencePackageRead(BaseModel):
    """Strict read model for one canonical Stage 7 evidence package.

    ``package_status`` is the single aggregate verdict: ``READY`` only when
    all six inputs agree and every READY condition holds, ``BLOCKED`` when
    the validated evidence carries an approved blocking state, and
    ``UNAVAILABLE`` for everything else. ``session_id`` is the common
    session shared by all inputs; it is empty when any mismatch is detected.
    ``findings`` are deterministic, sorted, and deduplicated;
    ``finding_count`` always equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    # Identity
    session_id: str

    # Task 162 evidence (verbatim)
    t162_session_id: str
    t162_admission_status: Literal["ADMITTED", "BLOCKED", "UNAVAILABLE"] | None
    t162_diagnostics_status: Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL"]
    t162_request_fingerprint: str | None
    t162_request_audit_status: (
        Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    )
    t162_proposal_audit_status: (
        Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    )
    t162_provider_name: str | None
    t162_model_name: str | None
    t162_finding_count: int
    t162_findings: list[str]
    t162_audit_source: str

    # Task 163 evidence (verbatim)
    t163_session_id: str
    t163_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    t163_admission_status: Literal["ADMITTED", "BLOCKED", "UNAVAILABLE"] | None
    t163_diagnostics_status: (
        Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL"] | None
    )
    t163_provider_name: str | None
    t163_model_name: str | None
    t163_finding_count: int
    t163_findings: list[str]
    t163_certification_source: str

    # Task 164 evidence (verbatim)
    t164_session_id: str
    t164_slice_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    t164_available: bool
    t164_consistent: bool
    t164_published_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t164_expected_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t164_finding_count: int
    t164_findings: list[str]
    t164_audit_source: str

    # Task 165 evidence (verbatim)
    t165_session_id: str
    t165_bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    t165_bundle_finding_count: int
    t165_bundle_findings: list[str]
    t165_bundle_source: str
    t165_bundle_evidence: ReasoningRunStage7EvidenceBundleSnapshot

    # Task 166 evidence (verbatim)
    t166_session_id: str
    t166_bundle_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    t166_available: bool
    t166_consistent: bool
    t166_published_bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t166_expected_bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    t166_finding_count: int
    t166_findings: list[str]
    t166_audit_source: str
    t166_audited_bundle: ReasoningRunStage7EvidenceBundleSnapshot | None

    # Task 167 evidence (verbatim)
    t167_session_id: str
    t167_consistency_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    t167_available: bool
    t167_consistent: bool
    t167_finding_count: int
    t167_findings: list[str]
    t167_consistency_source: str

    # Aggregate
    package_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    package_source: str

    @model_validator(mode="after")
    def _coherent_package(self) -> ReasoningRunStage7EvidencePackageRead:
        child_findings = (
            self.t162_findings
            + self.t163_findings
            + self.t164_findings
            + self.t165_bundle_findings
            + self.t166_findings
            + self.t167_findings
        )

        # All finding counts must match their findings lists
        if self.t162_finding_count != len(self.t162_findings):
            raise ValueError("t162_finding_count must equal len(t162_findings)")
        if self.t163_finding_count != len(self.t163_findings):
            raise ValueError("t163_finding_count must equal len(t163_findings)")
        if self.t164_finding_count != len(self.t164_findings):
            raise ValueError("t164_finding_count must equal len(t164_findings)")
        if self.t165_bundle_finding_count != len(self.t165_bundle_findings):
            raise ValueError(
                "t165_bundle_finding_count must equal len(t165_bundle_findings)"
            )
        if self.t166_finding_count != len(self.t166_findings):
            raise ValueError("t166_finding_count must equal len(t166_findings)")
        if self.t167_finding_count != len(self.t167_findings):
            raise ValueError("t167_finding_count must equal len(t167_findings)")
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")

        # All findings must be sorted and deduplicated
        if len(set(self.t162_findings)) != len(self.t162_findings):
            raise ValueError("t162_findings must not contain duplicates")
        if self.t162_findings != sorted(self.t162_findings):
            raise ValueError("t162_findings must be sorted")
        if len(set(self.t163_findings)) != len(self.t163_findings):
            raise ValueError("t163_findings must not contain duplicates")
        if self.t163_findings != sorted(self.t163_findings):
            raise ValueError("t163_findings must be sorted")
        if len(set(self.t164_findings)) != len(self.t164_findings):
            raise ValueError("t164_findings must not contain duplicates")
        if self.t164_findings != sorted(self.t164_findings):
            raise ValueError("t164_findings must be sorted")
        if len(set(self.t165_bundle_findings)) != len(self.t165_bundle_findings):
            raise ValueError("t165_bundle_findings must not contain duplicates")
        if self.t165_bundle_findings != sorted(self.t165_bundle_findings):
            raise ValueError("t165_bundle_findings must be sorted")
        if len(set(self.t166_findings)) != len(self.t166_findings):
            raise ValueError("t166_findings must not contain duplicates")
        if self.t166_findings != sorted(self.t166_findings):
            raise ValueError("t166_findings must be sorted")
        if len(set(self.t167_findings)) != len(self.t167_findings):
            raise ValueError("t167_findings must not contain duplicates")
        if self.t167_findings != sorted(self.t167_findings):
            raise ValueError("t167_findings must be sorted")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")

        # The Task 168 aggregate is exactly the child diagnostics plus the
        # deterministic package-level findings derived from published data.
        sessions = (
            self.t162_session_id,
            self.t163_session_id,
            self.t164_session_id,
            self.t165_session_id,
            self.t166_session_id,
            self.t167_session_id,
        )
        identity_matches = (
            bool(sessions[0])
            and all(session_id == sessions[0] for session_id in sessions)
            and self.session_id == sessions[0]
        )
        if self.session_id != (sessions[0] if identity_matches else ""):
            raise ValueError("session_id must preserve the common child session")

        package_findings: set[str] = set()
        if not identity_matches:
            package_findings.add("STAGE_7_SESSION_MISMATCH")

        sources = _canonical_upstream_sources()
        for field_name, source in sources.items():
            if getattr(self, field_name) != source:
                package_findings.add(f"T{field_name[1:4]}_SOURCE_MISMATCH")
        for field_name, source_field in (
            ("t162_audit_source", "t162_audit_source"),
            ("t163_certification_source", "certification_source"),
            ("t164_audit_source", "audit_source"),
            ("t165_bundle_source", "bundle_source"),
        ):
            if getattr(self.t165_bundle_evidence, source_field) != sources[field_name]:
                package_findings.add(f"T{field_name[1:4]}_SOURCE_MISMATCH")

        bundle = self.t165_bundle_evidence
        for field_name in (
            "bundle_status",
            "slice_status",
            "admission_status",
            "diagnostics_status",
            "slice_audit_status",
            "published_slice_status",
            "expected_slice_status",
            "request_audit_status",
            "proposal_audit_status",
        ):
            if not _bundle_status_is_valid(field_name, getattr(bundle, field_name)):
                package_findings.add("T165_STATUS_INVALID")

        if bundle.session_id != self.t162_session_id:
            package_findings.add("T165_SESSION_MISMATCH")
        t162_bundle_fields = {
            "request_fingerprint": self.t162_request_fingerprint,
            "request_audit_status": self.t162_request_audit_status,
            "proposal_audit_status": self.t162_proposal_audit_status,
            "t162_audit_source": self.t162_audit_source,
        }
        if any(
            getattr(bundle, name) != value for name, value in t162_bundle_fields.items()
        ):
            package_findings.add("T165_T162_EVIDENCE_MISMATCH")

        t163_bundle_fields = {
            "slice_status": self.t163_slice_status,
            "admission_status": self.t163_admission_status,
            "diagnostics_status": self.t163_diagnostics_status,
            "provider_name": self.t163_provider_name,
            "model_name": self.t163_model_name,
            "finding_count": self.t163_finding_count,
            "findings": self.t163_findings,
            "certification_source": self.t163_certification_source,
        }
        if any(
            getattr(bundle, name) != value for name, value in t163_bundle_fields.items()
        ):
            package_findings.add("T165_T163_EVIDENCE_MISMATCH")
        if (
            self.t162_provider_name != self.t163_provider_name
            or self.t162_model_name != self.t163_model_name
        ):
            package_findings.add("T162_T163_ATTRIBUTION_MISMATCH")

        t164_bundle_fields = {
            "slice_audit_status": self.t164_slice_audit_status,
            "audit_available": self.t164_available,
            "audit_consistent": self.t164_consistent,
            "published_slice_status": self.t164_published_slice_status,
            "expected_slice_status": self.t164_expected_slice_status,
            "audit_finding_count": self.t164_finding_count,
            "audit_findings": self.t164_findings,
            "audit_source": self.t164_audit_source,
        }
        if any(
            getattr(bundle, name) != value for name, value in t164_bundle_fields.items()
        ):
            package_findings.add("T165_T164_EVIDENCE_MISMATCH")
        if self.t164_published_slice_status != self.t163_slice_status:
            package_findings.add("T164_PUBLISHED_STATUS_MISMATCH")
        if self.t164_expected_slice_status != self.t163_slice_status:
            package_findings.add("T164_EXPECTED_STATUS_MISMATCH")
        if self.t164_slice_audit_status == "CONSISTENT" and (
            self.t164_published_slice_status != self.t164_expected_slice_status
            or not self.t164_available
            or not self.t164_consistent
            or self.t164_findings
        ):
            package_findings.add("T164_CONSISTENCY_INVALID")

        if (
            self.t166_published_bundle_status is not None
            and self.t166_published_bundle_status != self.t165_bundle_status
        ):
            package_findings.add("T166_PUBLISHED_STATUS_MISMATCH")
        if (
            self.t166_bundle_audit_status == "CONSISTENT"
            and self.t166_expected_bundle_status != self.t166_published_bundle_status
        ):
            package_findings.add("T166_EXPECTED_STATUS_MISMATCH")
        if self.t166_bundle_audit_status == "UNAVAILABLE":
            if (
                self.t166_published_bundle_status is not None
                or self.t166_expected_bundle_status is not None
                or self.t166_audited_bundle is not None
            ):
                raise ValueError(
                    "UNAVAILABLE Task 166 evidence must not claim a bundle"
                )
        else:
            if (
                self.t166_published_bundle_status is None
                or self.t166_expected_bundle_status is None
            ):
                raise ValueError("compared Task 166 evidence requires both statuses")
            if self.t166_audited_bundle is None:
                package_findings.add("T166_SNAPSHOT_MISSING")
            elif self.t166_audited_bundle != self.t165_bundle_evidence:
                package_findings.add("T166_SNAPSHOT_MISMATCH")

        if (
            self.t167_consistency_status == "CONSISTENT"
            and self.t166_bundle_audit_status != "CONSISTENT"
        ):
            package_findings.add("T167_BINDING_MISMATCH")
        expected_t167_status, expected_t167_findings = _expected_task167(
            bundle,
            self.t166_audited_bundle,
            self.t166_session_id,
            self.t166_bundle_audit_status,
            self.t166_available,
            self.t166_consistent,
            self.t166_published_bundle_status,
            self.t166_expected_bundle_status,
            self.t166_finding_count,
            self.t166_findings,
            self.t166_audit_source,
        )
        if (
            self.t167_consistency_status != expected_t167_status
            or self.t167_findings != expected_t167_findings
        ):
            package_findings.add("T167_RESULT_MISMATCH")

        expected_findings = sorted(set(child_findings) | package_findings)
        if self.findings != expected_findings:
            raise ValueError(
                "findings must equal child findings and package-level findings"
            )

        if self.t165_bundle_evidence.session_id != self.t165_session_id:
            raise ValueError("Task 165 bundle evidence session does not match")
        if (
            self.t165_bundle_evidence.bundle_status != self.t165_bundle_status
            or self.t165_bundle_evidence.bundle_findings != self.t165_bundle_findings
            or self.t165_bundle_evidence.bundle_source != self.t165_bundle_source
        ):
            raise ValueError("Task 165 bundle evidence does not match published fields")

        if self.t166_audited_bundle is not None and (
            self.t166_audited_bundle.session_id != self.t166_session_id
            or self.t166_audited_bundle.bundle_status
            != self.t166_published_bundle_status
        ):
            raise ValueError("Task 166 snapshot does not match audited identity")

        # Task 164 coherence
        if self.t164_available != (self.t164_slice_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "t164_available must equal (t164_slice_audit_status != 'UNAVAILABLE')"
            )
        if self.t164_consistent != (self.t164_slice_audit_status == "CONSISTENT"):
            raise ValueError(
                "t164_consistent must equal (t164_slice_audit_status == 'CONSISTENT')"
            )

        # Task 166 coherence
        if self.t166_available != (self.t166_bundle_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "t166_available must equal (t166_bundle_audit_status != 'UNAVAILABLE')"
            )
        if self.t166_consistent != (self.t166_bundle_audit_status == "CONSISTENT"):
            raise ValueError(
                "t166_consistent must equal (t166_bundle_audit_status == 'CONSISTENT')"
            )

        # Task 167 coherence
        if self.t167_available != (self.t167_consistency_status != "UNAVAILABLE"):
            raise ValueError(
                "t167_available must equal (t167_consistency_status != 'UNAVAILABLE')"
            )
        if self.t167_consistent != (self.t167_consistency_status == "CONSISTENT"):
            raise ValueError(
                "t167_consistent must equal (t167_consistency_status == 'CONSISTENT')"
            )

        # Task 168 source is always the canonical constant
        expected_source = REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168
        if self.package_source != expected_source:
            raise ValueError("package_source must be the canonical Task 168 source")

        # Precedence: BLOCKED > READY > UNAVAILABLE
        blocked = (
            self.t162_admission_status == "BLOCKED"
            or self.t162_diagnostics_status == "UNHEALTHY"
            or self.t163_slice_status == "BLOCKED"
            or self.t163_admission_status == "BLOCKED"
            or self.t163_diagnostics_status == "UNHEALTHY"
            or self.t165_bundle_status == "BLOCKED"
        )
        ready = (
            identity_matches
            and all(
                getattr(self, field_name) == source
                for field_name, source in sources.items()
            )
            and self.t162_admission_status == "ADMITTED"
            and self.t162_diagnostics_status == "HEALTHY"
            and self.t162_request_audit_status == "CONSISTENT"
            and self.t162_proposal_audit_status == "CONSISTENT"
            and self.t163_slice_status == "READY"
            and self.t163_admission_status == "ADMITTED"
            and self.t163_diagnostics_status == "HEALTHY"
            and self.t164_slice_audit_status == "CONSISTENT"
            and self.t164_available is True
            and self.t164_consistent is True
            and self.t165_bundle_status == "READY"
            and self.t166_bundle_audit_status == "CONSISTENT"
            and self.t166_available is True
            and self.t166_consistent is True
            and self.t166_published_bundle_status == self.t165_bundle_status
            and self.t166_expected_bundle_status == self.t165_bundle_status
            and self.t166_audited_bundle == self.t165_bundle_evidence
            and self.t167_consistency_status == "CONSISTENT"
            and self.t167_available is True
            and self.t167_consistent is True
            and all(
                count == 0
                for count in (
                    self.t162_finding_count,
                    self.t163_finding_count,
                    self.t164_finding_count,
                    self.t165_bundle_finding_count,
                    self.t166_finding_count,
                    self.t167_finding_count,
                    self.finding_count,
                )
            )
        )
        expected_status = "BLOCKED" if blocked else "READY" if ready else "UNAVAILABLE"
        if self.package_status != expected_status:
            raise ValueError(
                "package_status must follow BLOCKED > READY > UNAVAILABLE precedence"
            )
        return self
