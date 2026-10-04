from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models import ReasoningRunReceipt


class ReasoningRunReceiptRepository:
    """Database operations for reasoning-run receipts.

    Receipts are append-only history: they are written once per
    completed execution inside that execution's own transaction and
    never updated or deleted by later runs.
    """

    def record_completed(
        self,
        db: Session,
        session_id: UUID,
        input_fingerprint: str,
        exogenous_snapshot: dict[str, Any],
        input_snapshot: dict[str, Any] | None = None,
    ) -> ReasoningRunReceipt:
        """Stage a COMPLETED receipt without committing.

        The caller owns the transaction boundary. ``input_snapshot`` is
        the canonical Task 124 snapshot the fingerprint was computed
        over, persisted so Task 125 provenance binding can be
        hash-verified from persisted evidence (Task 139).
        """
        receipt = ReasoningRunReceipt(
            session_id=session_id,
            input_fingerprint=input_fingerprint,
            exogenous_snapshot=exogenous_snapshot,
            input_snapshot=input_snapshot,
            outcome="COMPLETED",
        )
        db.add(receipt)
        db.flush()
        db.refresh(receipt)
        return receipt

    def find_completed(
        self, db: Session, session_id: UUID, input_fingerprint: str
    ) -> ReasoningRunReceipt | None:
        """Return the latest COMPLETED receipt for an exact identity."""
        statement = (
            select(ReasoningRunReceipt)
            .where(
                ReasoningRunReceipt.session_id == session_id,
                ReasoningRunReceipt.input_fingerprint == input_fingerprint,
                ReasoningRunReceipt.outcome == "COMPLETED",
            )
            .order_by(ReasoningRunReceipt.created_at.desc())
        )
        return db.scalars(statement).first()

    def list_completed_by_session(
        self, db: Session, session_id: UUID
    ) -> list[ReasoningRunReceipt]:
        """Return persisted COMPLETED receipts for one exact session.

        Ordering is deterministic and stable across repeated reads: by
        creation time and then by receipt id so the API is not sensitive
        to database row ordering or incidental insertion behavior.
        """
        statement = (
            select(ReasoningRunReceipt)
            .where(
                ReasoningRunReceipt.session_id == session_id,
                ReasoningRunReceipt.outcome == "COMPLETED",
            )
            .order_by(
                ReasoningRunReceipt.created_at.asc(),
                ReasoningRunReceipt.id.asc(),
            )
        )
        return list(db.scalars(statement).all())

    def count_by_session(self, db: Session, session_id: UUID) -> int:
        statement = select(ReasoningRunReceipt).where(
            ReasoningRunReceipt.session_id == session_id
        )
        return len(list(db.scalars(statement).all()))
