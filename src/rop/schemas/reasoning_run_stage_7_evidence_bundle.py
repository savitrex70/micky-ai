"""Task 165: Stage 7 canonical vertical-slice evidence bundle contract.

Strict read-only projection of the canonical Stage 7 vertical-slice
evidence bundle: the Task 163 verdict, the Task 164 audit, and the
Task 162 attribution packaged into one deterministic, provider-neutral
evidence surface. The bundle answers the question of what the Stage 7
vertical-slice decision concluded, whether the Task 164 audit
independently confirmed it, and what the Stage 7 boundary currently
has evidence for.

The bundle is an evidence aggregation boundary, not a gate. It
consumes only already-published material from Tasks 162, 163, and 164
and never redoes their reasoning. Raw provider text, raw provider
response objects, raw request payloads, and raw proposal objects can
never appear.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# The Task 165 source constant lives here, next to the contract that enforces
# it, so the schema never has to import the service that imports the schema.
# The service re-exports the same name.
REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165 = (
    "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_TASK_165"
)

# Canonical request fingerprint shape: exactly 64 lowercase hexadecimal
# characters, matched with fullmatch so no trailing newline slips through.
# Shape only -- the value is never recomputed, normalised, or repaired.
_REQUEST_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")

# Bundle-level finding codes that explain a published non-canonical source.
_SOURCE_FINDING_CODES = {
    "t162_audit_source": "T162_AUDIT_SOURCE_NOT_CANONICAL",
    "certification_source": "T163_CERTIFICATION_SOURCE_NOT_CANONICAL",
    "audit_source": "T164_AUDIT_SOURCE_NOT_CANONICAL",
}


@cache
def _canonical_sources() -> dict[str, str]:
    """Return the canonical Task 162/163/164 source constants by bundle field.

    The constants are imported on first use rather than at module import
    time: the schemas package is loaded before the services package, and
    the services import the schemas, so a top-level import here would be
    circular. Only the three source constants are ever read; no service
    is called.
    """
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
        "certification_source": (REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163),
        "audit_source": REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
    }


def _present(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def stage_7_bundle_blocking_condition_holds(values: Mapping[str, Any]) -> bool:
    """Report whether the bundle publishes any canonical blocking condition.

    Pure and schema-local: it reads only the bundle's own published fields.
    The schema uses it in both directions (a BLOCKED bundle needs one, and
    any bundle that shows one must be BLOCKED); the service uses the same
    function so the two can never disagree.
    """
    return (
        values["slice_status"] == "BLOCKED"
        or values["admission_status"] == "BLOCKED"
        or values["diagnostics_status"] == "UNHEALTHY"
        or values["request_audit_status"] == "INCONSISTENT"
        or values["proposal_audit_status"] == "INCONSISTENT"
    )


def stage_7_bundle_ready_conditions_hold(values: Mapping[str, Any]) -> bool:
    """Report whether the published bundle evidence meets every READY condition.

    Pure and schema-local: it reads only the bundle's own published fields.
    The bundle schema uses it to reject a forged READY and to reject an
    UNAVAILABLE that withholds a decision the evidence fully supports; the
    service uses the same function so the two can never disagree.
    """
    fingerprint = values["request_fingerprint"]
    sources = _canonical_sources()
    return (
        _present(values["session_id"])
        and values["slice_status"] == "READY"
        and values["admission_status"] == "ADMITTED"
        and values["diagnostics_status"] == "HEALTHY"
        and values["request_audit_status"] == "CONSISTENT"
        and values["proposal_audit_status"] == "CONSISTENT"
        and isinstance(fingerprint, str)
        and _REQUEST_FINGERPRINT_RE.fullmatch(fingerprint) is not None
        and _present(values["provider_name"])
        and _present(values["model_name"])
        and values["finding_count"] == 0
        and values["findings"] == []
        and values["slice_audit_status"] == "CONSISTENT"
        and values["audit_available"] is True
        and values["audit_consistent"] is True
        and values["published_slice_status"] == "READY"
        and values["expected_slice_status"] == "READY"
        and values["audit_finding_count"] == 0
        and values["audit_findings"] == []
        and values["t162_audit_source"] == sources["t162_audit_source"]
        and values["certification_source"] == sources["certification_source"]
        and values["audit_source"] == sources["audit_source"]
        and values["bundle_source"]
        == REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165
        and values["bundle_finding_count"] == 0
        and values["bundle_findings"] == []
    )


class ReasoningRunStage7EvidenceBundleRead(BaseModel):
    """Strict read model for one canonical Stage 7 evidence bundle.

    ``bundle_status`` is the single aggregate verdict: ``READY`` only
    when all three child inputs agree and every READY condition holds,
    ``BLOCKED`` when the validated evidence carries an approved blocking
    state, and ``UNAVAILABLE`` for everything else. ``bundle_findings``
    contains only Task 165 structural finding codes, never copies of
    child findings. ``session_id`` is the common session shared by all
    three child inputs; it is empty when any mismatch is detected.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    # Identity
    session_id: str

    # Task 163 evidence (verbatim from the validated verdict)
    slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    admission_status: Literal["ADMITTED", "BLOCKED", "UNAVAILABLE"] | None
    diagnostics_status: (
        Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL"] | None
    )
    provider_name: str | None
    model_name: str | None
    finding_count: int
    findings: list[str]
    certification_source: str

    # Task 164 audit evidence (verbatim from the validated audit)
    slice_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    audit_available: bool
    audit_consistent: bool
    published_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    expected_slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    audit_finding_count: int
    audit_findings: list[str]
    audit_source: str  # Task 164 audit_source value

    # Task 162 attribution (verbatim from the validated package)
    request_fingerprint: str | None
    request_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    proposal_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    t162_audit_source: str  # Task 162 audit_source value (renamed to avoid collision)

    # Aggregate
    bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    bundle_finding_count: int
    bundle_findings: list[str]
    bundle_source: str  # Task 165 source constant

    @field_validator("request_fingerprint")
    @classmethod
    def _canonical_request_fingerprint(cls, value: str | None) -> str | None:
        if value is not None and _REQUEST_FINGERPRINT_RE.fullmatch(value) is None:
            raise ValueError(
                "request_fingerprint must be 64 lowercase hexadecimal characters"
            )
        return value

    @model_validator(mode="after")
    def _coherent_bundle(self) -> ReasoningRunStage7EvidenceBundleRead:
        # Task 163 surface: finding_count == len(findings), sorted, deduplicated
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        # Task 164 surface: audit_finding_count == len(audit_findings)
        if self.audit_finding_count != len(self.audit_findings):
            raise ValueError("audit_finding_count must equal len(audit_findings)")
        if len(set(self.audit_findings)) != len(self.audit_findings):
            raise ValueError("audit_findings must not contain duplicates")
        if self.audit_findings != sorted(self.audit_findings):
            raise ValueError("audit_findings must be sorted")
        # Bundle-level: bundle_finding_count == len(bundle_findings)
        if self.bundle_finding_count != len(self.bundle_findings):
            raise ValueError("bundle_finding_count must equal len(bundle_findings)")
        if len(set(self.bundle_findings)) != len(self.bundle_findings):
            raise ValueError("bundle_findings must not contain duplicates")
        if self.bundle_findings != sorted(self.bundle_findings):
            raise ValueError("bundle_findings must be sorted")
        # audit_available must equal (slice_audit_status != "UNAVAILABLE")
        if self.audit_available != (self.slice_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "audit_available must equal (slice_audit_status != 'UNAVAILABLE')"
            )
        # audit_consistent must equal (slice_audit_status == "CONSISTENT")
        if self.audit_consistent != (self.slice_audit_status == "CONSISTENT"):
            raise ValueError(
                "audit_consistent must equal (slice_audit_status == 'CONSISTENT')"
            )
        # provider_name and model_name must be set together
        if (self.provider_name is None) != (self.model_name is None):
            raise ValueError("provider_name and model_name must be set together")
        # Task 165 bundle source is always the canonical constant
        if self.bundle_source != REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165:
            raise ValueError("bundle_source must be the canonical Task 165 source")
        # Child sources are canonical, or the bundle itself names the problem
        canonical_sources = _canonical_sources()
        for field_name, finding_code in _SOURCE_FINDING_CODES.items():
            if (
                getattr(self, field_name) != canonical_sources[field_name]
                and finding_code not in self.bundle_findings
            ):
                raise ValueError(
                    f"{field_name} is not canonical and is not explained by "
                    f"{finding_code}"
                )
        values = {name: getattr(self, name) for name in type(self).model_fields}
        ready_evidence = stage_7_bundle_ready_conditions_hold(values)
        blocking = stage_7_bundle_blocking_condition_holds(values)
        # Precedence BLOCKED > READY > UNAVAILABLE, enforced in both directions
        if self.bundle_status == "BLOCKED":
            if not blocking:
                raise ValueError("BLOCKED bundle requires a published blocking state")
        elif blocking:
            raise ValueError(
                "a published blocking state requires bundle_status BLOCKED"
            )
        elif self.bundle_status == "READY":
            if not ready_evidence:
                raise ValueError("READY bundle requires complete READY evidence")
        elif ready_evidence:
            raise ValueError(
                "UNAVAILABLE bundle must not withhold fully supported READY evidence"
            )
        return self
