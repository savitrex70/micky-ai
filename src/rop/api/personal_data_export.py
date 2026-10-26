"""Versioned, bounded export of user-visible personal assistant data.

This endpoint intentionally exports only saved conversations/messages and
notes/tasks/reminders. Confirmation records have their own existing export
surface. Clinical reasoning records, pending confirmations/clarifications,
retrieval-root paths, policy material, and internal identifiers not needed to
re-import these records are deliberately excluded. Import is not implemented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rop.database import get_db
from rop.models.assistant_conversation import AssistantConversation
from rop.models.assistant_item import AssistantItem
from rop.models.assistant_message import AssistantMessage
from rop.schemas.personal_data_export import (
    PersonalDataExportCounts,
    PersonalDataExportPage,
)

router = APIRouter(prefix="/api/assistant/personal-data", tags=["personal-data-export"])

DEFAULT_EXPORT_PAGE_SIZE = 250
MAX_EXPORT_PAGE_SIZE = 500


def _count(db: Session, model: type[Any]) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _conversation_record(row: AssistantConversation) -> dict[str, object]:
    return {
        "record_type": "conversation",
        "id": str(row.id),
        "title": row.title,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _message_record(row: AssistantMessage) -> dict[str, object]:
    return {
        "record_type": "message",
        "id": str(row.id),
        "conversation_id": str(row.conversation_id),
        "role": row.role,
        "content": row.content,
        "sequence": row.sequence,
        "created_at": row.created_at,
    }


def _workspace_item_record(row: AssistantItem) -> dict[str, object]:
    return {
        "record_type": "workspace_item",
        "id": str(row.id),
        "kind": row.kind,
        "title": row.title,
        "content": row.content,
        "due_at": row.due_at,
        "timezone": row.timezone,
        "completed": row.completed,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/export", response_model=PersonalDataExportPage)
def export_personal_data(
    response: Response,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_EXPORT_PAGE_SIZE, ge=1, le=MAX_EXPORT_PAGE_SIZE),
    db: Session = Depends(get_db),
) -> PersonalDataExportPage:
    """Return one deterministic page of user-visible personal data."""
    # Personal content must not be retained by a browser or intermediary cache.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    conversation_count = _count(db, AssistantConversation)
    message_count = _count(db, AssistantMessage)
    item_count = _count(db, AssistantItem)
    counts = PersonalDataExportCounts(
        conversations=conversation_count,
        messages=message_count,
        workspace_items=item_count,
    )
    total_records = conversation_count + message_count + item_count
    if offset > total_records:
        raise HTTPException(
            status_code=422,
            detail="offset exceeds the total number of export records",
        )
    records: list[dict[str, object]] = []
    records_remaining = limit
    offset_remaining = offset

    sections = (
        (
            conversation_count,
            select(AssistantConversation).order_by(
                AssistantConversation.created_at.asc(), AssistantConversation.id.asc()
            ),
            _conversation_record,
        ),
        (
            message_count,
            select(AssistantMessage).order_by(
                AssistantMessage.conversation_id.asc(),
                AssistantMessage.sequence.asc(),
                AssistantMessage.id.asc(),
            ),
            _message_record,
        ),
        (
            item_count,
            select(AssistantItem).order_by(
                AssistantItem.created_at.asc(), AssistantItem.id.asc()
            ),
            _workspace_item_record,
        ),
    )

    for section_count, statement, mapper in sections:
        if records_remaining <= 0:
            break
        section_offset = min(offset_remaining, section_count)
        offset_remaining -= section_offset
        available = section_count - section_offset
        if available <= 0:
            continue
        take = min(records_remaining, available)
        rows = db.scalars(statement.offset(section_offset).limit(take)).all()
        records.extend(mapper(row) for row in rows)
        records_remaining -= len(rows)

    next_offset = (
        offset + len(records) if offset + len(records) < total_records else None
    )
    return PersonalDataExportPage(
        generated_at=datetime.now(UTC),
        offset=offset,
        limit=limit,
        total_records=total_records,
        counts=counts,
        next_offset=next_offset,
        complete=next_offset is None,
        records=records,
    )


__all__ = [
    "DEFAULT_EXPORT_PAGE_SIZE",
    "MAX_EXPORT_PAGE_SIZE",
    "export_personal_data",
    "router",
]
