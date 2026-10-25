"""Persistence boundary for notes, tasks, reminders, roots, and receipts."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rop.models.assistant_item import AssistantItem
from rop.models.assistant_operation_receipt import AssistantOperationReceipt
from rop.models.assistant_retrieval_root import AssistantRetrievalRoot
from rop.schemas.retrieval import MAX_RETRIEVAL_ROOTS_PER_REQUEST


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

    def list_roots(
        self,
        session: Session,
        *,
        limit: int = MAX_RETRIEVAL_ROOTS_PER_REQUEST,
    ) -> list[AssistantRetrievalRoot]:
        """Return at most ``limit`` roots, oldest first, bounded in SQL.

        The cap is applied by the database (``LIMIT``) so a legacy database with
        more roots than the limit never materializes the surplus rows. The order
        is stable (creation time, then id), so the same roots are selected on
        every request.
        """
        if limit < 0:
            raise ValueError("root limit must not be negative")
        statement = (
            select(AssistantRetrievalRoot)
            .order_by(
                AssistantRetrievalRoot.created_at.asc(),
                AssistantRetrievalRoot.id.asc(),
            )
            .limit(limit)
        )
        return list(session.scalars(statement).all())

    def count_roots(self, session: Session) -> int:
        """Count authorized roots in SQL without loading any row."""
        return int(
            session.scalar(select(func.count()).select_from(AssistantRetrievalRoot))
            or 0
        )

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
        self,
        session: Session,
        idempotency_key: UUID,
        *,
        for_update: bool = False,
    ) -> AssistantOperationReceipt | None:
        statement = select(AssistantOperationReceipt).where(
            AssistantOperationReceipt.idempotency_key == idempotency_key
        )
        if for_update:
            statement = statement.with_for_update()
        return session.scalar(statement)


__all__ = ["AssistantWorkspaceRepository"]
