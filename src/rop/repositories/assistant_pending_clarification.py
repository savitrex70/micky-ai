"""Repository boundary for short-lived assistant clarification state."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from rop.models.assistant_conversation import AssistantConversation
from rop.models.assistant_pending_clarification import AssistantPendingClarification

CLARIFICATION_LIFETIME = timedelta(minutes=10)
MAX_CLARIFICATIONS_PER_CONVERSATION = 1
MAX_EXPIRY_CLEANUP = 100


class AssistantPendingClarificationRepository:
    """Stage changes only; callers own transaction commits."""

    def create(
        self,
        session: Session,
        *,
        conversation_id: UUID,
        capability_identifier: str,
        original_message: str,
        partial_operation: dict,
        missing_fields: list[str],
        question: str,
        now: datetime | None = None,
    ) -> AssistantPendingClarification:
        current = now or datetime.now(UTC)
        # Lock the parent even when no pending row exists yet. This serializes
        # concurrent first-time clarifications for the same conversation.
        parent_id = session.scalar(
            select(AssistantConversation.id)
            .where(AssistantConversation.id == conversation_id)
            .with_for_update()
        )
        if parent_id is None:
            raise LookupError("assistant conversation does not exist")
        existing = self.get_active_for_conversation(
            session, conversation_id, now=current, for_update=True
        )
        if existing is not None:
            self.consume_and_clear(session, existing, now=current)
        row = AssistantPendingClarification(
            clarification_id=uuid4(),
            conversation_id=conversation_id,
            capability_identifier=capability_identifier,
            original_message=original_message[:2000],
            partial_operation=partial_operation,
            missing_fields=list(missing_fields),
            question=question[:512],
            expires_at=current + CLARIFICATION_LIFETIME,
            status="PENDING",
        )
        session.add(row)
        session.flush()
        return row

    def get_pending(
        self,
        session: Session,
        clarification_id: UUID,
        *,
        for_update: bool = False,
    ) -> AssistantPendingClarification | None:
        statement = select(AssistantPendingClarification).where(
            AssistantPendingClarification.clarification_id == clarification_id,
            AssistantPendingClarification.status == "PENDING",
        )
        if for_update:
            statement = statement.with_for_update()
        return session.scalar(statement)

    def get_active_for_conversation(
        self,
        session: Session,
        conversation_id: UUID,
        *,
        now: datetime | None = None,
        for_update: bool = False,
    ) -> AssistantPendingClarification | None:
        current = now or datetime.now(UTC)
        statement = (
            select(AssistantPendingClarification)
            .where(
                AssistantPendingClarification.conversation_id == conversation_id,
                AssistantPendingClarification.status == "PENDING",
                AssistantPendingClarification.expires_at > current,
            )
            .order_by(AssistantPendingClarification.created_at.desc())
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        return session.scalar(statement)

    def list_active_for_conversation(
        self,
        session: Session,
        conversation_id: UUID,
        *,
        now: datetime | None = None,
    ) -> list[AssistantPendingClarification]:
        current = now or datetime.now(UTC)
        statement = (
            select(AssistantPendingClarification)
            .where(
                AssistantPendingClarification.conversation_id == conversation_id,
                AssistantPendingClarification.status == "PENDING",
                AssistantPendingClarification.expires_at > current,
            )
            .order_by(AssistantPendingClarification.created_at.desc())
            .limit(MAX_CLARIFICATIONS_PER_CONVERSATION)
        )
        return list(session.scalars(statement).all())

    def consume_and_clear(
        self,
        session: Session,
        row: AssistantPendingClarification,
        *,
        now: datetime | None = None,
    ) -> None:
        """Clear user material and atomically make replay impossible."""
        row.status = "CONSUMED"
        row.consumed_at = now or datetime.now(UTC)
        row.original_message = ""
        row.partial_operation = {}
        row.missing_fields = []
        row.question = ""
        session.flush()

    def delete_expired(
        self,
        session: Session,
        *,
        now: datetime | None = None,
        limit: int = MAX_EXPIRY_CLEANUP,
    ) -> int:
        """Delete at most limit expired or already-redacted rows."""
        current = now or datetime.now(UTC)
        ids = (
            select(AssistantPendingClarification.id)
            .where(
                or_(
                    AssistantPendingClarification.status == "CONSUMED",
                    (
                        (AssistantPendingClarification.status == "PENDING")
                        & (AssistantPendingClarification.expires_at <= current)
                    ),
                )
            )
            .order_by(AssistantPendingClarification.expires_at.asc())
            .limit(limit)
        )
        result = session.execute(
            delete(AssistantPendingClarification).where(
                AssistantPendingClarification.id.in_(ids)
            )
        )
        return int(result.rowcount or 0)


__all__ = [
    "AssistantPendingClarificationRepository",
    "CLARIFICATION_LIFETIME",
    "MAX_CLARIFICATIONS_PER_CONVERSATION",
    "MAX_EXPIRY_CLEANUP",
]
