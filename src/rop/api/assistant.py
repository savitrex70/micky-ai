"""Honest capability-routed endpoint for the local assistant interface.

Requests are matched against a small deterministic registry of registered
capabilities. If exactly one capability matches, its predefined response is
returned. Otherwise the endpoint returns an explicit unsupported-capability
envelope. The endpoint does not access the database, does not persist
anything, does not call a model, and never echoes the user's message.
"""

from fastapi import APIRouter

from rop.capabilities.registry import CapabilityRegistry, build_default_registry
from rop.schemas.assistant import AssistantRequest, AssistantResponse

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_REGISTRY: CapabilityRegistry = build_default_registry()

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
    """Match ``request.message`` to a registered capability.

    The user's message is used only to select a capability and is not echoed
    into the response. Invalid, ambiguous, or unregistered requests resolve
    to the explicit unsupported-capability envelope.
    """
    capability = _REGISTRY.match(request.message)
    if capability is None:
        return AssistantResponse(
            status="unsupported-capability",
            message=_UNSUPPORTED_MESSAGE,
        )
    return AssistantResponse(
        status="success",
        message=capability.response,
    )
