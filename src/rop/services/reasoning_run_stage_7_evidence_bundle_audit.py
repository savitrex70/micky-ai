"""Task 166: independent Stage 7 evidence-bundle audit service.

Independent audit boundary over the already-published Task 165 evidence bundle.
The auditor independently derives the expected bundle state from the
published Task 162, Task 163, and Task 164 surfaces already present inside
the bundle, then compares the independently derived state against the
published Task 165 bundle status and findings.

The audit never trusts a self-reported finding as proof of a status: it
derives which Task 165 findings the published evidence actually warrants,
compares that expected set against the published ``bundle_findings``, and
derives the expected status from the evidence and the warranted findings.

The auditor never calls Task 165, never calls Tasks 162-164 services, never
recomputes fingerprints, never invokes a provider, and never accesses a
database. It only reads the already-published evidence surfaces contained
in the Task 165 bundle.

Missing or malformed bundle input is unavailable material, not evidence: the
audit is ``UNAVAILABLE``, names no session or bundle status, and carries an
explicit diagnostic finding. A readable bundle whose published values
contradict the independently derived expectations is ``INCONSISTENT``.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, no mutation. The audit is a deterministic
verification of the Task 165 bundle's internal coherence.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    ReasoningRunStage7EvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
    ReasoningRunStage7EvidenceBundleAuditRead,
    _canonical_sources,
    _derive_expected_bundle_status,
    _present,
    expected_bundle_findings,
)

__all__ = [
    "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166",
    "ReasoningRunStage7EvidenceBundleAuditContractError",
    "ReasoningRunStage7EvidenceBundleAuditService",
]

# Canonical request fingerprint shape: SHA-256 hex digest, exactly
# 64 lowercase hexadecimal characters. Checked with fullmatch so no trailing
# newline slips through. Shape only -- never recomputed.
_REQUEST_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")

_BUNDLE_STATUSES = ("READY", "BLOCKED", "UNAVAILABLE")
_AUDIT_STATUSES = ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE")

# Unavailable-input diagnostics. Detail suffixes name a field and a reason
# only; a published value is never echoed.
_BUNDLE_MISSING = "TASK_165_BUNDLE_MISSING"
_BUNDLE_INVALID = "TASK_165_BUNDLE_INVALID"

# Child source field -> (Task 165 finding that explains a non-canonical value,
# Task 166 finding for an unexplained one).
_SOURCE_AUDIT_CODES = {
    "t162_audit_source": (
        "T162_AUDIT_SOURCE_NOT_CANONICAL",
        "T162_SOURCE_MISMATCH",
    ),
    "certification_source": (
        "T163_CERTIFICATION_SOURCE_NOT_CANONICAL",
        "T163_SOURCE_MISMATCH",
    ),
    "audit_source": (
        "T164_AUDIT_SOURCE_NOT_CANONICAL",
        "T164_SOURCE_MISMATCH",
    ),
}

_STR_FIELDS = (
    "session_id",
    "certification_source",
    "audit_source",
    "t162_audit_source",
    "bundle_source",
)
_OPTIONAL_STR_FIELDS = ("provider_name", "model_name", "request_fingerprint")
_LIST_FIELDS = ("findings", "audit_findings", "bundle_findings")
_INT_FIELDS = ("finding_count", "audit_finding_count", "bundle_finding_count")
_BOOL_FIELDS = ("audit_available", "audit_consistent")


class ReasoningRunStage7EvidenceBundleAuditContractError(Exception):
    """Task 166: the evidence-bundle audit cannot be performed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def _canonical_fingerprint(value: str | None) -> bool:
    """Report whether a request fingerprint has the canonical shape.

    Shape-only check; the value is never recomputed, normalised, or
    repaired.
    """
    return (
        isinstance(value, str) and _REQUEST_FINGERPRINT_RE.fullmatch(value) is not None
    )


def _invalid_detail(exc: ValidationError) -> str:
    """Render one deterministic contract-rejection reason, never a value."""
    details = sorted(
        f"{'.'.join(str(part) for part in error['loc']) or 'model'}:{error['type']}"
        for error in exc.errors()
    )
    return details[0]


def _shape_problem(values: Mapping[str, Any]) -> str | None:
    """Return the first field whose type makes the bundle unreadable, if any.

    Only types are checked here. Statuses that are readable but wrong are
    contradictions the audit reports as findings, except the published
    bundle status, which the audit result must be able to name.
    """
    for name in _STR_FIELDS:
        if not isinstance(values[name], str):
            return f"{name}:not_a_string"
    for name in _OPTIONAL_STR_FIELDS:
        if values[name] is not None and not isinstance(values[name], str):
            return f"{name}:not_a_string"
    for name in _LIST_FIELDS:
        value = values[name]
        if not isinstance(value, list) or not all(isinstance(i, str) for i in value):
            return f"{name}:not_a_string_list"
    for name in _INT_FIELDS:
        if not isinstance(values[name], int) or isinstance(values[name], bool):
            return f"{name}:not_an_integer"
    for name in _BOOL_FIELDS:
        if not isinstance(values[name], bool):
            return f"{name}:not_a_boolean"
    if values["bundle_status"] not in _BUNDLE_STATUSES:
        return "bundle_status:not_a_bundle_status"
    return None


def _read_bundle(bundle: object) -> tuple[dict[str, Any] | None, str | None]:
    """Read the bundle's published fields, or report why it is unreadable.

    A typed bundle is read field by field and is deliberately not re-validated:
    the audit exists to catch a bundle whose published values contradict its
    own evidence. A mapping carries no such guarantee and must satisfy the
    Task 165 contract before it is read.
    """
    field_names = tuple(ReasoningRunStage7EvidenceBundleRead.model_fields)
    if bundle is None:
        return None, _BUNDLE_MISSING
    if isinstance(bundle, Mapping):
        try:
            bundle = ReasoningRunStage7EvidenceBundleRead.model_validate(dict(bundle))
        except ValidationError as exc:
            return None, f"{_BUNDLE_INVALID}:{_invalid_detail(exc)}"
        except Exception as exc:
            return None, f"{_BUNDLE_INVALID}:{type(exc).__name__}"
    elif not isinstance(bundle, ReasoningRunStage7EvidenceBundleRead):
        return None, f"{_BUNDLE_INVALID}:model:not_a_bundle"
    values: dict[str, Any] = {}
    for name in field_names:
        try:
            values[name] = getattr(bundle, name)
        except AttributeError:
            return None, f"{_BUNDLE_INVALID}:{name}:missing"
    problem = _shape_problem(values)
    if problem is not None:
        return None, f"{_BUNDLE_INVALID}:{problem}"
    return values, None


def _list_findings(count: int, items: list[str], code: str, findings: set[str]) -> None:
    """Flag a published finding list whose count, order, or uniqueness is off."""
    if count != len(items):
        findings.add(code)
    if len(set(items)) != len(items):
        findings.add(code)
    if items != sorted(items):
        findings.add(code)


def _task_164_findings(values: Mapping[str, Any]) -> set[str]:
    """Audit the coherence of the Task 163/164 evidence the bundle publishes.

    Applied to every bundle, whatever its outer status: a contradictory Task
    164 surface is not excused by a BLOCKED or UNAVAILABLE bundle.
    """
    found: set[str] = set()
    audit_status = values["slice_audit_status"]
    if audit_status not in _AUDIT_STATUSES:
        found.add("AUDIT_STATUS_MISMATCH")
        return found
    if values["audit_available"] is not (audit_status != "UNAVAILABLE"):
        found.add("AUDIT_AVAILABLE_MISMATCH")
    if values["audit_consistent"] is not (audit_status == "CONSISTENT"):
        found.add("AUDIT_CONSISTENT_MISMATCH")

    published = values["published_slice_status"]
    expected = values["expected_slice_status"]
    has_audit_findings = bool(values["audit_findings"])

    if audit_status == "UNAVAILABLE":
        # Unreadable material compared nothing: no status may be named, and
        # a diagnostic finding must say why.
        if published is not None:
            found.add("PUBLISHED_SLICE_STATUS_MISMATCH")
        if expected is not None:
            found.add("EXPECTED_SLICE_STATUS_MISMATCH")
        if not has_audit_findings:
            found.add("AUDIT_STATUS_MISMATCH")
        # Task 164 names no session when it is UNAVAILABLE, so Task 165 cannot
        # legitimately bind a common session to it.
        if _present(values["session_id"]):
            found.add("SESSION_ID_MISMATCH")
        return found

    # A compared audit names both statuses, and the published one must be
    # the Task 163 verdict the bundle itself publishes.
    if published not in _BUNDLE_STATUSES or published != values["slice_status"]:
        found.add("PUBLISHED_SLICE_STATUS_MISMATCH")
    if expected not in _BUNDLE_STATUSES:
        found.add("EXPECTED_SLICE_STATUS_MISMATCH")
    if audit_status == "CONSISTENT":
        if (
            published in _BUNDLE_STATUSES
            and expected in _BUNDLE_STATUSES
            and published != expected
        ):
            found.add("EXPECTED_SLICE_STATUS_MISMATCH")
        if has_audit_findings or values["audit_finding_count"] != 0:
            found.add("AUDIT_STATUS_MISMATCH")
    elif not has_audit_findings:
        # INCONSISTENT must be explained by at least one audit finding.
        found.add("AUDIT_STATUS_MISMATCH")
    return found


class ReasoningRunStage7EvidenceBundleAuditService:
    """Deterministic read-only audit of one Stage 7 evidence bundle."""

    @staticmethod
    def audit(
        *,
        bundle: ReasoningRunStage7EvidenceBundleRead | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Independently audit one already-published Task 165 evidence bundle.

        The audit derives the expected bundle status and the expected Task 165
        findings from the published Task 162, Task 163, and Task 164 evidence
        surfaces already present inside the bundle, then compares both against
        what the bundle publishes.

        ``CONSISTENT`` when the independently derived expectations match the
        published Task 165 bundle. ``INCONSISTENT`` when the published
        evidence contradicts them. ``UNAVAILABLE`` for missing or malformed
        Task 165 input, in which case nothing is verified and no session or
        bundle status is claimed.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        values, marker = _read_bundle(bundle)
        if values is None:
            return ReasoningRunStage7EvidenceBundleAuditService._project(
                {
                    "session_id": "",
                    "bundle_audit_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "published_bundle_status": None,
                    "expected_bundle_status": None,
                    "finding_count": 1,
                    "findings": [marker],
                    "audit_source": (
                        REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166
                    ),
                }
            )

        findings: set[str] = set()
        published_status = values["bundle_status"]

        # Step A — Validate bundle source
        if (
            values["bundle_source"]
            != REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165
        ):
            findings.add("TASK_165_SOURCE_MISMATCH")

        # Step B — Validate session identity in every bundle state. A blank
        # identity is faithful only when the bundle explains it with the
        # canonical Task 165 finding, and never under a READY claim.
        if not _present(values["session_id"]) and (
            published_status == "READY"
            or "STAGE_7_SESSION_MISMATCH" not in set(values["bundle_findings"])
        ):
            findings.add("SESSION_ID_MISMATCH")

        # Step C — Validate child sources. A non-canonical source the bundle
        # itself explains with its Task 165 finding is a faithful bundle; the
        # exact finding comparison in Step J checks that explanation. Only an
        # unexplained non-canonical source is a forgery.
        canonical_sources = _canonical_sources()
        published_codes = set(values["bundle_findings"])
        for field_name, (explaining_code, audit_code) in _SOURCE_AUDIT_CODES.items():
            if (
                values[field_name] != canonical_sources[field_name]
                and explaining_code not in published_codes
            ):
                findings.add(audit_code)

        # Step D — Validate fingerprint shape (no recomputation, only for READY)
        if published_status == "READY" and not _canonical_fingerprint(
            values["request_fingerprint"]
        ):
            findings.add("FINGERPRINT_MISMATCH")

        # Step E — Validate provider/model attribution (only for READY bundles)
        if published_status == "READY":
            if not _present(values["provider_name"]):
                findings.add("PROVIDER_NAME_MISMATCH")
            if not _present(values["model_name"]):
                findings.add("MODEL_NAME_MISMATCH")

        # Step F — Validate Task 163 evidence coherence
        if values["slice_status"] not in _BUNDLE_STATUSES:
            findings.add("SLICE_STATUS_MISMATCH")
        if values["admission_status"] not in (
            "ADMITTED",
            "BLOCKED",
            "UNAVAILABLE",
            None,
        ):
            findings.add("ADMISSION_STATUS_MISMATCH")
        if values["diagnostics_status"] not in (
            "HEALTHY",
            "DEGRADED",
            "UNHEALTHY",
            "NO_MATERIAL",
            None,
        ):
            findings.add("DIAGNOSTICS_STATUS_MISMATCH")

        # Step G — Validate Task 164 evidence coherence, in every bundle state
        findings |= _task_164_findings(values)

        # Step H — Validate Task 162 attribution coherence
        if values["request_audit_status"] not in (*_AUDIT_STATUSES, None):
            findings.add("REQUEST_AUDIT_STATUS_MISMATCH")
        if values["proposal_audit_status"] not in (*_AUDIT_STATUSES, None):
            findings.add("PROPOSAL_AUDIT_STATUS_MISMATCH")

        # Step I — Validate published finding lists
        _list_findings(
            values["finding_count"], values["findings"], "FINDINGS_MISMATCH", findings
        )
        _list_findings(
            values["audit_finding_count"],
            values["audit_findings"],
            "AUDIT_FINDINGS_MISMATCH",
            findings,
        )
        _list_findings(
            values["bundle_finding_count"],
            values["bundle_findings"],
            "BUNDLE_FINDING_MISMATCH",
            findings,
        )

        # Step J — Derive the Task 165 findings the evidence warrants and
        # compare them against the published findings exactly. The published
        # list is evidence to be checked, never a premise.
        required, optional = expected_bundle_findings(values)
        published_findings = set(values["bundle_findings"])
        if (required - published_findings) or (
            published_findings - required - optional
        ):
            findings.add("BUNDLE_FINDING_MISMATCH")

        # Step K — Derive the expected bundle status from the evidence and the
        # warranted findings, then compare against the published status
        expected_status = _derive_expected_bundle_status(values, required)
        if expected_status != published_status:
            findings.add("BUNDLE_STATUS_MISMATCH")

        # Step L — Populate result dict
        sorted_findings = sorted(findings)
        bundle_audit_status = "INCONSISTENT" if sorted_findings else "CONSISTENT"

        result: dict[str, Any] = {
            "session_id": values["session_id"],
            "bundle_audit_status": bundle_audit_status,
            "available": True,
            "consistent": bundle_audit_status == "CONSISTENT",
            "published_bundle_status": published_status,
            "expected_bundle_status": expected_status,
            "finding_count": len(sorted_findings),
            "findings": sorted_findings,
            "audit_source": REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
        }

        # Step M — Validate through schema, raise on contract error
        return ReasoningRunStage7EvidenceBundleAuditService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the audit result through the strict contract."""
        try:
            validated = ReasoningRunStage7EvidenceBundleAuditRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7EvidenceBundleAuditContractError(
                "EVIDENCE_BUNDLE_AUDIT_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
