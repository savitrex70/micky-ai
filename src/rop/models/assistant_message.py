"""Durable storage for one user-visible message in a conversation.

A message belongs to exactly one conversation. It carries the role and
content the user sees, plus a per-conversation integer sequence that
uniquely determines reading order. Nothing hidden is stored here: no
system instructions, no confirmation display codes or challenge
identifiers, no authorization material, no environment variables, and no
raw request headers. The ``role`` check constraint is deliberately narrow
(``user`` or ``assistant``) so that a hidden instruction role cannot be
smuggled into the domain simply to accommodate a future feature.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rop.database import Base

if TYPE_CHECKING:
    from rop.models.assistant_conversation import AssistantConversation

_ROLE_VALUES = "'user', 'assistant'"


class AssistantMessage(Base):
    """One user-visible message belonging to one conversation.

    ``sequence`` is an integer that orders messages within a conversation.
    It is unique per conversation (enforced by ``uq_assistant_messages_
    conversation_sequence``), so the same conversation can never contain
    two messages at the same position. The repository assigns the next
    integer when appending; concurrent appends that race for the same
    position fail on the unique constraint rather than silently producing
    an ambiguous order, and the caller is expected to retry.
    """

    __tablename__ = "assistant_messages"
    __table_args__ = (
        CheckConstraint(
            f"role IN ({_ROLE_VALUES})",
            name="ck_assistant_messages_role",
        ),
        CheckConstraint("sequence >= 0", name="ck_assistant_messages_sequence"),
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_assistant_messages_conversation_sequence",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    #: No standalone index on ``conversation_id``: the unique composite
    #: index created by ``uq_assistant_messages_conversation_sequence``
    #: already serves lookups and ordered retrieval by ``conversation_id``.
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Only ``user`` and ``assistant`` are supported; a hidden internal
    #: instruction role is not part of this domain.
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The message text as it is shown to the user.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: Position of this message within its conversation; unique per
    #: conversation. Zero-based; the first message is position 0.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["AssistantConversation"] = relationship(
        back_populates="messages"
    )
