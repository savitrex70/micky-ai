"""Explicitly authorized local folders for offline retrieval."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from rop.database import Base


class AssistantRetrievalRoot(Base):
    """A folder the user has explicitly authorized for retrieval."""

    __tablename__ = "assistant_retrieval_roots"
    __table_args__ = (
        UniqueConstraint("path", name="uq_assistant_retrieval_roots_path"),
        Index("ix_assistant_retrieval_roots_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
