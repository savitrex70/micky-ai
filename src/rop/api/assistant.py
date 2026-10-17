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

from fastapi import APIRouter, Request

from rop import database as database_module
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
from rop.schemas.assistant import (
    AssistantConfirmationChallenge,
    AssistantRequest,
    AssistantResponse,
)
from rop.schemas.authorization import AuthorizationOutcome, ProposedOperation
from rop.services.confirmation import (
    ChallengeIssueOutcome,
    ChallengeIssueResult,
    issue_challenge,
)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_REGISTRY: CapabilityRegistry = build_default_registry()

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
                "A challenge would be persisted but the request did not come "
                "from the configured local origin."
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
    capability = _REGISTRY.match(request.message)
    if capability is None:
        return AssistantResponse(
            status="unsupported-capability",
            message=_UNSUPPORTED_MESSAGE,
        )
    return _dispatch(capability, http_request)
