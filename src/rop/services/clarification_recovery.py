"""Bounded cleanup of short-lived assistant clarification state.

This startup sweep removes expired or already-consumed clarification rows,
including their temporary user message and partial-operation values. It never
executes an operation. A database failure is non-fatal to startup and is
reported as an unsuccessful sweep so a later startup can retry.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session

from rop import database as database_module
from rop.repositories.assistant_pending_clarification import (
    MAX_EXPIRY_CLEANUP,
    AssistantPendingClarificationRepository,
)

CLARIFICATION_RECOVERY_BATCH_LIMIT = MAX_EXPIRY_CLEANUP
"""Maximum clarification rows removed in one startup transaction."""


def recover_pending_clarification_state(
    *,
    session_factory: Callable[[], Session] | None = None,
    repository: AssistantPendingClarificationRepository | None = None,
    batch_limit: int = CLARIFICATION_RECOVERY_BATCH_LIMIT,
    now: datetime | None = None,
) -> bool:
    """Drain expired clarification state in separate bounded transactions.

    Each transaction removes at most 100 records. A full batch triggers a
    follow-up batch in the same sweep, so a backlog does not depend on later
    traffic or another restart. A failed batch is rolled back and returns
    False; earlier committed batches remain safe to retry. Return True only
    when the last batch confirms fewer than the limit remain to be removed.
    """
    if batch_limit <= 0:
        return False

    limit = min(batch_limit, CLARIFICATION_RECOVERY_BATCH_LIMIT)
    factory = session_factory or database_module.SessionLocal
    store = repository or AssistantPendingClarificationRepository()

    while True:
        db: Session | None = None
        try:
            db = factory()
            deleted = store.delete_expired(db, now=now, limit=limit)
            db.commit()
            if deleted < limit:
                return True
        except Exception:
            if db is not None:
                try:
                    db.rollback()
                except Exception:
                    pass
            return False
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass


__all__ = [
    "CLARIFICATION_RECOVERY_BATCH_LIMIT",
    "recover_pending_clarification_state",
]
