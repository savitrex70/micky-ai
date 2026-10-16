"""Honest capability-routed endpoint for the local assistant interface.

Requests are matched against a small deterministic registry of registered
capabilities. A match is not enough to answer: the authorization policy for
the resolved capability is evaluated first, and the capability's predefined
response is returned only when that decision is ``ALLOW``. Every other
outcome stops dispatch and returns an explicit non-success envelope, as
does an unmatched request. The endpoint does not access the database, does
not persist anything, does not call a model, and never echoes the user's
message.
"""

from fastapi import APIRouter

from rop.authorization.dispatch import authorize_capability_dispatch
from rop.authorization.policy import AuthorizationPolicy, build_default_policy
from rop.capabilities.registry import CapabilityRegistry, build_default_registry
from rop.schemas.assistant import AssistantRequest, AssistantResponse

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

_UNSUPPORTED_MESSAGE = (
    "No matching capability is currently available. "
    "This request was not executed and was not saved."
)


@router.post(
    "/requests",
    response_model=AssistantResponse,
    responses={
        422: {
            "description": (
                "Request body is empty, whitespace-only, overlong, or "
                "contains unexpected fields."
            ),
        },
    },
)
def submit_request(request: AssistantRequest) -> AssistantResponse:
    """Match ``request.message`` to a registered capability, then authorize it.

    The user's message is used only to select a capability and is not echoed
    into the response. An invalid, ambiguous, or unregistered request
    resolves to the explicit unsupported-capability envelope. A matched
    capability is dispatched only when the authorization policy returns
    ``ALLOW``; every other outcome returns the corresponding non-success
    status and no capability response.

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
    return authorize_capability_dispatch(capability, policy=_POLICY)
