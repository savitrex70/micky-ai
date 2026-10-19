"""Persistence for durable assistant conversations and their messages.

Conversations are independent of the clinical reasoning tables. They
contain only what the user sees in the assistant interface and are never
joined to or associated with a reasoning session, hypothesis, evidence,
provenance, certification, or audit record.

Transaction ownership follows the rest of ROP: repository methods stage
work, flush so constraints are checked, and never commit. A caller that
wants the work persisted must commit its own session. This makes it
possible to compose a conversation mutation with other work in one
atomic unit.

Deletion ownership: deleting a conversation deletes its owned messages
through ``ON DELETE CASCADE`` at the database level plus the ORM
``cascade="all, delete-orphan"`` relationship. It never touches another
conversation's messages and never touches clinical data.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rop.models.assistant_conversation import AssistantConversation
from rop.models.assistant_message import AssistantMessage
from rop.schemas.assistant_conversation import (
    AssistantConversationCreate,
    AssistantConversationRead,
    AssistantConversationUpdate,
    AssistantMessageCreate,
    AssistantMessageRead,
)

DEFAULT_CONVERSATION_LIST_LIMIT = 100
MAX_CONVERSATION_LIST_LIMIT = 500
DEFAULT_MESSAGE_LIST_LIMIT = 200
MAX_MESSAGE_LIST_LIMIT = 500


class ConversationNotFoundError(LookupError):
    """Raised when a caller references a conversation that does not exist."""


class ConversationRepository:
    """Database operations for assistant conversations and messages."""

    def create(
        self,
        db: Session,
        data: AssistantConversationCreate,
    ) -> AssistantConversationRead:
        """Stage one conversation and return its read shape."""
        conversation = AssistantConversation(title=data.title)
        db.add(conversation)
        db.flush()
        db.refresh(conversation)
        return AssistantConversationRead.model_validate(conversation)

    def get(
        self, db: Session, conversation_id: UUID
    ) -> AssistantConversationRead | None:
        """Return one conversation, or ``None`` if it does not exist."""
        record = db.get(AssistantConversation, conversation_id)
        if record is None:
            return None
        return AssistantConversationRead.model_validate(record)

    def list(
        self,
        db: Session,
        *,
        offset: int = 0,
        limit: int = DEFAULT_CONVERSATION_LIST_LIMIT,
    ) -> list[AssistantConversationRead]:
        """Return conversations in deterministic order, paginated.

        Ordering is by ``updated_at`` desc then ``id`` desc so the most
        recently active conversation sorts first, with a stable tie-break.
        ``limit`` must be positive and no greater than
        ``MAX_CONVERSATION_LIST_LIMIT``; ``offset`` must be non-negative.
        Both bounds are enforced here, not by the caller, so an
        out-of-range value cannot quietly reach the database.
        """
        if limit <= 0 or limit > MAX_CONVERSATION_LIST_LIMIT:
            raise ValueError("invalid conversation list limit")
        if offset < 0:
            raise ValueError("invalid conversation list offset")
        statement = (
            select(AssistantConversation)
            .order_by(
                AssistantConversation.updated_at.desc(),
                AssistantConversation.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return [
            AssistantConversationRead.model_validate(r)
            for r in db.scalars(statement).all()
        ]

    def update(
        self,
        db: Session,
        conversation_id: UUID,
        data: AssistantConversationUpdate,
    ) -> AssistantConversationRead:
        """Change a conversation's supported metadata.

        Only the title is editable. A missing conversation raises
        ``ConversationNotFoundError``; the caller can map that to a
        not-found response without having to distinguish an empty result
        from an un-flushed one.
        """
        record = db.get(AssistantConversation, conversation_id)
        if record is None:
            raise ConversationNotFoundError(
                f"conversation {conversation_id} does not exist"
            )
        record.title = data.title
        db.flush()
        db.refresh(record)
        return AssistantConversationRead.model_validate(record)

    def append_message(
        self,
        db: Session,
        conversation_id: UUID,
        data: AssistantMessageCreate,
    ) -> AssistantMessageRead:
        """Append one message to the end of a conversation.

        The next sequence is computed from the current maximum within the
        same conversation. If two appends race for the same position the
        database's ``uq_assistant_messages_conversation_sequence`` constraint
        raises; the caller is expected to retry. A missing conversation
        raises ``ConversationNotFoundError`` rather than silently
        persisting an orphaned message.
        """
        conversation = db.get(AssistantConversation, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(
                f"conversation {conversation_id} does not exist"
            )
        current_max = db.scalar(
            select(func.max(AssistantMessage.sequence)).where(
                AssistantMessage.conversation_id == conversation_id
            )
        )
        next_sequence = 0 if current_max is None else current_max + 1
        message = AssistantMessage(
            conversation_id=conversation_id,
            role=data.role,
            content=data.content,
            sequence=next_sequence,
        )
        db.add(message)
        # Touch the parent so its updated_at reflects the new activity.
        conversation.title = conversation.title
        db.flush()
        db.refresh(message)
        return AssistantMessageRead.model_validate(message)

    def list_messages(
        self,
        db: Session,
        conversation_id: UUID,
        *,
        offset: int = 0,
        limit: int = DEFAULT_MESSAGE_LIST_LIMIT,
    ) -> list[AssistantMessageRead]:
        """Return a conversation's messages in deterministic order."""
        if limit <= 0 or limit > MAX_MESSAGE_LIST_LIMIT:
            raise ValueError("invalid message list limit")
        if offset < 0:
            raise ValueError("invalid message list offset")
        # A caller asking for messages of a missing conversation gets an
        # empty list rather than a silently invented placeholder; the
        # caller decides whether a missing conversation should raise.
        statement = (
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conversation_id)
            .order_by(AssistantMessage.sequence.asc())
            .offset(offset)
            .limit(limit)
        )
        return [
            AssistantMessageRead.model_validate(r) for r in db.scalars(statement).all()
        ]

    def delete(self, db: Session, conversation_id: UUID) -> bool:
        """Delete one conversation and its messages.

        Returns ``True`` if the conversation existed and was staged for
        deletion; ``False`` if no conversation with that id was present.
        The caller commits (or rolls back) the enclosing transaction.
        """
        record = db.get(AssistantConversation, conversation_id)
        if record is None:
            return False
        db.delete(record)
        db.flush()
        return True


__all__ = [
    "DEFAULT_CONVERSATION_LIST_LIMIT",
    "DEFAULT_MESSAGE_LIST_LIMIT",
    "MAX_CONVERSATION_LIST_LIMIT",
    "MAX_MESSAGE_LIST_LIMIT",
    "ConversationNotFoundError",
    "ConversationRepository",
]
