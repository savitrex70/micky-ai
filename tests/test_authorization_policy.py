"""Tests for the deterministic risk-based authorization policy.

These tests assert safety behaviour, not the existence of a class: which
outcome a proposal receives, that no outcome other than ``ALLOW`` permits
execution, that one action's authorization never extends to a materially
different one, that a machine operation identifier is matched exactly
rather than normalized into something valid, and that every failure mode
fails closed.
"""

import pytest
from pydantic import ValidationError

from rop.authorization.policy import (
    DEFAULT_POLICY_RULES,
    HELP_OPERATION_ID,
    AuthorizationPolicyError,
    build_default_policy,
    evaluate_authorization,
)
from rop.capabilities.registry import (
    HELP_IDENTIFIER,
    Capability,
    build_default_registry,
    normalize_phrase,
)
from rop.database import SessionLocal
from rop.schemas.authorization import (
    AUTHORIZATION_CONTRACT_VERSION,
    REASON_OUTCOMES,
    AuthorizationDecision,
    AuthorizationErrorCode,
    AuthorizationOutcome,
    AuthorizationPolicy,
    AuthorizationReason,
    AuthorizedScope,
    OperationRule,
    ProposedOperation,
    RiskLevel,
)

WRITE_OPERATION_ID = "demo-write"
DELETE_OPERATION_ID = "demo-delete"
DISCLOSE_OPERATION_ID = "demo-disclose"
PROHIBITED_OPERATION_ID = "demo-exec"
UNCLASSIFIED_OPERATION_ID = "demo-unclassified"


def _rule(
    operation_id: str,
    *,
    risk: RiskLevel | None = RiskLevel.LOW,
    prohibited: bool = False,
    requires_target: bool = False,
    required_parameters: tuple[str, ...] = (),
) -> OperationRule:
    return OperationRule(
        operation_id=operation_id,
        description=f"Test rule for {operation_id}.",
        risk=risk,
        prohibited=prohibited,
        requires_target=requires_target,
        required_parameters=required_parameters,
    )


def _policy(*rules: OperationRule) -> AuthorizationPolicy:
    return AuthorizationPolicy(rules=rules)


def _demo_policy() -> AuthorizationPolicy:
    """A fixture policy spanning every classification the safety rules use."""
    return _policy(
        _rule(HELP_OPERATION_ID, risk=RiskLevel.LOW),
        _rule(WRITE_OPERATION_ID, risk=RiskLevel.CONSEQUENTIAL),
        _rule(
            DELETE_OPERATION_ID,
            risk=RiskLevel.CONSEQUENTIAL,
            requires_target=True,
        ),
        _rule(
            DISCLOSE_OPERATION_ID,
            risk=RiskLevel.CONSEQUENTIAL,
            required_parameters=("recipient",),
        ),
        _rule(PROHIBITED_OPERATION_ID, risk=RiskLevel.CONSEQUENTIAL, prohibited=True),
        _rule(UNCLASSIFIED_OPERATION_ID, risk=None),
    )


# --- 1. clear, supported, low-risk operations may proceed --------------------


def test_supported_low_risk_operation_is_allowed() -> None:
    decision = evaluate_authorization(
        ProposedOperation(operation_id=HELP_OPERATION_ID),
        policy=build_default_policy(),
    )

    assert decision.outcome is AuthorizationOutcome.ALLOW
    assert decision.reason is AuthorizationReason.ALLOWED_LOW_RISK
    assert decision.permits_execution is True
    assert decision.policy_version == AUTHORIZATION_CONTRACT_VERSION


def test_default_policy_registers_exactly_the_existing_capability() -> None:
    policy = build_default_policy()

    assert [rule.operation_id for rule in policy.rules] == [HELP_OPERATION_ID]
    assert policy.rules[0].risk is RiskLevel.LOW
    assert policy.rules[0].requires_target is False
    assert policy.rules[0].required_parameters == ()
    assert policy.rules[0].prohibited is False


def test_default_policy_operation_ids_match_registered_capabilities() -> None:
    registry = build_default_registry()

    registered = {c.identifier for c in registry.capabilities()}
    governed = {rule.operation_id for rule in build_default_policy().rules}
    assert governed == registered


# --- 2. potentially harmful operations require confirmation -----------------


def test_consequential_operation_requires_confirmation() -> None:
    decision = evaluate_authorization(
        ProposedOperation(operation_id=WRITE_OPERATION_ID),
        policy=_demo_policy(),
    )

    assert decision.outcome is AuthorizationOutcome.REQUIRE_CONFIRMATION
    assert decision.reason is AuthorizationReason.AUTHORIZATION_REQUIRED
    assert decision.permits_execution is False


@pytest.mark.parametrize(
    "operation_id",
    [WRITE_OPERATION_ID, DELETE_OPERATION_ID, DISCLOSE_OPERATION_ID],
)
def test_every_consequential_classification_requires_confirmation(
    operation_id: str,
) -> None:
    operation = ProposedOperation(
        operation_id=operation_id,
        target="note-1" if operation_id == DELETE_OPERATION_ID else None,
        parameters=(
            {"recipient": "self"} if operation_id == DISCLOSE_OPERATION_ID else {}
        ),
    )
    decision = evaluate_authorization(operation, policy=_demo_policy())

    assert decision.outcome is not AuthorizationOutcome.ALLOW
    assert decision.permits_execution is False


# --- 3. destructive or irreversible operations need authorization ----------


def test_destructive_operation_allowed_only_with_matching_authorization() -> None:
    operation = ProposedOperation(operation_id=DELETE_OPERATION_ID, target="note-42")
    policy = _demo_policy()

    without = evaluate_authorization(operation, policy=policy)
    assert without.outcome is AuthorizationOutcome.REQUIRE_CONFIRMATION
    assert without.permits_execution is False

    scope = AuthorizedScope(operation_id=DELETE_OPERATION_ID, target="note-42")
    with_authorization = evaluate_authorization(
        operation, policy=policy, authorized=scope
    )
    assert with_authorization.outcome is AuthorizationOutcome.ALLOW
    assert with_authorization.reason is AuthorizationReason.ALLOWED_BY_AUTHORIZATION
    assert with_authorization.permits_execution is True


def test_missing_authorization_never_defaults_to_permission() -> None:
    policy = _demo_policy()

    for rule in policy.rules:
        if rule.risk is not RiskLevel.CONSEQUENTIAL:
            continue
        operation = ProposedOperation(
            operation_id=rule.operation_id,
            target="note-1" if rule.requires_target else None,
            parameters={name: "value" for name in rule.required_parameters},
        )
        decision = evaluate_authorization(operation, policy=policy)
        assert decision.outcome is not AuthorizationOutcome.ALLOW


# --- 4. unclear intent, target, or parameters require clarification --------


def test_ambiguous_target_requires_clarification() -> None:
    policy = _demo_policy()

    for target in (None, "", "   ", "\t\n"):
        decision = evaluate_authorization(
            ProposedOperation(operation_id=DELETE_OPERATION_ID, target=target),
            policy=policy,
        )
        assert decision.outcome is AuthorizationOutcome.CLARIFY
        assert decision.reason is AuthorizationReason.TARGET_MISSING
        assert decision.permits_execution is False


def test_blank_target_is_not_a_distinct_material_value() -> None:
    assert (
        ProposedOperation(operation_id=DELETE_OPERATION_ID, target="   ").target is None
    )
    assert (
        ProposedOperation(operation_id=DELETE_OPERATION_ID, target=None).target is None
    )


def test_missing_required_parameter_requires_clarification() -> None:
    policy = _demo_policy()

    absent = evaluate_authorization(
        ProposedOperation(operation_id=DISCLOSE_OPERATION_ID),
        policy=policy,
    )
    assert absent.outcome is AuthorizationOutcome.CLARIFY
    assert absent.reason is AuthorizationReason.PARAMETER_MISSING

    unrelated = evaluate_authorization(
        ProposedOperation(
            operation_id=DISCLOSE_OPERATION_ID,
            parameters={"channel": "email"},
        ),
        policy=policy,
    )
    assert unrelated.outcome is AuthorizationOutcome.CLARIFY
    assert unrelated.reason is AuthorizationReason.PARAMETER_MISSING


def test_confirmation_of_an_underspecified_operation_is_not_authorization() -> None:
    """A covering-but-empty scope cannot authorize an unspecified action."""
    policy = _demo_policy()
    operation = ProposedOperation(operation_id=DISCLOSE_OPERATION_ID)
    scope = AuthorizedScope(operation_id=DISCLOSE_OPERATION_ID)

    assert scope.covers(operation) is True

    decision = evaluate_authorization(operation, policy=policy, authorized=scope)
    assert decision.outcome is AuthorizationOutcome.CLARIFY
    assert decision.reason is AuthorizationReason.PARAMETER_MISSING
    assert decision.permits_execution is False


# --- 4b. machine operation identifiers are exact, never normalized --------

MALFORMED_OPERATION_IDENTIFIERS = (
    " help",
    "help ",
    "  help  ",
    "\thelp",
    "help\t",
    "help\n",
    "help\r",
    "help\r\n",
    "\r\nhelp\n",
    "help\ncap",
    "Help",
    "HELP",
    "hElp",
    "hel p",
    "help cap",
    "help\tcap",
    "1help",
    "_help",
    "-help",
    "help!",
    "help.",
    "help/cap",
    "help\\cap",
    "help:caf\u00e9",
    "help\u00a0",
)

BLANK_OPERATION_IDENTIFIERS = ("", " ", "   ", "\t", "\n", "\r\n")


def test_malformed_operation_identifier_is_not_an_operation() -> None:
    """A malformed identifier cannot be represented at all, anywhere."""
    for identifier in MALFORMED_OPERATION_IDENTIFIERS:
        with pytest.raises(ValidationError):
            ProposedOperation(operation_id=identifier)
        with pytest.raises(ValidationError):
            AuthorizedScope(operation_id=identifier)
        with pytest.raises(ValidationError):
            _rule(identifier)
        with pytest.raises(ValidationError):
            AuthorizationDecision(
                operation_id=identifier,
                outcome=AuthorizationOutcome.ALLOW,
                reason=AuthorizationReason.ALLOWED_LOW_RISK,
            )


def test_blank_operation_identifier_is_not_an_operation() -> None:
    for identifier in BLANK_OPERATION_IDENTIFIERS:
        with pytest.raises(ValidationError):
            ProposedOperation(operation_id=identifier)
        with pytest.raises(ValidationError):
            AuthorizedScope(operation_id=identifier)


def test_no_malformed_identifier_can_obtain_any_decision() -> None:
    """Fails closed as unusable input: not allowed, not even denied."""
    policy = _demo_policy()

    for identifier in (*MALFORMED_OPERATION_IDENTIFIERS, *BLANK_OPERATION_IDENTIFIERS):
        with pytest.raises(AuthorizationPolicyError) as excinfo:
            evaluate_authorization({"operation_id": identifier}, policy=policy)
        assert excinfo.value.code is AuthorizationErrorCode.INVALID_OPERATION
        assert excinfo.value.__cause__ is None
        assert excinfo.value.__suppress_context__ is True


def test_malformed_variant_of_a_registered_operation_cannot_be_authorized() -> None:
    """A scope that looks like it matches cannot make `help\n` executable."""
    policy = _demo_policy()
    scope = AuthorizedScope(operation_id=HELP_OPERATION_ID)

    for identifier in ("help\n", "help\r", "help\r\n", " help", "Help"):
        with pytest.raises(AuthorizationPolicyError) as excinfo:
            evaluate_authorization(
                {"operation_id": identifier}, policy=policy, authorized=scope
            )
        assert excinfo.value.code is AuthorizationErrorCode.INVALID_OPERATION
        assert excinfo.value.code is not AuthorizationErrorCode.INVALID_AUTHORIZATION


def test_identifier_validation_cannot_be_bypassed_by_a_mutated_instance() -> None:
    """`model_copy` skips validation, so the evaluator re-checks on entry."""
    policy = build_default_policy()

    forged_operation = ProposedOperation(operation_id=HELP_OPERATION_ID).model_copy(
        update={"operation_id": "help\n"}
    )
    assert forged_operation.operation_id == "help\n"

    with pytest.raises(AuthorizationPolicyError) as excinfo:
        evaluate_authorization(forged_operation, policy=policy)
    assert excinfo.value.code is AuthorizationErrorCode.INVALID_OPERATION

    forged_scope = AuthorizedScope(operation_id=HELP_OPERATION_ID).model_copy(
        update={"operation_id": "help\n"}
    )
    assert forged_scope.operation_id == "help\n"
    # Exact comparison: a padded or newline-suffixed identifier is not `help`.
    assert (
        forged_scope.covers(ProposedOperation(operation_id=HELP_OPERATION_ID)) is False
    )
    with pytest.raises(AuthorizationPolicyError) as excinfo:
        evaluate_authorization(
            ProposedOperation(operation_id=HELP_OPERATION_ID),
            policy=policy,
            authorized=forged_scope,
        )
    assert excinfo.value.code is AuthorizationErrorCode.INVALID_AUTHORIZATION


def test_malformed_identifier_failure_does_not_echo_the_input() -> None:
    marker = "help\nPRIVATE_MARKER_4C1D"

    with pytest.raises(AuthorizationPolicyError) as excinfo:
        evaluate_authorization({"operation_id": marker}, policy=build_default_policy())

    message = str(excinfo.value)
    assert excinfo.value.code is AuthorizationErrorCode.INVALID_OPERATION
    assert marker not in message
    assert "PRIVATE_MARKER_4C1D" not in message
    assert "help" not in message


def test_valid_identifiers_still_behave_as_before() -> None:
    policy = build_default_policy()

    decision = evaluate_authorization(
        ProposedOperation(operation_id=HELP_OPERATION_ID), policy=policy
    )
    assert decision.outcome is AuthorizationOutcome.ALLOW
    assert decision.operation_id == HELP_OPERATION_ID

    for identifier in ("a", "h1", "help-1", "help_1", "help-cap"):
        assert ProposedOperation(operation_id=identifier).operation_id == identifier
        assert AuthorizedScope(operation_id=identifier).operation_id == identifier


def test_lookup_uses_exact_equality_for_well_formed_identifiers() -> None:
    policy = _policy(
        _rule(HELP_OPERATION_ID), _rule("help-2", risk=RiskLevel.CONSEQUENTIAL)
    )

    exact = evaluate_authorization(
        ProposedOperation(operation_id=HELP_OPERATION_ID), policy=policy
    )
    assert exact.reason is AuthorizationReason.ALLOWED_LOW_RISK
    assert exact.operation_id == HELP_OPERATION_ID

    similar = evaluate_authorization(
        ProposedOperation(operation_id="help-2"), policy=policy
    )
    assert similar.reason is AuthorizationReason.AUTHORIZATION_REQUIRED
    assert similar.operation_id == "help-2"


# --- 5. unclassified or missing risk information never grants permission ---


def test_unclassified_risk_is_denied_never_allowed() -> None:
    operation = ProposedOperation(operation_id=UNCLASSIFIED_OPERATION_ID)

    without = evaluate_authorization(operation, policy=_demo_policy())
    assert without.outcome is AuthorizationOutcome.DENY
    assert without.reason is AuthorizationReason.RISK_UNCLASSIFIED

    scope = AuthorizedScope(operation_id=UNCLASSIFIED_OPERATION_ID)
    with_authorization = evaluate_authorization(
        operation, policy=_demo_policy(), authorized=scope
    )
    assert with_authorization.outcome is AuthorizationOutcome.DENY
    assert with_authorization.permits_execution is False


def test_rule_without_risk_cannot_allow_by_omission() -> None:
    policy = _policy(_rule("demo-unknown-risk", risk=None))

    decision = evaluate_authorization(
        ProposedOperation(operation_id="demo-unknown-risk"), policy=policy
    )
    assert decision.outcome is AuthorizationOutcome.DENY


# --- 6. unsupported and prohibited operations are denied -------------------


def test_unregistered_operation_is_denied() -> None:
    decision = evaluate_authorization(
        ProposedOperation(operation_id="demo-not-registered"),
        policy=_demo_policy(),
    )

    assert decision.outcome is AuthorizationOutcome.DENY
    assert decision.reason is AuthorizationReason.OPERATION_UNSUPPORTED


def test_unsupported_operation_cannot_be_authorized_into_execution() -> None:
    operation = ProposedOperation(operation_id="demo-not-registered")
    scope = AuthorizedScope(operation_id="demo-not-registered")

    decision = evaluate_authorization(
        operation, policy=_demo_policy(), authorized=scope
    )
    assert decision.outcome is AuthorizationOutcome.DENY
    assert decision.permits_execution is False


def test_prohibited_operation_is_denied_even_with_matching_authorization() -> None:
    operation = ProposedOperation(operation_id=PROHIBITED_OPERATION_ID)
    policy = _demo_policy()

    assert (
        evaluate_authorization(operation, policy=policy).reason
        is AuthorizationReason.OPERATION_PROHIBITED
    )

    scope = AuthorizedScope(operation_id=PROHIBITED_OPERATION_ID)
    decision = evaluate_authorization(operation, policy=policy, authorized=scope)
    assert decision.outcome is AuthorizationOutcome.DENY
    assert decision.reason is AuthorizationReason.OPERATION_PROHIBITED
    assert decision.permits_execution is False


def test_prohibition_outranks_missing_specification() -> None:
    """A prohibited operation is denied, not clarified into feasibility."""
    policy = _policy(
        _rule(
            PROHIBITED_OPERATION_ID,
            risk=RiskLevel.CONSEQUENTIAL,
            prohibited=True,
            requires_target=True,
        )
    )

    decision = evaluate_authorization(
        ProposedOperation(operation_id=PROHIBITED_OPERATION_ID), policy=policy
    )
    assert decision.outcome is AuthorizationOutcome.DENY
    assert decision.reason is AuthorizationReason.OPERATION_PROHIBITED


def test_operation_identifier_is_not_case_folded_into_a_match() -> None:
    """Uppercase is malformed, not an alias for the lowercase operation."""
    with pytest.raises(ValidationError):
        ProposedOperation(operation_id=HELP_OPERATION_ID.upper())

    with pytest.raises(AuthorizationPolicyError) as excinfo:
        evaluate_authorization(
            {"operation_id": HELP_OPERATION_ID.upper()},
            policy=build_default_policy(),
        )
    assert excinfo.value.code is AuthorizationErrorCode.INVALID_OPERATION


# --- 7. one-action authorization scope ------------------------------------


def _consequential_policy() -> AuthorizationPolicy:
    return _policy(
        _rule(WRITE_OPERATION_ID, risk=RiskLevel.CONSEQUENTIAL),
        _rule(DELETE_OPERATION_ID, risk=RiskLevel.CONSEQUENTIAL, requires_target=True),
    )


def test_authorization_for_one_target_does_not_cover_another() -> None:
    policy = _consequential_policy()
    scope = AuthorizedScope(operation_id=DELETE_OPERATION_ID, target="note-a")

    other = evaluate_authorization(
        ProposedOperation(operation_id=DELETE_OPERATION_ID, target="note-b"),
        policy=policy,
        authorized=scope,
    )
    assert other.outcome is AuthorizationOutcome.REQUIRE_CONFIRMATION
    assert other.reason is AuthorizationReason.AUTHORIZATION_SCOPE_MISMATCH
    assert other.permits_execution is False


def test_authorization_for_one_operation_does_not_cover_another() -> None:
    policy = _consequential_policy()
    scope = AuthorizedScope(operation_id=WRITE_OPERATION_ID)

    decision = evaluate_authorization(
        ProposedOperation(operation_id=DELETE_OPERATION_ID, target="note-a"),
        policy=policy,
        authorized=scope,
    )
    assert decision.outcome is AuthorizationOutcome.REQUIRE_CONFIRMATION
    assert decision.reason is AuthorizationReason.AUTHORIZATION_SCOPE_MISMATCH


def test_authorization_for_one_scope_does_not_cover_another() -> None:
    policy = _consequential_policy()
    scope = AuthorizedScope(operation_id=WRITE_OPERATION_ID, scope="notes/today")

    decision = evaluate_authorization(
        ProposedOperation(operation_id=WRITE_OPERATION_ID, scope="notes/all"),
        policy=policy,
        authorized=scope,
    )
    assert decision.outcome is AuthorizationOutcome.REQUIRE_CONFIRMATION
    assert decision.reason is AuthorizationReason.AUTHORIZATION_SCOPE_MISMATCH


def test_authorization_for_one_parameter_set_does_not_cover_another() -> None:
    policy = _policy(
        _rule(
            DISCLOSE_OPERATION_ID,
            risk=RiskLevel.CONSEQUENTIAL,
            required_parameters=("recipient",),
        )
    )
    scope = AuthorizedScope(
        operation_id=DISCLOSE_OPERATION_ID,
        parameters={"recipient": "self"},
    )

    same = evaluate_authorization(
        ProposedOperation(
            operation_id=DISCLOSE_OPERATION_ID,
            parameters={"recipient": "self"},
        ),
        policy=policy,
        authorized=scope,
    )
    assert same.outcome is AuthorizationOutcome.ALLOW

    different = evaluate_authorization(
        ProposedOperation(
            operation_id=DISCLOSE_OPERATION_ID,
            parameters={"recipient": "public-list"},
        ),
        policy=policy,
        authorized=scope,
    )
    assert different.outcome is AuthorizationOutcome.REQUIRE_CONFIRMATION
    assert different.reason is AuthorizationReason.AUTHORIZATION_SCOPE_MISMATCH


def test_material_comparison_ignores_parameter_order_and_padding() -> None:
    policy = _policy(
        _rule(
            DISCLOSE_OPERATION_ID,
            risk=RiskLevel.CONSEQUENTIAL,
            required_parameters=("recipient", "channel"),
        )
    )
    scope = AuthorizedScope(
        operation_id=DISCLOSE_OPERATION_ID,
        target="  note-1  ",
        parameters={"channel": "email", "recipient": "self"},
    )

    decision = evaluate_authorization(
        ProposedOperation(
            operation_id=DISCLOSE_OPERATION_ID,
            target="note-1",
            parameters={"recipient": "self", "channel": "email"},
        ),
        policy=policy,
        authorized=scope,
    )
    assert decision.outcome is AuthorizationOutcome.ALLOW


def test_low_risk_operation_stays_allowed_with_unrelated_authorization() -> None:
    decision = evaluate_authorization(
        ProposedOperation(operation_id=HELP_OPERATION_ID),
        policy=build_default_policy(),
        authorized=AuthorizedScope(operation_id=DELETE_OPERATION_ID, target="note-1"),
    )
    assert decision.outcome is AuthorizationOutcome.ALLOW
    assert decision.reason is AuthorizationReason.ALLOWED_LOW_RISK


def test_covers_fails_closed_for_non_operation_input() -> None:
    scope = AuthorizedScope(operation_id=HELP_OPERATION_ID)

    assert scope.covers("help") is False
    assert scope.covers(None) is False
    assert scope.covers({"operation_id": HELP_OPERATION_ID}) is False


# --- 8. invalid policy input fails safely ----------------------------------


def test_invalid_policy_type_is_rejected() -> None:
    with pytest.raises(AuthorizationPolicyError) as excinfo:
        evaluate_authorization(
            ProposedOperation(operation_id=HELP_OPERATION_ID),
            policy="not-a-policy",  # type: ignore[arg-type]
        )
    assert excinfo.value.code is AuthorizationErrorCode.INVALID_POLICY


def test_invalid_operation_input_is_rejected() -> None:
    policy = build_default_policy()

    for bad in (None, 7, "help", ["help"], {"message": "help"}, {"operation_id": ""}):
        with pytest.raises(AuthorizationPolicyError) as excinfo:
            evaluate_authorization(bad, policy=policy)  # type: ignore[arg-type]
        assert excinfo.value.code is AuthorizationErrorCode.INVALID_OPERATION


def test_invalid_supplied_authorization_is_rejected() -> None:
    with pytest.raises(AuthorizationPolicyError) as excinfo:
        evaluate_authorization(
            ProposedOperation(operation_id=HELP_OPERATION_ID),
            policy=build_default_policy(),
            authorized={"operation_id": HELP_OPERATION_ID},  # type: ignore[arg-type]
        )
    assert excinfo.value.code is AuthorizationErrorCode.INVALID_AUTHORIZATION


def test_denied_and_clarified_failures_never_leak_input_values() -> None:
    marker = "PRIVATE_MARKER_4C1D"
    policy = _demo_policy()

    with pytest.raises(AuthorizationPolicyError) as excinfo:
        evaluate_authorization(
            {"operation_id": DELETE_OPERATION_ID, "target": marker, "junk": marker},
            policy=policy,
        )
    assert marker not in str(excinfo.value)
    assert marker not in repr(excinfo.value.__cause__)
    assert excinfo.value.__suppress_context__ is True


def test_policy_rejects_duplicate_operation_identifiers() -> None:
    with pytest.raises(ValidationError):
        _policy(_rule(HELP_OPERATION_ID), _rule(HELP_OPERATION_ID))


def test_policy_rejects_invalid_operation_identifier() -> None:
    invalid = (
        "Help",
        "help cap",
        "1help",
        "_help",
        "-help",
        "help!",
        "help\n",
        "help\r",
        "help\r\n",
        " help",
        "help ",
        "\thelp",
        "",
        "   ",
    )
    for identifier in invalid:
        with pytest.raises(ValidationError):
            _rule(identifier)


def test_policy_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        OperationRule(
            operation_id=HELP_OPERATION_ID,
            description="x",
            allows_anything=True,
        )
    with pytest.raises(ValidationError):
        AuthorizationPolicy(rules=(), risk=RiskLevel.LOW)
    with pytest.raises(ValidationError):
        ProposedOperation(operation_id=HELP_OPERATION_ID, execute_now=True)
    with pytest.raises(ValidationError):
        AuthorizedScope(operation_id=HELP_OPERATION_ID, confirmed=True)


def test_policy_rejects_invalid_parameter_and_required_parameter_names() -> None:
    with pytest.raises(ValidationError):
        ProposedOperation(operation_id=HELP_OPERATION_ID, parameters={"Bad Name": "x"})
    with pytest.raises(ValidationError):
        ProposedOperation(operation_id=HELP_OPERATION_ID, parameters={"ok": "   "})
    with pytest.raises(ValidationError):
        _rule(HELP_OPERATION_ID, required_parameters=("Bad",))
    with pytest.raises(ValidationError):
        _rule(HELP_OPERATION_ID, required_parameters=("ok", "ok"))


def test_decision_rejects_a_contradictory_outcome() -> None:
    """A decision cannot claim ALLOW while its reason states a denial."""
    with pytest.raises(ValidationError):
        AuthorizationDecision(
            operation_id=HELP_OPERATION_ID,
            outcome=AuthorizationOutcome.ALLOW,
            reason=AuthorizationReason.OPERATION_UNSUPPORTED,
        )


def test_every_reason_maps_to_exactly_one_outcome() -> None:
    assert set(REASON_OUTCOMES) == set(AuthorizationReason)

    allow_reasons = {
        reason
        for reason, outcome in REASON_OUTCOMES.items()
        if outcome is AuthorizationOutcome.ALLOW
    }
    assert allow_reasons == {
        AuthorizationReason.ALLOWED_LOW_RISK,
        AuthorizationReason.ALLOWED_BY_AUTHORIZATION,
    }


def test_decisions_are_immutable() -> None:
    decision = evaluate_authorization(
        ProposedOperation(operation_id=HELP_OPERATION_ID),
        policy=build_default_policy(),
    )

    with pytest.raises(ValidationError):
        decision.outcome = AuthorizationOutcome.DENY  # type: ignore[misc]


# --- 9. determinism and absence of side effects ----------------------------


def test_evaluation_is_deterministic_and_pure() -> None:
    policy = _demo_policy()
    operation = ProposedOperation(operation_id=DELETE_OPERATION_ID, target="note-7")
    scope = AuthorizedScope(operation_id=DELETE_OPERATION_ID, target="note-7")

    before_operation = operation.model_dump()
    before_policy = policy.model_dump()
    before_scope = scope.model_dump()

    first = evaluate_authorization(operation, policy=policy, authorized=scope)
    second = evaluate_authorization(operation, policy=policy, authorized=scope)

    assert first == second
    assert operation.model_dump() == before_operation
    assert policy.model_dump() == before_policy
    assert scope.model_dump() == before_scope


def test_evaluation_does_not_touch_the_database(monkeypatch) -> None:
    calls = {"count": 0}
    real = SessionLocal

    def counting_session_local(*args, **kwargs):
        calls["count"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr("rop.database.SessionLocal", counting_session_local)

    evaluate_authorization(
        ProposedOperation(operation_id=HELP_OPERATION_ID),
        policy=build_default_policy(),
    )
    evaluate_authorization(
        ProposedOperation(operation_id=UNCLASSIFIED_OPERATION_ID),
        policy=_demo_policy(),
    )
    assert calls["count"] == 0


def test_no_outcome_other_than_allow_permits_execution() -> None:
    policy = _demo_policy()
    proposals = [
        ProposedOperation(operation_id=HELP_OPERATION_ID),
        ProposedOperation(operation_id=WRITE_OPERATION_ID),
        ProposedOperation(operation_id=DELETE_OPERATION_ID),
        ProposedOperation(operation_id=DISCLOSE_OPERATION_ID),
        ProposedOperation(operation_id=PROHIBITED_OPERATION_ID),
        ProposedOperation(operation_id=UNCLASSIFIED_OPERATION_ID),
        ProposedOperation(operation_id="demo-not-registered"),
    ]

    for operation in proposals:
        decision = evaluate_authorization(operation, policy=policy)
        expected = decision.outcome is AuthorizationOutcome.ALLOW
        assert decision.permits_execution is expected
        if decision.outcome is not AuthorizationOutcome.ALLOW:
            assert decision.permits_execution is False, operation.operation_id


def test_evaluator_module_imports_no_network_or_model_facilities() -> None:
    import rop.authorization.policy as policy_module

    source = policy_module.__file__
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


# --- 10. existing deterministic capability-registry behaviour unchanged ----


def test_capability_registry_behaviour_is_unchanged() -> None:
    registry = build_default_registry()

    assert len(registry) == 1
    assert registry.capabilities()[0].identifier == HELP_IDENTIFIER
    assert HELP_IDENTIFIER == HELP_OPERATION_ID

    matched = registry.match("  What Can You Do?  ")
    assert matched is not None
    assert matched.identifier == HELP_IDENTIFIER

    assert registry.match("help me create a reminder") is None
    assert registry.match("") is None
    assert normalize_phrase("HELP!!") == "help"


def test_policy_adds_no_capability_aliases() -> None:
    """The registry keeps its own contract; the policy adds no aliases."""
    registry = build_default_registry()

    for alias in ("delete note", "send email", "run command"):
        assert registry.match(alias) is None


def test_contract_values_are_frozen() -> None:
    rule = DEFAULT_POLICY_RULES[0]
    operation = ProposedOperation(operation_id=HELP_OPERATION_ID)
    policy = build_default_policy()

    with pytest.raises(ValidationError):
        rule.risk = RiskLevel.CONSEQUENTIAL
    with pytest.raises(ValidationError):
        operation.operation_id = WRITE_OPERATION_ID
    with pytest.raises(ValidationError):
        policy.rules = ()


def test_unrelated_capability_can_be_registered_without_changing_policy() -> None:
    """A new capability does not silently inherit authorization."""
    registry = build_default_registry()
    registry.register(
        Capability(
            identifier="demo-new-capability",
            description="A capability added after the policy was written.",
            aliases=("demo new capability",),
            response="demo",
        )
    )

    assert registry.match("demo new capability") is not None

    decision = evaluate_authorization(
        ProposedOperation(operation_id="demo-new-capability"),
        policy=build_default_policy(),
    )
    assert decision.outcome is AuthorizationOutcome.DENY
    assert decision.reason is AuthorizationReason.OPERATION_UNSUPPORTED
