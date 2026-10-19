"""User-facing management of stored assistant confirmation records.

This router exposes inspection, export, and deletion of the durable
confirmation records written by Task 223 and consumed by Task 224. It is a
data-control surface, not a confirmation flow: it never confirms, cancels,
or executes an operation. The decision endpoint remains
``src/rop/api/confirmations.py``.

Privacy invariants enforced here:

* Every record returned to a caller is an :class:`AssistantConfirmationView`,
  which omits ``challenge_id``, ``display_code_hash``, ``display_code_salt``,
  ``material_digest``, and ``material_digest_salt``. The public record UUID is
  the only identifier exposed, and it is not the challenge id.
* Pagination boundaries and export page walks are bounded by
  ``MAX_INSPECTION_LIMIT`` so no single call can materialise an unbounded
  result set.
* Deletion accepts only record UUIDs, never challenge identifiers, and
  never a wildcard. A deleted pending record cannot be used to authorize or
  execute the underlying operation: the challenge no longer exists, and the
  confirmation service treats a missing challenge as an indistinguishable
  refusal.
* Errors are static, sanitized strings. No submitted identifier, no material
  value, and no database exception text is returned.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from rop.api.origin import require_local_origin
from rop.database import get_db
from rop.repositories.assistant_confirmation import (
    MAX_INSPECTION_LIMIT,
    AssistantConfirmationRepository,
    ConfirmationRecordError,
)
from rop.schemas.assistant_confirmation import (
    CONFIRMATION_EXPORT_BUNDLE_FORMAT,
    AssistantConfirmationDeletionResult,
    AssistantConfirmationExport,
    AssistantConfirmationExportBundle,
    ConfirmationRecordDeletionRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/assistant/confirmation-records",
    tags=["assistant-confirmation-records"],
)

_REPOSITORY = AssistantConfirmationRepository()

_EXPORT_PAGE_LIMIT = MAX_INSPECTION_LIMIT
"""Per-page size used when walking the store for a complete export.

This is the repository's own upper bound, so the export never asks for a
page larger than inspection is allowed to serve, and never silently
truncates at an internal limit that a caller could not predict.
"""

_ERROR_INVALID_PAGINATION = "The pagination parameters are invalid."


def _page_response(
    db: Session, *, limit: int, offset: int
) -> AssistantConfirmationExport:
    """Return one page of records plus accurate pagination metadata."""
    try:
        return _REPOSITORY.export_records(db, limit=limit, offset=offset)
    except ConfirmationRecordError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_ERROR_INVALID_PAGINATION,
        ) from None


def _walk_all_pages(db: Session, *, generated_at: datetime):
    """Walk the store deterministically, collecting every page.

    Returns ``(pages, total_record_count, collected_count)``. Pagination is
    bounded by ``_EXPORT_PAGE_LIMIT``; the walk terminates only when a page
    reports ``has_more=False``.

    The caller is responsible for establishing a consistent snapshot
    (REPEATABLE READ) on ``db`` before this function is invoked. Within a
    REPEATABLE READ transaction, every read in the walk sees the same
    snapshot, so page boundaries cannot shift under a concurrent
    insert+delete that preserves the total row count.
    """
    pages: list[AssistantConfirmationExport] = []
    total: int | None = None
    offset = 0
    while True:
        page = _REPOSITORY.export_records(
            db, generated_at=generated_at, limit=_EXPORT_PAGE_LIMIT, offset=offset
        )
        if total is None:
            total = page.total_record_count
        if total == 0:
            # Empty store: report zero pages. Adding an empty page would
            # be honest but noisy, and consumers flatten pages anyway.
            break
        pages.append(page)
        if not page.has_more:
            break
        if page.next_offset is None:
            # Contract violation — refuse to loop forever.
            raise ConfirmationRecordError("export page missing next_offset")
        offset = page.next_offset
    collected = sum(len(p.records) for p in pages)
    return pages, total if total is not None else 0, collected


@router.get(
    "",
    response_model=AssistantConfirmationExport,
    responses={
        422: {
            "description": (
                "The pagination parameters are invalid (non-positive limit, "
                "limit above the documented maximum, or negative offset)."
            ),
        },
    },
)
def list_records(
    limit: int = Query(default=100, ge=1, le=MAX_INSPECTION_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> AssistantConfirmationExport:
    """Return one page of confirmation records in deterministic order.

    The response is the established single-page export contract: it carries
    per-page metadata that makes pagination explicit and unambiguous. Only
    ``AssistantConfirmationView`` fields appear in ``records``; the challenge
    identifier and every secret-adjacent value are excluded by construction.
    """
    return _page_response(db, limit=limit, offset=offset)


@router.get(
    "/export",
    response_model=AssistantConfirmationExportBundle,
)
def export_all_records(
    response: Response,
    db: Session = Depends(get_db),
) -> AssistantConfirmationExportBundle:
    """Export every stored record as a complete, versioned bundle.

    Each page inside the bundle is a full ``AssistantConfirmationExport``
    with its own metadata preserved. The export runs inside a REPEATABLE
    READ transaction so that every page read in the walk sees the same
    database snapshot. This is what makes count equality sufficient:
    without a consistent snapshot, a concurrent insert+delete between page
    reads could shift which records appear at each offset while preserving
    the total row count, so count equality alone would not prove a
    consistent capture. If the snapshot cannot be established, the export
    fails closed with a sanitized 503 rather than returning a bundle that
    might be internally inconsistent.

    The response carries ``Content-Disposition: attachment`` with a fixed,
    sanitized JSON filename so a browser download receives a predictable
    name that never reflects record content.
    """
    generated_at = datetime.now(UTC)

    # ``SET TRANSACTION`` must be the first statement in the transaction, so
    # this runs before any repository read in this handler. The session
    # created by ``get_db`` starts its transaction lazily on first execute,
    # which is this SET.
    try:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The export could not be established as consistent.",
        ) from None

    try:
        pages, total, collected = _walk_all_pages(db, generated_at=generated_at)
    except ConfirmationRecordError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The export could not be completed.",
        ) from None

    is_complete = collected == total
    bundle = AssistantConfirmationExportBundle(
        format=CONFIRMATION_EXPORT_BUNDLE_FORMAT,
        generated_at=generated_at,
        total_record_count=total,
        page_count=len(pages),
        page_limit=_EXPORT_PAGE_LIMIT,
        is_complete=is_complete,
        pages=tuple(pages),
    )
    response.headers["Content-Disposition"] = (
        'attachment; filename="confirmation-records-export.json"'
    )
    return bundle


@router.post(
    "",
    response_model=AssistantConfirmationDeletionResult,
    dependencies=[Depends(require_local_origin)],
    status_code=status.HTTP_200_OK,
    responses={
        403: {
            "description": (
                "The request did not come from the configured local origin, "
                "or did not use a JSON content type."
            ),
        },
        422: {
            "description": (
                "The deletion body is malformed, carries unknown fields, "
                "contains a non-UUID identifier, is empty, or exceeds the "
                "documented batch limit."
            ),
        },
        503: {
            "description": (
                "The deletion could not be completed and was rolled back. "
                "No record was deleted."
            ),
        },
    },
)
def delete_records(
    body: ConfirmationRecordDeletionRequest,
    db: Session = Depends(get_db),
) -> AssistantConfirmationDeletionResult:
    """Delete the exact records identified by database UUID.

    The endpoint commits only after the delete succeeds; a database failure
    rolls back and returns 503 without claiming any record was removed.
    Deleting a pending record removes its challenge, so any later attempt to
    decide that challenge is refused by the confirmation service — the
    operation cannot be authorized or executed after its record is gone.

    The response reports only ``deleted_count``; that number is exactly what
    the database removed, so unknown UUIDs cannot inflate it.
    """
    try:
        result = _REPOSITORY.delete_by_ids(db, list(body.record_ids))
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("confirmation-record deletion failed; rolled back")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The deletion could not be completed.",
        ) from None
    return result


__all__ = ["router"]
