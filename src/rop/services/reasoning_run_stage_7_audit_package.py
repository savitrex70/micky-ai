"""Task 162: Stage 7 deterministic audit package service.

Assembles one deterministic, provider-neutral audit package from the
completed Stage 7 projections: the Task 154 admission verdict, the
Task 155 request package, the Task 156 request audit, the Task 158
validated proposal, the Task 159 proposal audit, and the Task 161
diagnostics verdict. Combination and presentation only: the service
invokes no other Stage 7 service, re-derives no verdict, and
re-implements no audit dimension.

No child status field is ever trusted on its own. Each piece of material
must first validate against its OWN approved contract --
``ReasoningRunStage7AdmissionRead``, ``ReasoningRunStage7RequestRead``,
``ReasoningRunStage7RequestAuditRead``, ``ReasoningRunStage7ProposalRead``,
``ReasoningRunStage7ProposalAuditRead`` and
``ReasoningRunStage7DiagnosticsRead`` -- and only the validated object is
read. Those schemas are reused, never duplicated here, so a forged,
incomplete, over-extended, or internally incoherent mapping is rejected
as unavailable material instead of contributing a status, a fingerprint,
a provider name, a session identity, or a finding. Because the children
already encode the exact provenance bindings (Task 156 names the audited
session and request fingerprint, Task 159 names the audited session and
proposal fingerprint, Task 161 carries the canonical health state), the
package preserves those bindings verbatim rather than inventing weaker
key comparisons.

Consequences of validating first: ``provider_name`` and ``model_name``
can only come from a ``VALIDATED`` Task 158 proposal, because that
contract makes provider and model present exactly when validated;
``request_fingerprint`` only from a ``PACKAGED`` Task 155 package, whose
contract guarantees the 64-hexadecimal shape; and session identity is
established only from validated children, so invalid material can never
claim a session.

Validation is not binding, though. A ``CONSISTENT`` audit verdict only
certifies the exact material its own binding fields name, so the
published Task 156 ``audited_session_id`` / ``audited_request_fingerprint``
are compared against the validated Task 155 package and the published
Task 159 ``audited_session_id`` / ``audited_proposal_fingerprint`` against
the validated Task 158 proposal. A detached audit is unusable evidence:
its status is not projected and one of Task 162's own structural
mismatch markers reports why. No audit service is re-run and no
fingerprint is recomputed to make that comparison.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, and no mutation of the inspected
material. Raw provider text and the raw provider response object can
never appear in the returned package; only canonical statuses, validated
provider metadata, and deterministic findings are projected.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from rop.schemas.reasoning_run_stage_7_admission import ReasoningRunStage7AdmissionRead
from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.schemas.reasoning_run_stage_7_diagnostics import (
    ReasoningRunStage7DiagnosticsRead,
)
from rop.schemas.reasoning_run_stage_7_proposal import ReasoningRunStage7ProposalRead
from rop.schemas.reasoning_run_stage_7_proposal_audit import (
    ReasoningRunStage7ProposalAuditRead,
)
from rop.schemas.reasoning_run_stage_7_request import ReasoningRunStage7RequestRead
from rop.schemas.reasoning_run_stage_7_request_audit import (
    ReasoningRunStage7RequestAuditRead,
)

REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162 = (
    "REASONING_RUN_STAGE_7_AUDIT_PACKAGE_TASK_162"
)

# One entry per approved child contract, in argument order: the schema is
# the only definition of genuine material for that child, and the two
# markers are this service's own clearly identified structural findings.
_CHILD_CONTRACTS: tuple[tuple[type[BaseModel], str, str], ...] = (
    (ReasoningRunStage7AdmissionRead, "ADMISSION_MISSING", "ADMISSION_INVALID"),
    (
        ReasoningRunStage7RequestRead,
        "REQUEST_PACKAGE_MISSING",
        "REQUEST_PACKAGE_INVALID",
    ),
    (
        ReasoningRunStage7RequestAuditRead,
        "REQUEST_AUDIT_MISSING",
        "REQUEST_AUDIT_INVALID",
    ),
    (
        ReasoningRunStage7ProposalRead,
        "PROPOSAL_RESULT_MISSING",
        "PROPOSAL_RESULT_INVALID",
    ),
    (
        ReasoningRunStage7ProposalAuditRead,
        "PROPOSAL_AUDIT_MISSING",
        "PROPOSAL_AUDIT_INVALID",
    ),
    (
        ReasoningRunStage7DiagnosticsRead,
        "DIAGNOSTICS_MISSING",
        "DIAGNOSTICS_INVALID",
    ),
)


class ReasoningRunStage7AuditPackageContractError(Exception):
    """Task 162: the audit package cannot be projected."""

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

    Absent or non-mapping material is a missing artifact, and material
    that its own contract rejects is an invalid artifact. Either way the
    child contributes nothing to the package -- not a status, not a
    fingerprint, not a session claim, and not a single finding -- so no
    unvalidated mapping can smuggle evidence into the audit package.
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

        Every child is validated against its own approved contract
        before any field is read, so canonical statuses are carried
        verbatim from validated objects only. Absent or invalid material
        yields a deterministic structural marker and never a fabricated
        verdict; an unreadable diagnostics verdict is the one exception
        the contract requires, folding to ``NO_MATERIAL``. Session
        identity is established only after validation, from the children
        that legitimately carry one, and contradictory validated claims
        leave the identity empty with the canonical mismatch finding. A
        ``CONSISTENT`` audit is projected only when its published binding
        session and fingerprint name the validated package or proposal
        beside it. Findings are this service's own structural markers
        combined with the validated children's canonical findings in one
        deterministic sorted union. No child service is invoked and no
        child verdict is recomputed here.
        """
        materials: tuple[Mapping[str, Any] | None, ...] = (
            admission_result,
            request_package,
            request_audit,
            proposal_result,
            proposal_audit,
            diagnostics_result,
        )
        validated: list[BaseModel | None] = []
        findings: list[str] = []
        for (schema, missing_finding, invalid_finding), material in zip(
            _CHILD_CONTRACTS, materials, strict=True
        ):
            child, child_findings = _read_child(
                schema, material, missing_finding, invalid_finding
            )
            validated.append(child)
            findings.extend(child_findings)

        (
            admission,
            request,
            request_verdict,
            proposal,
            proposal_verdict,
            diagnostics,
        ) = validated

        session_id = ReasoningRunStage7AuditPackageService._resolve_session(
            admission=admission,
            request=request,
            proposal=proposal,
            diagnostics=diagnostics,
            findings=findings,
        )

        # A CONSISTENT audit verdict is only evidence for the exact
        # material its own binding fields name, so those already-published
        # values are compared here before the status is projected.
        request_audit_status = _bound_audit_status(
            request_verdict,
            request,
            status_field="request_audit_status",
            audited_session_field="audited_session_id",
            audited_fingerprint_field="audited_request_fingerprint",
            session_marker="REQUEST_AUDIT_SESSION_MISMATCH",
            fingerprint_marker="REQUEST_AUDIT_FINGERPRINT_MISMATCH",
            findings=findings,
        )
        proposal_audit_status = _bound_audit_status(
            proposal_verdict,
            proposal,
            status_field="proposal_audit_status",
            audited_session_field="audited_session_id",
            audited_fingerprint_field="audited_proposal_fingerprint",
            session_marker="PROPOSAL_AUDIT_SESSION_MISMATCH",
            fingerprint_marker="PROPOSAL_AUDIT_FINGERPRINT_MISMATCH",
            findings=findings,
        )

        result: dict[str, Any] = {
            "session_id": session_id,
            "admission_status": _value(admission, "admission_status"),
            "request_fingerprint": _packaged_fingerprint(request),
            "request_audit_status": request_audit_status,
            "proposal_audit_status": proposal_audit_status,
            "diagnostics_status": _value(diagnostics, "diagnostics_status")
            or "NO_MATERIAL",
            "provider_name": _validated_metadata(proposal, "provider"),
            "model_name": _validated_metadata(proposal, "model"),
            "audit_source": REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        }
        for child in (admission, request_verdict, proposal_verdict, diagnostics):
            if child is not None:
                findings.extend(child.findings)

        combined = sorted(set(findings))
        result["finding_count"] = len(combined)
        result["findings"] = combined
        return ReasoningRunStage7AuditPackageService._project(result)

    @staticmethod
    def _resolve_session(
        *,
        admission: BaseModel | None,
        request: BaseModel | None,
        proposal: BaseModel | None,
        diagnostics: BaseModel | None,
        findings: list[str],
    ) -> str:
        """Establish one session identity from validated children only.

        An empty claim carries no identity -- the Task 161 contract uses
        ``""`` exactly when it admitted no material -- so only validated
        non-empty claims participate. Contradictory validated claims
        never resolve to an arbitrary winner: the identity is emptied
        and the mismatch is reported.
        """
        claims = {
            claim
            for claim in (
                _value(admission, "requested_session_id"),
                _value(request, "session_id"),
                _value(proposal, "session_id"),
                _value(diagnostics, "session_id"),
            )
            if claim
        }
        if len(claims) == 1:
            return next(iter(claims))
        if len(claims) > 1:
            findings.append("SESSION_MISMATCH")
        return ""

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate and dump the assembled package without repairing it.

        The combined findings were already placed in deterministic order
        by the documented combination step, so this only enforces the
        approved package contract -- the exact field set, the canonical
        status vocabularies, provider and model set together, sorted and
        deduplicated findings, and ``finding_count == len(findings)``.
        Anything the validated children did not establish fails closed
        here instead of being quietly rewritten.
        """
        try:
            validated = ReasoningRunStage7AuditPackageRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7AuditPackageContractError(
                "AUDIT_PACKAGE_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()


def _value(child: BaseModel | None, field: str) -> Any:
    """Read one field from a validated child, or ``None`` if unusable."""
    return None if child is None else getattr(child, field)


def _packaged_fingerprint(request: BaseModel | None) -> str | None:
    """Project the fingerprint only from a validated PACKAGED request.

    The Task 155 contract already guarantees the 64-hexadecimal shape and
    makes the fingerprint present exactly when ``PACKAGED``, so a
    ``BLOCKED`` or ``UNAVAILABLE`` package contributes nothing here.
    """
    if request is None or request.request_status != "PACKAGED":
        return None
    fingerprint = request.context_fingerprint
    return str(fingerprint) if fingerprint is not None else None


def _bound_audit_status(
    verdict: BaseModel | None,
    material: BaseModel | None,
    *,
    status_field: str,
    audited_session_field: str,
    audited_fingerprint_field: str,
    session_marker: str,
    fingerprint_marker: str,
    findings: list[str],
) -> str | None:
    """Project an audit status only when it names this exact material.

    Validation alone cannot prove that a ``CONSISTENT`` audit belongs to
    the request or proposal being packaged, so the binding evidence the
    audit itself publishes is compared exactly. Nothing is re-audited and
    no fingerprint is recomputed here -- both values are already canonical
    child output, and the child contracts guarantee a ``CONSISTENT``
    verdict names a non-empty session and fingerprint.

    An audit that names other material is detached evidence, so its
    status is not usable for this package and the mismatch is reported as
    one of Task 162's own structural markers. A non-``CONSISTENT`` verdict
    certifies nothing in the first place, so its canonical status is
    carried through untouched. When the counterpart material is absent or
    invalid there is nothing to bind to; the status is unusable and the
    already-reported ``*_MISSING`` or ``*_INVALID`` marker explains why,
    without inventing a new vocabulary.
    """
    if verdict is None:
        return None
    status = str(getattr(verdict, status_field))
    if status != "CONSISTENT":
        return status
    if material is None:
        return None

    bound = True
    if getattr(verdict, audited_session_field) != material.session_id:
        findings.append(session_marker)
        bound = False
    if getattr(verdict, audited_fingerprint_field) != material.context_fingerprint:
        findings.append(fingerprint_marker)
        bound = False
    return status if bound else None


def _validated_metadata(proposal: BaseModel | None, field: str) -> str | None:
    """Project provider metadata only from a validated proposal.

    The Task 158 contract makes provider and model present exactly when
    ``proposal_status == 'VALIDATED'``, so a failure-status, malformed,
    or absent proposal can never inject provider metadata.
    """
    if proposal is None or proposal.proposal_status != "VALIDATED":
        return None
    value = getattr(proposal, field)
    return str(value) if value is not None else None
