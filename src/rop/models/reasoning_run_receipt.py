from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from rop.database import Base


class ReasoningRunReceipt(Base):
    """Durable record binding one completed execution to its inputs.

    Task 127 correction: the canonical ``(session_id,
    input_fingerprint)`` identity is only meaningful when a stored
    completed run proves the fingerprint belongs to a prior run. Each
    completed execution writes exactly one receipt -- the exact input
    fingerprint it ran against plus the exogenous input projection that
    establishes continuity -- inside its own transaction, so idempotent
    reuse can establish, never merely trust, the prior run. History is
    preserved: receipts are never updated or deleted by later runs.
    """

    __tablename__ = "reasoning_run_receipts"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "input_fingerprint",
            name="uq_reasoning_run_receipts_session_fingerprint",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    exogenous_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    #: The canonical Task 124 input snapshot the input_fingerprint was
    #: computed over (Task 125), persisted so provenance binding can be
    #: hash-verified from persisted evidence alone. NULL only for
    #: receipts written before this column existed; their binding is
    #: reported as explicitly not persisted, never fabricated.
    input_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
