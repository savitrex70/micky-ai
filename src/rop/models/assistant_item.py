"""Durable user-controlled notes, tasks, and reminders.

These personal workspace items are intentionally separate from clinical
reasoning records. The model stores no clinical session identifier, and no
clinical table is modified when an item is created or changed.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from rop.database import Base


class AssistantItem(Base):
    """One user-owned note, task, or reminder."""

    __tablename__ = "assistant_items"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('note', 'task', 'reminder')",
            name="ck_assistant_items_kind",
        ),
        CheckConstraint("length(trim(title)) > 0", name="ck_assistant_items_title"),
        CheckConstraint(
            "(kind = 'reminder' AND due_at IS NOT NULL AND timezone IS NOT NULL) "
            "OR (kind <> 'reminder' AND due_at IS NULL AND timezone IS NULL)",
            name="ck_assistant_items_reminder_time",
        ),
        Index("ix_assistant_items_kind_updated_at", "kind", "updated_at"),
        Index("ix_assistant_items_reminder_due", "kind", "completed", "due_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(128), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
