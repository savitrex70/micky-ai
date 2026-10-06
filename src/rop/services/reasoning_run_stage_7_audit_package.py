"""Task 162: Stage 7 deterministic audit package service.

Assembles one deterministic, provider-neutral audit package from the
completed Stage 7 projections: the Task 154 admission verdict, the
Task 155 request package, the Task 156 request audit, the Task 158
validated proposal, the Task 159 proposal audit, and the Task 161
diagnostics verdict. Combination and presentation only: the service
invokes no other Stage 7 service, re-derives no verdict, and
re-implements no audit dimension -- the child material is consumed as
canonical evidence.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, and no mutation of the inspected
material. Raw provider text and the raw provider response object can
never appear in the returned package; only canonical statuses,
provider metadata, and deterministic findings are projected.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)

REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162 = (
    "REASONING_RUN_STAGE_7_AUDIT_PACKAGE_TASK_162"
)

_ADMISSION_STATUSES = ("ADMITTED", "BLOCKED", "UNAVAILABLE")
_AUDIT_STATUSES = ("CONSISTENT", "INCONSISTENT", "UNAVAILABLE")
_DIAGNOSTICS_STATUSES = ("HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL")


class ReasoningRunStage7AuditPackageContractError(Exception):
    """Task 162: the audit package cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7AuditPackageService:
    """Deterministic read-only assembly of one Stage 7 audit package."""

    @staticmethod
    def build(
        *,
        admission_result: Mapping[str, Any] | None = None,
        request_package: Mapping[str, Any] | None = None,
        request_audit: Mapping[str, Any] | None = None,
        proposal_result: Mapping[str, Any] | None = None,
        proposal_audit: Mapping[str, Any] | None = None,
        diagnostics_result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble one deterministic audit package from six projections.

        Every material arrives already produced: canonical statuses are
        carried verbatim, and an absent or invalid artifact is flagged
        with a deterministic finding instead of being fabricated.
        Session identity must agree across every material that claims
        one; contradictory claims leave the identity empty and add the
        canonical mismatch finding. Findings are this service's own
        structural markers plus the canonical child findings, sorted
        and deduplicated by the projection. No child service is invoked
        and no child verdict is recomputed here.
        """
        findings: list[str] = []

        admission_status: str | None = None
        if not isinstance(admission_result, Mapping):
            findings.append("ADMISSION_MISSING")
        else:
            raw_admission = admission_result.get("admission_status")
            if raw_admission in _ADMISSION_STATUSES:
                admission_status = raw_admission
            else:
                findings.append(f"ADMISSION_STATUS_INVALID:{raw_admission}")

        request_fingerprint: str | None = None
        if isinstance(request_package, Mapping):
            raw_fingerprint = request_package.get("context_fingerprint")
            if isinstance(raw_fingerprint, str) and raw_fingerprint:
                request_fingerprint = raw_fingerprint

        request_audit_status: str | None = None
        if isinstance(request_audit, Mapping):
            raw_request_audit = request_audit.get("request_audit_status")
            if raw_request_audit in _AUDIT_STATUSES:
                request_audit_status = raw_request_audit
            else:
                findings.append(f"REQUEST_AUDIT_STATUS_INVALID:{raw_request_audit}")

        proposal_audit_status: str | None = None
        if isinstance(proposal_audit, Mapping):
            raw_proposal_audit = proposal_audit.get("proposal_audit_status")
            if raw_proposal_audit in _AUDIT_STATUSES:
                proposal_audit_status = raw_proposal_audit
            else:
                findings.append(f"PROPOSAL_AUDIT_STATUS_INVALID:{raw_proposal_audit}")

        diagnostics_status = "NO_MATERIAL"
        if not isinstance(diagnostics_result, Mapping):
            findings.append("DIAGNOSTICS_MISSING")
        else:
            raw_diagnostics = diagnostics_result.get("diagnostics_status")
            if raw_diagnostics in _DIAGNOSTICS_STATUSES:
                diagnostics_status = raw_diagnostics
            else:
                findings.append(f"DIAGNOSTICS_STATUS_INVALID:{raw_diagnostics}")

        session_id = ReasoningRunStage7AuditPackageService._resolve_session(
            admission_result=admission_result,
            request_package=request_package,
            proposal_result=proposal_result,
            diagnostics_result=diagnostics_result,
            findings=findings,
        )

        provider_name: str | None = None
        model_name: str | None = None
        if isinstance(proposal_result, Mapping):
            raw_provider = proposal_result.get("provider")
            raw_model = proposal_result.get("model")
            if (
                isinstance(raw_provider, str)
                and raw_provider.strip() != ""
                and isinstance(raw_model, str)
                and raw_model.strip() != ""
            ):
                provider_name = raw_provider
                model_name = raw_model

        children = (admission_result, request_audit, proposal_audit, diagnostics_result)
        for child in children:
            findings.extend(
                ReasoningRunStage7AuditPackageService._child_findings(child)
            )

        result: dict[str, Any] = {
            "session_id": session_id,
            "admission_status": admission_status,
            "request_fingerprint": request_fingerprint,
            "request_audit_status": request_audit_status,
            "proposal_audit_status": proposal_audit_status,
            "diagnostics_status": diagnostics_status,
            "provider_name": provider_name,
            "model_name": model_name,
            "finding_count": len(findings),
            "findings": findings,
            "audit_source": REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        }
        return ReasoningRunStage7AuditPackageService._project(result)

    @staticmethod
    def _resolve_session(
        *,
        admission_result: Mapping[str, Any] | None,
        request_package: Mapping[str, Any] | None,
        proposal_result: Mapping[str, Any] | None,
        diagnostics_result: Mapping[str, Any] | None,
        findings: list[str],
    ) -> str:
        claims: set[str] = set()
        for material, key in (
            (admission_result, "requested_session_id"),
            (request_package, "session_id"),
            (proposal_result, "session_id"),
            (diagnostics_result, "session_id"),
        ):
            if not isinstance(material, Mapping):
                continue
            raw_claim = material.get(key)
            if isinstance(raw_claim, str) and raw_claim:
                claims.add(raw_claim)
        if not claims:
            return ""
        if len(claims) == 1:
            return next(iter(claims))
        findings.append("SESSION_MISMATCH")
        return ""

    @staticmethod
    def _child_findings(material: Mapping[str, Any] | None) -> list[str]:
        if not isinstance(material, Mapping):
            return []
        raw = material.get("findings")
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw]

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        normalized = sorted(set(str(item) for item in result["findings"]))
        candidate = {**result, "finding_count": len(normalized), "findings": normalized}
        try:
            validated = ReasoningRunStage7AuditPackageRead.model_validate(candidate)
        except ValidationError as exc:
            raise ReasoningRunStage7AuditPackageContractError(
                "AUDIT_PACKAGE_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
