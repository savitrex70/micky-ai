"""Deterministic, fail-closed authorization policy for the assistant layer.

``evaluate_authorization`` states what must happen next for one proposed
operation: ``ALLOW``, ``CLARIFY``, ``REQUIRE_CONFIRMATION``, or ``DENY``.
It evaluates only. It does not execute, persist, log, or record an
operation, it does not access the database or the network, it does not
call a model, and it never mints a confirmation.

The evaluator is deterministic: the same policy, operation, and supplied
authorization always produce an equal decision.

Fail-closed ordering
--------------------
Rules are applied in a fixed order, and the most restrictive applicable
answer wins:

1. an unusable proposal is denied (``OPERATION_INVALID``);
2. an unregistered operation is denied (``OPERATION_UNSUPPORTED``);
3. a prohibited operation is denied (``OPERATION_PROHIBITED``), even when
   a matching authorization is supplied;
4. an unclassified operation is denied (``RISK_UNCLASSIFIED``), so
   missing risk information can never grant permission;
5. an under-specified operation requires clarification
   (``TARGET_MISSING`` / ``PARAMETER_MISSING``), and confirmation of an
   under-specified operation is not valid authorization, so this check
   precedes any confirmation decision;
6. a ``LOW``-risk operation is allowed (``ALLOWED_LOW_RISK``);
7. a ``CONSEQUENTIAL`` operation is allowed only against a supplied scope
   that covers it exactly (``ALLOWED_BY_AUTHORIZATION``); otherwise it
   requires a fresh authorization decision (``AUTHORIZATION_REQUIRED``
   when none is supplied, ``AUTHORIZATION_SCOPE_MISMATCH`` when the
   supplied scope is for something materially different).

Integration boundary
--------------------
This module is deliberately not wired into the assistant request path.
``src/rop/api/assistant.py`` serves only the registered ``help``
capability, which changes no state, so there is nothing for the policy to
gate yet. A ``DENY`` or ``REQUIRE_CONFIRMATION`` outcome is only as
strong as the code path that honours it, and no such enforcement path
exists today. ``AuthorizedScope`` is a comparison input only: this module
cannot tell whether a scope was actually authorized by a user, and
supplying one is an assertion by the caller. The end-to-end permission
flow - obtaining, verifying, and recording a user's confirmation - is not
implemented here and is not claimed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rop.schemas.authorization import (
    REASON_OUTCOMES,
    AuthorizationDecision,
    AuthorizationErrorCode,
    AuthorizationPolicy,
    AuthorizationReason,
    AuthorizedScope,
    OperationRule,
    ProposedOperation,
    RiskLevel,
)

HELP_OPERATION_ID = "help"
"""The only registered assistant capability that changes no state."""

DEFAULT_POLICY_RULES: tuple[OperationRule, ...] = (
    OperationRule(
        operation_id=HELP_OPERATION_ID,
        description="Explain what the assistant can and cannot currently do.",
        risk=RiskLevel.LOW,
    ),
)
"""The default rule table.

It contains exactly the operations that exist today. No rule is derived
from the capability registry on purpose: a capability added to the
registry without a deliberate policy rule is denied as unsupported
instead of silently inheriting permission. The default table therefore
registers no state-changing operation, and ``REQUIRE_CONFIRMATION`` is
not reachable through it until a consequential operation is added with an
explicit rule.
"""


class AuthorizationPolicyError(Exception):
    """A typed policy failure with a static, sanitized message."""

    def __init__(self, code: AuthorizationErrorCode, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


def build_default_policy() -> AuthorizationPolicy:
    """Return the policy for the operations that actually exist."""
    return AuthorizationPolicy(rules=DEFAULT_POLICY_RULES)


def _checked_policy(policy: AuthorizationPolicy) -> AuthorizationPolicy:
    """Re-validate a policy so a mutated instance cannot pass as valid."""
    try:
        if isinstance(policy, AuthorizationPolicy):
            return AuthorizationPolicy.model_validate(policy.model_dump())
    except Exception as exc:
        raise AuthorizationPolicyError(
            AuthorizationErrorCode.INVALID_POLICY, "authorization policy is invalid"
        ) from exc
    raise AuthorizationPolicyError(
        AuthorizationErrorCode.INVALID_POLICY, "authorization policy is invalid"
    )


def _checked_operation(
    operation: ProposedOperation | Mapping[str, Any],
) -> ProposedOperation:
    """Re-validate a proposal, chaining nothing so no value can leak.

    Validation errors quote the offending input. A target, scope, or
    parameter value is private user information, so the cause is dropped
    rather than chained onto the raised error.
    """
    try:
        if isinstance(operation, ProposedOperation):
            return ProposedOperation.model_validate(operation.model_dump())
        if isinstance(operation, Mapping):
            return ProposedOperation.model_validate(dict(operation))
    except Exception:
        raise AuthorizationPolicyError(
            AuthorizationErrorCode.INVALID_OPERATION, "proposed operation is invalid"
        ) from None
    raise AuthorizationPolicyError(
        AuthorizationErrorCode.INVALID_OPERATION, "proposed operation is invalid"
    )


def _checked_authorization(
    authorized: AuthorizedScope | None,
) -> AuthorizedScope | None:
    """Re-validate a supplied authorization, keeping values out of errors."""
    if authorized is None:
        return None
    try:
        if isinstance(authorized, AuthorizedScope):
            return AuthorizedScope.model_validate(authorized.model_dump())
    except Exception:
        raise AuthorizationPolicyError(
            AuthorizationErrorCode.INVALID_AUTHORIZATION,
            "supplied authorization is invalid",
        ) from None
    raise AuthorizationPolicyError(
        AuthorizationErrorCode.INVALID_AUTHORIZATION,
        "supplied authorization is invalid",
    )


def _decision(
    policy: AuthorizationPolicy,
    operation_id: str,
    reason: AuthorizationReason,
) -> AuthorizationDecision:
    """Build a decision whose outcome follows from its reason."""
    return AuthorizationDecision(
        policy_version=policy.policy_version,
        operation_id=operation_id,
        outcome=REASON_OUTCOMES[reason],
        reason=reason,
    )


def evaluate_authorization(
    operation: ProposedOperation | Mapping[str, Any],
    *,
    policy: AuthorizationPolicy,
    authorized: AuthorizedScope | None = None,
) -> AuthorizationDecision:
    """Decide what must happen next for ``operation`` under ``policy``.

    ``authorized`` describes what the calling boundary asserts is already
    authorized. It defaults to nothing, which is the only safe default: an
    absent authorization can never produce ``ALLOW`` for a consequential
    operation. Passing a scope that does not cover ``operation`` exactly
    does not authorize it.
    """
    checked_policy = _checked_policy(policy)
    checked_operation = _checked_operation(operation)
    checked_authorized = _checked_authorization(authorized)

    operation_id = checked_operation.operation_id.strip()
    if not operation_id:
        return _decision(
            checked_policy,
            operation_id,
            AuthorizationReason.OPERATION_INVALID,
        )

    rule = checked_policy.rule(operation_id)
    if rule is None:
        return _decision(
            checked_policy,
            operation_id,
            AuthorizationReason.OPERATION_UNSUPPORTED,
        )
    if rule.prohibited:
        return _decision(
            checked_policy,
            operation_id,
            AuthorizationReason.OPERATION_PROHIBITED,
        )
    if rule.risk is None:
        return _decision(
            checked_policy,
            operation_id,
            AuthorizationReason.RISK_UNCLASSIFIED,
        )
    if rule.requires_target and checked_operation.target is None:
        return _decision(
            checked_policy,
            operation_id,
            AuthorizationReason.TARGET_MISSING,
        )
    supplied_parameters = set(checked_operation.parameters)
    if not set(rule.required_parameters) <= supplied_parameters:
        return _decision(
            checked_policy,
            operation_id,
            AuthorizationReason.PARAMETER_MISSING,
        )
    if rule.risk is RiskLevel.LOW:
        return _decision(
            checked_policy,
            operation_id,
            AuthorizationReason.ALLOWED_LOW_RISK,
        )
    if checked_authorized is not None and checked_authorized.covers(checked_operation):
        return _decision(
            checked_policy,
            operation_id,
            AuthorizationReason.ALLOWED_BY_AUTHORIZATION,
        )
    if checked_authorized is None:
        return _decision(
            checked_policy,
            operation_id,
            AuthorizationReason.AUTHORIZATION_REQUIRED,
        )
    return _decision(
        checked_policy,
        operation_id,
        AuthorizationReason.AUTHORIZATION_SCOPE_MISMATCH,
    )
