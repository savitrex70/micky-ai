"""Task 127: deterministic reasoning-run idempotency.

Canonical run identity is ``(session_id, input_fingerprint)``: the
session locates the run, the Task 125 fingerprint pins its exact
approved inputs. Re-running unchanged inputs never rewrites state --
the current state is recomposed read-only and reported as
``REUSED_IDENTICAL``. Changed inputs are reported as ``STALE_CHANGED``
without executing, so a changed fingerprint is never treated as the
same run. No queues, workers, history deletion, or external services.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.repositories.reasoning_run_receipt import (
    ReasoningRunReceiptRepository,
)
from rop.schemas.reasoning_run_idempotency import (
    ReasoningRunIdempotentExecutionRead,
)
from rop.services.reasoning_run import ReasoningRunService
from rop.services.reasoning_run_consistency import (
    ReasoningRunConsistencyService,
)
from rop.services.reasoning_run_execution import (
    EXECUTION_STAGE_IDS,
    ReasoningRunExecutionService,
)
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    ReasoningRunInputSnapshotService,
    exogenous_projection,
)

DISPOSITION_EXECUTED_NEW = "EXECUTED_NEW"
DISPOSITION_REUSED_IDENTICAL = "REUSED_IDENTICAL"
DISPOSITION_STALE_CHANGED = "STALE_CHANGED"

_VALID_DISPOSITIONS = (
    DISPOSITION_EXECUTED_NEW,
    DISPOSITION_REUSED_IDENTICAL,
    DISPOSITION_STALE_CHANGED,
)


class ReasoningRunIdempotencyContractError(Exception):
    """Task 127: the idempotent request could not be evaluated."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def derive_run_identity(session_id: UUID, input_fingerprint: str) -> str:
    """Return the canonical identity key for a reasoning run."""
    return f"{session_id}:{input_fingerprint}"


class ReasoningRunIdempotencyService:
    """Idempotency-aware entry point over the deterministic executor.

    The caller supplies the fingerprint it last observed
    (``known_input_fingerprint``), always the exact ``input_fingerprint``
    returned by an earlier execution -- one stable meaning everywhere:

    - ``None`` -- observe nothing, execute unconditionally (``EXECUTED_NEW``);
    - a stored COMPLETED receipt for the exact ``(session_id,
      fingerprint)`` identity, plus exogenous continuity between the
      recorded run and current inputs, plus a consistent read-only
      recomposition -- reuse without rewriting anything
      (``REUSED_IDENTICAL`` reporting exactly the known fingerprint);
    - anything else -- inputs moved, or no completed run proves the
      identity: ``STALE_CHANGED`` without executing, or a fresh
      execution that never claims reuse.

    A changed fingerprint is therefore never treated as the same run,
    and repeat calls create no duplicate state: reuse performs zero
    writes, and every execution path funnels through the atomic
    replace-semantics executor.
    """

    def __init__(
        self,
        execution_service: ReasoningRunExecutionService | None = None,
        snapshot_service: ReasoningRunInputSnapshotService | None = None,
        reasoning_run_service: ReasoningRunService | None = None,
        reasoning_run_consistency_service: ReasoningRunConsistencyService | None = None,
        receipt_repository: ReasoningRunReceiptRepository | None = None,
    ) -> None:
        self.execution_service = execution_service or ReasoningRunExecutionService()
        self.snapshot_service = snapshot_service or ReasoningRunInputSnapshotService()
        self.reasoning_run_service = reasoning_run_service or ReasoningRunService()
        self.reasoning_run_consistency_service = (
            reasoning_run_consistency_service or ReasoningRunConsistencyService()
        )
        self.receipt_repository = receipt_repository or ReasoningRunReceiptRepository()

    def execute_idempotent(
        self,
        db: Session,
        session_id: UUID,
        *,
        known_input_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        """Execute once, reuse when identical, or report stale input.

        The canonical identity is ``(session_id, input_fingerprint)``
        where the fingerprint is the exact Task 124 snapshot fingerprint
        the execution ran against -- one stable meaning everywhere. The
        flow establishes the prior run instead of trusting the caller:

        - ``None``: execute unconditionally (``EXECUTED_NEW``);
        - no COMPLETED receipt for the supplied identity: a fingerprint
          matching current inputs executes anew (no proof of a prior
          run), anything else is ``STALE_CHANGED`` -- a fabricated
          fingerprint is never proof;
        - receipt found but current exogenous inputs moved since the
          recorded run: ``STALE_CHANGED``;
        - receipt found, exogenous continuity holds, and the current
          state recomposes to a consistent completed run:
          ``REUSED_IDENTICAL`` reporting exactly the known fingerprint.
          Otherwise the request executes anew, so a failed run stays
          retryable and never satisfies reuse.
        """
        try:
            snapshot = self.snapshot_service.build_snapshot(db, session_id)
            current_fingerprint = compute_snapshot_fingerprint(snapshot)
            current_exogenous = exogenous_projection(snapshot)
        except Exception as exc:
            raise ReasoningRunIdempotencyContractError(
                "INPUT_SNAPSHOT_FAILED",
                "idempotent input state could not be established: "
                + type(exc).__name__,
            ) from exc

        if known_input_fingerprint is not None:
            receipt = self.receipt_repository.find_completed(
                db, session_id, known_input_fingerprint
            )
            if receipt is None:
                if known_input_fingerprint != current_fingerprint:
                    return self._envelope(
                        disposition=DISPOSITION_STALE_CHANGED,
                        session_id=session_id,
                        known_input_fingerprint=known_input_fingerprint,
                        current_fingerprint=current_fingerprint,
                        result=None,
                    )
            elif receipt.exogenous_snapshot != current_exogenous:
                return self._envelope(
                    disposition=DISPOSITION_STALE_CHANGED,
                    session_id=session_id,
                    known_input_fingerprint=known_input_fingerprint,
                    current_fingerprint=current_fingerprint,
                    result=None,
                )
            else:
                reused = self._try_reuse(db, session_id, known_input_fingerprint)
                if reused is not None:
                    return self._envelope(
                        disposition=DISPOSITION_REUSED_IDENTICAL,
                        session_id=session_id,
                        known_input_fingerprint=known_input_fingerprint,
                        current_fingerprint=current_fingerprint,
                        result=reused,
                    )

        result = self.execution_service.execute_for_session(db, session_id)
        return self._envelope(
            disposition=DISPOSITION_EXECUTED_NEW,
            session_id=session_id,
            known_input_fingerprint=known_input_fingerprint,
            current_fingerprint=current_fingerprint,
            result=result,
        )

    def _try_reuse(
        self, db: Session, session_id: UUID, known_input_fingerprint: str
    ) -> dict[str, Any] | None:
        """Recompose the current state read-only; None when unusable.

        The recomposed result is stamped with the recorded canonical
        input fingerprint (``known_input_fingerprint``) -- never the
        current full snapshot fingerprint, which legitimately includes
        newly generated derived state. The three fingerprint roles stay
        distinct: ``current_input_fingerprint`` for comparison/reporting,
        ``result.input_fingerprint`` and ``receipt.input_fingerprint``
        for the recorded canonical identity.
        """
        try:
            run = self.reasoning_run_service.build_for_session(db, session_id)
            audit = self.reasoning_run_consistency_service.build_for_session(
                db, session_id
            )
        except Exception:
            return None
        if not isinstance(run, dict) or not isinstance(audit, dict):
            return None
        if audit.get("run_consistent") is not True:
            return None
        return ReasoningRunExecutionService._build_result(
            session_id=session_id,
            input_fingerprint=known_input_fingerprint,
            completed_ids=list(EXECUTION_STAGE_IDS),
            failed_id=None,
            run=run,
            audit=audit,
        )

    @staticmethod
    def _envelope(
        *,
        disposition: str,
        session_id: UUID,
        known_input_fingerprint: str | None,
        current_fingerprint: str,
        result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        envelope = {
            "disposition": disposition,
            "session_id": str(session_id),
            "known_input_fingerprint": known_input_fingerprint,
            "current_input_fingerprint": current_fingerprint,
            "result": result,
        }
        return ReasoningRunIdempotentExecutionRead.model_validate(envelope).model_dump()
