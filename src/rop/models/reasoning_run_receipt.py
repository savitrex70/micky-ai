from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from rop.database import Base


class ReasoningRunReceipt(Base):
    """Durable record binding one completed execution to its state.

    Task 127 correction: the canonical ``(session_id, fingerprint)``
    identity is only meaningful when a stored completed run proves the
    fingerprint belongs to a prior run. Each completed execution writes
    exactly one receipt -- fingerprinting the full state the run
    produced -- inside its own transaction, so idempotent reuse can
    establish, never merely trust, the prior run. History is preserved:
    receipts are never updated or deleted by later runs.
    """

    __tablename__ = "reasoning_run_receipts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
