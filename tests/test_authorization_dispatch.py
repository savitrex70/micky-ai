"""Tests for the policy-enforced assistant capability dispatch boundary.

These tests assert the security behaviour of the boundary, not the
existence of a helper: a capability's predefined response is selected only
for ``ALLOW``, every other outcome and every policy failure stops dispatch,
and a caller cannot supply an authorization assertion.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

import rop.authorization.dispatch as dispatch_module
from rop.authorization.dispatch import (
    NOT_EXECUTED_NOTE,
    authorize_capability_dispatch,
    blocked_status,
)
from rop.authorization.policy import build_default_policy
from rop.capabilities.registry import (
    HELP_IDENTIFIER,
    HELP_RESPONSE,
    Capability,
    build_default_registry,
)
from rop.database import SessionLocal
from rop.schemas.authorization import (
    AuthorizationOutcome,
    AuthorizationPolicy,
    OperationRule,
    RiskLevel,
)

ALLOWED_IDENTIFIER = HELP_IDENTIFIER
CLARIFY_IDENTIFIER = "demo-delete"
CONFIRM_IDENTIFIER = "demo-write"
DENIED_IDENTIFIER = "demo-exec"
UNCLASSIFIED_IDENTIFIER = "demo-unclassified"
UNLISTED_IDENTIFIER = "demo-unlisted"

REPLY = "DEMO PREDEFINED REPLY"

SUCCESS_STATUS = "success"
UNSUPPORTED_STATUS = "unsupported-capability"
BLOCKED_STATUSES = frozenset(
    {
        "clarification-required",
        "confirmation-required",
        "refused",
    }
)
"""Every status the dispatch boundary can report for a matched capability."""


def _capability(identifier: str, *, response: str = REPLY) -> Capability:
    return Capability(
        identifier=identifier,
        description=f"Test capability {identifier}.",
        aliases=(identifier.replace("-", " "),),
        response=response,
    )


def _rule(
    identifier: str,
    *,
    risk: RiskLevel | None = RiskLevel.LOW,
    prohibited: bool = False,
    requires_target: bool = False,
) -> OperationRule:
    return OperationRule(
        operation_id=identifier,
        description=f"Test rule for {identifier}.",
        risk=risk,
        prohibited=prohibited,
        requires_target=requires_target,
    )


def _policy(*rules: OperationRule) -> AuthorizationPolicy:
    return AuthorizationPolicy(rules=rules)


def _demo_policy() -> AuthorizationPolicy:
    """A policy spanning every outcome the boundary must handle."""
    return _policy(
        _rule(ALLOWED_IDENTIFIER, risk=RiskLevel.LOW),
        _rule(CLARIFY_IDENTIFIER, risk=RiskLevel.CONSEQUENTIAL, requires_target=True),
        _rule(CONFIRM_IDENTIFIER, risk=RiskLevel.CONSEQUENTIAL),
        _rule(DENIED_IDENTIFIER, risk=RiskLevel.CONSEQUENTIAL, prohibited=True),
        _rule(UNCLASSIFIED_IDENTIFIER, risk=None),
    )


@pytest.fixture
def dispatch_calls(monkeypatch):
    """Record every call to the capability-response selection step."""
    calls: list[Capability] = []

    def spy(capability: Capability) -> str:
        calls.append(capability)
        return capability.response

    monkeypatch.setattr(dispatch_module, "capability_reply", spy)
    return calls


# --- allowed capabilities still answer ---------------------------------------


def test_allowed_capability_dispatches_its_predefined_response(dispatch_calls) -> None:
    capability = _capability(ALLOWED_IDENTIFIER)

    response = authorize_capability_dispatch(capability, policy=_demo_policy())

    assert response.status == SUCCESS_STATUS
    assert response.message == REPLY
    assert dispatch_calls == [capability]


def test_default_policy_allows_the_non_state_changing_help_capability(
    dispatch_calls,
) -> None:
    capability = _capability(ALLOWED_IDENTIFIER, response=HELP_RESPONSE)

    response = authorize_capability_dispatch(capability, policy=build_default_policy())

    assert response.status == SUCCESS_STATUS
    assert response.message == HELP_RESPONSE
    assert len(dispatch_calls) == 1


# --- every other outcome stops dispatch --------------------------------------


@pytest.mark.parametrize(
    ("identifier", "expected_status"),
    [
        (CLARIFY_IDENTIFIER, "clarification-required"),
        (CONFIRM_IDENTIFIER, "confirmation-required"),
        (DENIED_IDENTIFIER, "refused"),
        (UNCLASSIFIED_IDENTIFIER, "refused"),
        (UNLISTED_IDENTIFIER, "refused"),
    ],
)
def test_non_allow_outcome_never_dispatches(
    dispatch_calls, identifier: str, expected_status: str
) -> None:
    response = authorize_capability_dispatch(
        _capability(identifier), policy=_demo_policy()
    )

    assert response.status == expected_status
    assert dispatch_calls == []
    assert REPLY not in response.message
    assert NOT_EXECUTED_NOTE in response.message


def test_only_allow_can_produce_a_success_status(dispatch_calls) -> None:
    policy = _demo_policy()
    statuses = {
        identifier: authorize_capability_dispatch(
            _capability(identifier), policy=policy
        ).status
        for identifier in (
            ALLOWED_IDENTIFIER,
            CLARIFY_IDENTIFIER,
            CONFIRM_IDENTIFIER,
            DENIED_IDENTIFIER,
            UNCLASSIFIED_IDENTIFIER,
            UNLISTED_IDENTIFIER,
        )
    }

    assert statuses[ALLOWED_IDENTIFIER] == SUCCESS_STATUS
    assert set(statuses.values()) - {SUCCESS_STATUS} == BLOCKED_STATUSES
    assert UNSUPPORTED_STATUS not in set(statuses.values())
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0].identifier == ALLOWED_IDENTIFIER


def test_registered_capability_absent_from_the_policy_is_blocked(
    dispatch_calls,
) -> None:
    """Registering a capability must not authorize it."""
    registry = build_default_registry()
    registry.register(_capability("demo-new"))
    registered = registry.match("demo new")
    assert registered is not None

    response = authorize_capability_dispatch(registered, policy=build_default_policy())

    assert response.status == "refused"
    assert dispatch_calls == []
    assert REPLY not in response.message


# --- failures fail closed ----------------------------------------------------


def test_a_policy_that_cannot_be_evaluated_fails_closed(dispatch_calls) -> None:
    capability = _capability(ALLOWED_IDENTIFIER)

    for broken in ("not-a-policy", None, 7, ["help"]):
        response = authorize_capability_dispatch(
            capability,  # type: ignore[arg-type]
            policy=broken,  # type: ignore[arg-type]
        )
        assert response.status == "refused"
        assert NOT_EXECUTED_NOTE in response.message

    assert dispatch_calls == []


def test_unexpected_evaluation_error_never_dispatches(
    monkeypatch, dispatch_calls
) -> None:
    detail = "SENSITIVE_INTERNAL_DETAIL_7A2"

    def exploding_evaluator(*args, **kwargs):
        raise RuntimeError(detail)

    monkeypatch.setattr(dispatch_module, "evaluate_authorization", exploding_evaluator)

    response = authorize_capability_dispatch(
        _capability(ALLOWED_IDENTIFIER), policy=build_default_policy()
    )

    assert response.status == "refused"
    assert detail not in response.message
    assert dispatch_calls == []


def test_forged_malformed_identifier_is_refused(dispatch_calls) -> None:
    """The boundary must not trust the registry's identifier contract."""
    forged = dataclasses.replace(_capability(ALLOWED_IDENTIFIER), identifier="help\n")

    response = authorize_capability_dispatch(forged, policy=build_default_policy())

    assert response.status == "refused"
    assert dispatch_calls == []


# --- the caller cannot supply authorization ----------------------------------


def test_boundary_accepts_no_authorization_or_confirmation_argument() -> None:
    """There is no parameter through which permission could be asserted."""
    parameters = set(inspect.signature(authorize_capability_dispatch).parameters)

    assert parameters == {"capability", "policy"}


def test_status_for_an_unknown_outcome_is_the_safest_one() -> None:
    for outcome in AuthorizationOutcome:
        status = blocked_status(outcome)
        if outcome is AuthorizationOutcome.ALLOW:
            # ``ALLOW`` is never reached here, and even if it were it must
            # not be reported as successful by the blocked path.
            assert status != SUCCESS_STATUS
            continue
        assert status in BLOCKED_STATUSES

    assert blocked_status("NOT_AN_OUTCOME") == "refused"  # type: ignore[arg-type]


# --- no side effects ---------------------------------------------------------


def test_dispatch_boundary_does_not_touch_the_database(monkeypatch) -> None:
    calls = {"count": 0}
    real = SessionLocal

    def counting_session_local(*args, **kwargs):
        calls["count"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr("rop.database.SessionLocal", counting_session_local)

    authorize_capability_dispatch(
        _capability(ALLOWED_IDENTIFIER), policy=build_default_policy()
    )
    authorize_capability_dispatch(
        _capability(UNLISTED_IDENTIFIER), policy=build_default_policy()
    )

    assert calls["count"] == 0


def test_dispatch_module_imports_no_network_or_model_facilities() -> None:
    source = dispatch_module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        text = handle.read()

    for forbidden in (
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
        "torch",
        "transformers",
        "ollama",
        "openai",
    ):
        assert forbidden not in text, f"forbidden dependency reference: {forbidden}"


# --- existing deterministic behaviour is unchanged ---------------------------


def test_capability_registry_behaviour_is_unchanged() -> None:
    registry = build_default_registry()

    assert len(registry) == 1
    assert registry.capabilities()[0].identifier == HELP_IDENTIFIER
    assert registry.match("  HELP!  ") is not None
    assert registry.match("help me write a note") is None
