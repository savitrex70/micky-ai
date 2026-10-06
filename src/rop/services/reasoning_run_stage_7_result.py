"""Task 160: Stage 7 unified reasoning result boundary service.

Combines the Task 155 request package, the Task 156 request audit, the
Task 158 validated proposal, and the Task 159 proposal audit into one
strict provider-neutral result. Presentation and orchestration only:
no reasoning algorithm, no re-validation of model output, and no
re-implementation of any audit dimension -- the child verdicts are
consumed as canonical evidence, and only cross-material consistency
(session identity, fingerprint identity, material coherence) is added
here.

The service is pure over the four material projections: no database
session, no persistence, no provider invocation, no network. Raw
provider text and the raw provider response object never appear in the
returned projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_result import (
    ReasoningRunStage7ResultRead,
)
from rop.services.llm_boundary_contract import (
    OUTCOME_MODEL_OUTPUT_INCONSISTENT,
    OUTCOME_MODEL_OUTPUT_INVALID,
    OUTCOME_MODEL_UNAVAILABLE,
)

REASONING_RUN_STAGE_7_RESULT_SOURCE_TASK_160 = "REASONING_RUN_STAGE_7_RESULT_TASK_160"

_READABLE_AUDIT_STATUSES = ("CONSISTENT", "INCONSISTENT")
_MODEL_OUTPUT_OUTCOMES = (
    OUTCOME_MODEL_OUTPUT_INVALID,
    OUTCOME_MODEL_OUTPUT_INCONSISTENT,
)


class ReasoningRunStage7ResultContractError(Exception):
    """Task 160: the unified result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7ResultService:
    """Deterministic combination of the four Stage 7 evidence surfaces.

    Pure read-only projection: accepts the four canonical material
    mappings and never a database session, so no write and no provider
    call is possible from this boundary.
    """

    @staticmethod
    def build(
        *,
        request_package: Mapping[str, Any] | None = None,
        request_audit: Mapping[str, Any] | None = None,
        proposal_result: Mapping[str, Any] | None = None,
        proposal_audit: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Combine one Stage 7 interaction into a single strict result.

        Material gates run first: anything other than a packaged request,
        a readable request audit, a readable proposal status, and -- for
        a validated proposal -- a readable proposal audit is
        ``UNAVAILABLE`` ("missing required result material") and no
        consistency claim is certified. Otherwise the canonical child
        verdicts decide with deterministic precedence: any request or
        proposal integrity failure is ``INCONSISTENT``; a canonical Task
        057 provider failure is ``MODEL_UNAVAILABLE``; a validated,
        audited, coherent pair is ``READY``.
        """
        findings: list[str] = []

        # ---- Task 155 request package -----------------------------------
        request_status = "UNAVAILABLE"
        session_id = ""
        fingerprint: str | None = None
        if not isinstance(request_package, Mapping):
            findings.append("REQUEST_PACKAGE_MISSING")
        else:
            raw_status = request_package.get("request_status")
            if raw_status == "PACKAGED":
                request_status = "PACKAGED"
                raw_session = request_package.get("session_id")
                if isinstance(raw_session, str):
                    session_id = raw_session
                raw_fingerprint = request_package.get("context_fingerprint")
                if isinstance(raw_fingerprint, str) and raw_fingerprint:
                    fingerprint = raw_fingerprint
                if session_id == "":
                    findings.append("REQUEST_SESSION_MISSING")
                if fingerprint is None:
                    findings.append("REQUEST_FINGERPRINT_MISSING")
            else:
                findings.append(f"REQUEST_NOT_PACKAGED:{raw_status}")

        # ---- Task 156 request audit -------------------------------------
        request_audit_status: str | None = None
        if not isinstance(request_audit, Mapping):
            findings.append("REQUEST_AUDIT_MISSING")
        else:
            raw_audit_status = request_audit.get("request_audit_status")
            if raw_audit_status in _READABLE_AUDIT_STATUSES:
                request_audit_status = raw_audit_status
            else:
                findings.append("REQUEST_AUDIT_UNAVAILABLE")
            findings.extend(
                ReasoningRunStage7ResultService._child_findings(request_audit)
            )

        # ---- Task 158 proposal result -----------------------------------
        proposal_status = "UNAVAILABLE"
        proposal_known = False
        if not isinstance(proposal_result, Mapping):
            findings.append("PROPOSAL_RESULT_MISSING")
        else:
            raw_proposal_status = proposal_result.get("proposal_status")
            if raw_proposal_status in (
                "VALIDATED",
                OUTCOME_MODEL_UNAVAILABLE,
                *_MODEL_OUTPUT_OUTCOMES,
            ):
                proposal_known = True
                proposal_status = raw_proposal_status
            elif raw_proposal_status == "UNAVAILABLE":
                findings.append("PROPOSAL_UNAVAILABLE")
            else:
                findings.append(f"PROPOSAL_STATUS_INVALID:{raw_proposal_status}")

        # ---- Cross-material identity ------------------------------------
        session_matches = True
        fingerprint_matches = True
        if proposal_known and session_id != "":
            raw_proposal_session = proposal_result.get("session_id")
            if (
                isinstance(raw_proposal_session, str)
                and raw_proposal_session != session_id
            ):
                session_matches = False
                findings.append("SESSION_MISMATCH")
        if proposal_known and fingerprint is not None:
            raw_proposal_fingerprint = proposal_result.get("context_fingerprint")
            if (
                isinstance(raw_proposal_fingerprint, str)
                and raw_proposal_fingerprint != fingerprint
            ):
                fingerprint_matches = False
                findings.append("FINGERPRINT_MISMATCH")

        # ---- Proposal material coherence and provider metadata ----------
        proposal_material_ok = True
        provider_name: str | None = None
        model_name: str | None = None
        if proposal_known and proposal_status == "VALIDATED":
            if proposal_result.get("available") is not True or not isinstance(
                proposal_result.get("proposal"), Mapping
            ):
                proposal_material_ok = False
                findings.append("PROPOSAL_MATERIAL_INCONSISTENT")
            else:
                raw_provider = proposal_result.get("provider")
                raw_model = proposal_result.get("model")
                if (
                    not isinstance(raw_provider, str)
                    or raw_provider.strip() == ""
                    or not isinstance(raw_model, str)
                    or raw_model.strip() == ""
                ):
                    proposal_material_ok = False
                    findings.append("PROPOSAL_METADATA_INCONSISTENT")
                else:
                    provider_name = raw_provider
                    model_name = raw_model

        # ---- Task 159 proposal audit ------------------------------------
        proposal_audit_status: str | None = None
        if isinstance(proposal_audit, Mapping):
            raw_proposal_audit = proposal_audit.get("proposal_audit_status")
            if raw_proposal_audit in _READABLE_AUDIT_STATUSES:
                proposal_audit_status = raw_proposal_audit
            elif proposal_status == "VALIDATED":
                findings.append("PROPOSAL_AUDIT_UNAVAILABLE")
            findings.extend(
                ReasoningRunStage7ResultService._child_findings(proposal_audit)
            )
        elif proposal_status == "VALIDATED":
            findings.append("PROPOSAL_AUDIT_MISSING")

        # ---- Deterministic classification -------------------------------
        material_missing = (
            request_status != "PACKAGED"
            or session_id == ""
            or fingerprint is None
            or request_audit_status is None
            or not proposal_known
            or (proposal_status == "VALIDATED" and proposal_audit_status is None)
        )
        request_consistent = request_audit_status == "CONSISTENT"
        proposal_consistent = (
            proposal_status == "VALIDATED"
            and proposal_audit_status == "CONSISTENT"
            and proposal_material_ok
            and session_matches
            and fingerprint_matches
        )

        if material_missing:
            result_status = "UNAVAILABLE"
            request_consistent = False
            proposal_consistent = False
            provider_name = None
            model_name = None
        elif proposal_status == "VALIDATED":
            integrity_failure = not (request_consistent and proposal_consistent)
            result_status = "INCONSISTENT" if integrity_failure else "READY"
        elif proposal_status in _MODEL_OUTPUT_OUTCOMES:
            proposal_consistent = False
            result_status = "INCONSISTENT"
        elif proposal_status == OUTCOME_MODEL_UNAVAILABLE:
            proposal_consistent = False
            integrity_failure = not (request_consistent and session_matches)
            result_status = "INCONSISTENT" if integrity_failure else "MODEL_UNAVAILABLE"
        else:  # pragma: no cover - proposal_known guarantees a known status
            proposal_consistent = False
            result_status = "INCONSISTENT"

        result: dict[str, Any] = {
            "session_id": session_id,
            "request_fingerprint": fingerprint,
            "request_status": request_status,
            "proposal_status": proposal_status,
            "request_consistent": request_consistent,
            "proposal_consistent": proposal_consistent,
            "provider_name": provider_name,
            "model_name": model_name,
            "result_status": result_status,
            "finding_count": len(findings),
            "findings": findings,
            "source": REASONING_RUN_STAGE_7_RESULT_SOURCE_TASK_160,
        }
        return ReasoningRunStage7ResultService._project(result)

    @staticmethod
    def _child_findings(material: Mapping[str, Any]) -> list[str]:
        raw = material.get("findings")
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw]

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        normalized = sorted(set(str(item) for item in result["findings"]))
        candidate = {**result, "finding_count": len(normalized), "findings": normalized}
        try:
            validated = ReasoningRunStage7ResultRead.model_validate(candidate)
        except ValidationError as exc:
            raise ReasoningRunStage7ResultContractError(
                "RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
