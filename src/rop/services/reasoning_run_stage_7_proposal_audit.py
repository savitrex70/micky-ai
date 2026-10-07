"""Task 159: Stage 7 proposal provenance and consistency audit service.

Independent deterministic audit of one returned Task 158 proposal
result against the canonical Task 055 context that produced it.

Two provenance gates run before the canonical audit is consulted, and
both fail closed:

1. The complete outer mapping must validate as the existing Task 158
   contract, ``ReasoningRunStage7ProposalRead``. Those rules are reused,
   never duplicated here, so a mapping that is not a mapping, has
   missing or extra fields, carries an invalid ``proposal_status``,
   violates ``available`` coherence, supplies ``proposal`` while not
   validated, omits it while validated, or has an incoherent
   ``context_fingerprint``/``provider``/``model`` presence is rejected
   instead of being trusted.
2. The validated envelope must be internally bound to the nested Task
   057 proposal: ``session_id``, ``context_fingerprint``, ``provider``,
   and ``model`` must be exactly equal in both copies. Neither copy is
   preferred, so a forged Task 158 envelope wrapped around a genuine
   proposal can never reach the canonical audit.

Only once both gates pass is the nested proposal handed to Task 103,
which remains the sole authority for proposal consistency. This service
orchestrates it and projects its evidence into the Stage 7 verdict. It
never reimplements, weakens, or extends the canonical Task 103 checks,
and the verdict is never derived from any other source.

The verdict also carries ``audited_session_id`` and
``audited_proposal_fingerprint``: the audited nested proposal's own
``session_id`` and ``context_fingerprint``, read straight from the
validated material so downstream stages can bind the audit to the exact
proposal that was certified. No fingerprint is computed here.

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

from rop.schemas.reasoning_run_stage_7_proposal import (
    ReasoningRunStage7ProposalRead,
)
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

# Provenance fields the Task 158 envelope duplicates from the nested
# Task 057 proposal, with the diagnostic raised when the two copies
# disagree.
_BINDING_FIELDS = (
    ("session_id", "PROPOSAL_SESSION_BINDING_MISMATCH"),
    ("context_fingerprint", "PROPOSAL_FINGERPRINT_BINDING_MISMATCH"),
    ("provider", "PROPOSAL_PROVIDER_BINDING_MISMATCH"),
    ("model", "PROPOSAL_MODEL_BINDING_MISMATCH"),
)


class ReasoningRunStage7ProposalAuditContractError(Exception):
    """Task 159: the proposal audit result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def _observed(value: object) -> str:
    """Render an observed nested value for a deterministic diagnostic."""
    if isinstance(value, str):
        return value
    return "None" if value is None else type(value).__name__


def _binding_value(proposal: Mapping[str, Any], field: str) -> str | None:
    """Read one audited-proposal binding value without inventing anything.

    The value is the nested Task 057 proposal's own field, so the binding
    evidence names the exact proposal that was handed to Task 103.
    """
    value = proposal.get(field)
    return value if isinstance(value, str) else None


def _invalid_detail(exc: ValidationError) -> str:
    """Render one deterministic Task 158 schema rejection reason."""
    details = sorted(
        f"{'.'.join(str(part) for part in error['loc']) or 'model'}:{error['type']}"
        for error in exc.errors()
    )
    return details[0]


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
        and did not certify consistency), ``UNAVAILABLE`` (the Task 158
        envelope is unreadable or not validated, its provenance is not
        bound to the nested proposal, the canonical context is missing,
        or the canonical audit itself could not run -- no dimension is
        certified).

        ``findings`` carries two disjoint kinds of evidence and never
        mixes them in one result:

        * when Task 103 runs, ``findings`` is exactly its
          ``consistency_issues`` -- the canonical Task 103 vocabulary,
          unaltered and unextended;
        * when required Task 158 or canonical material is missing,
          invalid, or unbound, Task 103 never runs and ``findings`` is
          this service's own deterministic availability/provenance
          diagnostic: ``PROPOSAL_RESULT_MISSING``,
          ``PROPOSAL_RESULT_INVALID:<field>:<reason>``,
          ``PROPOSAL_NOT_VALIDATED:<status>``,
          ``PROPOSAL_SESSION_BINDING_MISMATCH:<observed>``,
          ``PROPOSAL_FINGERPRINT_BINDING_MISMATCH:<observed>``,
          ``PROPOSAL_PROVIDER_BINDING_MISMATCH:<observed>``,
          ``PROPOSAL_MODEL_BINDING_MISMATCH:<observed>``,
          ``CANONICAL_CONTEXT_MISSING``,
          ``PROPOSAL_AUDIT_UNAVAILABLE:<invariant>``,
          ``PROPOSAL_AUDIT_FAILED:<error>``.

        Every dimension flag of a non-unavailable result is Task 103
        evidence; this service derives no consistency of its own.

        ``audited_session_id`` and ``audited_proposal_fingerprint`` are
        the audited nested proposal's own ``session_id`` and
        ``context_fingerprint``, so a ``CONSISTENT`` verdict names the
        exact proposal it certifies. Material rejected by the provenance
        gates certifies no binding and carries ``None``.
        """
        if not isinstance(proposal_result, Mapping):
            return ReasoningRunStage7ProposalAuditService._finalize(
                "UNAVAILABLE",
                proposal_consistent=False,
                dimensions={},
                findings=["PROPOSAL_RESULT_MISSING"],
            )

        # Gate 1: the outer mapping must be a genuine Task 158 result.
        # The Task 158 schema is the only definition of that contract.
        try:
            envelope = ReasoningRunStage7ProposalRead.model_validate(
                dict(proposal_result)
            )
        except ValidationError as exc:
            return ReasoningRunStage7ProposalAuditService._finalize(
                "UNAVAILABLE",
                proposal_consistent=False,
                dimensions={},
                findings=[f"PROPOSAL_RESULT_INVALID:{_invalid_detail(exc)}"],
            )
        except Exception as exc:
            # A hostile mapping can fail conversion in arbitrary ways;
            # it is unreadable material, never an auditable proposal.
            return ReasoningRunStage7ProposalAuditService._finalize(
                "UNAVAILABLE",
                proposal_consistent=False,
                dimensions={},
                findings=[f"PROPOSAL_RESULT_INVALID:{type(exc).__name__}"],
            )

        if envelope.proposal_status != "VALIDATED":
            return ReasoningRunStage7ProposalAuditService._finalize(
                "UNAVAILABLE",
                proposal_consistent=False,
                dimensions={},
                findings=[f"PROPOSAL_NOT_VALIDATED:{envelope.proposal_status}"],
            )

        # The Task 158 contract already guarantees a nested proposal
        # exactly when the status is VALIDATED, so its presence is not
        # re-checked here.
        proposal = envelope.proposal

        # Gate 2: the envelope must be internally coherent with the
        # nested proposal it claims to carry.
        binding_findings = [
            f"{finding}:{_observed(proposal.get(field))}"
            for field, finding in _BINDING_FIELDS
            if proposal.get(field) != getattr(envelope, field)
        ]
        if binding_findings:
            return ReasoningRunStage7ProposalAuditService._finalize(
                "UNAVAILABLE",
                proposal_consistent=False,
                dimensions={},
                findings=binding_findings,
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
            audited_session_id=_binding_value(proposal, "session_id"),
            audited_proposal_fingerprint=_binding_value(
                proposal, "context_fingerprint"
            ),
        )

    @staticmethod
    def _finalize(
        status: str,
        *,
        proposal_consistent: bool,
        dimensions: Mapping[str, bool],
        findings: list[str],
        audited_session_id: str | None = None,
        audited_proposal_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        if status == "UNAVAILABLE":
            proposal_consistent = False
            dimensions = {name: False for name in _DIMENSION_NAMES}
        normalized = sorted(set(findings))
        result: dict[str, Any] = {
            "proposal_audit_status": status,
            "available": status != "UNAVAILABLE",
            "audited_session_id": audited_session_id,
            "audited_proposal_fingerprint": audited_proposal_fingerprint,
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
