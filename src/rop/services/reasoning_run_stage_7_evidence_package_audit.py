"""Task 169: independent Stage 7 evidence-package audit service.

Independent audit boundary over the already-published Task 168 evidence package.
The auditor receives the package and the underlying Task 162-167 evidence as
arguments and independently derives, from that evidence alone, the complete
state Task 168 is contractually required to publish: every package-level
finding (canonical sources, session/status/attribution/fingerprint/finding
bindings, Task 165 bundle coherence, Task 165/166 snapshot binding, Task
164/166 availability and consistency relationships, and Task 167's expected
verdict) unioned with the child findings, and the BLOCKED > READY >
UNAVAILABLE package status. It then compares the derived state against the
published package. The package's own findings are never the oracle.

The auditor never calls Task 168, never calls Tasks 162-167 services, never
recomputes fingerprints, never invokes a provider, and never accesses a
database. It only reads already-published evidence and the canonical source
constants.

Verdict contract (shared with the result schema):

* ``CONSISTENT`` -- everything was readable and the published package equals
  the independently derived state. A correctly assembled ``UNAVAILABLE`` or
  ``BLOCKED`` package is ``CONSISTENT``.
* ``INCONSISTENT`` -- everything was readable but the package contradicts the
  derived state, or the evidence breaks a precondition Task 168 would refuse
  to publish.
* ``UNAVAILABLE`` -- the package or the supplied evidence is too malformed to
  audit (wrong model, missing or wrongly shaped nested object, unreadable
  identity, or a published status outside the permitted set). Nothing is
  verified: no package status is named and the findings only say why.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, no mutation. Published models may have
been mutated after construction, so every input is read once into a plain
view and shape-checked before any derivation uses it.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
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
from rop.schemas.reasoning_run_stage_7_evidence_package import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    ReasoningRunStage7EvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    ReasoningRunStage7EvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
    ReasoningRunStage7VerticalSliceAuditRead,
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

__all__ = [
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169",
    "ReasoningRunStage7EvidencePackageAuditContractError",
    "ReasoningRunStage7EvidencePackageAuditService",
]


class ReasoningRunStage7EvidencePackageAuditContractError(Exception):
    """Task 169: the evidence-package audit cannot be performed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class _Unreadable(Exception):
    """Internal: published evidence is too malformed to audit.

    ``code`` is the deterministic diagnostic finding the audit reports.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_PERMITTED_PACKAGE_STATUSES = ("READY", "BLOCKED", "UNAVAILABLE")

# Task 165 status fields and the values each may legitimately publish.
_BUNDLE_STATUS_FIELDS = (
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
_ALLOWED_BUNDLE_STATUSES: dict[str, tuple[object, ...]] = {
    "bundle_status": ("READY", "BLOCKED", "UNAVAILABLE"),
    "slice_status": ("READY", "BLOCKED", "UNAVAILABLE"),
    "admission_status": ("ADMITTED", "BLOCKED", "UNAVAILABLE", None),
    "diagnostics_status": ("HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL", None),
    "slice_audit_status": ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE"),
    "published_slice_status": ("READY", "BLOCKED", "UNAVAILABLE", None),
    "expected_slice_status": ("READY", "BLOCKED", "UNAVAILABLE", None),
    "request_audit_status": ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE", None),
    "proposal_audit_status": ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE", None),
}

# Package fields that must be a list of strings for the package to be readable.
_PACKAGE_LIST_FIELDS = (
    "t162_findings",
    "t163_findings",
    "t164_findings",
    "t165_bundle_findings",
    "t166_findings",
    "t167_findings",
    "findings",
)

# (package field, evidence field, finding when the package copy disagrees).
_T162_BINDINGS = (
    ("t162_session_id", "session_id", "T162_SESSION_MISMATCH"),
    ("t162_admission_status", "admission_status", "T162_ADMISSION_STATUS_MISMATCH"),
    (
        "t162_diagnostics_status",
        "diagnostics_status",
        "T162_DIAGNOSTICS_STATUS_MISMATCH",
    ),
    (
        "t162_request_fingerprint",
        "request_fingerprint",
        "T162_REQUEST_FINGERPRINT_MISMATCH",
    ),
    (
        "t162_request_audit_status",
        "request_audit_status",
        "T162_REQUEST_AUDIT_STATUS_MISMATCH",
    ),
    (
        "t162_proposal_audit_status",
        "proposal_audit_status",
        "T162_PROPOSAL_AUDIT_STATUS_MISMATCH",
    ),
    ("t162_provider_name", "provider_name", "T162_PROVIDER_NAME_MISMATCH"),
    ("t162_model_name", "model_name", "T162_MODEL_NAME_MISMATCH"),
    ("t162_finding_count", "finding_count", "T162_FINDING_COUNT_MISMATCH"),
    ("t162_findings", "findings", "T162_FINDINGS_MISMATCH"),
    ("t162_audit_source", "audit_source", "T162_AUDIT_SOURCE_MISMATCH"),
)
_T163_BINDINGS = (
    ("t163_session_id", "session_id", "T163_SESSION_MISMATCH"),
    ("t163_slice_status", "slice_status", "T163_SLICE_STATUS_MISMATCH"),
    ("t163_admission_status", "admission_status", "T163_ADMISSION_STATUS_MISMATCH"),
    (
        "t163_diagnostics_status",
        "diagnostics_status",
        "T163_DIAGNOSTICS_STATUS_MISMATCH",
    ),
    ("t163_provider_name", "provider_name", "T163_PROVIDER_NAME_MISMATCH"),
    ("t163_model_name", "model_name", "T163_MODEL_NAME_MISMATCH"),
    ("t163_finding_count", "finding_count", "T163_FINDING_COUNT_MISMATCH"),
    ("t163_findings", "findings", "T163_FINDINGS_MISMATCH"),
    (
        "t163_certification_source",
        "certification_source",
        "T163_CERTIFICATION_SOURCE_MISMATCH",
    ),
)
_T164_BINDINGS = (
    ("t164_session_id", "session_id", "T164_SESSION_MISMATCH"),
    (
        "t164_slice_audit_status",
        "slice_audit_status",
        "T164_SLICE_AUDIT_STATUS_MISMATCH",
    ),
    ("t164_available", "available", "T164_AVAILABLE_MISMATCH"),
    ("t164_consistent", "consistent", "T164_CONSISTENT_MISMATCH"),
    (
        "t164_published_slice_status",
        "published_slice_status",
        "T164_PUBLISHED_SLICE_STATUS_MISMATCH",
    ),
    (
        "t164_expected_slice_status",
        "expected_slice_status",
        "T164_EXPECTED_SLICE_STATUS_MISMATCH",
    ),
    ("t164_finding_count", "finding_count", "T164_FINDING_COUNT_MISMATCH"),
    ("t164_findings", "findings", "T164_FINDINGS_MISMATCH"),
    ("t164_audit_source", "audit_source", "T164_AUDIT_SOURCE_MISMATCH"),
)
_T165_BINDINGS = (
    ("t165_session_id", "session_id", "T165_SESSION_MISMATCH"),
    ("t165_bundle_status", "bundle_status", "T165_BUNDLE_STATUS_MISMATCH"),
    (
        "t165_bundle_finding_count",
        "bundle_finding_count",
        "T165_BUNDLE_FINDING_COUNT_MISMATCH",
    ),
    ("t165_bundle_findings", "bundle_findings", "T165_BUNDLE_FINDINGS_MISMATCH"),
    ("t165_bundle_source", "bundle_source", "T165_BUNDLE_SOURCE_MISMATCH"),
)
_T166_BINDINGS = (
    ("t166_session_id", "session_id", "T166_SESSION_MISMATCH"),
    (
        "t166_bundle_audit_status",
        "bundle_audit_status",
        "T166_BUNDLE_AUDIT_STATUS_MISMATCH",
    ),
    ("t166_available", "available", "T166_AVAILABLE_MISMATCH"),
    ("t166_consistent", "consistent", "T166_CONSISTENT_MISMATCH"),
    (
        "t166_published_bundle_status",
        "published_bundle_status",
        "T166_PUBLISHED_BUNDLE_STATUS_MISMATCH",
    ),
    (
        "t166_expected_bundle_status",
        "expected_bundle_status",
        "T166_EXPECTED_BUNDLE_STATUS_MISMATCH",
    ),
    ("t166_finding_count", "finding_count", "T166_FINDING_COUNT_MISMATCH"),
    ("t166_findings", "findings", "T166_FINDINGS_MISMATCH"),
    ("t166_audit_source", "audit_source", "T166_AUDIT_SOURCE_MISMATCH"),
    ("t166_audited_bundle", "audited_bundle", "T166_AUDITED_BUNDLE_MISMATCH"),
)
_T167_BINDINGS = (
    ("t167_session_id", "session_id", "T167_SESSION_MISMATCH"),
    (
        "t167_consistency_status",
        "consistency_status",
        "T167_CONSISTENCY_STATUS_MISMATCH",
    ),
    ("t167_available", "available", "T167_AVAILABLE_MISMATCH"),
    ("t167_consistent", "consistent", "T167_CONSISTENT_MISMATCH"),
    ("t167_finding_count", "finding_count", "T167_FINDING_COUNT_MISMATCH"),
    ("t167_findings", "findings", "T167_FINDINGS_MISMATCH"),
    (
        "t167_consistency_source",
        "consistency_source",
        "T167_CONSISTENCY_SOURCE_MISMATCH",
    ),
)

# Task 165 evidence that must agree with the directly supplied upstream
# evidence: (bundle field, upstream field).
_BUNDLE_VS_T162 = (
    ("request_fingerprint", "request_fingerprint"),
    ("request_audit_status", "request_audit_status"),
    ("proposal_audit_status", "proposal_audit_status"),
    ("t162_audit_source", "audit_source"),
)
_BUNDLE_VS_T163 = (
    ("slice_status", "slice_status"),
    ("admission_status", "admission_status"),
    ("diagnostics_status", "diagnostics_status"),
    ("provider_name", "provider_name"),
    ("model_name", "model_name"),
    ("finding_count", "finding_count"),
    ("findings", "findings"),
    ("certification_source", "certification_source"),
)
_BUNDLE_VS_T164 = (
    ("slice_audit_status", "slice_audit_status"),
    ("audit_available", "available"),
    ("audit_consistent", "consistent"),
    ("published_slice_status", "published_slice_status"),
    ("expected_slice_status", "expected_slice_status"),
    ("audit_finding_count", "finding_count"),
    ("audit_findings", "findings"),
    ("audit_source", "audit_source"),
)


def _exactly_equal(left: Any, right: Any) -> bool:
    """Compare published evidence recursively without bool/int overlap."""
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _exactly_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _exactly_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right


def _is_zero(value: Any) -> bool:
    return type(value) is int and value == 0


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _bundle_status_is_valid(field_name: str, value: object) -> bool:
    return value in _ALLOWED_BUNDLE_STATUSES[field_name]


def _read_fields(obj: Any, model_cls: type) -> dict[str, Any]:
    """Read every declared field of ``obj`` once into a plain dict."""
    if not isinstance(obj, model_cls):
        raise _Unreadable("")
    try:
        return {name: getattr(obj, name) for name in model_cls.model_fields}
    except (AttributeError, TypeError, ValueError) as exc:
        raise _Unreadable("") from exc


def _read_snapshot(value: Any, *, optional: bool) -> dict[str, Any] | None:
    """Read a nested Task 165 snapshot; anything else is unreadable."""
    if value is None and optional:
        return None
    if not isinstance(value, ReasoningRunStage7EvidenceBundleSnapshot):
        raise _Unreadable("")
    try:
        return value.model_dump()
    except (AttributeError, TypeError, ValueError) as exc:
        raise _Unreadable("") from exc


def _read_evidence(
    obj: Any,
    model_cls: type,
    label: str,
    list_fields: tuple[str, ...],
) -> dict[str, Any]:
    """Read one supplied upstream input, or report why it cannot be audited."""
    try:
        view = _read_fields(obj, model_cls)
        if not isinstance(view["session_id"], str):
            raise _Unreadable("SESSION_ID_INVALID")
        if not all(_is_str_list(view[name]) for name in list_fields):
            raise _Unreadable("")
        if label == "T165":
            # Task 168 itself refuses a bundle its strict snapshot cannot hold.
            ReasoningRunStage7EvidenceBundleSnapshot.model_validate(view)
        if label == "T166":
            view["audited_bundle"] = _read_snapshot(
                view["audited_bundle"], optional=True
            )
    except _Unreadable as exc:
        raise _Unreadable(exc.code or f"{label}_INPUT_UNREADABLE") from exc
    except ValidationError as exc:
        raise _Unreadable(f"{label}_INPUT_UNREADABLE") from exc
    return view


def _read_package(package: Any) -> dict[str, Any]:
    """Read the published package into a plain view, or report it unreadable."""
    view = _read_fields(package, ReasoningRunStage7EvidencePackageRead)
    view["t165_bundle_evidence"] = _read_snapshot(
        view["t165_bundle_evidence"], optional=False
    )
    view["t166_audited_bundle"] = _read_snapshot(
        view["t166_audited_bundle"], optional=True
    )
    if not isinstance(view["session_id"], str):
        raise _Unreadable("")
    if not all(_is_str_list(view[name]) for name in _PACKAGE_LIST_FIELDS):
        raise _Unreadable("")
    return view


def _expected_task167(
    bundle: dict[str, Any],
    snapshot: dict[str, Any] | None,
    a166: dict[str, Any],
) -> tuple[str, list[str]]:
    """Independently derive the Task 167 verdict from Task 165/166 evidence."""
    for field_name in _BUNDLE_STATUS_FIELDS:
        if not _bundle_status_is_valid(field_name, bundle[field_name]):
            return (
                "UNAVAILABLE",
                [f"TASK_165_BUNDLE_INVALID:{field_name}:not_a_permitted_status"],
            )
    status = a166["bundle_audit_status"]
    if status == "UNAVAILABLE":
        return "UNAVAILABLE", ["TASK_166_AUDIT_UNAVAILABLE"]
    if snapshot is None:
        return "UNAVAILABLE", ["TASK_166_AUDITED_BUNDLE_MISSING"]

    audit_findings = a166["findings"]
    findings: set[str] = set()
    if bundle["bundle_source"] != REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165:
        findings.add("BUNDLE_SOURCE_MISMATCH")
    if (
        a166["audit_source"]
        != REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166
    ):
        findings.add("AUDIT_SOURCE_MISMATCH")
    if not _exactly_equal(bundle, snapshot):
        findings.add("BUNDLE_SNAPSHOT_MISMATCH")
    if bundle["session_id"] != snapshot["session_id"]:
        findings.add("SESSION_MISMATCH")
    if bundle["bundle_status"] != a166["published_bundle_status"]:
        findings.add("PUBLISHED_STATUS_MISMATCH")
    if (
        a166["available"] is not True
        or a166["consistent"] is not (status == "CONSISTENT")
        or a166["finding_count"] != len(audit_findings)
        or len(set(audit_findings)) != len(audit_findings)
        or audit_findings != sorted(audit_findings)
        or (
            status == "CONSISTENT"
            and (
                audit_findings
                or a166["published_bundle_status"] != a166["expected_bundle_status"]
            )
        )
        or (status == "INCONSISTENT" and not audit_findings)
        or snapshot["session_id"] != a166["session_id"]
        or snapshot["bundle_status"] != a166["published_bundle_status"]
    ):
        findings.add("AUDIT_INTERNAL_MISMATCH")
    if status == "CONSISTENT":
        if bundle["bundle_status"] != a166["expected_bundle_status"]:
            findings.add("EXPECTED_STATUS_CONTRADICTION")
    else:
        findings.add("AUDIT_REPORTS_BUNDLE_INCONSISTENT")

    ordered = sorted(findings)
    return ("INCONSISTENT" if ordered else "CONSISTENT"), ordered


def _derive_expected_package(
    v162: dict[str, Any],
    v163: dict[str, Any],
    v164: dict[str, Any],
    bundle: dict[str, Any],
    v166: dict[str, Any],
    v167: dict[str, Any],
) -> tuple[list[str], str, set[str]]:
    """Independently derive the full Task 168 package state from the evidence.

    Returns ``(expected_findings, expected_status, unpublishable)``.
    ``expected_findings`` is the exact sorted aggregate Task 168 must publish:
    the child findings unioned with every package-level finding the evidence
    warrants. ``unpublishable`` names contradictions in the evidence that
    Task 168 would refuse to publish at all (so no valid package can carry
    them); they are audit findings, never part of the expected aggregate.
    """
    problems: set[str] = set()

    # Session binding: every input shares one nonblank identity.
    sessions = (
        v162["session_id"],
        v163["session_id"],
        v164["session_id"],
        bundle["session_id"],
        v166["session_id"],
        v167["session_id"],
    )
    session_bound = len(set(sessions)) == 1 and v162["session_id"] != ""
    if not session_bound:
        problems.add("STAGE_7_SESSION_MISMATCH")

    # Canonical provenance: every published source, including the ones the
    # Task 165 bundle carries, must be the canonical constant.
    for value, canonical, code in (
        (
            v162["audit_source"],
            REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
            "T162",
        ),
        (
            v163["certification_source"],
            REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
            "T163",
        ),
        (
            v164["audit_source"],
            REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
            "T164",
        ),
        (
            bundle["bundle_source"],
            REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
            "T165",
        ),
        (
            bundle["t162_audit_source"],
            REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
            "T162",
        ),
        (
            bundle["certification_source"],
            REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
            "T163",
        ),
        (
            bundle["audit_source"],
            REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
            "T164",
        ),
        (
            v166["audit_source"],
            REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
            "T166",
        ),
        (
            v167["consistency_source"],
            REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167,
            "T167",
        ),
    ):
        if value != canonical:
            problems.add(f"{code}_SOURCE_MISMATCH")

    # Task 165 bundle: full contract coherence, then binding to its sources.
    try:
        ReasoningRunStage7EvidenceBundleRead.model_validate(dict(bundle))
    except (AttributeError, TypeError, ValueError):
        problems.add("T165_BUNDLE_INVALID")
    if bundle["bundle_finding_count"] != len(bundle["bundle_findings"]):
        problems.add("T165_PACKAGE_EVIDENCE_MISMATCH")
    for field_name in _BUNDLE_STATUS_FIELDS:
        if not _bundle_status_is_valid(field_name, bundle[field_name]):
            problems.add("T165_STATUS_INVALID")
    if bundle["session_id"] != v162["session_id"]:
        problems.add("T165_SESSION_MISMATCH")
    if any(
        not _exactly_equal(bundle[name], v162[source])
        for name, source in _BUNDLE_VS_T162
    ):
        problems.add("T165_T162_EVIDENCE_MISMATCH")
    if any(
        not _exactly_equal(bundle[name], v163[source])
        for name, source in _BUNDLE_VS_T163
    ):
        problems.add("T165_T163_EVIDENCE_MISMATCH")
    if (
        v162["provider_name"] != v163["provider_name"]
        or v162["model_name"] != v163["model_name"]
    ):
        problems.add("T162_T163_ATTRIBUTION_MISMATCH")
    if any(
        not _exactly_equal(bundle[name], v164[source])
        for name, source in _BUNDLE_VS_T164
    ):
        problems.add("T165_T164_EVIDENCE_MISMATCH")

    # Task 164: published/expected status relationships and consistency.
    if v164["published_slice_status"] != v163["slice_status"]:
        problems.add("T164_PUBLISHED_STATUS_MISMATCH")
    if v164["expected_slice_status"] != v163["slice_status"]:
        problems.add("T164_EXPECTED_STATUS_MISMATCH")
    if v164["slice_audit_status"] == "CONSISTENT" and (
        v164["published_slice_status"] != v164["expected_slice_status"]
        or v164["available"] is not True
        or v164["consistent"] is not True
        or v164["findings"]
    ):
        problems.add("T164_CONSISTENCY_INVALID")

    # Task 166: bound to the exact Task 165 bundle it compared.
    status166 = v166["bundle_audit_status"]
    snapshot = v166["audited_bundle"]
    if (
        v166["published_bundle_status"] is not None
        and v166["published_bundle_status"] != bundle["bundle_status"]
    ):
        problems.add("T166_PUBLISHED_STATUS_MISMATCH")
    if (
        status166 == "CONSISTENT"
        and v166["expected_bundle_status"] != v166["published_bundle_status"]
    ):
        problems.add("T166_EXPECTED_STATUS_MISMATCH")
    if status166 != "UNAVAILABLE":
        if snapshot is None:
            problems.add("T166_SNAPSHOT_MISSING")
        elif not _exactly_equal(snapshot, bundle):
            problems.add("T166_SNAPSHOT_MISMATCH")

    # Task 167: binding and the verdict it was required to reach.
    if v167["consistency_status"] == "CONSISTENT" and status166 != "CONSISTENT":
        problems.add("T167_BINDING_MISMATCH")
    expected_t167_status, expected_t167_findings = _expected_task167(
        bundle, snapshot, v166
    )
    if (
        v167["consistency_status"] != expected_t167_status
        or v167["findings"] != expected_t167_findings
    ):
        problems.add("T167_RESULT_MISMATCH")

    # Aggregate: the child findings plus every package-level finding.
    child_findings = (
        v162["findings"]
        + v163["findings"]
        + v164["findings"]
        + bundle["bundle_findings"]
        + v166["findings"]
        + v167["findings"]
    )
    expected_findings = sorted(set(child_findings) | problems)

    # Evidence contradictions Task 168 refuses to publish at all.
    unpublishable: set[str] = set()
    if v164["available"] != (v164["slice_audit_status"] != "UNAVAILABLE") or v164[
        "consistent"
    ] != (v164["slice_audit_status"] == "CONSISTENT"):
        unpublishable.add("T164_FLAGS_INCOHERENT")
    if v166["available"] != (status166 != "UNAVAILABLE") or v166["consistent"] != (
        status166 == "CONSISTENT"
    ):
        unpublishable.add("T166_FLAGS_INCOHERENT")
    if status166 == "UNAVAILABLE":
        if (
            v166["published_bundle_status"] is not None
            or v166["expected_bundle_status"] is not None
            or snapshot is not None
        ):
            unpublishable.add("T166_UNAVAILABLE_CLAIMS_BUNDLE")
    elif (
        v166["published_bundle_status"] is None
        or v166["expected_bundle_status"] is None
    ):
        unpublishable.add("T166_COMPARED_STATUS_MISSING")
    if v167["available"] != (v167["consistency_status"] != "UNAVAILABLE") or v167[
        "consistent"
    ] != (v167["consistency_status"] == "CONSISTENT"):
        unpublishable.add("T167_FLAGS_INCOHERENT")

    # Package status: BLOCKED > READY > UNAVAILABLE. BLOCKED needs a genuine
    # published blocking state; READY needs every cross-link, flag and source
    # to agree and no finding of any kind.
    blocked = (
        v162["admission_status"] == "BLOCKED"
        or v162["diagnostics_status"] == "UNHEALTHY"
        or v163["slice_status"] == "BLOCKED"
        or v163["admission_status"] == "BLOCKED"
        or v163["diagnostics_status"] == "UNHEALTHY"
        or bundle["bundle_status"] == "BLOCKED"
    )
    ready = (
        not expected_findings
        and not unpublishable
        and session_bound
        and v162["admission_status"] == "ADMITTED"
        and v162["diagnostics_status"] == "HEALTHY"
        and v162["request_audit_status"] == "CONSISTENT"
        and v162["proposal_audit_status"] == "CONSISTENT"
        and v163["slice_status"] == "READY"
        and v163["admission_status"] == "ADMITTED"
        and v163["diagnostics_status"] == "HEALTHY"
        and v164["slice_audit_status"] == "CONSISTENT"
        and v164["available"] is True
        and v164["consistent"] is True
        and bundle["bundle_status"] == "READY"
        and status166 == "CONSISTENT"
        and v166["available"] is True
        and v166["consistent"] is True
        and v166["published_bundle_status"] == bundle["bundle_status"]
        and v166["expected_bundle_status"] == bundle["bundle_status"]
        and snapshot is not None
        and _exactly_equal(snapshot, bundle)
        and v167["consistency_status"] == "CONSISTENT"
        and v167["available"] is True
        and v167["consistent"] is True
        and all(
            _is_zero(count)
            for count in (
                v162["finding_count"],
                v163["finding_count"],
                v164["finding_count"],
                bundle["bundle_finding_count"],
                v166["finding_count"],
                v167["finding_count"],
            )
        )
    )
    if blocked:
        expected_status = "BLOCKED"
    elif ready:
        expected_status = "READY"
    else:
        expected_status = "UNAVAILABLE"
    return expected_findings, expected_status, unpublishable


class ReasoningRunStage7EvidencePackageAuditService:
    """Deterministic read-only audit of one Stage 7 evidence package."""

    @staticmethod
    def audit(
        *,
        package: ReasoningRunStage7EvidencePackageRead,
        pkg162: ReasoningRunStage7AuditPackageRead,
        slice163: ReasoningRunStage7VerticalSliceRead,
        audit164: ReasoningRunStage7VerticalSliceAuditRead,
        bundle165: ReasoningRunStage7EvidenceBundleRead,
        audit166: ReasoningRunStage7EvidenceBundleAuditRead,
        consistency167: ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
    ) -> dict[str, Any]:
        """Independently audit one already-published package.

        The audit receives the Task 168 package and the underlying Task
        162-167 evidence directly as arguments, never calls any upstream
        service, derives the complete expected package findings and status
        from that evidence, and compares the derived state against the
        published package. See the module docstring for the
        ``CONSISTENT`` / ``INCONSISTENT`` / ``UNAVAILABLE`` contract.

        No child service is invoked, no fingerprint is recomputed, no input
        is mutated, and no database is written.
        """
        # Step A — Re-run the strict Task 168 contract at this boundary.
        # Existing model instances may have been mutated after construction.
        revalidation_failed = False
        if isinstance(package, ReasoningRunStage7EvidencePackageRead):
            try:
                # Malformed post-construction values only fail revalidation;
                # they must not also emit serializer warnings.
                ReasoningRunStage7EvidencePackageRead.model_validate(
                    package.model_dump(warnings=False)
                )
            except (AttributeError, TypeError, ValueError):
                revalidation_failed = True

        # Step B — Read every input into a plain, shape-checked view. Evidence
        # too malformed to read makes the audit UNAVAILABLE: nothing is
        # verified, so the result carries only diagnostics.
        unreadable: set[str] = set()
        pk: dict[str, Any] | None = None
        try:
            pk = _read_package(package)
        except _Unreadable:
            unreadable.add("TASK_168_PACKAGE_UNREADABLE")
        if pk is not None and (
            pk["package_status"] not in _PERMITTED_PACKAGE_STATUSES
            or not isinstance(pk["package_status"], str)
        ):
            unreadable.add("TASK_168_PACKAGE_STATUS_UNREADABLE")

        inputs: dict[str, dict[str, Any]] = {}
        for label, obj, model_cls, list_fields in (
            ("T162", pkg162, ReasoningRunStage7AuditPackageRead, ("findings",)),
            ("T163", slice163, ReasoningRunStage7VerticalSliceRead, ("findings",)),
            ("T164", audit164, ReasoningRunStage7VerticalSliceAuditRead, ("findings",)),
            (
                "T165",
                bundle165,
                ReasoningRunStage7EvidenceBundleRead,
                ("findings", "audit_findings", "bundle_findings"),
            ),
            (
                "T166",
                audit166,
                ReasoningRunStage7EvidenceBundleAuditRead,
                ("findings",),
            ),
            (
                "T167",
                consistency167,
                ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
                ("findings",),
            ),
        ):
            try:
                inputs[label] = _read_evidence(obj, model_cls, label, list_fields)
            except _Unreadable as exc:
                unreadable.add(exc.code)

        if unreadable or pk is None:
            if revalidation_failed:
                unreadable.add("TASK_168_PACKAGE_INVALID")
            return ReasoningRunStage7EvidencePackageAuditService._project(
                ReasoningRunStage7EvidencePackageAuditService._unavailable(unreadable)
            )

        v162, v163, v164, bundle, v166, v167 = (
            inputs["T162"],
            inputs["T163"],
            inputs["T164"],
            inputs["T165"],
            inputs["T166"],
            inputs["T167"],
        )
        findings: set[str] = set()
        if revalidation_failed:
            findings.add("TASK_168_PACKAGE_INVALID")

        # Step C — Package source and identity.
        if (
            pk["package_source"]
            != REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168
        ):
            findings.add("TASK_168_SOURCE_MISMATCH")

        # Step D — Independently derive the complete expected package state.
        expected_findings, expected_status, unpublishable = _derive_expected_package(
            v162, v163, v164, bundle, v166, v167
        )
        findings |= unpublishable

        sessions = (
            v162["session_id"],
            v163["session_id"],
            v164["session_id"],
            bundle["session_id"],
            v166["session_id"],
            v167["session_id"],
        )
        expected_session = (
            v162["session_id"]
            if len(set(sessions)) == 1 and v162["session_id"] != ""
            else ""
        )
        if pk["session_id"] != expected_session:
            findings.add("SESSION_ID_MISMATCH")

        # Step E — The package must carry verbatim copies of every input.
        for bindings, evidence in (
            (_T162_BINDINGS, v162),
            (_T163_BINDINGS, v163),
            (_T164_BINDINGS, v164),
            (_T165_BINDINGS, bundle),
            (_T166_BINDINGS, v166),
            (_T167_BINDINGS, v167),
        ):
            for package_field, evidence_field, code in bindings:
                if not _exactly_equal(pk[package_field], evidence[evidence_field]):
                    findings.add(code)
        if not _exactly_equal(pk["t165_bundle_evidence"], bundle):
            findings.add("T165_BUNDLE_EVIDENCE_MISMATCH")

        # Step F — The published aggregate must equal the derived aggregate.
        if pk["findings"] != expected_findings:
            findings.add("AGGREGATE_FINDINGS_MISMATCH")
        if not _exactly_equal(pk["finding_count"], len(expected_findings)):
            findings.add("AGGREGATE_FINDING_COUNT_MISMATCH")

        # Step G — The published status must equal the derived status.
        published_status = pk["package_status"]
        if expected_status != published_status:
            findings.add("PACKAGE_STATUS_MISMATCH")

        ordered = sorted(findings)
        result: dict[str, Any] = {
            "session_id": pk["session_id"],
            "package_audit_status": "INCONSISTENT" if ordered else "CONSISTENT",
            "available": True,
            "consistent": not ordered,
            "published_package_status": published_status,
            "expected_package_status": expected_status,
            "finding_count": len(ordered),
            "findings": ordered,
            "audit_source": (
                REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169
            ),
        }
        return ReasoningRunStage7EvidencePackageAuditService._project(result)

    @staticmethod
    def _unavailable(diagnostics: set[str]) -> dict[str, Any]:
        """Build the result for evidence too malformed to audit."""
        ordered = sorted(diagnostics)
        return {
            "session_id": "",
            "package_audit_status": "UNAVAILABLE",
            "available": False,
            "consistent": False,
            "published_package_status": None,
            "expected_package_status": None,
            "finding_count": len(ordered),
            "findings": ordered,
            "audit_source": (
                REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169
            ),
        }

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the audit result through the strict contract."""
        try:
            validated = ReasoningRunStage7EvidencePackageAuditRead.model_validate(
                result
            )
        except ValidationError as exc:
            raise ReasoningRunStage7EvidencePackageAuditContractError(
                "EVIDENCE_PACKAGE_AUDIT_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
