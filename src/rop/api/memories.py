"""Local API for explicitly user-controlled memory and preferences.

No conversation or clinical session content is imported automatically. Writes
require the configured local origin, strict schemas, and a user-initiated
request. This application currently has a single local-user security model;
entries are not tied to a conversation.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from rop.api.origin import enforce_local_origin
from rop.database import get_db
from rop.models.assistant_memory_entry import AssistantMemoryEntry
from rop.schemas.assistant_memory import (
    MemoryClearRequest,
    MemoryClearResponse,
    MemoryCreate,
    MemoryListResponse,
    MemoryRead,
    MemoryUpdate,
)

router = APIRouter(
    prefix="/api/assistant/memories",
    tags=["assistant-memory"],
)
logger = logging.getLogger(__name__)

CLEAR_ALL_PHRASE = "CLEAR ALL SAVED MEMORY"
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:password|passwd|passphrase|api[\s_-]*key|access[\s_-]*token|"
    r"refresh[\s_-]*token|client[\s_-]*secret|private[\s_-]*key)\b"
    r"\s*(?:is|:|=)\s*\S+",
    re.IGNORECASE,
)
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PATIENT_IDENTIFIER_RE = re.compile(
    r"\b(?:patient\s+(?:name|id|number|record|dob)|medical record number|mrn)"
    r"\s*(?:is|:|=|#)?\s*[A-Za-z0-9-]{2,}",
    re.IGNORECASE,
)


def _validate_personal_content(title: str, content: str) -> None:
    """Reject obvious credential material and explicit patient identifiers."""
    combined = f"{title}\n{content}"
    if (
        _SECRET_ASSIGNMENT_RE.search(combined)
        or _PRIVATE_KEY_RE.search(combined)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Credentials and secret values must not be saved in personal memory."
            ),
        )
    if _PATIENT_IDENTIFIER_RE.search(combined):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Patient identifiers and clinical record details must remain in "
                "the separate clinical-record workflow."
            ),
        )


def _set_private_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"


@router.get("", response_model=MemoryListResponse)
def list_memories(
    response: Response,
    q: str | None = Query(default=None, min_length=1, max_length=200),
    offset: int = Query(default=0, ge=0, le=100_000),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
) -> MemoryListResponse:
    """List saved entries, with optional literal text search and bounded pages."""
    _set_private_headers(response)
    statement = select(AssistantMemoryEntry)
    count_statement = select(func.count()).select_from(AssistantMemoryEntry)
    query = q.strip() if q is not None else None
    if query:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        predicate = or_(
            AssistantMemoryEntry.title.ilike(f"%{escaped}%", escape="\\"),
            AssistantMemoryEntry.content.ilike(f"%{escaped}%", escape="\\"),
        )
        statement = statement.where(predicate)
        count_statement = count_statement.where(predicate)
    total = int(db.scalar(count_statement) or 0)
    rows = db.scalars(
        statement.order_by(
            AssistantMemoryEntry.updated_at.desc(),
            AssistantMemoryEntry.id.asc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return MemoryListResponse(
        items=[MemoryRead.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
def create_memory(
    body: MemoryCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MemoryRead:
    """Save one entry only after an explicit, local user submission."""
    enforce_local_origin(request)
    _validate_personal_content(body.title, body.content)
    row = AssistantMemoryEntry(
        entry_type=body.entry_type,
        title=body.title,
        content=body.content,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except SQLAlchemyError:
        db.rollback()
        logger.warning("assistant memory create failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The memory could not be saved. No success is claimed.",
        ) from None
    _set_private_headers(response)
    return MemoryRead.model_validate(row)


@router.patch("/{entry_id}", response_model=MemoryRead)
def update_memory(
    entry_id: UUID,
    body: MemoryUpdate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MemoryRead:
    """Edit only explicitly supplied fields on one known entry."""
    enforce_local_origin(request)
    row = db.get(AssistantMemoryEntry, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="The memory entry does not exist.")
    fields = body.model_dump(exclude_unset=True)
    title = fields.get("title", row.title)
    content = fields.get("content", row.content)
    _validate_personal_content(title, content)
    try:
        for name, value in fields.items():
            setattr(row, name, value)
        db.commit()
        db.refresh(row)
    except SQLAlchemyError:
        db.rollback()
        logger.warning("assistant memory update failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The memory could not be updated. No success is claimed.",
        ) from None
    _set_private_headers(response)
    return MemoryRead.model_validate(row)


@router.post("/clear", response_model=MemoryClearResponse)
def clear_memories(
    body: MemoryClearRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MemoryClearResponse:
    """Permanently clear all entries after exact, explicit confirmation."""
    enforce_local_origin(request)
    if body.confirmation_phrase != CLEAR_ALL_PHRASE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Type {CLEAR_ALL_PHRASE!r} to clear saved memory.",
        )
    try:
        result = db.query(AssistantMemoryEntry).delete(synchronize_session=False)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("assistant memory clear failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Saved memory could not be cleared. Inspect the local state.",
        ) from None
    _set_private_headers(response)
    return MemoryClearResponse(deleted_count=int(result or 0))


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    entry_id: UUID,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> Response:
    """Permanently delete one entry."""
    enforce_local_origin(request)
    row = db.get(AssistantMemoryEntry, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="The memory entry does not exist.")
    try:
        db.delete(row)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.warning("assistant memory delete failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The memory could not be deleted. Inspect the local state.",
        ) from None
    _set_private_headers(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["CLEAR_ALL_PHRASE", "router"]
