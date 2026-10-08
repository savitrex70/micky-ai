"""Task 163: Stage 7 provider-agnostic vertical-slice certification service.

First end-to-end deterministic Stage 7 gate over the provider-agnostic
path built by Tasks 154-162: the canonical Task 162 audit package --
admission, request package, request audit, proposal, proposal audit,
and diagnostics -- is certified into exactly one vertical-slice
verdict. This is certification, not completion: the gate proves the
ROP boundary is structurally and deterministically validated with a
test-only fake provider, and it makes no claim that a real model has
been integrated.

The Task 162 contract is the single authority on whether the supplied
package is genuine material. The complete mapping is validated against
``ReasoningRunStage7AuditPackageRead`` before a single field takes part
in certification, so a hand-written mapping of legal-looking status
strings cannot manufacture ``READY``: unreadable material is rejected as
``AUDIT_PACKAGE_INVALID`` with one deterministic detail and absent
material as ``AUDIT_PACKAGE_MISSING``. A package that does not identify
itself with the canonical Task 162 source is not Task 162 material at
all and is rejected the same way. Schema validity is still not
completeness: Task 162 legitimately projects ``None`` for unavailable
evidence, so ``READY`` additionally requires the published request
fingerprint -- present and of the canonical 64-lowercase-hex shape --
plus session identity and provider metadata to actually be present.
Nothing is re-derived to make a package usable -- no child service is
invoked, no audit is re-run, and no fingerprint is recomputed.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, and no mutation of the inspected
package. Raw provider text and the raw provider response object can
never appear in the returned verdict.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
)
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
)

REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163 = (
    "REASONING_RUN_STAGE_7_VERTICAL_SLICE_TASK_163"
)

# Canonical Task 155 request fingerprint shape: SHA-256 hex digest, exactly
# 64 lowercase hexadecimal characters. Matched with ``fullmatch`` so no
# trailing newline slips through. The value is only shape-checked here; it
# is never recomputed, normalized, or repaired.
_REQUEST_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")


class ReasoningRunStage7VerticalSliceContractError(Exception):
    """Task 163: the vertical-slice verdict cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def _invalid_detail(exc: ValidationError) -> str:
    """Render one deterministic package-contract rejection reason."""
    details = sorted(
        f"{'.'.join(str(part) for part in error['loc']) or 'model'}:{error['type']}"
        for error in exc.errors()
    )
    return details[0]


def _present(value: str | None) -> bool:
    """Report whether a published evidence field actually carries content."""
    return isinstance(value, str) and value.strip() != ""


def _canonical_fingerprint(value: str | None) -> bool:
    """Report whether a request fingerprint has the canonical Task 155 shape."""
    return (
        isinstance(value, str) and _REQUEST_FINGERPRINT_RE.fullmatch(value) is not None
    )


def _read_package(
    audit_package: Mapping[str, Any] | None,
) -> tuple[ReasoningRunStage7AuditPackageRead | None, list[str]]:
    """Validate the entire package mapping against the Task 162 contract.

    Malformed material is rejected, never repaired. The contract forbids
    extra fields and carries its own coherence rules, so a mapping that
    merely looks healthy contributes no evidence at all. The canonical
    Task 162 source identifier is part of what makes the material Task
    162 material: an altered source string is unusable evidence, not a
    package to be certified.
    """
    if not isinstance(audit_package, Mapping):
        return None, ["AUDIT_PACKAGE_MISSING"]
    try:
        package = ReasoningRunStage7AuditPackageRead.model_validate(dict(audit_package))
    except ValidationError as exc:
        return None, [f"AUDIT_PACKAGE_INVALID:{_invalid_detail(exc)}"]
    except Exception as exc:
        # Material that cannot even be converted is unreadable,
        # never certifying evidence.
        return None, [f"AUDIT_PACKAGE_INVALID:{type(exc).__name__}"]
    if package.audit_source != REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162:
        return None, ["AUDIT_PACKAGE_SOURCE_NOT_CANONICAL"]
    return package, []


class ReasoningRunStage7VerticalSliceService:
    """Deterministic read-only certification of one Stage 7 vertical slice."""

    @staticmethod
    def certify(*, audit_package: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Certify one Stage 7 vertical slice from its canonical audit package.

        The validated Task 162 package decides with no new reasoning: a
        blocked admission, an inconsistent request or proposal audit, or
        unhealthy diagnostics is ``BLOCKED``; only an admitted, healthy,
        fully consistent package that carries the complete evidence for
        the request path -- a real session identity, the published
        request fingerprint, provider and model attribution, and no open
        findings -- is ``READY``; anything else -- a missing,
        contract-violating, or non-Task-162-sourced package, degraded or
        absent health material, unusable audit evidence, or an evidence
        field the package legitimately projected as absent -- is
        ``UNAVAILABLE``. The verdict is built only from fields the Task
        162 contract has already accepted, so no raw mapping value can
        influence it. Findings are the validated package findings
        preserved verbatim, or this gate's own single structural marker
        for unusable material; nothing is re-sorted or re-deduplicated to
        launder malformed input.
        """
        package, findings = _read_package(audit_package)
        if package is None:
            slice_status = "UNAVAILABLE"
            session_id = ""
            admission_status = None
            diagnostics_status = None
            provider_name = None
            model_name = None
        else:
            findings = list(package.findings)
            slice_status = ReasoningRunStage7VerticalSliceService._classify(package)
            session_id = package.session_id
            admission_status = package.admission_status
            diagnostics_status = package.diagnostics_status
            # Only a slice that is whole or explicitly refused keeps the
            # package's provider attribution. Degraded or absent health
            # material can never decide READY, so it lands here as
            # UNAVAILABLE and names no provider.
            attributed = slice_status != "UNAVAILABLE"
            provider_name = package.provider_name if attributed else None
            model_name = package.model_name if attributed else None

        result: dict[str, Any] = {
            "session_id": session_id,
            "slice_status": slice_status,
            "admission_status": admission_status,
            "diagnostics_status": diagnostics_status,
            "provider_name": provider_name,
            "model_name": model_name,
            "finding_count": len(findings),
            "findings": findings,
            "certification_source": (
                REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163
            ),
        }
        return ReasoningRunStage7VerticalSliceService._project(result)

    @staticmethod
    def _classify(package: ReasoningRunStage7AuditPackageRead) -> str:
        """Decide the one verdict from validated Task 162 fields only."""
        if (
            package.admission_status == "BLOCKED"
            or package.diagnostics_status == "UNHEALTHY"
            or package.request_audit_status == "INCONSISTENT"
            or package.proposal_audit_status == "INCONSISTENT"
        ):
            return "BLOCKED"
        if (
            package.admission_status == "ADMITTED"
            and package.diagnostics_status == "HEALTHY"
            and package.request_audit_status == "CONSISTENT"
            and package.proposal_audit_status == "CONSISTENT"
            and _present(package.session_id)
            and _canonical_fingerprint(package.request_fingerprint)
            and _present(package.provider_name)
            and _present(package.model_name)
            and package.findings == []
            and package.finding_count == 0
            and package.audit_source
            == REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162
        ):
            return "READY"
        return "UNAVAILABLE"

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Project the verdict through the strict contract, unmodified.

        A validated Task 162 package already guarantees sorted,
        deduplicated findings and this gate's own marker is a single
        structural finding, so the finding list is already deterministic
        and is never re-normalized here.
        """
        try:
            validated = ReasoningRunStage7VerticalSliceRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7VerticalSliceContractError(
                "VERTICAL_SLICE_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
