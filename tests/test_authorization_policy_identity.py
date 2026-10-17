"""Task 223: deterministic effective-policy identity tests.

The identity exists because ``policy_version`` is the fixed literal
``"1"``: a rule's classification can change while the label does not, so a
pending confirmation must be bound to the policy's actual contents. These
tests prove the helper is stable for equivalent policies, changes when any
authorization-affecting field changes, and never fabricates an identity
when it cannot compute one.
"""

from __future__ import annotations

import re

import pytest

from rop.authorization.policy import (
    HELP_OPERATION_ID,
    AuthorizationPolicyError,
    authorization_policy_identity,
    build_default_policy,
)
from rop.schemas.authorization import (
    AUTHORIZATION_CONTRACT_VERSION,
    AuthorizationErrorCode,
    AuthorizationPolicy,
    OperationRule,
    RiskLevel,
)

DEFAULT_POLICY_IDENTITY = (
    "333f68dd5aa2bcbd424e13adf56a85303da49181fd51491b5df6cbf837dc5685"
)
"""Golden digest for the default policy.

A fixed expected value proves the identity is a stable function of the
policy contents rather than of this process's memory, ordering, or run.
Changing a decision-relevant field must change this constant, which is
exactly the behaviour a stored confirmation depends on.
"""

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _rule(
    operation_id: str = "demo-write",
    *,
    description: str = "Write one note.",
    risk: RiskLevel | None = RiskLevel.CONSEQUENTIAL,
    prohibited: bool = False,
    requires_target: bool = False,
    required_parameters: tuple[str, ...] = (),
) -> OperationRule:
    return OperationRule(
        operation_id=operation_id,
        description=description,
        risk=risk,
        prohibited=prohibited,
        requires_target=requires_target,
        required_parameters=required_parameters,
    )


def _policy(*rules: OperationRule) -> AuthorizationPolicy:
    return AuthorizationPolicy(rules=rules)


def test_identity_is_a_lowercase_sha256_hex_digest() -> None:
    identity = authorization_policy_identity(_policy(_rule()))

    assert _HEX64.fullmatch(identity)
    assert identity == identity.lower()


def test_default_policy_identity_matches_the_golden_value() -> None:
    assert authorization_policy_identity(build_default_policy()) == (
        DEFAULT_POLICY_IDENTITY
    )


def test_equivalent_policies_with_different_rule_order_share_one_identity() -> None:
    first = _policy(
        _rule("alpha-op", risk=RiskLevel.LOW),
        _rule("beta-op", risk=RiskLevel.CONSEQUENTIAL, requires_target=True),
        _rule("gamma-op", risk=None),
    )
    reordered = _policy(
        _rule("gamma-op", risk=None),
        _rule("beta-op", risk=RiskLevel.CONSEQUENTIAL, requires_target=True),
        _rule("alpha-op", risk=RiskLevel.LOW),
    )

    assert authorization_policy_identity(first) == authorization_policy_identity(
        reordered
    )


def test_required_parameter_order_is_not_material() -> None:
    declared = _policy(_rule(required_parameters=("recipient", "channel")))
    swapped = _policy(_rule(required_parameters=("channel", "recipient")))

    assert authorization_policy_identity(declared) == authorization_policy_identity(
        swapped
    )


def test_a_description_only_edit_does_not_change_the_identity() -> None:
    before = _policy(_rule(description="Write one note."))
    after = _policy(_rule(description="Completely reworded documentation."))

    assert authorization_policy_identity(before) == authorization_policy_identity(after)


@pytest.mark.parametrize(
    "changed_rule",
    [
        _rule(risk=RiskLevel.LOW),
        _rule(risk=None),
        _rule(prohibited=True),
        _rule(requires_target=True),
        _rule(required_parameters=("recipient",)),
        _rule(required_parameters=("recipient", "channel")),
        _rule(operation_id="demo-write-2"),
    ],
    ids=[
        "risk-lowered",
        "risk-unclassified",
        "prohibited",
        "requires-target",
        "one-required-parameter",
        "more-required-parameters",
        "renamed-operation",
    ],
)
def test_every_authorization_affecting_change_changes_the_identity(
    changed_rule: OperationRule,
) -> None:
    baseline = _policy(_rule())

    assert authorization_policy_identity(_policy(changed_rule)) != (
        authorization_policy_identity(baseline)
    )


def test_removing_or_adding_a_rule_changes_the_identity() -> None:
    one = _policy(_rule("alpha-op", risk=RiskLevel.LOW))
    two = _policy(
        _rule("alpha-op", risk=RiskLevel.LOW),
        _rule("beta-op", risk=RiskLevel.CONSEQUENTIAL),
    )

    assert authorization_policy_identity(one) != authorization_policy_identity(two)
    assert authorization_policy_identity(_policy()) != authorization_policy_identity(
        one
    )


def test_policy_version_label_is_part_of_the_identity_contract() -> None:
    """A label change is included; today no other label is a valid policy.

    ``AuthorizationPolicy`` pins the label to the literal ``"1"``, so a
    policy carrying a different label is invalid input rather than a
    silently accepted variant. The identity refuses it instead of
    pretending the change did not happen or inventing a digest.
    """
    forged = AuthorizationPolicy.model_construct(
        policy_version="2", rules=build_default_policy().rules
    )

    with pytest.raises(AuthorizationPolicyError) as excinfo:
        authorization_policy_identity(forged)
    assert excinfo.value.code is AuthorizationErrorCode.INVALID_POLICY


def test_identity_is_stable_across_repeated_calls_and_equal_instances() -> None:
    first = _policy(_rule())
    second = _policy(_rule())

    assert first == second
    assert authorization_policy_identity(first) == authorization_policy_identity(second)
    assert authorization_policy_identity(first) == authorization_policy_identity(first)


def test_identity_does_not_mutate_the_supplied_policy() -> None:
    policy = _policy(_rule(required_parameters=("b", "a")))
    before = policy.model_dump()

    authorization_policy_identity(policy)

    assert policy.model_dump() == before


@pytest.mark.parametrize(
    "invalid",
    [None, "not-a-policy", {}, [], 7, {"rules": ()}],
    ids=["none", "string", "empty-dict", "list", "int", "mapping"],
)
def test_invalid_input_never_produces_a_fabricated_identity(
    invalid: object,
) -> None:
    with pytest.raises(AuthorizationPolicyError) as excinfo:
        authorization_policy_identity(invalid)  # type: ignore[arg-type]

    assert excinfo.value.code is AuthorizationErrorCode.INVALID_POLICY
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True


def test_failure_message_carries_no_policy_content() -> None:
    marker = "PRIVATE_MARKER_9A7B"

    with pytest.raises(AuthorizationPolicyError) as excinfo:
        authorization_policy_identity({"rules": marker})  # type: ignore[arg-type]

    assert marker not in str(excinfo.value)
    assert marker not in repr(excinfo.value.__cause__)


def test_identity_is_not_the_version_label_itself() -> None:
    """The identity is a content fingerprint, not a restatement of "1"."""
    identity = authorization_policy_identity(build_default_policy())

    assert identity != AUTHORIZATION_CONTRACT_VERSION
    assert len(identity) == 64


def test_help_operation_rule_change_moves_the_identity() -> None:
    """The registered ``help`` rule is covered like any other rule."""
    changed = _policy(
        OperationRule(
            operation_id=HELP_OPERATION_ID,
            description="Explain what the assistant can do.",
            risk=RiskLevel.CONSEQUENTIAL,
        )
    )

    assert authorization_policy_identity(changed) != DEFAULT_POLICY_IDENTITY
