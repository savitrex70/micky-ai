"""Task 137: deterministic reasoning-run receipt inspection service.

Read-only inspection of one exact canonical completed receipt identity
``(session_id, input_fingerprint)`` over the existing append-only
receipt model and repository. The lookup is exact: the requested
session AND the requested fingerprint AND the persisted COMPLETED
outcome must all match -- no "latest receipt" semantics, no
substitution of a different fingerprint, session, or outcome, no
recomputation or fabrication of a receipt that does not exist. No
execution, no replay, no writes, no model/provider logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.repositories.reasoning_run_receipt import ReasoningRunReceiptRepository
from rop.schemas.reasoning_run_receipt import ReasoningRunReceiptRead

REASONING_RUN_RECEIPT_SERVICE_SOURCE_TASK_137 = "REASONING_RUN_RECEIPT_TASK_137"

_OUTCOME_COMPLETED = "COMPLETED"

_REQUIRED_FIELDS = (
    "id",
    "session_id",
    "input_fingerprint",
    "exogenous_snapshot",
    "outcome",
    "created_at",
)


class ReasoningRunReceiptContractError(Exception):
    """Task 137: the requested receipt identity cannot be inspected.

    Raised only for contract-level failures (e.g. a receipt row whose
    persisted state cannot be projected onto the canonical read
    schema). A valid-but-nonexistent canonical identity is a normal
    deterministic result (``found=False``), not an error.
    """

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunReceiptService:
    """Read-only inspection of one canonical completed receipt identity."""

    def __init__(
        self, receipt_repository: ReasoningRunReceiptRepository | None = None
    ) -> None:
        self.receipt_repository = receipt_repository or ReasoningRunReceiptRepository()

    def inspect(
        self,
        db: Session,
        session_id: UUID,
        input_fingerprint: str,
    ) -> dict[str, Any]:
        """Return the Task 137 inspection result for one exact identity.

        The result distinguishes exactly two deterministic outcomes:

        - a matching completed receipt exists: ``found=True`` with the
          strict read projection of the persisted fields, where the
          receipt's ``session_id`` and ``input_fingerprint``
          correspond exactly to the requested identity;
        - no matching completed receipt exists: ``found=False`` with
          ``receipt=None`` -- never a fabricated, recomputed, or
          substituted receipt.

        The requested canonical identity is always echoed in the
        result. Read-only: no writes, no execution, no replay, no
        mutation of any reasoning state.
        """
        receipt = self.receipt_repository.find_completed(
            db, session_id, input_fingerprint
        )
        result: dict[str, Any] = {
            "found": False,
            "available": True,
            "requested_session_id": str(session_id),
            "requested_input_fingerprint": input_fingerprint,
            "receipt": None,
            "receipt_source": REASONING_RUN_RECEIPT_SERVICE_SOURCE_TASK_137,
        }
        if receipt is None:
            return result

        projected = self._project(receipt, session_id, input_fingerprint)
        if projected is None:
            raise ReasoningRunReceiptContractError(
                "RECEIPT_UNREADABLE",
                "persisted receipt state cannot be projected onto the "
                "canonical read schema",
            )
        result["found"] = True
        result["receipt"] = projected
        return result

    def list_completed_by_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> list[dict[str, Any]]:
        """Project all persisted COMPLETED receipts for one exact session.

        The returned items are strict read projections, ordered by the
        durable receipt history contract. No writes, no execution, no
        replay, no mutation.
        """
        receipts = self.receipt_repository.list_completed_by_session(db, session_id)
        projected: list[dict[str, Any]] = []
        for receipt in receipts:
            item = self._project(
                receipt,
                session_id,
                receipt.input_fingerprint,
            )
            if item is None:
                raise ReasoningRunReceiptContractError(
                    "RECEIPT_UNREADABLE",
                    "persisted receipt state cannot be projected onto the "
                    "canonical read schema",
                )
            projected.append(item)
        return projected

    def history(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Return the deterministic read-only history for a session."""
        return {
            "session_id": str(session_id),
            "receipts": self.list_completed_by_session(db, session_id),
        }

    def _project(
        self,
        receipt: Any,
        session_id: UUID,
        input_fingerprint: str,
    ) -> dict[str, Any] | None:
        """Project one persisted receipt onto the strict read schema.

        Returns ``None`` when the persisted state is unusable (missing
        required field, identity mismatch with the requested
        canonical identity, or a non-completed outcome) so the caller
        reports a contract error instead of a fabricated receipt.
        """
        data: dict[str, Any] = {}
        for field in _REQUIRED_FIELDS:
            value = getattr(receipt, field, None)
            if value is None:
                return None
            if field == "created_at":
                if not isinstance(value, datetime):
                    return None
                data[field] = value.isoformat()
            elif field == "session_id":
                data[field] = str(value)
            elif field == "id":
                data[field] = str(value)
            elif field == "exogenous_snapshot":
                if not isinstance(value, dict):
                    return None
                data[field] = value
            else:
                data[field] = value

        if data["outcome"] != _OUTCOME_COMPLETED:
            return None
        if data["session_id"] != str(session_id):
            return None
        if data["input_fingerprint"] != input_fingerprint:
            return None

        try:
            ReasoningRunReceiptRead.model_validate(data)
        except Exception:
            return None
        return data
