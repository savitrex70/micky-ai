"""Persistence boundary for notes, tasks, reminders, roots, and receipts."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models.assistant_item import AssistantItem
from rop.models.assistant_operation_receipt import AssistantOperationReceipt
from rop.models.assistant_retrieval_root import AssistantRetrievalRoot


class AssistantWorkspaceRepository:
    """Repository methods only; transaction ownership stays in callers."""

    def list_items(
        self,
        session: Session,
        *,
        kind: str | None = None,
        include_completed: bool = True,
        limit: int = 200,
    ) -> list[AssistantItem]:
        statement = select(AssistantItem).order_by(
            AssistantItem.updated_at.desc(), AssistantItem.id.desc()
        )
        if kind is not None:
            statement = statement.where(AssistantItem.kind == kind)
        if not include_completed:
            statement = statement.where(AssistantItem.completed.is_(False))
        return list(session.scalars(statement.limit(limit)).all())

    def get_item(self, session: Session, item_id: UUID) -> AssistantItem | None:
        return session.get(AssistantItem, item_id)

    def list_roots(self, session: Session) -> list[AssistantRetrievalRoot]:
        statement = select(AssistantRetrievalRoot).order_by(
            AssistantRetrievalRoot.created_at.asc(), AssistantRetrievalRoot.id.asc()
        )
        return list(session.scalars(statement).all())

    def get_root(
        self, session: Session, root_id: UUID
    ) -> AssistantRetrievalRoot | None:
        return session.get(AssistantRetrievalRoot, root_id)

    def get_root_by_path(
        self, session: Session, path: str
    ) -> AssistantRetrievalRoot | None:
        return session.scalar(
            select(AssistantRetrievalRoot).where(AssistantRetrievalRoot.path == path)
        )

    def get_receipt(
        self, session: Session, idempotency_key: UUID
    ) -> AssistantOperationReceipt | None:
        return session.scalar(
            select(AssistantOperationReceipt).where(
                AssistantOperationReceipt.idempotency_key == idempotency_key
            )
        )


__all__ = ["AssistantWorkspaceRepository"]
