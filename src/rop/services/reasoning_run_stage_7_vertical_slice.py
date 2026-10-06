"""Task 163: Stage 7 provider-agnostic vertical-slice certification service.

First end-to-end deterministic Stage 7 gate over the provider-agnostic
path built by Tasks 154-162: the canonical Task 162 audit package --
admission, request package, request audit, proposal, proposal audit,
and diagnostics -- is certified into exactly one vertical-slice
verdict. This is certification, not completion: the gate proves the
ROP boundary is structurally and deterministically validated with a
test-only fake provider, and it makes no claim that a real model has
been integrated.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, and no mutation of the inspected
material. The Task 162 package is consumed as canonical evidence:
nothing is re-derived, no child service is invoked, and raw provider
text can never appear in the returned verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
)

REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163 = (
    "REASONING_RUN_STAGE_7_VERTICAL_SLICE_TASK_163"
)

_ADMISSION_STATUSES = ("ADMITTED", "BLOCKED", "UNAVAILABLE")
_AUDIT_STATUSES = ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE")
_DIAGNOSTICS_STATUSES = ("HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL")


class ReasoningRunStage7VerticalSliceContractError(Exception):
    """Task 163: the vertical-slice verdict cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7VerticalSliceService:
    """Deterministic read-only certification of one Stage 7 vertical slice."""

    @staticmethod
    def certify(*, audit_package: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Certify one Stage 7 vertical slice from its canonical audit package.

        The canonical Task 162 package decides with no new reasoning: a
        blocked admission, an inconsistent request or proposal audit,
        or unhealthy diagnostics is ``BLOCKED``; only an admitted,
        healthy, fully consistent, attributable, and finding-free
        package is ``READY``; anything else -- missing, degraded, or
        unattributable material -- is ``UNAVAILABLE``. Findings are the
        canonical package findings plus this gate's own structural
        markers, sorted and deduplicated.
        """
        findings: list[str] = []
        admission_status: str | None = None
        diagnostics_status: str | None = None
        request_audit_status: str | None = None
        proposal_audit_status: str | None = None
        session_id = ""
        provider_name: str | None = None
        model_name: str | None = None

        if not isinstance(audit_package, Mapping):
            findings.append("AUDIT_PACKAGE_MISSING")
        else:
            raw_admission = audit_package.get("admission_status")
            if raw_admission in _ADMISSION_STATUSES:
                admission_status = raw_admission
            raw_diagnostics = audit_package.get("diagnostics_status")
            if raw_diagnostics in _DIAGNOSTICS_STATUSES:
                diagnostics_status = raw_diagnostics
            raw_request_audit = audit_package.get("request_audit_status")
            if raw_request_audit in _AUDIT_STATUSES:
                request_audit_status = raw_request_audit
            raw_proposal_audit = audit_package.get("proposal_audit_status")
            if raw_proposal_audit in _AUDIT_STATUSES:
                proposal_audit_status = raw_proposal_audit
            raw_session = audit_package.get("session_id")
            if isinstance(raw_session, str):
                session_id = raw_session
            raw_provider = audit_package.get("provider_name")
            raw_model = audit_package.get("model_name")
            if (
                isinstance(raw_provider, str)
                and raw_provider.strip() != ""
                and isinstance(raw_model, str)
                and raw_model.strip() != ""
            ):
                provider_name = raw_provider
                model_name = raw_model
            findings.extend(
                ReasoningRunStage7VerticalSliceService._package_findings(audit_package)
            )

        blocked = (
            admission_status == "BLOCKED"
            or request_audit_status == "INCONSISTENT"
            or proposal_audit_status == "INCONSISTENT"
            or diagnostics_status == "UNHEALTHY"
        )
        ready = (
            admission_status == "ADMITTED"
            and diagnostics_status == "HEALTHY"
            and request_audit_status == "CONSISTENT"
            and proposal_audit_status == "CONSISTENT"
            and session_id != ""
            and provider_name is not None
            and model_name is not None
            and not findings
        )

        if blocked:
            slice_status = "BLOCKED"
        elif ready:
            slice_status = "READY"
        else:
            slice_status = "UNAVAILABLE"

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
    def _package_findings(audit_package: Mapping[str, Any]) -> list[str]:
        raw = audit_package.get("findings")
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw]

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        normalized = sorted(set(str(item) for item in result["findings"]))
        candidate = {**result, "finding_count": len(normalized), "findings": normalized}
        try:
            validated = ReasoningRunStage7VerticalSliceRead.model_validate(candidate)
        except ValidationError as exc:
            raise ReasoningRunStage7VerticalSliceContractError(
                "VERTICAL_SLICE_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
