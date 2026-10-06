"""Task 159: Stage 7 proposal provenance and consistency audit service.

Independent deterministic audit of a returned Task 158 proposal result
against the canonical Task 055 context that produced it. The Task 103
audit is authoritative: this service orchestrates it and projects its
evidence into the Stage 7 verdict. It never reimplements, weakens, or
extends the canonical Task 103 checks, and the verdict is never
derived from any other source.

Provenance is verified, not assumed. The canonical context is
REQUIRED: without it session identity, the context fingerprint, and
every candidate/evidence/missing-information reference cannot be
verified, so the audit reports UNAVAILABLE instead of a misleading
success.

Read-only: no persistence, no provider call, no network, and no
mutation of the audited material.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_proposal_audit import (
    ReasoningRunStage7ProposalAuditRead,
)
from rop.services.llm_reasoning_audit import (
    LLMReasoningAuditContractError,
    LLMReasoningAuditService,
)

REASONING_RUN_STAGE_7_PROPOSAL_AUDIT_SOURCE_TASK_159 = (
    "REASONING_RUN_STAGE_7_PROPOSAL_AUDIT_TASK_159"
)

_DIMENSION_NAMES = (
    "session_consistent",
    "fingerprint_consistent",
    "candidate_assessments_consistent",
    "evidence_references_consistent",
    "unresolved_info_consistent",
    "candidate_order_consistent",
    "provenance_consistent",
    "metadata_consistent",
)


class ReasoningRunStage7ProposalAuditContractError(Exception):
    """Task 159: the proposal audit result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7ProposalAuditService:
    """Deterministic read-only proposal audit over canonical Task 103.

    Pure orchestration. The service accepts no database session,
    performs no persistence, and never invokes any provider.
    """

    @staticmethod
    def audit(
        *,
        proposal_result: Mapping[str, Any] | None,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Audit one Task 158 proposal result against its canonical context.

        Statuses: ``CONSISTENT`` (Task 103 certified the returned
        proposal consistent), ``INCONSISTENT`` (the Task 103 audit ran
        and did not certify consistency), ``UNAVAILABLE`` (the proposal
        material, the canonical context, or the audit itself is
        unreadable -- no dimension is certified). Every dimension flag
        and every finding of the result is Task 103 evidence; this
        service derives nothing on its own.
        """
        if not isinstance(proposal_result, Mapping):
            return ReasoningRunStage7ProposalAuditService._finalize(
                "UNAVAILABLE",
                proposal_consistent=False,
                dimensions={},
                findings=["PROPOSAL_RESULT_MISSING"],
            )

        proposal_status = proposal_result.get("proposal_status")
        if proposal_status != "VALIDATED":
            return ReasoningRunStage7ProposalAuditService._finalize(
                "UNAVAILABLE",
                proposal_consistent=False,
                dimensions={},
                findings=[f"PROPOSAL_NOT_VALIDATED:{proposal_status}"],
            )

        proposal = proposal_result.get("proposal")
        if not isinstance(proposal, Mapping):
            return ReasoningRunStage7ProposalAuditService._finalize(
                "UNAVAILABLE",
                proposal_consistent=False,
                dimensions={},
                findings=["PROPOSAL_MATERIAL_MISSING"],
            )

        if not isinstance(context, Mapping):
            return ReasoningRunStage7ProposalAuditService._finalize(
                "UNAVAILABLE",
                proposal_consistent=False,
                dimensions={},
                findings=["CANONICAL_CONTEXT_MISSING"],
            )

        try:
            audit = LLMReasoningAuditService.build(proposal=proposal, context=context)
        except LLMReasoningAuditContractError as exc:
            return ReasoningRunStage7ProposalAuditService._finalize(
                "UNAVAILABLE",
                proposal_consistent=False,
                dimensions={},
                findings=[f"PROPOSAL_AUDIT_UNAVAILABLE:{exc.invariant}"],
            )
        except Exception as exc:
            return ReasoningRunStage7ProposalAuditService._finalize(
                "UNAVAILABLE",
                proposal_consistent=False,
                dimensions={},
                findings=[f"PROPOSAL_AUDIT_FAILED:{type(exc).__name__}"],
            )

        dimensions = {name: bool(audit.get(name)) for name in _DIMENSION_NAMES}
        proposal_consistent = bool(audit.get("proposal_consistent"))
        findings = [str(issue) for issue in audit.get("consistency_issues", [])]
        status = "CONSISTENT" if proposal_consistent else "INCONSISTENT"
        return ReasoningRunStage7ProposalAuditService._finalize(
            status,
            proposal_consistent=proposal_consistent,
            dimensions=dimensions,
            findings=findings,
        )

    @staticmethod
    def _finalize(
        status: str,
        *,
        proposal_consistent: bool,
        dimensions: Mapping[str, bool],
        findings: list[str],
    ) -> dict[str, Any]:
        if status == "UNAVAILABLE":
            proposal_consistent = False
            dimensions = {name: False for name in _DIMENSION_NAMES}
        normalized = sorted(set(findings))
        result: dict[str, Any] = {
            "proposal_audit_status": status,
            "available": status != "UNAVAILABLE",
            "proposal_consistent": proposal_consistent,
            **{name: bool(dimensions.get(name)) for name in _DIMENSION_NAMES},
            "finding_count": len(normalized),
            "findings": normalized,
            "audit_source": REASONING_RUN_STAGE_7_PROPOSAL_AUDIT_SOURCE_TASK_159,
        }
        try:
            validated = ReasoningRunStage7ProposalAuditRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7ProposalAuditContractError(
                "PROPOSAL_AUDIT_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
