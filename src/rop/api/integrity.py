"""Classification of SQLAlchemy ``IntegrityError`` by exact constraint name.

Two endpoints — the public message-append route and the assistant request
endpoint when a conversation is supplied — can both hit database
constraint violations on ``assistant_messages``. Each needs the same
distinction: an expected unique-sequence conflict is a retryable 409,
a foreign-key violation on ``conversation_id`` is a 404 (the parent
conversation was deleted mid-append), and anything else is a generic
persistence failure.

The two constraint names below come from the Task 228 migration
(``20261019_0018_create_assistant_conversations.py``) and are matched
exactly. Substring matching would misclassify near-miss constraint names.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

SEQUENCE_CONSTRAINT = "uq_assistant_messages_conversation_sequence"
"""Unique ``(conversation_id, sequence)`` — concurrent-append conflict."""

CONVERSATION_FK_CONSTRAINT = "assistant_messages_conversation_id_fkey"
"""FK on ``conversation_id`` — parent conversation vanished mid-append."""


def classify_integrity_error(exc: IntegrityError) -> str:
    """Return one of ``"sequence_conflict"``, ``"missing_parent"``, ``"unknown"``.

    Only exact constraint names from the Task 228 migration are trusted.
    Missing driver metadata and any other constraint name are classified as
    ``"unknown"`` so a caller returns a sanitized generic failure rather
    than a misleading 409 or 404.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint = getattr(diag, "constraint_name", None) if diag else None
    if constraint is None:
        return "unknown"
    if constraint == SEQUENCE_CONSTRAINT:
        return "sequence_conflict"
    if constraint == CONVERSATION_FK_CONSTRAINT:
        return "missing_parent"
    return "unknown"


__all__ = [
    "CONVERSATION_FK_CONSTRAINT",
    "SEQUENCE_CONSTRAINT",
    "classify_integrity_error",
]
