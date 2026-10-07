"""Task 160: Stage 7 unified reasoning result boundary service.

Combines the Task 155 request package, the Task 156 request audit, the
Task 158 validated proposal, and the Task 159 proposal audit into one
strict provider-neutral result.

Presentation and orchestration only: no reasoning algorithm, no
re-validation of model output, and no re-implementation of any audit
dimension. Child status fields are never trusted on their own -- each
piece of material must first validate against the child's OWN existing
contract (``ReasoningRunStage7RequestRead``,
``ReasoningRunStage7RequestAuditRead``, ``ReasoningRunStage7ProposalRead``
and ``ReasoningRunStage7ProposalAuditRead``). Those schemas are reused,
never duplicated here, so a forged, incomplete, over-extended, or
internally incoherent mapping is rejected as unavailable material
instead of contributing a verdict or a finding.

Validation alone is not binding. A ``CONSISTENT`` audit only certifies
the material this boundary is actually acting on, so the binding
evidence the children already publish is compared exactly:

* Task 156 ``audited_session_id`` / ``audited_request_fingerprint``
  against the Task 155 ``session_id`` / ``context_fingerprint``,
* the Task 158 ``session_id`` / ``context_fingerprint`` against the same
  Task 155 package,
* Task 159 ``audited_session_id`` / ``audited_proposal_fingerprint``
  against the Task 158 envelope that carries the audited proposal.

Any disagreement fails closed as ``INCONSISTENT``, and material that
cannot be validly established fails closed as ``UNAVAILABLE``. A
detached-but-internally-valid ``CONSISTENT`` audit can therefore never
manufacture ``READY``: ``READY`` requires the whole provenance chain to
name the same session and fingerprint end to end.

The two failure classes stay distinct. ``INCONSISTENT`` means the
required material was established and then contradicted itself or its
provenance. ``UNAVAILABLE`` means a required child verdict could not
establish the needed evidence at all -- including a *validated* child
whose own status is ``UNAVAILABLE``, such as a Task 156 request audit
that could not read its package or a Task 159 proposal audit that could
not reach Task 103 for a ``VALIDATED`` proposal. Unavailable evidence is
never reinterpreted as an integrity failure, and it outranks every other
aggregate category: unavailability first, then established
contradictions, then the canonical Task 057 provider failure, and only
then ``READY``.

Only validated children contribute findings. Task 160 adds nothing to
the children's own vocabularies, only its clearly identified
cross-material mismatch and material-unavailability diagnostics.

The service is pure over the four material projections: no database
session, no persistence, no provider invocation, no network. Raw
provider text and the raw provider response object never appear in the
returned projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from rop.schemas.reasoning_run_stage_7_proposal import (
    ReasoningRunStage7ProposalRead,
)
from rop.schemas.reasoning_run_stage_7_proposal_audit import (
    ReasoningRunStage7ProposalAuditRead,
)
from rop.schemas.reasoning_run_stage_7_request import ReasoningRunStage7RequestRead
from rop.schemas.reasoning_run_stage_7_request_audit import (
    ReasoningRunStage7RequestAuditRead,
)
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


def _invalid_detail(exc: ValidationError) -> str:
    """Render one deterministic child-contract rejection reason."""
    details = sorted(
        f"{'.'.join(str(part) for part in error['loc']) or 'model'}:{error['type']}"
        for error in exc.errors()
    )
    return details[0]


def _read_child(
    schema: type[BaseModel],
    material: Mapping[str, Any] | None,
    missing_finding: str,
    invalid_finding: str,
) -> tuple[BaseModel | None, list[str]]:
    """Validate one piece of material against its own child contract.

    The child schema is the only definition of what counts as genuine
    material, so nothing here infers the contract from selected keys.
    """
    if not isinstance(material, Mapping):
        return None, [missing_finding]
    try:
        return schema.model_validate(dict(material)), []
    except ValidationError as exc:
        return None, [f"{invalid_finding}:{_invalid_detail(exc)}"]
    except Exception as exc:
        # Hostile material that cannot even be converted is unreadable,
        # never auditable evidence.
        return None, [f"{invalid_finding}:{type(exc).__name__}"]


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

        Every child is validated against its own contract first, then
        bound: a ``CONSISTENT`` verdict counts only when the audit names
        the exact package or proposal being aggregated. Material this
        boundary cannot validly establish -- including a validated child
        whose own verdict is ``UNAVAILABLE`` -- is ``UNAVAILABLE`` with
        no consistency claim; material that is established but
        contradicts its own provenance is ``INCONSISTENT``. A canonical
        Task 057 provider failure with a fully established and bound
        request chain is ``MODEL_UNAVAILABLE``, and only a fully bound,
        fully audited chain is ``READY``.
        """
        findings: list[str] = []

        # ---- Task 155 request package -----------------------------------
        package, package_findings = _read_child(
            ReasoningRunStage7RequestRead,
            request_package,
            "REQUEST_PACKAGE_MISSING",
            "REQUEST_PACKAGE_INVALID",
        )
        findings.extend(package_findings)

        session_id = package.session_id if package is not None else ""
        packaged = package is not None and package.request_status == "PACKAGED"
        fingerprint = package.context_fingerprint if packaged else None
        request_status = "PACKAGED" if packaged else "UNAVAILABLE"
        if package is not None and not packaged:
            findings.append(f"REQUEST_NOT_PACKAGED:{package.request_status}")

        # ---- Task 156 request audit -------------------------------------
        request_verdict, request_verdict_findings = _read_child(
            ReasoningRunStage7RequestAuditRead,
            request_audit,
            "REQUEST_AUDIT_MISSING",
            "REQUEST_AUDIT_INVALID",
        )
        findings.extend(request_verdict_findings)
        request_audit_status: str | None = None
        request_binding_ok = False
        if isinstance(request_verdict, ReasoningRunStage7RequestAuditRead):
            request_audit_status = request_verdict.request_audit_status
            if request_audit_status not in _READABLE_AUDIT_STATUSES:
                findings.append("REQUEST_AUDIT_UNAVAILABLE")
            elif packaged and request_audit_status == "CONSISTENT":
                # A CONSISTENT audit must name the exact package consumed.
                session_ok = request_verdict.audited_session_id == session_id
                fingerprint_ok = (
                    request_verdict.audited_request_fingerprint == fingerprint
                )
                if not session_ok:
                    findings.append("REQUEST_AUDIT_SESSION_MISMATCH")
                if not fingerprint_ok:
                    findings.append("REQUEST_AUDIT_FINGERPRINT_MISMATCH")
                request_binding_ok = session_ok and fingerprint_ok
            findings.extend(request_verdict.findings)

        # ---- Task 158 proposal result -----------------------------------
        proposal, proposal_findings = _read_child(
            ReasoningRunStage7ProposalRead,
            proposal_result,
            "PROPOSAL_RESULT_MISSING",
            "PROPOSAL_RESULT_INVALID",
        )
        findings.extend(proposal_findings)
        proposal_status = "UNAVAILABLE"
        proposal_known = False
        if proposal is not None:
            proposal_status = proposal.proposal_status
            proposal_known = proposal_status != "UNAVAILABLE"
            if not proposal_known:
                findings.append("PROPOSAL_UNAVAILABLE")

        # ---- Cross-material identity: proposal against the package ------
        proposal_binding_ok = True
        if proposal is not None and proposal_known and packaged:
            if proposal.session_id != session_id:
                proposal_binding_ok = False
                findings.append("PROPOSAL_SESSION_MISMATCH")
            if (
                proposal_status == "VALIDATED"
                and proposal.context_fingerprint != fingerprint
            ):
                proposal_binding_ok = False
                findings.append("PROPOSAL_FINGERPRINT_MISMATCH")

        # ---- Task 159 proposal audit ------------------------------------
        audit_verdict, audit_verdict_findings = _read_child(
            ReasoningRunStage7ProposalAuditRead,
            proposal_audit,
            "PROPOSAL_AUDIT_MISSING",
            "PROPOSAL_AUDIT_INVALID",
        )
        if proposal_status != "VALIDATED":
            # Without a validated proposal the audit certifies nothing, so
            # its absence is not missing required material.
            audit_verdict_findings = [
                item
                for item in audit_verdict_findings
                if item != "PROPOSAL_AUDIT_MISSING"
            ]
        findings.extend(audit_verdict_findings)
        proposal_audit_status: str | None = None
        proposal_audit_consistent = False
        proposal_audit_binding_ok = False
        if isinstance(audit_verdict, ReasoningRunStage7ProposalAuditRead):
            proposal_audit_status = audit_verdict.proposal_audit_status
            proposal_audit_consistent = audit_verdict.proposal_consistent
            if proposal_audit_status not in _READABLE_AUDIT_STATUSES:
                if proposal_status == "VALIDATED":
                    findings.append("PROPOSAL_AUDIT_UNAVAILABLE")
            elif (
                packaged
                and proposal is not None
                and proposal_audit_status == "CONSISTENT"
            ):
                # A CONSISTENT audit must name the exact proposal carried
                # by the Task 158 envelope being aggregated.
                session_ok = audit_verdict.audited_session_id == proposal.session_id
                fingerprint_ok = (
                    audit_verdict.audited_proposal_fingerprint
                    == proposal.context_fingerprint
                )
                if not session_ok:
                    findings.append("PROPOSAL_AUDIT_SESSION_MISMATCH")
                if not fingerprint_ok:
                    findings.append("PROPOSAL_AUDIT_FINGERPRINT_MISMATCH")
                proposal_audit_binding_ok = session_ok and fingerprint_ok
            findings.extend(audit_verdict.findings)

        # ---- Deterministic classification -------------------------------
        # A child verdict that is itself UNAVAILABLE is unavailable
        # material, not an integrity contradiction: the evidence was never
        # established, so nothing can be certified from it.
        request_audit_unavailable = request_audit_status == "UNAVAILABLE"
        proposal_audit_unavailable = (
            proposal_status == "VALIDATED" and proposal_audit_status == "UNAVAILABLE"
        )
        required_material_unavailable = (
            not packaged
            or request_audit_status is None
            or request_audit_unavailable
            or not proposal_known
            or (proposal_status == "VALIDATED" and proposal_audit_status is None)
            or proposal_audit_unavailable
        )
        request_consistent = request_audit_status == "CONSISTENT" and request_binding_ok
        proposal_consistent = (
            proposal_status == "VALIDATED"
            and proposal_audit_status == "CONSISTENT"
            and proposal_audit_consistent
            and proposal_audit_binding_ok
            and proposal_binding_ok
        )

        provider_name: str | None = None
        model_name: str | None = None
        if proposal_status == "VALIDATED" and proposal is not None:
            # The Task 158 contract guarantees provider and model exactly
            # when the status is VALIDATED, so they are read, not inferred.
            provider_name = proposal.provider
            model_name = proposal.model

        if required_material_unavailable:
            result_status = "UNAVAILABLE"
            request_consistent = False
            proposal_consistent = False
        elif proposal_status in _MODEL_OUTPUT_OUTCOMES:
            result_status = "INCONSISTENT"
        elif proposal_status == OUTCOME_MODEL_UNAVAILABLE:
            provider_name = None
            model_name = None
            integrity_failure = not (request_consistent and proposal_binding_ok)
            result_status = "INCONSISTENT" if integrity_failure else "MODEL_UNAVAILABLE"
        elif request_consistent and proposal_consistent:
            result_status = "READY"
        else:
            result_status = "INCONSISTENT"

        if result_status == "UNAVAILABLE":
            provider_name = None
            model_name = None

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
