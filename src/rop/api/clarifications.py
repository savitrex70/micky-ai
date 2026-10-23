"""Restore and abandon pending assistant clarification prompts."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from rop import database as database_module
from rop.api.origin import enforce_local_origin
from rop.repositories.assistant_pending_clarification import (
    AssistantPendingClarificationRepository,
)
from rop.schemas.assistant import ClarificationPrompt

router = APIRouter(
    prefix="/api/assistant/clarifications",
    tags=["assistant-clarifications"],
)
_REPOSITORY = AssistantPendingClarificationRepository()


@router.get("", response_model=list[ClarificationPrompt])
def list_clarifications(
    conversation_id: UUID = Query(...),
) -> list[ClarificationPrompt]:
    """Restore only the sanitized active prompt for the selected conversation."""
    session = database_module.SessionLocal()
    try:
        now = datetime.now(UTC)
        _REPOSITORY.delete_expired(session, now=now)
        rows = _REPOSITORY.list_active_for_conversation(
            session, conversation_id, now=now
        )
        session.commit()
        return [
            ClarificationPrompt(
                clarification_id=row.clarification_id,
                capability_identifier=row.capability_identifier,
                question=row.question,
                missing_fields=list(row.missing_fields),
            )
            for row in rows
        ]
    except Exception:
        session.rollback()
        return []
    finally:
        session.close()


@router.delete(
    "/{clarification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def abandon_clarification(
    clarification_id: UUID,
    http_request: Request,
    conversation_id: UUID = Query(...),
) -> Response:
    """Abandon a prompt without revealing whether a guessed ID exists."""
    enforce_local_origin(http_request)
    session = database_module.SessionLocal()
    try:
        row = _REPOSITORY.get_pending(session, clarification_id, for_update=True)
        if row is not None and row.conversation_id == conversation_id:
            _REPOSITORY.consume_and_clear(session, row)
        _REPOSITORY.delete_expired(session)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception:
        session.rollback()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    finally:
        session.close()


__all__ = ["router"]
