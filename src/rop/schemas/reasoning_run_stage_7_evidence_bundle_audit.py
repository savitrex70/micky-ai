"""Task 166: independent Stage 7 evidence-bundle audit contract.

Strict read-only audit verdict for one published Task 165 evidence bundle.
The audit independently derives the expected bundle state from the
published Task 162, Task 163, and Task 164 surfaces already present inside
the bundle, then compares the independently derived state against the
published Task 165 bundle status.

The audit is a pure, provider-neutral boundary: it never calls Task 165,
never calls Tasks 162-164 services, never recomputes fingerprints, never
invokes a provider, and never accesses a database. It only reads the
already-published evidence surfaces contained in the validated Task 165
bundle.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

# The Task 166 source constant lives here, next to the contract that enforces
# it, so the schema never has to import the service that imports the schema.
# The service re-exports the same name.
REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166 = (
    "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_TASK_166"
)

# Canonical request fingerprint shape: exactly 64 lowercase hexadecimal
# characters, matched with fullmatch so no trailing newline slips through.
# Shape only -- the value is never recomputed, normalised, or repaired.
_REQUEST_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")

# Task 165 finding codes that explain a published non-canonical child source,
# keyed by the bundle field that carries the source.
_SOURCE_FINDING_CODES = {
    "t162_audit_source": "T162_AUDIT_SOURCE_NOT_CANONICAL",
    "certification_source": "T163_CERTIFICATION_SOURCE_NOT_CANONICAL",
    "audit_source": "T164_AUDIT_SOURCE_NOT_CANONICAL",
}


@cache
def _canonical_sources() -> dict[str, str]:
    """Return the canonical Task 162/163/164/165 source constants.

    The constants are imported on first use rather than at module import
    time: the schemas package is loaded before the services package, and
    the services import the schemas, so a top-level import here would be
    circular. Only the four source constants are ever read; no service
    is called.
    """
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
        "certification_source": REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
        "audit_source": REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
        "bundle_source": REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    }


def _present(value: object) -> bool:
    """Report whether a value is a non-empty string."""
    return isinstance(value, str) and value.strip() != ""


def expected_bundle_findings(
    values: Mapping[str, object],
) -> tuple[frozenset[str], frozenset[str]]:
    """Independently derive the Task 165 findings the published evidence warrants.

    Pure and audit-local: it reads only the bundle's own published evidence
    fields and never the published ``bundle_findings`` list, so a forged or
    withheld finding can never vouch for itself. The canonical Task 165
    finding codes keep their established meanings.

    Returns ``(required, optional)``. ``required`` findings are warranted by
    the evidence and must be published. ``optional`` findings are warranted
    only if the unpublished Task 162 package carried the condition, which
    the bundle cannot show; they may be published but are never demanded.
    Any published finding outside both sets is unsupported.
    """
    required: set[str] = set()
    optional: set[str] = set()

    # Task 165 empties the session only together with this finding, and
    # never publishes it for a non-empty session identity.
    if values["session_id"] == "":
        required.add("STAGE_7_SESSION_MISMATCH")

    sources = _canonical_sources()
    for field_name, code in _SOURCE_FINDING_CODES.items():
        if values[field_name] != sources[field_name]:
            required.add(code)

    # A fingerprint that is absent or not canonical is withheld and explained.
    fingerprint = values["request_fingerprint"]
    if not (
        isinstance(fingerprint, str)
        and _REQUEST_FINGERPRINT_RE.fullmatch(fingerprint) is not None
    ):
        required.add("REQUEST_FINGERPRINT_MISSING_OR_MALFORMED")

    # Task 163 publishes the package attribution verbatim for any attributed
    # (READY or BLOCKED) slice, so missing attribution there is warranted.
    # For an UNAVAILABLE slice it publishes none regardless of the package,
    # so the finding cannot be demanded or refuted from the bundle.
    if not values["provider_name"] or not values["model_name"]:
        if values["slice_status"] in ("READY", "BLOCKED"):
            required.add("PROVIDER_ATTRIBUTION_MISSING")
        elif values["slice_status"] == "UNAVAILABLE":
            optional.add("PROVIDER_ATTRIBUTION_MISSING")

    return frozenset(required), frozenset(optional - required)


def _derive_expected_bundle_status(
    values: Mapping[str, object], warranted_findings: frozenset[str]
) -> str:
    """Independently derive the expected bundle status from published evidence.

    Pure function that reads only the Task 165 bundle's published evidence
    fields and the findings the evidence itself warrants. It never trusts the
    published ``bundle_findings`` list: a fabricated finding cannot turn
    complete READY evidence into UNAVAILABLE. The derivation follows the
    BLOCKED > READY > UNAVAILABLE precedence.
    """
    # BLOCKED conditions: any canonical blocking state in the published evidence
    blocked = (
        values["slice_status"] == "BLOCKED"
        or values["admission_status"] == "BLOCKED"
        or values["diagnostics_status"] == "UNHEALTHY"
        or values["request_audit_status"] == "INCONSISTENT"
        or values["proposal_audit_status"] == "INCONSISTENT"
    )

    if blocked:
        return "BLOCKED"

    # READY conditions: all canonical READY conditions must hold
    fingerprint = values["request_fingerprint"]
    sources = _canonical_sources()
    ready = (
        not warranted_findings
        and _present(values["session_id"])
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
        and values["bundle_source"] == sources["bundle_source"]
    )

    if ready:
        return "READY"

    return "UNAVAILABLE"


class ReasoningRunStage7EvidenceBundleAuditRead(BaseModel):
    """Strict read model for one independent Stage 7 evidence-bundle audit.

    ``bundle_audit_status`` is the single audit verdict: ``CONSISTENT`` when
    the independently derived expected state matches the published Task 165
    bundle, ``INCONSISTENT`` when the published evidence contradicts the
    independently derived result, and ``UNAVAILABLE`` for missing or malformed
    Task 165 input. ``published_bundle_status`` is the status the Task 165
    bundle claims, and ``expected_bundle_status`` is the status independently
    derived from the published evidence surfaces; both are ``None`` exactly
    when the audit is ``UNAVAILABLE``, because nothing was verified. An
    ``UNAVAILABLE`` audit also names no session. ``findings`` are
    deterministic, sorted, and deduplicated; ``finding_count`` always
    equals ``len(findings)``. ``audit_source`` is always the canonical
    Task 166 source.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    bundle_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    available: bool
    consistent: bool
    published_bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    expected_bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"] | None
    finding_count: int
    findings: list[str]
    audit_source: str

    @model_validator(mode="after")
    def _coherent_audit(self) -> ReasoningRunStage7EvidenceBundleAuditRead:
        if (
            self.audit_source
            != REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166
        ):
            raise ValueError("audit_source must be the canonical Task 166 source")
        if self.available != (self.bundle_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "available must equal (bundle_audit_status != 'UNAVAILABLE')"
            )
        if self.consistent != (self.bundle_audit_status == "CONSISTENT"):
            raise ValueError(
                "consistent must equal (bundle_audit_status == 'CONSISTENT')"
            )
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.bundle_audit_status == "UNAVAILABLE":
            if (
                self.published_bundle_status is not None
                or self.expected_bundle_status is not None
            ):
                raise ValueError("UNAVAILABLE must not name a bundle status")
            if self.session_id != "":
                raise ValueError("UNAVAILABLE must not claim a session identity")
            if not self.findings:
                raise ValueError("UNAVAILABLE requires at least one diagnostic finding")
            return self
        if self.published_bundle_status is None or self.expected_bundle_status is None:
            raise ValueError("a compared audit requires both bundle statuses")
        if self.bundle_audit_status == "CONSISTENT":
            if self.published_bundle_status != self.expected_bundle_status:
                raise ValueError(
                    "CONSISTENT requires published and expected bundle status to match"
                )
            if self.findings:
                raise ValueError("CONSISTENT requires a finding-free audit")
        elif not self.findings:
            raise ValueError("INCONSISTENT requires at least one finding")
        return self
