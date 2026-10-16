"""Honest placeholder endpoint for the local assistant web interface.

Capability routing has not been implemented. Every well-formed request
receives an explicit ``unsupported-capability`` envelope. The endpoint does
not access the database, does not persist anything, and does not echo the
user's message back in the response.
"""

from fastapi import APIRouter

from rop.schemas.assistant import AssistantRequest, AssistantResponse

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

_UNSUPPORTED_MESSAGE = (
    "No assistant capability is currently connected. "
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
def submit_request(_: AssistantRequest) -> AssistantResponse:
    """Return the honest unsupported-capability envelope.

    The parsed request is intentionally ignored: the endpoint never reads
    ``request.message`` so it cannot echo the user's text into the response,
    logs, or exception details.
    """
    return AssistantResponse(
        status="unsupported-capability",
        message=_UNSUPPORTED_MESSAGE,
    )
