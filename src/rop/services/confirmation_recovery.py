"""Bounded, non-fatal startup recovery for assistant confirmations.

Recovery only repairs metadata: consumed records with no established outcome
are marked UNKNOWN_AFTER_CONSUME, and overdue pending records become EXPIRED.
It never executes or retries an operation. A database outage must not prevent
the local assistant from starting; a failed recovery is retried on a later
startup and never reported as success.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from rop import database as database_module
from rop.repositories.assistant_confirmation import AssistantConfirmationRepository

RECOVERY_BATCH_LIMIT = 100
"""Maximum records handled by each startup maintenance sweep."""


def recover_confirmation_state(
    *,
    session_factory: Callable[[], Session] | None = None,
    repository: AssistantConfirmationRepository | None = None,
    batch_limit: int = RECOVERY_BATCH_LIMIT,
) -> bool:
    """Run one bounded startup recovery transaction.

    Returns True only after both bounded sweeps and the transaction commit
    succeed. Any connection, query, or commit failure is rolled back when
    possible, returns False, and is intentionally not propagated so a
    temporary database outage cannot stop application startup.
    """
    if batch_limit <= 0:
        return False

    factory = session_factory or database_module.SessionLocal
    store = repository or AssistantConfirmationRepository()
    db: Session | None = None
    try:
        db = factory()
        store.mark_unestablished_outcomes(db, limit=batch_limit)
        store.expire_overdue(db, limit=batch_limit)
        db.commit()
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


__all__ = ["RECOVERY_BATCH_LIMIT", "recover_confirmation_state"]
