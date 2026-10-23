"""Honest capability-routed endpoint for the local assistant interface.

Requests are matched against a small deterministic registry of registered
capabilities. A match is not enough to answer: the authorization policy for
the resolved capability is evaluated first, and the capability's predefined
response is returned only when that decision is ``ALLOW``. Every other
outcome stops dispatch and returns an explicit non-success envelope, as
does an unmatched request. The endpoint never echoes the user's message.

A consequential operation is never executed here. When the policy requires
confirmation and a server-owned executor exists, this endpoint mints a
durable challenge through the trusted confirmation service and returns the
display values; otherwise it returns an honest non-success. A challenge is
only ever persisted from the configured local origin.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from rop import database as database_module
from rop.api.integrity import classify_integrity_error
from rop.api.origin import enforce_local_origin
from rop.authorization.dispatch import authorize_capability_dispatch
from rop.authorization.executors import ExecutorRegistry
from rop.authorization.policy import AuthorizationPolicy, evaluate_authorization
from rop.capabilities.parser import CapabilityParseError
from rop.capabilities.registry import (
    Capability,
    CapabilityRegistry,
    build_default_registry,
)
from rop.capabilities.workspace_parser import WorkspaceCommandParser
from rop.models.assistant_confirmation import AssistantConfirmation
from rop.models.assistant_operation_receipt import AssistantOperationReceipt
from rop.repositories.assistant_confirmation import AssistantConfirmationRepository
from rop.repositories.assistant_conversation import (
    ConversationNotFoundError,
    ConversationRepository,
)
from rop.repositories.assistant_pending_clarification import (
    AssistantPendingClarificationRepository,
)
from rop.repositories.assistant_workspace import AssistantWorkspaceRepository
from rop.schemas.assistant import (
    AssistantConfirmationChallenge,
    AssistantRequest,
    AssistantResponse,
    ClarificationPrompt,
)
from rop.schemas.assistant_conversation import AssistantMessageCreate
from rop.schemas.authorization import AuthorizationOutcome, ProposedOperation
from rop.services.confirmation import (
    ChallengeIssueOutcome,
    ChallengeIssueResult,
    issue_challenge,
)
from rop.services.workspace_executor import (
    build_workspace_executor_registry,
    build_workspace_policy,
    operation_fingerprint,
)
from rop.services.workspace_read import run_workspace_read

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_REGISTRY: CapabilityRegistry = build_default_registry()
_WORKSPACE_CAPABILITY = Capability(
    identifier="workspace-command",
    description="Run explicit deterministic commands against the local workspace.",
    aliases=(),
    response="",
    parser=WorkspaceCommandParser(),
)
_REGISTRY.register(_WORKSPACE_CAPABILITY)

_CONVERSATION_REPOSITORY = ConversationRepository()
_PENDING_CLARIFICATION_REPOSITORY = AssistantPendingClarificationRepository()
_WORKSPACE_REPOSITORY = AssistantWorkspaceRepository()

_POLICY: AuthorizationPolicy = build_workspace_policy()
"""The explicit authorization policy for help and workspace operations.

The policy is constructed by build_workspace_policy() and contains rules
for the help capability, low-risk local listing/search, and fixed protected
workspace mutations. It is independent of the capability registry: registering
a command never grants permission without its explicit policy rule.
"""

_EXECUTORS: ExecutorRegistry = build_workspace_executor_registry()
"""The dedicated whitelist of workspace executors.

This registry contains only the fixed workspace mutation operations defined
in rop.services.workspace_executor. The separate generic default executor
factory remains empty. These executors are only invoked by the trusted
confirmation service after exact-scope challenge consumption.
"""

_REPOSITORY = AssistantConfirmationRepository()

_UNSUPPORTED_MESSAGE = (
    "No matching capability is currently available. "
    "This request was not executed and was not saved."
)

_CONFIRMATION_REQUIRED_MESSAGE = (
    "This operation has not run and will not run unless you confirm this "
    "exact action. Enter the display code to confirm it, or cancel."
)

_CONFIRMATION_UNAVAILABLE_MESSAGE = (
    "This operation requires confirmation, but a confirmation could not be "
    "created for it, so it was not run. This request was not executed and "
    "was not saved."
)


def _issue_challenge(capability: Capability) -> ChallengeIssueResult | None:
    """Mint a challenge in its own short transaction, or return ``None``."""
    session = database_module.SessionLocal()
    try:
        result = issue_challenge(
            session,
            ProposedOperation(operation_id=capability.identifier),
            policy=_POLICY,
            executors=_EXECUTORS,
            repository=_REPOSITORY,
        )
        if result.outcome is ChallengeIssueOutcome.ISSUED:
            session.commit()
        else:
            session.rollback()
        return result
    except Exception:
        session.rollback()
        return None
    finally:
        session.close()


def _dispatch(capability: Capability, http_request: Request) -> AssistantResponse:
    """Authorize one matched capability, minting a challenge when required."""
    if _EXECUTORS.get(capability.identifier) is not None:
        try:
            decision = evaluate_authorization(
                ProposedOperation(operation_id=capability.identifier),
                policy=_POLICY,
            )
        except Exception:
            # Fall through to the dispatch boundary, which fails closed.
            return authorize_capability_dispatch(capability, policy=_POLICY)

        if decision.outcome is AuthorizationOutcome.REQUIRE_CONFIRMATION:
            # Persisting a challenge is a state-changing act: enforce the
            # configured local origin before anything is written.
            enforce_local_origin(http_request)
            issued = _issue_challenge(capability)
            if (
                issued is not None
                and issued.outcome is ChallengeIssueOutcome.ISSUED
                and issued.challenge is not None
            ):
                challenge = issued.challenge
                return AssistantResponse(
                    status="confirmation-required",
                    message=_CONFIRMATION_REQUIRED_MESSAGE,
                    challenge=AssistantConfirmationChallenge(
                        challenge_id=challenge.challenge_id,
                        summary=challenge.summary,
                        display_code=challenge.display_code,
                        expires_at=challenge.expires_at,
                    ),
                )
            return AssistantResponse(
                status="confirmation-required",
                message=_CONFIRMATION_UNAVAILABLE_MESSAGE,
            )

    return authorize_capability_dispatch(capability, policy=_POLICY)


def _workspace_refusal(message: str) -> AssistantResponse:
    """Build a static, input-safe refusal for a workspace command."""
    return AssistantResponse(status="refused", message=message)


def _make_clarification_response(
    session,
    *,
    conversation_id: UUID,
    original_message: str,
    error: CapabilityParseError,
) -> AssistantResponse:
    """Persist only a real, resumable clarification for a selected conversation."""
    operation = error.partial_operation
    if operation is None:
        return _workspace_refusal(
            "The command could not be completed safely. Nothing was executed or saved."
        )
    missing_fields = list(error.missing_fields or [error.field_name])
    row = _PENDING_CLARIFICATION_REPOSITORY.create(
        session,
        conversation_id=conversation_id,
        capability_identifier=_WORKSPACE_CAPABILITY.identifier,
        original_message=original_message,
        partial_operation=operation.model_dump(mode="json"),
        missing_fields=missing_fields,
        question=error.question,
    )
    return AssistantResponse(
        status="clarification-required",
        message=error.question,
        clarification_prompt=ClarificationPrompt(
            clarification_id=row.clarification_id,
            capability_identifier=row.capability_identifier,
            question=row.question,
            missing_fields=list(row.missing_fields),
        ),
    )


def _prepare_workspace_confirmation(
    session,
    operation: ProposedOperation,
    *,
    conversation_id: UUID,
    pending_row,
) -> AssistantResponse:
    """Bind an operation key and challenge in one transaction."""
    raw_key = operation.parameters.get("idempotency_key")
    try:
        key = UUID(raw_key or "")
    except (TypeError, ValueError):
        return _workspace_refusal(
            "This change could not be safely identified. Nothing was changed."
        )

    fingerprint = operation_fingerprint(operation)
    receipt = _WORKSPACE_REPOSITORY.get_receipt(session, key, for_update=True)
    if receipt is not None:
        if receipt.operation_fingerprint != fingerprint:
            return _workspace_refusal(
                "That operation key is already bound to a different change. "
                "Nothing new was executed."
            )
        if receipt.status == "SUCCEEDED":
            return AssistantResponse(
                status="success",
                message=(
                    "This exact change has already completed. "
                    "No duplicate change was applied."
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
            return _workspace_refusal(
                "A matching confirmation may already be pending. Inspect the "
                "confirmation records before proceeding; no second challenge was "
                "created."
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
        repository=_REPOSITORY,
    )
    if result.outcome is not ChallengeIssueOutcome.ISSUED or result.challenge is None:
        return AssistantResponse(
            status="confirmation-unavailable",
            message=(
                "This change requires confirmation, but a usable challenge "
                "could not be created. Nothing was changed."
            ),
        )

    challenge = result.challenge
    if pending_row is not None:
        _PENDING_CLARIFICATION_REPOSITORY.consume_and_clear(session, pending_row)
    return AssistantResponse(
        status="confirmation-required",
        message=(
            "This change has not run. Review the exact confirmation card and "
            "confirm it to apply the change."
        ),
        challenge=AssistantConfirmationChallenge(
            challenge_id=challenge.challenge_id,
            summary=challenge.summary,
            display_code=challenge.display_code,
            expires_at=challenge.expires_at,
        ),
    )


def _persist_clarified_success(
    session,
    *,
    conversation_id: UUID,
    pending_row,
    original_message: str,
    answer: str,
    assistant_message: str,
) -> None:
    """Consume clarification and save one successful turn atomically."""
    user_content = f"{original_message}\nClarification: {answer}"
    _CONVERSATION_REPOSITORY.append_message(
        session,
        conversation_id,
        AssistantMessageCreate(role="user", content=user_content),
    )
    _CONVERSATION_REPOSITORY.append_message(
        session,
        conversation_id,
        AssistantMessageCreate(role="assistant", content=assistant_message),
    )
    _PENDING_CLARIFICATION_REPOSITORY.consume_and_clear(session, pending_row)
    session.commit()


def _dispatch_workspace_command(
    request: AssistantRequest,
) -> tuple[AssistantResponse, str, bool]:
    """Parse, clarify, authorize and dispatch one explicit workspace command.

    Returns response, user message for persistence, and whether the successful
    turn has already been persisted atomically with clarification consumption.
    """
    conversation_id = request.conversation_id
    if conversation_id is None:
        return (
            _workspace_refusal(
                "Select or create a saved conversation before using workspace "
                "commands. Nothing was executed or saved."
            ),
            request.message,
            False,
        )

    session = database_module.SessionLocal()
    pending_row = None
    original_message = request.message
    turn_message = request.message
    context = None
    idempotency_key = str(request.idempotency_key or uuid4())
    try:
        if request.clarification_id is not None:
            pending_row = _PENDING_CLARIFICATION_REPOSITORY.get_pending(
                session, request.clarification_id, for_update=True
            )
            if pending_row is None or pending_row.conversation_id != conversation_id:
                session.rollback()
                return (
                    _workspace_refusal(
                        "That clarification is no longer active for this conversation. "
                        "Start the command again."
                    ),
                    request.message,
                    False,
                )
            now = datetime.now(UTC)
            expires_at = pending_row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                _PENDING_CLARIFICATION_REPOSITORY.consume_and_clear(
                    session, pending_row, now=now
                )
                _PENDING_CLARIFICATION_REPOSITORY.delete_expired(session, now=now)
                session.commit()
                return (
                    _workspace_refusal(
                        "That clarification expired. Start the workspace command again."
                    ),
                    request.message,
                    False,
                )
            original_message = pending_row.original_message
            turn_message = f"{original_message}\nClarification: {request.message}"
            parameters = pending_row.partial_operation.get("parameters", {})
            idempotency_key = parameters.get("idempotency_key", idempotency_key)
            context = {
                "partial_operation": pending_row.partial_operation,
                "missing_fields": list(pending_row.missing_fields),
            }

        try:
            operation = _WORKSPACE_CAPABILITY.parser.parse(
                request.message,
                pending_context=context,
                idempotency_key=idempotency_key,
            )
        except CapabilityParseError as exc:
            if exc.partial_operation is None:
                if pending_row is not None:
                    _PENDING_CLARIFICATION_REPOSITORY.consume_and_clear(
                        session, pending_row
                    )
                    session.commit()
                else:
                    session.rollback()
                return (
                    _workspace_refusal(
                        "The command could not be processed safely. "
                        "Nothing was executed."
                    ),
                    turn_message,
                    False,
                )
            response = _make_clarification_response(
                session,
                conversation_id=conversation_id,
                original_message=original_message,
                error=exc,
            )
            session.commit()
            return response, turn_message, False
        except Exception:
            session.rollback()
            logger.warning("workspace command parser failed")
            return (
                _workspace_refusal(
                    "The command could not be processed safely. Nothing was executed."
                ),
                turn_message,
                False,
            )

        try:
            decision = evaluate_authorization(operation, policy=_POLICY)
        except Exception:
            session.rollback()
            logger.warning("workspace command authorization failed")
            return (
                _workspace_refusal(
                    "The command could not be authorized. Nothing was executed."
                ),
                turn_message,
                False,
            )

        if decision.outcome is AuthorizationOutcome.CLARIFY:
            rule = _POLICY.rule(operation.operation_id)
            missing = []
            if rule is not None:
                if rule.requires_target and operation.target is None:
                    missing.append("target")
                missing.extend(
                    name
                    for name in rule.required_parameters
                    if name not in operation.parameters
                )
            if not missing:
                missing = [str(decision.reason).lower()]
            question = "Please provide the missing information: " + ", ".join(missing)
            response = _make_clarification_response(
                session,
                conversation_id=conversation_id,
                original_message=original_message,
                error=CapabilityParseError(
                    missing[0],
                    question,
                    partial_operation=operation,
                    missing_fields=missing,
                ),
            )
            session.commit()
            return response, turn_message, False

        if decision.outcome is AuthorizationOutcome.DENY:
            if pending_row is not None:
                _PENDING_CLARIFICATION_REPOSITORY.consume_and_clear(
                    session, pending_row
                )
                session.commit()
            else:
                session.rollback()
            return (
                _workspace_refusal(
                    "The command is not permitted by the current policy. "
                    "Nothing was changed."
                ),
                turn_message,
                False,
            )

        if decision.outcome is AuthorizationOutcome.ALLOW:
            try:
                message = run_workspace_read(operation)
            except Exception:
                session.rollback()
                logger.warning("workspace read operation failed")
                return (
                    _workspace_refusal(
                        "The local workspace request could not be completed. "
                        "No change was made."
                    ),
                    turn_message,
                    False,
                )
            response = AssistantResponse(status="success", message=message)
            if pending_row is not None:
                _persist_clarified_success(
                    session,
                    conversation_id=conversation_id,
                    pending_row=pending_row,
                    original_message=original_message,
                    answer=request.message,
                    assistant_message=message,
                )
                return response, turn_message, True
            session.rollback()
            return response, turn_message, False

        if decision.outcome is AuthorizationOutcome.REQUIRE_CONFIRMATION:
            response = _prepare_workspace_confirmation(
                session,
                operation,
                conversation_id=conversation_id,
                pending_row=pending_row,
            )
            if (
                response.status == "confirmation-required"
                and response.challenge is not None
            ):
                session.commit()
            elif response.status == "success":
                session.rollback()
            elif response.status == "refused":
                if pending_row is not None:
                    _PENDING_CLARIFICATION_REPOSITORY.consume_and_clear(
                        session, pending_row
                    )
                    session.commit()
                else:
                    session.rollback()
            else:
                # Keep both the original clarification and the receipt
                # reservation unchanged when challenge issuance fails.
                session.rollback()
            return response, turn_message, False

        session.rollback()
        return (
            _workspace_refusal("The command could not be safely dispatched."),
            turn_message,
            False,
        )
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        logger.warning("workspace command handler failed")
        return (
            _workspace_refusal(
                "The workspace command could not be completed safely. "
                "Inspect the local application state before retrying."
            ),
            turn_message,
            False,
        )
    finally:
        session.close()


_ERROR_CONVERSATION_NOT_FOUND = "The conversation does not exist."
_ERROR_SAVE_FAILED = (
    "The request was answered but the exchange could not be saved to the "
    "conversation. The response above was not stored."
)
_ERROR_SAVE_CONFLICT = (
    "The exchange could not be saved because of a concurrent update; "
    "reload the conversation and try again."
)


def _verify_conversation(conversation_id: UUID) -> None:
    """Raise 404 if the conversation does not exist; open no session on success.

    The verification session is opened and closed here, not held open across
    dispatch. That keeps the no-conversation path database-free and avoids
    holding a connection while the capability and policy run.
    """
    session = database_module.SessionLocal()
    try:
        record = _CONVERSATION_REPOSITORY.get(session, conversation_id)
    finally:
        session.close()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_ERROR_CONVERSATION_NOT_FOUND,
        )


def _persist_successful_turn(
    conversation_id: UUID,
    user_message: str,
    assistant_message: str,
) -> None:
    """Atomically append the user/assistant pair and commit once.

    On any failure — sequence conflict, FK violation, or an unexpected
    exception — the session is rolled back and the pair is not written.
    Integrity errors are classified exactly per ``classify_integrity_error``
    so a sequence conflict maps to 409, a missing parent to 404, and any
    other constraint failure to a sanitized 503.
    """
    session = database_module.SessionLocal()
    try:
        _CONVERSATION_REPOSITORY.append_message(
            session,
            conversation_id,
            AssistantMessageCreate(role="user", content=user_message),
        )
        _CONVERSATION_REPOSITORY.append_message(
            session,
            conversation_id,
            AssistantMessageCreate(role="assistant", content=assistant_message),
        )
        session.commit()
    except ConversationNotFoundError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_ERROR_CONVERSATION_NOT_FOUND,
        ) from None
    except IntegrityError as exc:
        session.rollback()
        kind = classify_integrity_error(exc)
        if kind == "sequence_conflict":
            logger.info("assistant turn persistence hit a sequence conflict")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_ERROR_SAVE_CONFLICT,
            ) from None
        if kind == "missing_parent":
            logger.info("assistant turn persistence raced a conversation delete")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_ERROR_CONVERSATION_NOT_FOUND,
            ) from None
        logger.warning("assistant turn persistence hit an unclassified integrity error")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ERROR_SAVE_FAILED,
        ) from None
    except Exception:
        session.rollback()
        logger.warning("assistant turn persistence failed; rolled back")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_ERROR_SAVE_FAILED,
        ) from None
    finally:
        session.close()


def _enforce_persistence_origin(http_request: Request) -> None:
    """Enforce the trusted local origin before reading or writing a
    persisted conversation. Reuses the exact same helper the confirmation
    flow already uses; nothing about the origin contract changes.
    """
    enforce_local_origin(http_request)


@router.post(
    "/requests",
    response_model=AssistantResponse,
    response_model_exclude_none=True,
    responses={
        422: {
            "description": (
                "Request body is empty, whitespace-only, overlong, or "
                "contains unexpected fields."
            ),
        },
        403: {
            "description": (
                "A state-changing operation was requested but the request "
                "did not come from the configured local origin."
            ),
        },
        404: {
            "description": (
                "A conversation_id was supplied but does not identify an "
                "existing conversation."
            ),
        },
        409: {
            "description": (
                "A successful exchange could not be saved because of a "
                "concurrent sequence conflict; the response was not stored."
            ),
        },
        503: {
            "description": (
                "A successful exchange could not be saved due to a "
                "persistence failure; the response was not stored."
            ),
        },
    },
)
def submit_request(
    request: AssistantRequest, http_request: Request
) -> AssistantResponse:
    """Match ``request.message`` to a registered capability, then authorize it.

    The user's message is used only to select a capability and is not echoed
    into the response. An invalid, ambiguous, or unregistered request
    resolves to the explicit unsupported-capability envelope. A matched
    capability is dispatched only when the authorization policy returns
    ``ALLOW``; ``CLARIFY`` and ``DENY`` return their non-success status. A
    ``REQUIRE_CONFIRMATION`` outcome with a registered executor mints a
    challenge and returns its display values; without one it returns an
    honest non-success. This request endpoint never directly applies a
    protected workspace mutation: it either performs an explicitly allowed
    read-only workspace action or prepares a challenge. Protected state
    changes run only through the separate confirmation-decision endpoint.

    The request carries no confirmation and no authorization assertion, so
    this endpoint cannot be talked into treating a request as already
    approved.
    """
    conversation_id = request.conversation_id

    if conversation_id is not None:
        # Persistence path: enforce origin and verify the conversation
        # before doing any dispatch or DB work.
        _enforce_persistence_origin(http_request)
        _verify_conversation(conversation_id)

    if request.clarification_id is not None:
        response, persistence_message, already_persisted = _dispatch_workspace_command(
            request
        )
    else:
        capability = _REGISTRY.match(request.message)
        if capability is None:
            capability = _REGISTRY.match_parser(request.message)
        if capability is None:
            return AssistantResponse(
                status="unsupported-capability",
                message=_UNSUPPORTED_MESSAGE,
            )
        if capability.parser is not None:
            response, persistence_message, already_persisted = (
                _dispatch_workspace_command(request)
            )
        else:
            response = _dispatch(capability, http_request)
            persistence_message = request.message
            already_persisted = False

    # Successful clarification continuations append their original command,
    # answer, and result atomically with consuming the pending record.
    if (
        conversation_id is not None
        and not already_persisted
        and response.status == "success"
        and response.challenge is None
    ):
        _persist_successful_turn(
            conversation_id,
            persistence_message,
            response.message,
        )
    return response
