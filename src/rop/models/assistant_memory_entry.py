"""Explicitly user-approved personal memories and preferences."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from rop.database import Base


class AssistantMemoryEntry(Base):
    """One locally stored memory or preference approved by the user."""

    __tablename__ = "assistant_memory_entries"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('memory', 'preference')",
            name="ck_assistant_memory_entries_type",
        ),
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_assistant_memory_entries_title",
        ),
        CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_assistant_memory_entries_content",
        ),
        Index(
            "ix_assistant_memory_entries_updated_at",
            "updated_at",
            "id",
        ),
        Index(
            "uq_assistant_memory_entries_idempotency_key",
            "idempotency_key",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    entry_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="memory", server_default="memory"
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
