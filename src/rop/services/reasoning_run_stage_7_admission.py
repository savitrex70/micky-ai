"""Task 154: Stage 7 per-session LLM admission service.

The deterministic per-session admission boundary answering one
question: is this specific reasoning session eligible to enter the LLM
reasoning path? This is deliberately separate from Task 153: the entry
contract confirms the Stage 7 boundary itself is structurally healthy,
while admission decides permission for one exact session to request
LLM reasoning.

The decision consumes the canonical Task 152 Stage 6 certification
service and reproduces none of its logic. Mapping: certification
``CERTIFIED`` -> ``ADMITTED``; ``NO_MATERIAL`` -> ``BLOCKED`` (an
empty deterministic session must never be sent to an LLM); ``BLOCKED``
and ``UNVERIFIABLE`` -> ``BLOCKED``; a certification that cannot be
read or projected -> ``UNAVAILABLE``. A certification record that is
not internally coherent can never admit.

Read-only: no persistence, no reasoning execution, no provider/model
calls, no network, no server. Admission never means a model is
configured or invoked.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionRead,
)
from rop.services.reasoning_run_stage_6_certification import (
    ReasoningRunStage6CertificationContractError,
    ReasoningRunStage6CertificationService,
)

REASONING_RUN_STAGE_7_ADMISSION_SOURCE_TASK_154 = (
    "REASONING_RUN_STAGE_7_ADMISSION_TASK_154"
)

_CERTIFICATION_UNREADABLE_STATUS = "UNAVAILABLE"


class ReasoningRunStage7AdmissionContractError(Exception):
    """Task 154: the admission result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7AdmissionService:
    """Deterministic read-only per-session LLM admission decision."""

    def __init__(
        self,
        certification_service: ReasoningRunStage6CertificationService | None = None,
    ) -> None:
        self._certification_service = (
            certification_service
            if certification_service is not None
            else ReasoningRunStage6CertificationService()
        )

    def evaluate(self, db: Session, session_id: UUID) -> dict[str, Any]:
        """Return the strict admission verdict for one exact session.

        Read-only over session state: the only consumer of ``db`` is
        the canonical Task 152 certification handoff. ``NO_MATERIAL``
        is deliberately not eligible for LLM reasoning -- an empty
        deterministic session must never be sent to a model. Fail
        closed on an unreadable certification: release readiness and
        record consistency are ``False`` and the status is
        ``UNAVAILABLE``; the question is never answered by fabricating
        certification evidence.
        """
        readable = True
        certification_status: str = _CERTIFICATION_UNREADABLE_STATUS
        release_ready: Any = False
        certification_consistent = False
        admission_findings: list[str] = []
        try:
            certification = self._certification_service.certify(db, session_id)
        except ReasoningRunStage6CertificationContractError as exc:
            readable = False
            admission_findings.append(
                f"STAGE_6_CERTIFICATION_UNREADABLE:{exc.invariant}"
            )
        else:
            certification_status = certification.get("certification_status")
            certified = certification.get("certified")
            release_ready = certification.get("release_ready")
            certification_consistent = (
                certified == (certification_status == "CERTIFIED")
                and release_ready == certified
            )
            if not certification_consistent:
                admission_findings.append("STAGE_6_CERTIFICATION_INCOHERENT")
            elif certification_status != "CERTIFIED":
                admission_findings.append(
                    f"STAGE_6_CERTIFICATION_NOT_CERTIFIED:{certification_status}"
                )

        findings = sorted(set(admission_findings))

        if not readable:
            admission_status = "UNAVAILABLE"
        elif not certification_consistent or certification_status != "CERTIFIED":
            admission_status = "BLOCKED"
        else:
            admission_status = "ADMITTED"

        result: dict[str, Any] = {
            "requested_session_id": str(session_id),
            "admission_status": admission_status,
            "admitted": admission_status == "ADMITTED",
            "stage_6_certification_status": certification_status,
            "stage_6_release_ready": release_ready,
            "stage_6_certification_consistent": certification_consistent,
            "finding_count": len(findings),
            "findings": findings,
            "admission_source": REASONING_RUN_STAGE_7_ADMISSION_SOURCE_TASK_154,
        }
        try:
            validated = ReasoningRunStage7AdmissionRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7AdmissionContractError(
                "ADMISSION_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
