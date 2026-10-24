"""Local-only personal workspace API.

Read endpoints expose only local notes/tasks/reminders and explicitly
authorized folders. Mutations do not directly write data: they prepare a
server-side confirmation for an exact ProposedOperation, which is executed
only after the existing trusted confirmation endpoint consumes it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from rop import database as database_module
from rop.api.origin import enforce_local_origin
from rop.authorization.policy import evaluate_authorization
from rop.models.assistant_confirmation import AssistantConfirmation
from rop.models.assistant_item import AssistantItem
from rop.models.assistant_operation_receipt import AssistantOperationReceipt
from rop.models.assistant_retrieval_root import AssistantRetrievalRoot
from rop.repositories.assistant_confirmation import AssistantConfirmationRepository
from rop.repositories.assistant_workspace import AssistantWorkspaceRepository
from rop.schemas.assistant import AssistantConfirmationChallenge
from rop.schemas.authorization import AuthorizationOutcome, ProposedOperation
from rop.schemas.workspace import (
    RetrievalRootRead,
    WorkspaceChangeRequest,
    WorkspaceChangeResponse,
    WorkspaceItemKind,
    WorkspaceItemRead,
    WorkspaceReceiptRead,
)
from rop.services.confirmation import ChallengeIssueOutcome, issue_challenge
from rop.services.local_paths import is_network_path as _is_network_path
from rop.services.workspace_executor import (
    build_workspace_executor_registry,
    build_workspace_policy,
    operation_fingerprint,
)

router = APIRouter(prefix="/api/assistant/workspace", tags=["assistant-workspace"])
_REPOSITORY = AssistantWorkspaceRepository()
_CONFIRMATION_REPOSITORY = AssistantConfirmationRepository()
_POLICY = build_workspace_policy()
_EXECUTORS = build_workspace_executor_registry()

_UNAVAILABLE = (
    "This change requires confirmation, but a challenge could not be created. "
    "Nothing was changed."
)
_REQUIRED = "Review the exact change in the confirmation card. It has not been applied."


def _parse_local_due(value: str, timezone_name: str) -> datetime:
    """Convert local wall time to UTC, refusing missing or ambiguous DST times."""
    try:
        local = datetime.fromisoformat(value)
        zone = ZoneInfo(timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter a valid local date/time and timezone.",
        ) from None
    if local.tzinfo is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The date/time field must be local wall time without an offset.",
        )
    valid = []
    for fold in (0, 1):
        candidate = local.replace(tzinfo=zone, fold=fold)
        round_trip = candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
        if round_trip == local:
            valid.append(candidate)
    offsets = {candidate.utcoffset() for candidate in valid}
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "That local time does not exist because of a daylight-saving "
                "transition. Choose another time."
            ),
        )
    if len(offsets) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "That local time is ambiguous because clocks change. "
                "Choose a different time."
            ),
        )
    return valid[0].astimezone(UTC)


def _operation_for(request: WorkspaceChangeRequest) -> ProposedOperation:
    """Build a fixed operation ID and validated material values server-side."""
    params: dict[str, str] = {"idempotency_key": str(request.idempotency_key)}
    target = None
    operation_id: str
    if request.kind == "retrieval_root":
        if request.action == "add":
            raw_root = Path(request.path or "").expanduser()
            if _is_network_path(raw_root):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Network folders are not supported for offline retrieval.",
                )
            try:
                root = raw_root.resolve(strict=True)
            except (OSError, RuntimeError, ValueError):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Choose an accessible local folder.",
                ) from None
            if _is_network_path(root) or not root.is_dir():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="The selected path is not a directory.",
                )
            params["path"] = str(root)
            operation_id = "workspace_root_add"
        else:
            target = str(request.item_id)
            operation_id = "workspace_root_remove"
        return ProposedOperation(
            operation_id=operation_id, target=target, parameters=params
        )

    operation_id = f"workspace_{request.kind}_{request.action}"
    if request.action != "create":
        target = str(request.item_id)
    if request.title is not None:
        params["title"] = request.title
    if request.content is not None:
        params["content"] = request.content
    if request.clear_content:
        params["clear_content"] = "true"
    if request.action == "complete":
        params["completed"] = "true" if request.completed else "false"
    if request.kind == "reminder" and request.action in {"create", "update"}:
        due_utc = _parse_local_due(request.due_local or "", request.timezone or "")
        params["due_at"] = due_utc.isoformat()
        params["timezone"] = request.timezone or ""
    return ProposedOperation(
        operation_id=operation_id, target=target, parameters=params
    )


@router.get("/items", response_model=list[WorkspaceItemRead])
def list_items(
    kind: WorkspaceItemKind | None = None,
    include_completed: bool = True,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[WorkspaceItemRead]:
    """List local items only; this endpoint never accesses the network."""
    session = database_module.SessionLocal()
    try:
        statement = (
            select(AssistantItem)
            .order_by(AssistantItem.updated_at.desc(), AssistantItem.id.desc())
            .limit(limit)
        )
        if kind is not None:
            statement = statement.where(AssistantItem.kind == kind)
        if not include_completed:
            statement = statement.where(AssistantItem.completed.is_(False))
        rows = session.scalars(statement).all()
        return [WorkspaceItemRead.model_validate(row) for row in rows]
    finally:
        session.close()


@router.get("/retrieval-roots", response_model=list[RetrievalRootRead])
def list_retrieval_roots() -> list[RetrievalRootRead]:
    """List only folders explicitly authorized by the user."""
    session = database_module.SessionLocal()
    try:
        rows = session.scalars(
            select(AssistantRetrievalRoot).order_by(
                AssistantRetrievalRoot.created_at.asc(),
                AssistantRetrievalRoot.id.asc(),
            )
        ).all()
        return [RetrievalRootRead.model_validate(row) for row in rows]
    finally:
        session.close()


@router.get("/receipts/{idempotency_key}", response_model=WorkspaceReceiptRead)
def get_receipt(idempotency_key: UUID) -> WorkspaceReceiptRead:
    """Recover a workspace operation result after a lost HTTP response."""
    session = database_module.SessionLocal()
    try:
        receipt = session.scalar(
            select(AssistantOperationReceipt).where(
                AssistantOperationReceipt.idempotency_key == idempotency_key
            )
        )
        if receipt is None:
            return WorkspaceReceiptRead(
                idempotency_key=idempotency_key,
                status="not-found",
                message="No completed workspace operation was recorded for this key.",
            )
        if receipt.status == "SUCCEEDED":
            return WorkspaceReceiptRead(
                idempotency_key=idempotency_key,
                status="succeeded",
                message="The workspace change completed successfully.",
            )
        return WorkspaceReceiptRead(
            idempotency_key=idempotency_key,
            status="unknown",
            message=(
                "The operation has no established terminal result. "
                "Do not retry it with a new key."
            ),
        )
    finally:
        session.close()


@router.delete(
    "/receipts/{idempotency_key}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def abandon_receipt(idempotency_key: UUID, http_request: Request) -> Response:
    """Abandon an unused reservation only when no active challenge remains."""
    enforce_local_origin(http_request)
    session = database_module.SessionLocal()
    try:
        receipt = _REPOSITORY.get_receipt(session, idempotency_key, for_update=True)
        if receipt is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        if receipt.status != "PENDING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "A completed or unresolved operation receipt cannot be deleted."
                ),
            )
        active = session.scalar(
            select(AssistantConfirmation.id)
            .where(
                AssistantConfirmation.status == "PENDING",
                AssistantConfirmation.expires_at > datetime.now(UTC),
                AssistantConfirmation.parameters["idempotency_key"].as_string()
                == str(idempotency_key),
            )
            .limit(1)
        )
        if active is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "A confirmation is still active. Cancel or delete that "
                    "challenge before abandoning this key."
                ),
            )
        session.delete(receipt)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The operation key could not be abandoned.",
        ) from None
    finally:
        session.close()


@router.post(
    "/changes",
    response_model=WorkspaceChangeResponse,
    response_model_exclude_none=True,
)
def prepare_change(
    body: WorkspaceChangeRequest, http_request: Request
) -> WorkspaceChangeResponse:
    """Validate and prepare an exact, protected workspace mutation."""
    enforce_local_origin(http_request)
    operation = _operation_for(body)
    try:
        decision = evaluate_authorization(operation, policy=_POLICY)
    except Exception:
        return WorkspaceChangeResponse(
            status="refused",
            message="The workspace change could not be authorized.",
        )
    if decision.outcome is AuthorizationOutcome.CLARIFY:
        return WorkspaceChangeResponse(
            status="refused",
            message="The change is missing required information. Nothing was changed.",
        )
    if decision.outcome is not AuthorizationOutcome.REQUIRE_CONFIRMATION:
        return WorkspaceChangeResponse(
            status="refused",
            message=(
                "The current policy did not authorize a confirmation "
                "for this change."
            ),
        )
    key = body.idempotency_key
    fingerprint = operation_fingerprint(operation)
    session = database_module.SessionLocal()
    try:
        receipt = _REPOSITORY.get_receipt(session, key, for_update=True)
        if receipt is not None:
            if receipt.operation_fingerprint != fingerprint:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "This idempotency key is already bound to a different "
                        "workspace change. Resolve the earlier change first."
                    ),
                )
            if receipt.status == "SUCCEEDED":
                return WorkspaceChangeResponse(
                    status="success",
                    message=(
                        "This exact change already completed. "
                        "No duplicate change was applied."
                    ),
                )
            if receipt.status == "RUNNING":
                return WorkspaceChangeResponse(
                    status="unknown",
                    message=(
                        "This operation has no established terminal result. "
                        "Do not submit it with a new key."
                    ),
                )
            active = session.scalar(
                select(AssistantConfirmation.id)
                .where(
                    AssistantConfirmation.status == "PENDING",
                    AssistantConfirmation.expires_at > datetime.now(UTC),
                    AssistantConfirmation.parameters["idempotency_key"].as_string()
                    == str(key),
                )
                .limit(1)
            )
            if active is not None:
                return WorkspaceChangeResponse(
                    status="unknown",
                    message=(
                        "A confirmation for this exact change may already be "
                        "pending. Check the confirmation records; do not create "
                        "a new operation key."
                    ),
                )
        else:
            receipt = AssistantOperationReceipt(
                idempotency_key=key,
                operation_id=operation.operation_id,
                operation_fingerprint=fingerprint,
                status="PENDING",
            )
            session.add(receipt)
            session.flush()

        result = issue_challenge(
            session,
            operation,
            policy=_POLICY,
            executors=_EXECUTORS,
            repository=_CONFIRMATION_REPOSITORY,
        )
        if (
            result.outcome is ChallengeIssueOutcome.ISSUED
            and result.challenge is not None
        ):
            session.commit()
            challenge = result.challenge
            return WorkspaceChangeResponse(
                status="confirmation-required",
                message=_REQUIRED,
                challenge=AssistantConfirmationChallenge(
                    challenge_id=challenge.challenge_id,
                    summary=challenge.summary,
                    display_code=challenge.display_code,
                    expires_at=challenge.expires_at,
                ),
            )
        session.rollback()
        return WorkspaceChangeResponse(
            status="confirmation-unavailable",
            message=_UNAVAILABLE,
        )
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        return WorkspaceChangeResponse(
            status="confirmation-unavailable", message=_UNAVAILABLE
        )
    finally:
        session.close()


__all__ = ["router"]
