"""Strict confirmation decision endpoint.

``POST /api/assistant/confirmations/{challenge_id}/decision`` accepts exactly
one decision (``confirm``, ``cancel``, or ``reject``) and, for a confirmation,
the short display code. It accepts no operation identifier, target, scope,
parameters, authorization scope, policy identity, or ``confirmed`` flag: the
stored record is the authority for which operation is being decided.

Every request is checked against the configured local origin before anything
is read or written, and every refusal returns the same value-free wording, so
a caller cannot learn whether a challenge exists or how close a guess was.
The endpoint never evaluates its own authorization rules; it delegates to the
server-side confirmation service.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from rop.api.origin import require_local_origin
from rop.authorization.executors import ExecutorRegistry
from rop.authorization.policy import AuthorizationPolicy
from rop.database import get_db
from rop.repositories.assistant_confirmation import AssistantConfirmationRepository
from rop.schemas.confirmation import (
    ConfirmationDecisionRequest,
    ConfirmationDecisionResponse,
)
from rop.services.confirmation import decide
from rop.services.workspace_executor import (
    build_workspace_executor_registry,
    build_workspace_policy,
)

router = APIRouter(
    prefix="/api/assistant/confirmations", tags=["assistant-confirmations"]
)

_POLICY: AuthorizationPolicy = build_workspace_policy()
_EXECUTORS: ExecutorRegistry = build_workspace_executor_registry()
_REPOSITORY = AssistantConfirmationRepository()


@router.post(
    "/{challenge_id}/decision",
    response_model=ConfirmationDecisionResponse,
    dependencies=[Depends(require_local_origin)],
    responses={
        403: {
            "description": (
                "The request did not come from the configured local origin, "
                "or did not use a JSON content type."
            ),
        },
        422: {
            "description": (
                "The decision body is malformed, carries unknown fields, or "
                "omits a required display code."
            ),
        },
    },
)
def decide_confirmation(
    challenge_id: str,
    body: ConfirmationDecisionRequest,
    db: Session = Depends(get_db),
) -> ConfirmationDecisionResponse:
    """Apply a decision to one challenge and return its sanitized result.

    The stored record decides which operation is in question; nothing in the
    path or body can change it. A confirmation is consumed at most once,
    committed before any executor runs, and every failure path executes
    nothing and returns the same generic refusal.
    """
    result = decide(
        db,
        challenge_id,
        decision=body.decision,
        display_code=body.display_code,
        policy=_POLICY,
        executors=_EXECUTORS,
        repository=_REPOSITORY,
    )
    return ConfirmationDecisionResponse(
        status=result.outcome,
        message=result.message,
        executed=result.executed,
    )
