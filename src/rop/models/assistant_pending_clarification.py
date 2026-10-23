"""Short-lived server-owned state for assistant clarification turns.

The record belongs only to an assistant conversation. It has no relationship
to clinical reasoning sessions or other clinical records.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from rop.database import Base


class AssistantPendingClarification(Base):
    """One pending clarification tied to one saved assistant conversation."""

    __tablename__ = "assistant_pending_clarifications"
    __table_args__ = (
        UniqueConstraint(
            "clarification_id",
            name="uq_assistant_pending_clarifications_public_id",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'CONSUMED')",
            name="ck_assistant_pending_clarifications_status",
        ),
        CheckConstraint(
            "(status = 'PENDING') = (consumed_at IS NULL)",
            name="ck_assistant_pending_clarifications_consumed_at",
        ),
        Index(
            "ix_assistant_pending_clarifications_conversation_status",
            "conversation_id",
            "status",
        ),
        Index(
            "ix_assistant_pending_clarifications_status_expires_at",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    clarification_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    capability_identifier: Mapped[str] = mapped_column(String(64), nullable=False)
    original_message: Mapped[str] = mapped_column(Text, nullable=False)
    partial_operation: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    missing_fields: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    question: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING"
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
