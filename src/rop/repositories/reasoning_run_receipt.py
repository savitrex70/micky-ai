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
        self, db: Session, session_id: UUID, state_fingerprint: str
    ) -> ReasoningRunReceipt:
        """Stage a COMPLETED receipt without committing.

        ``state_fingerprint`` is the fingerprint of the full state the
        completed run produced. The caller owns the transaction boundary.
        """
        receipt = ReasoningRunReceipt(
            session_id=session_id,
            state_fingerprint=state_fingerprint,
            outcome="COMPLETED",
        )
        db.add(receipt)
        db.flush()
        db.refresh(receipt)
        return receipt

    def find_completed(
        self, db: Session, session_id: UUID, state_fingerprint: str
    ) -> ReasoningRunReceipt | None:
        """Return the latest COMPLETED receipt for an exact identity."""
        statement = (
            select(ReasoningRunReceipt)
            .where(
                ReasoningRunReceipt.session_id == session_id,
                ReasoningRunReceipt.state_fingerprint == state_fingerprint,
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
