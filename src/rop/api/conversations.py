"""HTTP API for durable assistant conversations and their messages.

This router exposes the Task 228 repository operations through a small,
explicit FastAPI surface. It is the HTTP layer only: it does not implement
any conversation-management UI, does not wire persistence into
``/api/assistant/requests``, and does not add a state-changing capability
or a production executor.

Design boundaries:

* All writes go through :class:`ConversationRepository`. Route handlers
  never contain SQL and never duplicate the repository's invariants.
* Transaction ownership lives at this boundary: a successful write commits
  its session; a failed write rolls back and returns a sanitized error.
  The repository deliberately does not commit.
* Every state-changing endpoint enforces the configured local origin
  (``require_local_origin``) before writing. Read-only endpoints do not
  add that machinery, matching the rest of the local API surface.
* Error bodies are fixed, sanitized strings. Submitted content, database
  exception text, SQL fragments, and connection details never appear in a
  response or a log line.
* The public append endpoint stores only ``user`` messages. A caller
  cannot forge an ``assistant`` message through this API and make invented
  output appear to have been produced by Micky AI. Internal code that
  persists genuine assistant replies continues to use the internal
  :class:`AssistantMessageCreate` schema.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rop.api.origin import require_local_origin
from rop.database import get_db
from rop.repositories.assistant_conversation import (
    DEFAULT_CONVERSATION_LIST_LIMIT,
    DEFAULT_MESSAGE_LIST_LIMIT,
    MAX_CONVERSATION_LIST_LIMIT,
    MAX_MESSAGE_LIST_LIMIT,
    ConversationNotFoundError,
    ConversationRepository,
)
from rop.schemas.assistant_conversation import (
    AssistantConversationCreate,
    AssistantConversationRead,
    AssistantConversationUpdate,
    AssistantMessageCreate,
    AssistantMessageRead,
    AssistantUserMessageCreate,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/assistant/conversations",
    tags=["assistant-conversations"],
)

_REPOSITORY = ConversationRepository()

# Fixed, sanitized error strings used across the router. Keeping them as
# constants makes it impossible for a handler to accidentally interpolate
# a value into a client-facing error.
_ERROR_WRITE_FAILED = "The operation could not be completed."
_ERROR_SEQUENCE_CONFLICT = (
    "The message could not be appended due to a concurrent update; "
    "reload the conversation and try again."
)

#: The unique constraint that arbitrates concurrent appends on
#: ``(conversation_id, sequence)``. Must match the name used by the
#: Task 228 migration and model.
_INTEGRITY_SEQUENCE_CONSTRAINT = "uq_assistant_messages_conversation_sequence"


def _classify_integrity_error(exc: IntegrityError) -> str:
    """Classify an ``IntegrityError`` into a handler-usable category.

    Returns one of ``"sequence_conflict"``, ``"missing_parent"``, or
    ``"unknown"``. Only the sequence-conflict case is treated as a
    concurrency-conflict retryable state; the parent-FK case is treated
    as a not-found (the conversation was deleted while the append was
    racing); anything else is a genuine persistence failure that must
    not be reported as a sequence conflict.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint = getattr(diag, "constraint_name", None) if diag else None
    if constraint == _INTEGRITY_SEQUENCE_CONSTRAINT:
        return "sequence_conflict"
    # PostgreSQL names foreign-key constraints ``<table>_<col>_fkey``. The
    # only FK on ``assistant_messages`` is on ``conversation_id``; a
    # violation therefore means the parent conversation vanished mid-append.
    if constraint and "conversation_id" in constraint and "fkey" in constraint.lower():
        return "missing_parent"
    return "unknown"


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="The conversation does not exist.",
    )


# ---------------------------------------------------------------------------
# List / create conversations
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[AssistantConversationRead],
)
def list_conversations(
    limit: int = Query(
        default=DEFAULT_CONVERSATION_LIST_LIMIT,
        ge=1,
        le=MAX_CONVERSATION_LIST_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[AssistantConversationRead]:
    """Return one page of conversations in deterministic order.

    Ordering is the repository's established order: ``updated_at``
    descending, then ``id`` descending. This means the most recently
    active conversation sorts first, and a new message appended to an
    older conversation moves it to the top.
    """
    return _REPOSITORY.list(db, offset=offset, limit=limit)


@router.post(
    "",
    response_model=AssistantConversationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_local_origin)],
    responses={
        403: {
            "description": (
                "The request did not come from the configured local origin, "
                "or did not use a JSON content type."
            ),
        },
        503: {
            "description": (
                "The conversation could not be created; the transaction was "
                "rolled back and no conversation was stored."
            ),
        },
    },
)
def create_conversation(
    body: AssistantConversationCreate,
    db: Session = Depends(get_db),
) -> AssistantConversationRead:
    """Create one new conversation.

    The id and both timestamps are server-assigned; the caller can only
    supply a title. Any other field is rejected by the schema before this
    handler runs.
    """
    try:
        result = _REPOSITORY.create(db, body)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("conversation create failed; rolled back")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ERROR_WRITE_FAILED,
        ) from None
    return result


# ---------------------------------------------------------------------------
# Single-conversation read / update / delete
# ---------------------------------------------------------------------------


@router.get(
    "/{conversation_id}",
    response_model=AssistantConversationRead,
    responses={
        404: {"description": "The conversation does not exist."},
    },
)
def get_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
) -> AssistantConversationRead:
    """Return one conversation, or 404 if it does not exist."""
    result = _REPOSITORY.get(db, conversation_id)
    if result is None:
        raise _not_found()
    return result


@router.patch(
    "/{conversation_id}",
    response_model=AssistantConversationRead,
    dependencies=[Depends(require_local_origin)],
    responses={
        403: {
            "description": (
                "The request did not come from the configured local origin, "
                "or did not use a JSON content type."
            ),
        },
        404: {"description": "The conversation does not exist."},
        503: {
            "description": (
                "The update could not be completed; the transaction was " "rolled back."
            ),
        },
    },
)
def rename_conversation(
    conversation_id: UUID,
    body: AssistantConversationUpdate,
    db: Session = Depends(get_db),
) -> AssistantConversationRead:
    """Change a conversation's title.

    Only the fields permitted by :class:`AssistantConversationUpdate` may
    be changed. IDs, timestamps, and message contents are not reachable
    through this schema.
    """
    try:
        result = _REPOSITORY.update(db, conversation_id, body)
        db.commit()
    except ConversationNotFoundError:
        db.rollback()
        raise _not_found() from None
    except Exception:
        db.rollback()
        logger.warning("conversation update failed; rolled back")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ERROR_WRITE_FAILED,
        ) from None
    return result


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_local_origin)],
    responses={
        403: {
            "description": (
                "The request did not come from the configured local origin, "
                "or did not use a JSON content type."
            ),
        },
        404: {"description": "The conversation does not exist."},
        503: {
            "description": (
                "The deletion could not be completed; the transaction was "
                "rolled back."
            ),
        },
    },
)
def delete_conversation(
    conversation_id: UUID,
    db: Session = Depends(get_db),
) -> None:
    """Delete one conversation and its owned messages.

    The cascade in Task 228's schema means only this conversation's
    messages are removed. Clinical reasoning, confirmation, and audit
    records are untouched.
    """
    try:
        deleted = _REPOSITORY.delete(db, conversation_id)
        if not deleted:
            db.rollback()
            raise _not_found()
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.warning("conversation delete failed; rolled back")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ERROR_WRITE_FAILED,
        ) from None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@router.get(
    "/{conversation_id}/messages",
    response_model=list[AssistantMessageRead],
    responses={
        404: {"description": "The conversation does not exist."},
    },
)
def list_messages(
    conversation_id: UUID,
    limit: int = Query(
        default=DEFAULT_MESSAGE_LIST_LIMIT,
        ge=1,
        le=MAX_MESSAGE_LIST_LIMIT,
    ),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[AssistantMessageRead]:
    """Return a conversation's messages in ascending sequence order.

    A caller referencing a conversation that does not exist receives 404
    rather than an empty list; the missing parent is surfaced explicitly.
    """
    conversation = _REPOSITORY.get(db, conversation_id)
    if conversation is None:
        raise _not_found()
    return _REPOSITORY.list_messages(db, conversation_id, offset=offset, limit=limit)


@router.post(
    "/{conversation_id}/messages",
    response_model=AssistantMessageRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_local_origin)],
    responses={
        403: {
            "description": (
                "The request did not come from the configured local origin, "
                "or did not use a JSON content type."
            ),
        },
        404: {"description": "The conversation does not exist."},
        409: {
            "description": (
                "A concurrent append raced for the same sequence position. "
                "The append was not applied; reload and retry."
            ),
        },
        503: {
            "description": (
                "The append could not be completed; the transaction was " "rolled back."
            ),
        },
    },
)
def append_user_message(
    conversation_id: UUID,
    body: AssistantUserMessageCreate,
    db: Session = Depends(get_db),
) -> AssistantMessageRead:
    """Append one user-authored message to a conversation.

    The stored role is always ``user``; the caller cannot supply a role
    field. A body that includes ``"role": "assistant"`` fails schema
    validation (HTTP 422) and writes nothing.

    If two appends race for the same sequence position, the database's
    unique constraint raises and this handler returns 409. The append is
    not retried automatically: a silent retry could duplicate a visible
    message, so the caller must reload and re-submit deliberately.
    """
    internal = AssistantMessageCreate(role="user", content=body.content)
    try:
        result = _REPOSITORY.append_message(db, conversation_id, internal)
        db.commit()
    except ConversationNotFoundError:
        db.rollback()
        raise _not_found() from None
    except IntegrityError as exc:
        db.rollback()
        kind = _classify_integrity_error(exc)
        if kind == "sequence_conflict":
            logger.info("conversation message append hit a sequence conflict")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_ERROR_SEQUENCE_CONFLICT,
            ) from None
        if kind == "missing_parent":
            logger.info("conversation message append raced a parent deletion")
            raise _not_found() from None
        logger.warning(
            "conversation message append hit an unclassified integrity error"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ERROR_WRITE_FAILED,
        ) from None
    except Exception:
        db.rollback()
        logger.warning("conversation message append failed; rolled back")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ERROR_WRITE_FAILED,
        ) from None
    return result


__all__ = ["router"]
