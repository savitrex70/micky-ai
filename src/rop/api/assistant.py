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
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from rop import database as database_module
from rop.api.integrity import classify_integrity_error
from rop.api.origin import enforce_local_origin
from rop.authorization.dispatch import authorize_capability_dispatch
from rop.authorization.executors import (
    ExecutorRegistry,
    build_default_executor_registry,
)
from rop.authorization.policy import (
    AuthorizationPolicy,
    build_default_policy,
    evaluate_authorization,
)
from rop.capabilities.registry import (
    Capability,
    CapabilityRegistry,
    build_default_registry,
)
from rop.repositories.assistant_confirmation import AssistantConfirmationRepository
from rop.repositories.assistant_conversation import (
    ConversationNotFoundError,
    ConversationRepository,
)
from rop.schemas.assistant import (
    AssistantConfirmationChallenge,
    AssistantRequest,
    AssistantResponse,
)
from rop.schemas.assistant_conversation import AssistantMessageCreate
from rop.schemas.authorization import AuthorizationOutcome, ProposedOperation
from rop.services.confirmation import (
    ChallengeIssueOutcome,
    ChallengeIssueResult,
    issue_challenge,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_REGISTRY: CapabilityRegistry = build_default_registry()

_CONVERSATION_REPOSITORY = ConversationRepository()

_POLICY: AuthorizationPolicy = build_default_policy()
"""The explicitly configured policy the dispatch boundary consults.

It is the Task 220 default table, which registers exactly the capabilities
that exist today. It is written down here rather than derived from the
registry on purpose: registering a capability does not authorize it, so a
capability added to the registry without a deliberate policy rule is refused
instead of silently inheriting permission.
"""

_EXECUTORS: ExecutorRegistry = build_default_executor_registry()
"""The server-side executors that can perform a confirmed operation.

Empty by default: this build registers no production executor, so a
consequential operation cannot run. A test may register a fake executor.
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
    honest non-success. Nothing is executed on any path.

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

    capability = _REGISTRY.match(request.message)
    if capability is None:
        # Unsupported requests are transient, not saved.
        return AssistantResponse(
            status="unsupported-capability",
            message=_UNSUPPORTED_MESSAGE,
        )
    response = _dispatch(capability, http_request)

    # Only a genuinely successful turn is persisted, and only when a
    # conversation was supplied. Non-success outcomes and no-conversation
    # requests do not touch the conversation store.
    if (
        conversation_id is not None
        and response.status == "success"
        and response.challenge is None
    ):
        _persist_successful_turn(
            conversation_id,
            request.message,
            response.message,
        )
    return response
