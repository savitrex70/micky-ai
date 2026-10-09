"""Task 167: Stage 7 evidence-bundle audit consistency service.

Independent consistency boundary between the Task 165 Evidence Bundle and the
Task 166 Evidence-Bundle Audit. The service proves that the audit belongs to
the exact bundle supplied: the Task 166 audit carries a snapshot of the
bundle evidence it audited, and the supplied bundle must equal that snapshot
field for field. Matching session and statuses alone is never enough.

Verdicts:

* ``UNAVAILABLE`` -- an input, or the binding material (the audited-bundle
  snapshot), is missing or malformed. Nothing is verified and no session is
  claimed.
* ``INCONSISTENT`` -- both inputs are readable but the audit is detached from
  the bundle, forges a provenance source, contradicts itself, or itself
  reports the bundle inconsistent. An audit that is correctly bound to its
  bundle and reports INCONSISTENT is a valid audit of an inconsistent
  bundle: it yields the single ``AUDIT_REPORTS_BUNDLE_INCONSISTENT`` finding
  and no binding finding, so it stays distinguishable from a detached audit
  and from an unavailable one.
* ``CONSISTENT`` -- the supplied bundle equals the audit's snapshot, all
  provenance and status checks hold, and the audit itself is CONSISTENT.

The service never calls Task 165 or Task 166 services, never recomputes
fingerprints, never invokes a provider, and never accesses a database. It
only reads the already-published objects. Read-only and pure: no database
session, no persistence, no network, no mutation.
"""

from __future__ import annotations

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
    ReasoningRunStage7EvidenceBundleSnapshot,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167,
    ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167",
    "ReasoningRunStage7EvidenceBundleAuditConsistencyContractError",
    "ReasoningRunStage7EvidenceBundleAuditConsistencyService",
]

_AUDIT_STATUSES = ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE")

# Unavailable-input diagnostics. Detail suffixes name a field and a reason
# only; a published value is never echoed.
_BUNDLE_MISSING = "TASK_165_BUNDLE_MISSING"
_BUNDLE_INVALID = "TASK_165_BUNDLE_INVALID"
_AUDIT_MISSING = "TASK_166_AUDIT_MISSING"
_AUDIT_INVALID = "TASK_166_AUDIT_INVALID"
_AUDIT_UNAVAILABLE = "TASK_166_AUDIT_UNAVAILABLE"
_SNAPSHOT_MISSING = "TASK_166_AUDITED_BUNDLE_MISSING"

# Published-field type groups for the Task 165 bundle (and its snapshot).
_BUNDLE_STR = (
    "session_id",
    "certification_source",
    "audit_source",
    "t162_audit_source",
    "bundle_source",
    "bundle_status",
)
_BUNDLE_OPTIONAL_STR = (
    "slice_status",
    "admission_status",
    "diagnostics_status",
    "provider_name",
    "model_name",
    "slice_audit_status",
    "published_slice_status",
    "expected_slice_status",
    "request_fingerprint",
    "request_audit_status",
    "proposal_audit_status",
)
_BUNDLE_LISTS = ("findings", "audit_findings", "bundle_findings")
_BUNDLE_INTS = ("finding_count", "audit_finding_count", "bundle_finding_count")
_BUNDLE_BOOLS = ("audit_available", "audit_consistent")

_AUDIT_STR = ("session_id", "bundle_audit_status", "audit_source")
_AUDIT_OPTIONAL_STR = ("published_bundle_status", "expected_bundle_status")


class ReasoningRunStage7EvidenceBundleAuditConsistencyContractError(Exception):
    """Task 167: the bundle-audit consistency cannot be verified."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def _invalid_detail(exc: ValidationError) -> str:
    """Render one deterministic contract-rejection reason, never a value."""
    details = sorted(
        f"{'.'.join(str(part) for part in error['loc']) or 'model'}:{error['type']}"
        for error in exc.errors()
    )
    return details[0]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _bundle_shape_problem(values: Mapping[str, Any]) -> str | None:
    """Return the first bundle field whose type makes the object unreadable."""
    for name in _BUNDLE_STR:
        if not isinstance(values[name], str):
            return f"{name}:not_a_string"
    for name in _BUNDLE_OPTIONAL_STR:
        if values[name] is not None and not isinstance(values[name], str):
            return f"{name}:not_a_string"
    for name in _BUNDLE_LISTS:
        if not _is_str_list(values[name]):
            return f"{name}:not_a_string_list"
    for name in _BUNDLE_INTS:
        if not _is_int(values[name]):
            return f"{name}:not_an_integer"
    for name in _BUNDLE_BOOLS:
        if not isinstance(values[name], bool):
            return f"{name}:not_a_boolean"
    return None


def _read_fields(obj: object, names: tuple[str, ...]) -> tuple[dict[str, Any], str]:
    """Read named attributes; return the values and the first missing name."""
    values: dict[str, Any] = {}
    for name in names:
        try:
            values[name] = getattr(obj, name)
        except AttributeError:
            return values, name
    return values, ""


def _read_bundle(bundle: object) -> tuple[dict[str, Any] | None, str | None]:
    """Read the Task 165 bundle's published fields, or say why it is unreadable.

    A typed bundle is read field by field and deliberately not re-validated
    against the Task 165 coherence rules: the binding check must be able to
    see a bundle whose published values were altered, for example a forged
    source. A mapping carries no such guarantee and must satisfy the Task 165
    contract before it is read.
    """
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
    names = tuple(ReasoningRunStage7EvidenceBundleRead.model_fields)
    values, missing = _read_fields(bundle, names)
    if missing:
        return None, f"{_BUNDLE_INVALID}:{missing}:missing"
    problem = _bundle_shape_problem(values)
    if problem is not None:
        return None, f"{_BUNDLE_INVALID}:{problem}"
    return values, None


def _read_audit(
    audit: object,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Read the Task 166 audit and its snapshot, or say why it is unreadable.

    Returns ``(audit_values, snapshot_values, marker)``. ``snapshot_values`` is
    ``None`` when the audit carries no snapshot. Like the bundle, a typed
    audit is read field by field so that a tampered audit is reported rather
    than hidden; a mapping must satisfy the Task 166 contract first.
    """
    if audit is None:
        return None, None, _AUDIT_MISSING
    if isinstance(audit, Mapping):
        try:
            audit = ReasoningRunStage7EvidenceBundleAuditRead.model_validate(
                dict(audit)
            )
        except ValidationError as exc:
            return None, None, f"{_AUDIT_INVALID}:{_invalid_detail(exc)}"
        except Exception as exc:
            return None, None, f"{_AUDIT_INVALID}:{type(exc).__name__}"
    elif not isinstance(audit, ReasoningRunStage7EvidenceBundleAuditRead):
        return None, None, f"{_AUDIT_INVALID}:model:not_an_audit"
    names = tuple(ReasoningRunStage7EvidenceBundleAuditRead.model_fields)
    values, missing = _read_fields(audit, names)
    if missing:
        return None, None, f"{_AUDIT_INVALID}:{missing}:missing"
    for name in _AUDIT_STR:
        if not isinstance(values[name], str):
            return None, None, f"{_AUDIT_INVALID}:{name}:not_a_string"
    for name in _AUDIT_OPTIONAL_STR:
        if values[name] is not None and not isinstance(values[name], str):
            return None, None, f"{_AUDIT_INVALID}:{name}:not_a_string"
    for name in ("available", "consistent"):
        if not isinstance(values[name], bool):
            return None, None, f"{_AUDIT_INVALID}:{name}:not_a_boolean"
    if not _is_int(values["finding_count"]):
        return None, None, f"{_AUDIT_INVALID}:finding_count:not_an_integer"
    if not _is_str_list(values["findings"]):
        return None, None, f"{_AUDIT_INVALID}:findings:not_a_string_list"
    if values["bundle_audit_status"] not in _AUDIT_STATUSES:
        return None, None, f"{_AUDIT_INVALID}:bundle_audit_status:not_an_audit_status"

    snapshot = values["audited_bundle"]
    if snapshot is None:
        return values, None, None
    if not isinstance(snapshot, ReasoningRunStage7EvidenceBundleSnapshot):
        return None, None, f"{_AUDIT_INVALID}:audited_bundle:not_a_snapshot"
    snapshot_names = tuple(ReasoningRunStage7EvidenceBundleSnapshot.model_fields)
    snapshot_values, missing = _read_fields(snapshot, snapshot_names)
    if missing:
        return None, None, f"{_AUDIT_INVALID}:audited_bundle.{missing}:missing"
    problem = _bundle_shape_problem(snapshot_values)
    if problem is not None:
        return None, None, f"{_AUDIT_INVALID}:audited_bundle.{problem}"
    return values, snapshot_values, None


def _same(left: object, right: object) -> bool:
    """Exact equality: same type and same value, element by element for lists."""
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right


def _audit_internal_findings(
    audit: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> set[str]:
    """Report a Task 166 audit that contradicts its own contract."""
    found: set[str] = set()
    status = audit["bundle_audit_status"]
    findings = audit["findings"]
    if audit["available"] is not True or audit["consistent"] is not (
        status == "CONSISTENT"
    ):
        found.add("AUDIT_INTERNAL_MISMATCH")
    if audit["finding_count"] != len(findings):
        found.add("AUDIT_INTERNAL_MISMATCH")
    if len(set(findings)) != len(findings) or findings != sorted(findings):
        found.add("AUDIT_INTERNAL_MISMATCH")
    if (
        audit["published_bundle_status"] is None
        or audit["expected_bundle_status"] is None
    ):
        found.add("AUDIT_INTERNAL_MISMATCH")
    if status == "CONSISTENT" and (
        findings or audit["published_bundle_status"] != audit["expected_bundle_status"]
    ):
        found.add("AUDIT_INTERNAL_MISMATCH")
    if status == "INCONSISTENT" and not findings:
        found.add("AUDIT_INTERNAL_MISMATCH")
    # The snapshot the audit carries must describe the audit's own subject.
    if (
        snapshot["session_id"] != audit["session_id"]
        or snapshot["bundle_status"] != audit["published_bundle_status"]
    ):
        found.add("AUDIT_INTERNAL_MISMATCH")
    return found


class ReasoningRunStage7EvidenceBundleAuditConsistencyService:
    """Deterministic read-only consistency check for bundle-audit binding."""

    @staticmethod
    def verify(
        *,
        bundle: ReasoningRunStage7EvidenceBundleRead | Mapping[str, Any] | None = None,
        audit: (
            ReasoningRunStage7EvidenceBundleAuditRead | Mapping[str, Any] | None
        ) = None,
    ) -> dict[str, Any]:
        """Verify that ``audit`` is bound to the exact ``bundle`` supplied.

        ``UNAVAILABLE`` for a missing or malformed input, an audit that is
        itself unavailable, or an audit without its audited-bundle snapshot:
        nothing is verified and no session is claimed. ``INCONSISTENT`` when
        both are readable but the audit is detached, forged, self-
        contradictory, or reports the bundle inconsistent. ``CONSISTENT``
        only when the bundle equals the audit's snapshot and every provenance
        and status check holds.

        No child service is invoked, no fingerprint is recomputed, no input is
        modified, and no database is touched.
        """
        bundle_values, bundle_marker = _read_bundle(bundle)
        audit_values, snapshot, audit_marker = _read_audit(audit)

        markers: set[str] = set()
        if bundle_marker is not None:
            markers.add(bundle_marker)
        if audit_marker is not None:
            markers.add(audit_marker)
        elif audit_values is not None:
            if audit_values["bundle_audit_status"] == "UNAVAILABLE":
                markers.add(_AUDIT_UNAVAILABLE)
            elif snapshot is None:
                markers.add(_SNAPSHOT_MISSING)
        if markers or bundle_values is None or audit_values is None or snapshot is None:
            return ReasoningRunStage7EvidenceBundleAuditConsistencyService._project(
                {
                    "session_id": "",
                    "consistency_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "finding_count": len(markers),
                    "findings": sorted(markers),
                    "consistency_source": (
                        REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167
                    ),
                }
            )

        findings: set[str] = set()

        # Step A — Provenance: both sources must be canonical.
        if (
            bundle_values["bundle_source"]
            != REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165
        ):
            findings.add("BUNDLE_SOURCE_MISMATCH")
        if (
            audit_values["audit_source"]
            != REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166
        ):
            findings.add("AUDIT_SOURCE_MISMATCH")

        # Step B — Exact evidence binding: the supplied bundle must equal the
        # snapshot the audit recorded, field for field, with no
        # normalisation and no fingerprint recomputation.
        if any(
            not _same(bundle_values[name], snapshot[name]) for name in bundle_values
        ):
            findings.add("BUNDLE_SNAPSHOT_MISMATCH")

        # Step C — Session identity and published status must match.
        if bundle_values["session_id"] != audit_values["session_id"]:
            findings.add("SESSION_MISMATCH")
        if bundle_values["bundle_status"] != audit_values["published_bundle_status"]:
            findings.add("PUBLISHED_STATUS_MISMATCH")

        # Step D — The audit must be coherent with itself and its snapshot.
        findings |= _audit_internal_findings(audit_values, snapshot)

        # Step E — Audit verdict. A CONSISTENT audit must expect exactly the
        # status the bundle published. An INCONSISTENT audit that is bound to
        # its bundle is valid evidence that the bundle itself is inconsistent;
        # it is reported as such rather than as a binding failure.
        if audit_values["bundle_audit_status"] == "CONSISTENT":
            if bundle_values["bundle_status"] != audit_values["expected_bundle_status"]:
                findings.add("EXPECTED_STATUS_CONTRADICTION")
        else:
            findings.add("AUDIT_REPORTS_BUNDLE_INCONSISTENT")

        sorted_findings = sorted(findings)
        status = "INCONSISTENT" if sorted_findings else "CONSISTENT"
        return ReasoningRunStage7EvidenceBundleAuditConsistencyService._project(
            {
                "session_id": bundle_values["session_id"],
                "consistency_status": status,
                "available": True,
                "consistent": status == "CONSISTENT",
                "finding_count": len(sorted_findings),
                "findings": sorted_findings,
                "consistency_source": (
                    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167
                ),
            }
        )

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the consistency result through the strict contract."""
        try:
            validated = (
                ReasoningRunStage7EvidenceBundleAuditConsistencyRead.model_validate(
                    result
                )
            )
        except ValidationError as exc:
            raise ReasoningRunStage7EvidenceBundleAuditConsistencyContractError(
                "BUNDLE_AUDIT_CONSISTENCY_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
