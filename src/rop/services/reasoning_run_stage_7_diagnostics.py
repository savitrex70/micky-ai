"""Task 161: Stage 7 diagnostics health classification service.

Presentation over the completed Stage 7 evidence surfaces: the Task 155
request package, the Task 156 request audit, the Task 158 validated
proposal, and the Task 159 proposal audit are aggregated by the
canonical Task 160 unified result boundary, and that deterministic
verdict is classified into exactly one health state. This is not a
second reasoning engine: it adds no new validation and re-derives
nothing -- the canonical child verdicts decide, and a model's own claim
of confidence can never influence the health state.

``DEGRADED`` and ``NO_MATERIAL`` stay distinct, because a proposal
mapping on its own proves nothing about the request it supposedly
belonged to. Only the aggregate evidence that a result was actually
admitted -- a ``PACKAGED`` Task 160 request status together with a
``VALIDATED`` proposal -- can degrade, and then only when the missing
material is the canonical audit-evidence diagnostics. An ``UNAVAILABLE``
aggregate whose request was never packaged is ``NO_MATERIAL`` even when
a complete, internally valid, validated proposal is supplied.

Read-only: no database session, no persistence, no provider call, no
network, and no mutation of the inspected material.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_diagnostics import (
    ReasoningRunStage7DiagnosticsRead,
)
from rop.services.reasoning_run_stage_7_result import (
    ReasoningRunStage7ResultService,
)

REASONING_RUN_STAGE_7_DIAGNOSTICS_SOURCE_TASK_161 = (
    "REASONING_RUN_STAGE_7_DIAGNOSTICS_TASK_161"
)

_UNHEALTHY_RESULT_STATUSES = ("INCONSISTENT", "MODEL_UNAVAILABLE")

# Task 160's own diagnostics for required provenance/audit evidence that
# cannot be established: absent, malformed or unreadable, or a validated
# child verdict that itself reports UNAVAILABLE.
_AUDIT_EVIDENCE_FINDINGS = (
    "REQUEST_AUDIT_MISSING",
    "REQUEST_AUDIT_UNAVAILABLE",
    "PROPOSAL_AUDIT_MISSING",
    "PROPOSAL_AUDIT_UNAVAILABLE",
)
_AUDIT_EVIDENCE_FINDING_PREFIXES = (
    "REQUEST_AUDIT_INVALID:",
    "PROPOSAL_AUDIT_INVALID:",
)


class ReasoningRunStage7DiagnosticsContractError(Exception):
    """Task 161: the diagnostics verdict cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def _audit_evidence_unavailable(findings: list[str]) -> bool:
    """True when the unavailability is specifically provenance evidence.

    Task 160 alone decides which required evidence is missing; this only
    reads its canonical diagnostics, so no child validation is repeated
    here and an aggregate that is unavailable for any other reason stays
    ``NO_MATERIAL`` instead of becoming a degraded result.
    """
    return any(
        finding in _AUDIT_EVIDENCE_FINDINGS
        or finding.startswith(_AUDIT_EVIDENCE_FINDING_PREFIXES)
        for finding in findings
    )


class ReasoningRunStage7DiagnosticsService:
    """Deterministic read-only health classification over Stage 7 evidence.

    Pure presentation: accepts the four canonical child material
    mappings and never a database session, so no write and no provider
    call is possible from this boundary.
    """

    @staticmethod
    def diagnose(
        *,
        request_package: Mapping[str, Any] | None = None,
        request_audit: Mapping[str, Any] | None = None,
        proposal_result: Mapping[str, Any] | None = None,
        proposal_audit: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Classify one Stage 7 interaction into a deterministic health state.

        The canonical Task 160 aggregate decides with no new reasoning:
        a READY result is ``HEALTHY``; an INCONSISTENT contradiction or
        a canonical provider failure is ``UNHEALTHY``; ``DEGRADED``
        requires the aggregate to be ``UNAVAILABLE`` while an admitted
        packaged request AND a validated proposal both exist AND the
        unavailable material is specifically the required
        provenance/audit evidence; anything else is ``NO_MATERIAL``. A
        detached validated proposal with no packaged request is
        therefore ``NO_MATERIAL``, never a degraded result. Findings and
        statuses are the canonical Task 160 evidence, deterministic,
        sorted, and deduplicated.
        """
        aggregate = ReasoningRunStage7ResultService.build(
            request_package=request_package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
        )
        result_status = aggregate["result_status"]
        request_status = aggregate["request_status"]
        proposal_status = aggregate["proposal_status"]

        if result_status == "READY":
            diagnostics_status = "HEALTHY"
        elif result_status in _UNHEALTHY_RESULT_STATUSES:
            diagnostics_status = "UNHEALTHY"
        elif (
            result_status == "UNAVAILABLE"
            and request_status == "PACKAGED"
            and proposal_status == "VALIDATED"
            and _audit_evidence_unavailable(aggregate["findings"])
        ):
            # An admitted packaged request and a validated proposal prove
            # a reasoning result exists; only its required audit evidence
            # is missing, so this is degradation, not absent material. A
            # standalone validated proposal mapping never gets here.
            diagnostics_status = "DEGRADED"
        else:
            diagnostics_status = "NO_MATERIAL"

        result: dict[str, Any] = {
            "session_id": aggregate["session_id"],
            "result_status": result_status,
            "request_status": request_status,
            "proposal_status": proposal_status,
            "diagnostics_status": diagnostics_status,
            "available": diagnostics_status != "NO_MATERIAL",
            "finding_count": aggregate["finding_count"],
            "findings": aggregate["findings"],
            "source": REASONING_RUN_STAGE_7_DIAGNOSTICS_SOURCE_TASK_161,
        }
        return ReasoningRunStage7DiagnosticsService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Project the canonical Task 160 evidence without renormalizing it.

        Task 160 already guarantees sorted, deduplicated findings and a
        matching ``finding_count``; the strict schema re-checks that
        guarantee rather than silently repairing it. Anything the
        canonical aggregate did not establish fails closed here instead
        of being quietly rewritten into a coherent-looking verdict.
        """
        try:
            validated = ReasoningRunStage7DiagnosticsRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7DiagnosticsContractError(
                "DIAGNOSTICS_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
