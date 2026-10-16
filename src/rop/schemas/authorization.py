"""Stage 9 assistant authorization-policy contracts.

Data-only contracts for the deterministic, fail-closed, risk-based
authorization decision over one proposed assistant operation. Nothing
here executes, persists, or records anything: an ``AuthorizationDecision``
states only what must happen next.

These contracts deliberately do not model a user's confirmation. There is
no receipt, token, nonce, or confirmation record in this module, and no
policy result is evidence that a user approved anything. ``AuthorizedScope``
describes what the boundary that owns the real permission interaction
asserts is already authorized for exactly one operation; creating that
assertion, and the interaction behind it, are outside this module and are
not implemented.

Operation identifiers are machine-facing names, not user text. They are
matched exactly: surrounding whitespace, case, and embedded spacing are
never trimmed, lowercased, or otherwise canonicalized, so a malformed
identifier such as ``"help\n"`` cannot resolve to the registered ``help``
operation. An identifier that violates the contract is not an operation
at all and is rejected as invalid input rather than described in a
decision.

Every reason code maps to exactly one outcome, and a decision pairing a
reason with the wrong outcome cannot be constructed. Failure always fails
closed: an unregistered, prohibited, unclassified, or unresolvable
proposal is denied, never allowed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AUTHORIZATION_CONTRACT_VERSION = "1"
MAX_OPERATION_ID_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 240
MAX_TARGET_LENGTH = 512
MAX_SCOPE_LENGTH = 512
MAX_PARAMETER_NAME_LENGTH = 64
MAX_PARAMETER_VALUE_LENGTH = 512
MAX_PARAMETERS = 16
MAX_RULES = 256

# Identifiers are machine-facing names resolved by the deterministic
# capability registry, not user text. The pattern matches the capability
# identifier contract in ``rop.capabilities.registry``.
_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class AuthorizationErrorCode(StrEnum):
    """Stable, sanitized policy failure codes.

    These describe a broken policy or a malformed evaluator input. They
    carry no user content: a caller must never learn a target, parameter,
    or message value from a failure.
    """

    INVALID_POLICY = "INVALID_POLICY"
    INVALID_OPERATION = "INVALID_OPERATION"
    INVALID_AUTHORIZATION = "INVALID_AUTHORIZATION"


class RiskLevel(StrEnum):
    """How much care an operation needs before it may run.

    ``LOW`` operations are supported, explicitly permitted by the policy,
    and require no additional confirmation. ``CONSEQUENTIAL`` operations
    can cause harm: they change or destroy state, disclose private
    information, produce external side effects, incur cost, or are hard to
    reverse. They may not run without an explicit, matching authorization.

    Risk is never inferred. An operation whose rule carries no risk level
    is unclassified and is denied.
    """

    LOW = "LOW"
    CONSEQUENTIAL = "CONSEQUENTIAL"


class AuthorizationOutcome(StrEnum):
    """What must happen next for one proposed operation.

    An outcome is a policy statement, not an execution. ``ALLOW`` means
    the operation may be attempted by the code path that owns it; it does
    not execute anything, and it is not proof that a user confirmed
    anything. ``CLARIFY`` means no operation could be selected safely.
    ``REQUIRE_CONFIRMATION`` means explicit user permission for this exact
    operation is required first. ``DENY`` means the operation must not be
    performed under any provided authorization.
    """

    ALLOW = "ALLOW"
    CLARIFY = "CLARIFY"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    DENY = "DENY"


class AuthorizationReason(StrEnum):
    """Why an outcome was reached. Exactly one outcome per reason.

    There is deliberately no reason code for a malformed identifier. A
    malformed identifier is not a registered or unregistered operation but
    an unusable input, so it is rejected before a decision exists rather
    than being reported as a decision about an operation that was never
    valid. Consequently every reason here is reachable.
    """

    OPERATION_UNSUPPORTED = "OPERATION_UNSUPPORTED"
    OPERATION_PROHIBITED = "OPERATION_PROHIBITED"
    RISK_UNCLASSIFIED = "RISK_UNCLASSIFIED"
    TARGET_MISSING = "TARGET_MISSING"
    PARAMETER_MISSING = "PARAMETER_MISSING"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    AUTHORIZATION_SCOPE_MISMATCH = "AUTHORIZATION_SCOPE_MISMATCH"
    ALLOWED_LOW_RISK = "ALLOWED_LOW_RISK"
    ALLOWED_BY_AUTHORIZATION = "ALLOWED_BY_AUTHORIZATION"


REASON_OUTCOMES: Mapping[AuthorizationReason, AuthorizationOutcome] = MappingProxyType(
    {
        AuthorizationReason.OPERATION_UNSUPPORTED: AuthorizationOutcome.DENY,
        AuthorizationReason.OPERATION_PROHIBITED: AuthorizationOutcome.DENY,
        AuthorizationReason.RISK_UNCLASSIFIED: AuthorizationOutcome.DENY,
        AuthorizationReason.TARGET_MISSING: AuthorizationOutcome.CLARIFY,
        AuthorizationReason.PARAMETER_MISSING: AuthorizationOutcome.CLARIFY,
        AuthorizationReason.AUTHORIZATION_REQUIRED: (
            AuthorizationOutcome.REQUIRE_CONFIRMATION
        ),
        AuthorizationReason.AUTHORIZATION_SCOPE_MISMATCH: (
            AuthorizationOutcome.REQUIRE_CONFIRMATION
        ),
        AuthorizationReason.ALLOWED_LOW_RISK: AuthorizationOutcome.ALLOW,
        AuthorizationReason.ALLOWED_BY_AUTHORIZATION: AuthorizationOutcome.ALLOW,
    }
)
"""The single outcome each reason can produce.

A decision is constructed from a reason, so an outcome that contradicts
its reason is unrepresentable rather than merely discouraged.
"""


def _is_printable_text(value: str) -> bool:
    return value.isprintable()


def _validate_operation_identifier(value: str) -> str:
    """Enforce the exact identifier contract for a machine operation name.

    The value is returned unchanged. It is never trimmed, lowercased, or
    otherwise canonicalized: an identifier is either exactly one of the
    names the deterministic registry can resolve, or it is malformed.
    """
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError("invalid operation identifier")
    return value


def _normalize_optional_text(value: str | None) -> str | None:
    """Strip surrounding whitespace; treat an empty result as absent.

    A blank target is an unspecified target, not a different target. This
    keeps ``"   "`` and ``None`` from being mistaken for two distinct
    material values.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("text must be a string")
    stripped = value.strip()
    if not stripped:
        return None
    if not _is_printable_text(stripped):
        raise ValueError("text must be printable")
    return stripped


def _validate_parameters(value: dict[str, str]) -> dict[str, str]:
    """Normalize a parameter map to non-blank, printable machine values."""
    if not isinstance(value, dict):
        raise ValueError("parameters must be a mapping")
    if len(value) > MAX_PARAMETERS:
        raise ValueError("too many parameters")
    normalized: dict[str, str] = {}
    for name, item in value.items():
        if (
            not isinstance(name, str)
            or len(name) > MAX_PARAMETER_NAME_LENGTH
            or not _IDENTIFIER_PATTERN.fullmatch(name)
        ):
            raise ValueError("invalid parameter name")
        if not isinstance(item, str):
            raise ValueError("invalid parameter value")
        text = item.strip()
        if (
            not text
            or len(text) > MAX_PARAMETER_VALUE_LENGTH
            or not _is_printable_text(text)
        ):
            raise ValueError("invalid parameter value")
        normalized[name] = text
    return normalized


class ProposedOperation(BaseModel):
    """One proposed assistant operation and its material parameters.

    ``operation_id`` is an exact machine identifier and is never
    normalized. ``target`` and ``scope`` identify what would be acted
    upon; when a rule requires a target, an absent or blank target cannot
    be confirmed into existence and resolves to ``CLARIFY``. Those user
    values are stripped and blank becomes ``None``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1, max_length=MAX_OPERATION_ID_LENGTH)
    target: str | None = Field(default=None, max_length=MAX_TARGET_LENGTH)
    scope: str | None = Field(default=None, max_length=MAX_SCOPE_LENGTH)
    parameters: dict[str, str] = Field(default_factory=dict)

    @field_validator("operation_id")
    @classmethod
    def check_operation_id(cls, value: str) -> str:
        return _validate_operation_identifier(value)

    @field_validator("target", "scope")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("parameters")
    @classmethod
    def check_parameters(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_parameters(value)


class AuthorizedScope(BaseModel):
    """The exact operation a boundary asserts is already authorized.

    This is a comparison input, not a credential. It cannot be produced,
    signed, or verified here, and supplying one is an assertion by the
    caller that the boundary which owns the real permission interaction
    has obtained authorization for precisely these material values. The
    evaluator never mints, extends, or infers one, and it has no way to
    tell whether such authorization genuinely exists.

    ``operation_id`` carries the same exact identifier contract as
    ``ProposedOperation``, so a malformed identifier cannot be used to
    make an unusable operation look authorized by comparison.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1, max_length=MAX_OPERATION_ID_LENGTH)
    target: str | None = Field(default=None, max_length=MAX_TARGET_LENGTH)
    scope: str | None = Field(default=None, max_length=MAX_SCOPE_LENGTH)
    parameters: dict[str, str] = Field(default_factory=dict)

    @field_validator("operation_id")
    @classmethod
    def check_operation_id(cls, value: str) -> str:
        return _validate_operation_identifier(value)

    @field_validator("target", "scope")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("parameters")
    @classmethod
    def check_parameters(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_parameters(value)

    def covers(self, operation: ProposedOperation) -> bool:
        """Return True only for the same operation and material values.

        Authorization for one target, scope, or parameter set does not
        extend to a materially different operation. A value of the wrong
        type is not covered, so an unusable input fails closed.
        """
        if not isinstance(operation, ProposedOperation):
            return False
        return _material_key(
            operation_id=self.operation_id,
            target=self.target,
            scope=self.scope,
            parameters=self.parameters,
        ) == _material_key(
            operation_id=operation.operation_id,
            target=operation.target,
            scope=operation.scope,
            parameters=operation.parameters,
        )


def _material_key(
    *,
    operation_id: str,
    target: str | None,
    scope: str | None,
    parameters: dict[str, str],
) -> tuple[str, str | None, str | None, tuple[tuple[str, str], ...]]:
    """A comparable, order-insensitive identity for material values.

    Operation identifiers are compared exactly. Only user-facing targets,
    scopes, and parameter values are normalized, and only because their
    normalization is part of the contract that accepted them.
    """
    return (
        operation_id,
        target,
        scope,
        tuple(sorted((str(k), str(v)) for k, v in parameters.items())),
    )


class OperationRule(BaseModel):
    """The policy's classification of one operation.

    ``risk=None`` means the operation is unclassified. An unclassified
    operation is denied, never allowed, so a rule cannot grant permission
    by omission. ``prohibited`` outranks every other field: a prohibited
    operation is denied even when a matching authorization is supplied.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1, max_length=MAX_OPERATION_ID_LENGTH)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_LENGTH)
    risk: RiskLevel | None = None
    prohibited: bool = False
    requires_target: bool = False
    required_parameters: tuple[str, ...] = ()

    @field_validator("operation_id")
    @classmethod
    def check_operation_id(cls, value: str) -> str:
        return _validate_operation_identifier(value)

    @field_validator("description")
    @classmethod
    def check_description(cls, value: str) -> str:
        if not value.strip() or not _is_printable_text(value):
            raise ValueError("invalid description")
        return value

    @field_validator("required_parameters")
    @classmethod
    def check_required_parameters(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > MAX_PARAMETERS:
            raise ValueError("too many required parameters")
        seen: set[str] = set()
        for name in value:
            if not isinstance(name, str) or not _IDENTIFIER_PATTERN.fullmatch(name):
                raise ValueError("invalid required parameter name")
            if name in seen:
                raise ValueError("duplicate required parameter name")
            seen.add(name)
        return value


class AuthorizationPolicy(BaseModel):
    """A versioned, ordered table of operation rules.

    Lookup is exact and case-sensitive on the operation identifier. The
    evaluator performs no normalization of its own, because the
    deterministic capability registry has already resolved the user's
    phrase into an identifier.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: Literal["1"] = AUTHORIZATION_CONTRACT_VERSION
    rules: tuple[OperationRule, ...] = ()

    @model_validator(mode="after")
    def check_rules(self) -> AuthorizationPolicy:
        if len(self.rules) > MAX_RULES:
            raise ValueError("too many rules")
        seen: set[str] = set()
        for rule in self.rules:
            if rule.operation_id in seen:
                raise ValueError("duplicate operation identifier")
            seen.add(rule.operation_id)
        return self

    def rule(self, operation_id: str) -> OperationRule | None:
        """Return the rule for ``operation_id``, or None if unregistered."""
        for rule in self.rules:
            if rule.operation_id == operation_id:
                return rule
        return None


class AuthorizationDecision(BaseModel):
    """A machine-readable statement of what must happen next.

    The decision carries no target, parameter, or message content, and it
    records no execution. ``outcome`` is always the outcome its ``reason``
    implies, so a contradictory decision cannot be built. ``operation_id``
    carries the same exact identifier contract as the proposal it decides,
    so a decision can never name a malformed identifier.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: Literal["1"] = AUTHORIZATION_CONTRACT_VERSION
    operation_id: str = Field(min_length=1, max_length=MAX_OPERATION_ID_LENGTH)
    outcome: AuthorizationOutcome
    reason: AuthorizationReason

    @field_validator("operation_id")
    @classmethod
    def check_operation_id(cls, value: str) -> str:
        return _validate_operation_identifier(value)

    @model_validator(mode="after")
    def check_pairing(self) -> AuthorizationDecision:
        if REASON_OUTCOMES[self.reason] is not self.outcome:
            raise ValueError("outcome does not match reason")
        return self

    @property
    def permits_execution(self) -> bool:
        """True only for ``ALLOW``.

        This describes what the owning code path may attempt. It performs
        nothing, records nothing, and is not evidence that a user
        confirmed anything.
        """
        return self.outcome is AuthorizationOutcome.ALLOW
