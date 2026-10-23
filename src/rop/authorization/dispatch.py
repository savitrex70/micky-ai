"""Policy-enforced dispatch boundary for the assistant capability registry.

A matched capability is a candidate, not an answer. This boundary turns the
capability the deterministic registry already resolved into a
``ProposedOperation`` and asks the authorization policy what may happen
next. The capability's predefined response is selected only when the
decision is ``ALLOW``. Every other outcome, and every failure to evaluate
the policy at all, stops dispatch and returns an honest non-success
envelope.

This boundary obtains no confirmation and manufactures none. It accepts no
``AuthorizedScope``, no ``confirmed`` flag, and no permission assertion from
anywhere: its only inputs are a capability the registry already resolved and
the explicitly configured policy. There is therefore no way for a caller to
reach a state-changing operation through it, and a consequential capability
would remain non-executable without a registered executor. The separate
trusted confirmation workflow (`src/rop/services/confirmation.py`,
`src/rop/api/confirmations.py`) implements the server-side lifecycle that
obtains, records, and consumes a user's approval, and the executor boundary
(`src/rop/authorization/executors.py`) runs only after consumption. That
workflow does not accept a caller-supplied `confirmed` flag,
`AuthorizedScope`, or permission assertion either. This generic dispatch
boundary never executes a mutation. Its default executor factory is empty;
the workspace feature constructs a separate whitelist registry for fixed
note/task/reminder/retrieval-root operations that still require the trusted
confirmation flow and durable idempotency receipt. The first-party browser
confirmation UI exists separately. This boundary continues to fail closed.

Nothing here executes, persists, logs, or records anything, and it touches
no database, model, or network.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from rop.authorization.policy import (
    AuthorizationPolicy,
    evaluate_authorization,
)
from rop.capabilities.registry import Capability
from rop.schemas.assistant import AssistantResponse, AssistantStatus
from rop.schemas.authorization import (
    AuthorizationOutcome,
    ProposedOperation,
)

NOT_EXECUTED_NOTE = "This request was not executed and was not saved."
"""The sentence every non-success envelope carries.

A refusal, a clarification, or a confirmation requirement is only honest if
it also says that nothing happened.
"""

_CLARIFY_MESSAGE = (
    "This request is not specific enough for an operation to be selected "
    f"safely. {NOT_EXECUTED_NOTE}"
)
_CONFIRMATION_MESSAGE = (
    "This operation needs your explicit confirmation for this exact action "
    "before it may run, and no executor for it is available in this build, "
    f"so it was not run and cannot be completed here. {NOT_EXECUTED_NOTE}"
)
_REFUSED_MESSAGE = (
    "This operation is not permitted by the current authorization policy. "
    f"{NOT_EXECUTED_NOTE}"
)
_UNEVALUABLE_MESSAGE = (
    "The authorization policy for this request could not be evaluated, so "
    f"nothing was permitted. {NOT_EXECUTED_NOTE}"
)

_NON_SUCCESS_STATUS: Mapping[AuthorizationOutcome, AssistantStatus] = MappingProxyType(
    {
        AuthorizationOutcome.CLARIFY: "clarification-required",
        AuthorizationOutcome.REQUIRE_CONFIRMATION: "confirmation-required",
        AuthorizationOutcome.DENY: "refused",
    }
)
"""The status each non-``ALLOW`` outcome reports.

``ALLOW`` is absent on purpose: it is handled by ``capability_reply`` and is
the only outcome that can produce ``success``.
"""

_NON_SUCCESS_MESSAGE: Mapping[AssistantStatus, str] = MappingProxyType(
    {
        "clarification-required": _CLARIFY_MESSAGE,
        "confirmation-required": _CONFIRMATION_MESSAGE,
        "refused": _REFUSED_MESSAGE,
    }
)


def blocked_status(outcome: AuthorizationOutcome) -> AssistantStatus:
    """Return the honest non-success status for a non-``ALLOW`` outcome.

    An outcome this boundary does not recognise is reported as ``refused``
    rather than passed through: the default is the safest status, never the
    most permissive one.
    """
    return _NON_SUCCESS_STATUS.get(outcome, "refused")


def blocked_response(outcome: AuthorizationOutcome) -> AssistantResponse:
    """Return the static, input-free envelope for a blocked outcome."""
    status = blocked_status(outcome)
    return AssistantResponse(status=status, message=_NON_SUCCESS_MESSAGE[status])


def capability_reply(capability: Capability) -> str:
    """Select the registered capability's predefined response.

    This is the only path that produces a ``success`` envelope, and it is
    reached only when the authorization decision for the capability is
    ``ALLOW``. It is a separate function so tests can assert that it is
    never reached for any other outcome. It performs nothing: a registered
    capability holds a predefined deterministic response, and selecting it
    executes no operation, persists nothing, and calls no model.
    """
    return capability.response


def authorize_capability_dispatch(
    capability: Capability,
    *,
    policy: AuthorizationPolicy,
) -> AssistantResponse:
    """Return the response envelope for an already matched capability.

    The policy is consulted before anything is returned. A capability the
    policy does not register, or one whose outcome is not ``ALLOW``, yields
    a non-success status and never the capability's reply. A policy or a
    proposal that cannot be evaluated permits nothing, so an evaluation
    failure is reported as a sanitized refusal instead of falling through to
    the capability.
    """
    try:
        decision = evaluate_authorization(
            ProposedOperation(operation_id=capability.identifier),
            policy=policy,
        )
    except Exception:
        # Fail closed. This deliberately catches broadly: any failure to
        # establish that the operation is allowed must stop dispatch, and
        # the caller learns only that nothing ran - never an exception
        # message, which could carry policy or input detail.
        return AssistantResponse(status="refused", message=_UNEVALUABLE_MESSAGE)

    if decision.outcome is AuthorizationOutcome.ALLOW:
        return AssistantResponse(
            status="success",
            message=capability_reply(capability),
        )
    return blocked_response(decision.outcome)
