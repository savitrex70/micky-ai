"""Task 161: Stage 7 diagnostics health classification service.

Presentation over the completed Stage 7 evidence surfaces: the Task 155
request package, the Task 156 request audit, the Task 158 validated
proposal, and the Task 159 proposal audit are aggregated by the
canonical Task 160 unified result boundary, and that deterministic
verdict is classified into exactly one health state. This is not a
second reasoning engine: it adds no new validation and re-derives
nothing -- the canonical child verdicts decide, and a model's own claim
of confidence can never influence the health state.

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


class ReasoningRunStage7DiagnosticsContractError(Exception):
    """Task 161: the diagnostics verdict cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


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
        a READY result is ``HEALTHY``; an INCONSISTENT request/proposal
        contradiction or a canonical provider failure is ``UNHEALTHY``;
        an unauditable result backed by an existing validated proposal
        is ``DEGRADED``; and the absence of any admitted result is
        ``NO_MATERIAL``. Findings are the canonical Task 160 evidence,
        deterministic, sorted, and deduplicated.
        """
        aggregate = ReasoningRunStage7ResultService.build(
            request_package=request_package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
        )
        result_status = aggregate["result_status"]
        proposal_status = aggregate["proposal_status"]

        if result_status == "READY":
            diagnostics_status = "HEALTHY"
        elif result_status in ("INCONSISTENT", "MODEL_UNAVAILABLE"):
            diagnostics_status = "UNHEALTHY"
        elif proposal_status == "VALIDATED":
            diagnostics_status = "DEGRADED"
        else:
            diagnostics_status = "NO_MATERIAL"

        result: dict[str, Any] = {
            "session_id": aggregate["session_id"],
            "result_status": result_status,
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
        normalized = sorted(set(str(item) for item in result["findings"]))
        candidate = {**result, "finding_count": len(normalized), "findings": normalized}
        try:
            validated = ReasoningRunStage7DiagnosticsRead.model_validate(candidate)
        except ValidationError as exc:
            raise ReasoningRunStage7DiagnosticsContractError(
                "DIAGNOSTICS_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
