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
    ) -> ReasoningRunReceipt:
        """Stage a COMPLETED receipt without committing.

        The caller owns the transaction boundary.
        """
        receipt = ReasoningRunReceipt(
            session_id=session_id,
            input_fingerprint=input_fingerprint,
            exogenous_snapshot=exogenous_snapshot,
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

    def count_by_session(self, db: Session, session_id: UUID) -> int:
        statement = select(ReasoningRunReceipt).where(
            ReasoningRunReceipt.session_id == session_id
        )
        return len(list(db.scalars(statement).all()))
