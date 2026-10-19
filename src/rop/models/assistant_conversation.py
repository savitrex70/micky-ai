"""Durable storage for one user-visible assistant conversation.

A conversation is a container for an ordered sequence of user-visible
messages. It is deliberately independent of the clinical reasoning
tables: there is no foreign key to ``reasoning_sessions`` or to any
clinical evidence, provenance, certification, or audit record, and no
conversation content is ever stored in those tables.

Only the fields a later feature layer actually needs are present. There
is no user profile, no speculative metadata, and no clinical relationship.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rop.database import Base

if TYPE_CHECKING:
    from rop.models.assistant_message import AssistantMessage


class AssistantConversation(Base):
    """One stored assistant conversation.

    ``updated_at`` is bumped automatically whenever the row is modified
    (for example, when its title changes or a message is appended through
    the repository), so the listing order of a conversation reflects the
    last activity on it.
    """

    __tablename__ = "assistant_conversations"
    __table_args__ = (
        Index("ix_assistant_conversations_created_at", "created_at"),
        Index("ix_assistant_conversations_updated_at", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    #: Human-editable label. Not used for routing or identity; the primary
    #: key is the only identifier the rest of the system needs.
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    messages: Mapped[list["AssistantMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AssistantMessage.sequence",
    )
