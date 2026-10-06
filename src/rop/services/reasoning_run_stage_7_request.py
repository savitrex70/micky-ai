"""Task 155: canonical Stage 7 provider request package service.

Builds the provider-neutral request package for exactly one session from
the Task 154 admission verdict and the canonical Task 055 context. The
package delegates all deterministic serialization, payload validation,
and fingerprinting to the established Task 104 helpers and all privacy
screening to the Task 108 boundary; no serializer logic is duplicated
here.

Only an admitted session produces a package: a refused or undecidable
admission yields a status result with no payload and no fingerprint,
and the canonical context is not read at all. Building the package
performs no provider call, no network access, and no persistence.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_7_request import (
    ReasoningRunStage7RequestRead,
)
from rop.services.llm_privacy_boundary import check_payload_privacy
from rop.services.llm_request_serialization import (
    compute_fingerprint,
    serialize_context,
    validate_payload,
)
from rop.services.reasoning_context import (
    ReasoningContextContractError,
    ReasoningContextService,
)
from rop.services.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionService,
)

REASONING_RUN_STAGE_7_REQUEST_SOURCE_TASK_155 = "REASONING_RUN_STAGE_7_REQUEST_TASK_155"


class ReasoningRunStage7RequestContractError(Exception):
    """Task 155: the request package cannot be built or projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7RequestService:
    """Deterministic provider-neutral request package builder."""

    def __init__(
        self,
        admission_service: ReasoningRunStage7AdmissionService | None = None,
        reasoning_context_service: ReasoningContextService | None = None,
    ) -> None:
        self._admission_service = (
            admission_service
            if admission_service is not None
            else ReasoningRunStage7AdmissionService()
        )
        self._context_service = (
            reasoning_context_service
            if reasoning_context_service is not None
            else ReasoningContextService()
        )

    def build(self, db: Session, session_id: UUID) -> dict[str, Any]:
        """Return the strict request package for one exact session.

        Only a Task 154 ``ADMITTED`` verdict consults the canonical
        context. A refused admission (``BLOCKED``) or an undecidable one
        (``UNAVAILABLE``) returns the matching status with ``payload``
        and ``context_fingerprint`` as ``None``. An admitted session
        whose canonical context cannot be read or reports itself
        unavailable also fails closed with ``UNAVAILABLE`` and no
        package. The fingerprint is computed from the exact canonical
        serialized payload that is shipped, so any later payload
        modification no longer matches it.
        """
        admission = self._admission_service.evaluate(db, session_id)
        admission_status = admission.get("admission_status")
        result: dict[str, Any] = {
            "session_id": str(session_id),
            "admission_status": admission_status,
            "stage_6_certification_status": admission.get(
                "stage_6_certification_status"
            ),
            "request_status": "UNAVAILABLE",
            "available": False,
            "context_fingerprint": None,
            "payload": None,
            "request_source": REASONING_RUN_STAGE_7_REQUEST_SOURCE_TASK_155,
        }
        if admission_status != "ADMITTED":
            result["request_status"] = (
                "BLOCKED" if admission_status == "BLOCKED" else "UNAVAILABLE"
            )
            return self._project(result)

        try:
            context = self._context_service.build_for_session(db, session_id)
        except ReasoningContextContractError:
            return self._project(result)
        if not isinstance(context, Mapping) or context.get("available") is not True:
            return self._project(result)

        serialized = serialize_context(context)
        unexpected = validate_payload(serialized)
        if unexpected:
            raise ReasoningRunStage7RequestContractError(
                "PAYLOAD_FIELDS_INVALID",
                "serialized payload carries unexpected fields: "
                + ", ".join(sorted(unexpected)),
            )
        violations = check_payload_privacy(serialized)
        if violations:
            raise ReasoningRunStage7RequestContractError(
                "PAYLOAD_PRIVACY_VIOLATION", "; ".join(violations)
            )

        result["request_status"] = "PACKAGED"
        result["available"] = True
        result["context_fingerprint"] = compute_fingerprint(serialized)
        result["payload"] = copy.deepcopy(serialized)
        return self._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        try:
            validated = ReasoningRunStage7RequestRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7RequestContractError(
                "REQUEST_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
