"""Idempotency reservations and receipts for workspace mutations.

A reservation binds an idempotency key to one operation before a
confirmation challenge is issued. The local mutation and SUCCEEDED receipt
commit atomically. No user-authored content is stored in this receipt.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from rop.database import Base


class AssistantOperationReceipt(Base):
    """One canonical, once-only workspace operation."""

    __tablename__ = "assistant_operation_receipts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_assistant_operation_receipts_key"),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED')",
            name="ck_assistant_operation_receipts_status",
        ),
        Index("ix_assistant_operation_receipts_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    idempotency_key: Mapped[UUID] = mapped_column(nullable=False)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    result_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="workspace-change-completed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
