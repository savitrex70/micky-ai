"""Task 137: canonical read-only receipt inspection service."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models import ReasoningRunReceipt


class ReasoningRunReceiptService:
    """Read-only inspection service for deterministic reasoning-run receipts.

    Pure inspection: no writes, no mutations, no execution.
    """

    @staticmethod
    def get_by_id(db: Session, receipt_id: UUID) -> ReasoningRunReceipt | None:
        """Get a single receipt by its primary key."""
        return db.get(ReasoningRunReceipt, receipt_id)

    @staticmethod
    def find_by_session_and_fingerprint(
        db: Session, session_id: UUID, input_fingerprint: str
    ) -> ReasoningRunReceipt | None:
        """Find a receipt by session and canonical input fingerprint."""
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

    @staticmethod
    def list_by_session(
        db: Session, session_id: UUID, *, offset: int = 0, limit: int = 100
    ) -> list[ReasoningRunReceipt]:
        """List receipts for a session in deterministic order."""
        statement = (
            select(ReasoningRunReceipt)
            .where(ReasoningRunReceipt.session_id == session_id)
            .order_by(
                ReasoningRunReceipt.created_at.asc(), ReasoningRunReceipt.id.asc()
            )
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    @staticmethod
    def count_by_session(db: Session, session_id: UUID) -> int:
        """Count receipts for a session."""
        from sqlalchemy import func

        statement = select(func.count()).where(
            ReasoningRunReceipt.session_id == session_id
        )
        return db.scalar(statement) or 0
