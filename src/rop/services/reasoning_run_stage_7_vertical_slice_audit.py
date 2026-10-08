"""Task 164: Stage 7 vertical-slice consistency audit service.

Independent, deterministic audit of one published Task 163
vertical-slice verdict against the Task 162 audit package it claims to
certify. The question answered is: does this verdict faithfully
represent the package it certifies?

This is an audit, not a second certification, and it is deliberately
independent of Task 163. The service never calls Task 163 or Task 162 --
it receives the two already-published pieces of material and compares
them. The verdict the package supports is derived here from the
validated package alone, with this module's own predicates, so a defect
in the Task 163 gate cannot hide behind itself. No other Stage 7
service, no context builder, and no provider is touched.

Neither input is trusted on its own. Each mapping is first validated
against its OWN approved contract --
``ReasoningRunStage7AuditPackageRead`` and
``ReasoningRunStage7VerticalSliceRead`` -- and only the validated object
is read. Both contracts forbid extra fields and carry their own
coherence rules, so a forged, truncated, or over-extended mapping is
unavailable material rather than evidence. Missing or contract-violating
material of either kind makes the audit ``UNAVAILABLE``: nothing is
compared, nothing is repaired, and no status is guessed.

When both inputs are valid, every published field is compared to the
projection the package supports, verbatim: no re-sorting, no
re-deduplication, no string normalization, and no repair of findings.
Any disagreement is reported as a specific deterministic finding code
and the audit is ``INCONSISTENT``. Faithful verdicts are accepted in
every state -- a ``BLOCKED`` or ``UNAVAILABLE`` verdict that correctly
represents its package is ``CONSISTENT`` -- while a verdict that
certifies more than the package supports, refuses without a blocking
condition, or withholds a certification the package fully supports is
``INCONSISTENT``.

Provenance is only read, never rebuilt: request, proposal, and context
fingerprints are never recomputed. The request fingerprint is checked
for the canonical Task 155 shape only, exactly as the published value
stands.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, and no mutation of either input.
Findings are audit codes only and never echo a published value, so raw
provider text and the raw provider response object can never appear in
the returned audit.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, NamedTuple

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
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

REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164 = (
    "REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_TASK_164"
)

# Canonical Task 155 request fingerprint shape: SHA-256 hex digest, exactly
# 64 lowercase hexadecimal characters, matched with ``fullmatch`` so no
# trailing newline slips through. Shape only -- never recomputed.
_REQUEST_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")

# The one finding the approved Task 163 verdict publishes for a package that
# does not carry the canonical Task 162 source: the package is not usable
# evidence, so the verdict names no session, status, or attribution.
_PACKAGE_SOURCE_NOT_CANONICAL = "AUDIT_PACKAGE_SOURCE_NOT_CANONICAL"


class ReasoningRunStage7VerticalSliceAuditContractError(Exception):
    """Task 164: the vertical-slice audit result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class _Expected(NamedTuple):
    """The Task 163 verdict fields the validated package supports."""

    slice_status: str
    session_id: str
    admission_status: str | None
    diagnostics_status: str | None
    provider_name: str | None
    model_name: str | None
    findings: list[str]


def _invalid_detail(exc: ValidationError) -> str:
    """Render one deterministic contract-rejection reason."""
    details = sorted(
        f"{'.'.join(str(part) for part in error['loc']) or 'model'}:{error['type']}"
        for error in exc.errors()
    )
    return details[0]


def _usable(value: str | None) -> bool:
    """Report whether a published evidence field actually carries content."""
    return isinstance(value, str) and value.strip() != ""


def _canonical_fingerprint(value: str | None) -> bool:
    """Report whether a request fingerprint has the canonical shape."""
    return (
        isinstance(value, str) and _REQUEST_FINGERPRINT_RE.fullmatch(value) is not None
    )


def _read_package(
    audit_package: object,
) -> tuple[ReasoningRunStage7AuditPackageRead | None, str | None]:
    """Validate the whole Task 162 mapping against its own contract."""
    if not isinstance(audit_package, Mapping):
        return None, "TASK_162_PACKAGE_MISSING"
    try:
        return (
            ReasoningRunStage7AuditPackageRead.model_validate(dict(audit_package)),
            None,
        )
    except ValidationError as exc:
        return None, f"TASK_162_PACKAGE_INVALID:{_invalid_detail(exc)}"
    except Exception as exc:
        # Material that cannot even be converted is unreadable,
        # never evidence.
        return None, f"TASK_162_PACKAGE_INVALID:{type(exc).__name__}"


def _read_verdict(
    vertical_slice: object,
) -> tuple[ReasoningRunStage7VerticalSliceRead | None, str | None]:
    """Validate the whole Task 163 mapping against its own contract."""
    if not isinstance(vertical_slice, Mapping):
        return None, "TASK_163_RESULT_MISSING"
    try:
        return (
            ReasoningRunStage7VerticalSliceRead.model_validate(dict(vertical_slice)),
            None,
        )
    except ValidationError as exc:
        return None, f"TASK_163_RESULT_INVALID:{_invalid_detail(exc)}"
    except Exception as exc:
        return None, f"TASK_163_RESULT_INVALID:{type(exc).__name__}"


def _blocking_condition(package: ReasoningRunStage7AuditPackageRead) -> bool:
    """Report whether the package carries an approved blocking condition."""
    return (
        package.admission_status == "BLOCKED"
        or package.diagnostics_status == "UNHEALTHY"
        or package.request_audit_status == "INCONSISTENT"
        or package.proposal_audit_status == "INCONSISTENT"
    )


def _ready_evidence(package: ReasoningRunStage7AuditPackageRead) -> bool:
    """Report whether the package holds every item the READY gate requires."""
    return (
        package.admission_status == "ADMITTED"
        and package.diagnostics_status == "HEALTHY"
        and package.request_audit_status == "CONSISTENT"
        and package.proposal_audit_status == "CONSISTENT"
        and _usable(package.session_id)
        and _canonical_fingerprint(package.request_fingerprint)
        and _usable(package.provider_name)
        and _usable(package.model_name)
        and package.findings == []
        and package.finding_count == 0
        and package.audit_source == REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162
    )


def _expected(package: ReasoningRunStage7AuditPackageRead) -> _Expected:
    """Project the verdict the validated package supports, fields verbatim."""
    if package.audit_source != REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162:
        # Not Task 162 material at all: the faithful verdict claims nothing.
        return _Expected(
            "UNAVAILABLE", "", None, None, None, None, [_PACKAGE_SOURCE_NOT_CANONICAL]
        )
    if _blocking_condition(package):
        status = "BLOCKED"
    elif _ready_evidence(package):
        status = "READY"
    else:
        status = "UNAVAILABLE"
    attributed = status != "UNAVAILABLE"
    return _Expected(
        status,
        package.session_id,
        package.admission_status,
        package.diagnostics_status,
        package.provider_name if attributed else None,
        package.model_name if attributed else None,
        list(package.findings),
    )


def _disagreements(
    verdict: ReasoningRunStage7VerticalSliceRead, expected: _Expected
) -> set[str]:
    """Compare every published verdict field to its supported projection."""
    found: set[str] = set()
    if (
        verdict.certification_source
        != REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163
    ):
        found.add("TASK_163_SOURCE_MISMATCH")
    if verdict.session_id != expected.session_id:
        found.add("SESSION_ID_MISMATCH")
    if verdict.admission_status != expected.admission_status:
        found.add("ADMISSION_STATUS_MISMATCH")
    if verdict.diagnostics_status != expected.diagnostics_status:
        found.add("DIAGNOSTICS_STATUS_MISMATCH")
    if verdict.provider_name != expected.provider_name:
        found.add("PROVIDER_NAME_MISMATCH")
    if verdict.model_name != expected.model_name:
        found.add("MODEL_NAME_MISMATCH")
    if verdict.findings != expected.findings:
        found.add("FINDINGS_MISMATCH")
    # The verdict contract already guarantees finding_count equals the
    # length of its own published findings; the audit adds agreement with
    # the count the package supports.
    if verdict.finding_count != len(expected.findings):
        found.add("FINDING_COUNT_MISMATCH")
    if verdict.slice_status != expected.slice_status:
        found.add("SLICE_STATUS_MISMATCH")
        found.add(f"{verdict.slice_status}_EVIDENCE_MISMATCH")
    return found


class ReasoningRunStage7VerticalSliceAuditService:
    """Deterministic read-only audit of one published vertical-slice verdict."""

    @staticmethod
    def audit(
        *,
        audit_package: Mapping[str, Any] | None = None,
        vertical_slice: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Audit one published Task 163 verdict against its Task 162 package.

        ``UNAVAILABLE`` when either input is missing or fails its own
        contract; otherwise ``CONSISTENT`` only when every published
        field agrees with the projection the package supports, and
        ``INCONSISTENT`` with one finding per disagreement. Findings are
        audit codes in sorted, deduplicated order, independent of
        dictionary ordering.
        """
        package, package_marker = _read_package(audit_package)
        verdict, verdict_marker = _read_verdict(vertical_slice)

        if package is None or verdict is None:
            markers = sorted(
                marker for marker in (package_marker, verdict_marker) if marker
            )
            return ReasoningRunStage7VerticalSliceAuditService._project(
                {
                    "session_id": "",
                    "slice_audit_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "published_slice_status": None,
                    "expected_slice_status": None,
                    "finding_count": len(markers),
                    "findings": markers,
                    "audit_source": (
                        REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164
                    ),
                }
            )

        expected = _expected(package)
        findings = sorted(_disagreements(verdict, expected))
        consistent = not findings
        return ReasoningRunStage7VerticalSliceAuditService._project(
            {
                # One identity is named only when both inputs agree on it.
                "session_id": (
                    verdict.session_id
                    if verdict.session_id == expected.session_id
                    else ""
                ),
                "slice_audit_status": "CONSISTENT" if consistent else "INCONSISTENT",
                "available": True,
                "consistent": consistent,
                "published_slice_status": verdict.slice_status,
                "expected_slice_status": expected.slice_status,
                "finding_count": len(findings),
                "findings": findings,
                "audit_source": (
                    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164
                ),
            }
        )

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Project the audit through the strict contract, unmodified."""
        try:
            validated = ReasoningRunStage7VerticalSliceAuditRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7VerticalSliceAuditContractError(
                "VERTICAL_SLICE_AUDIT_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
