"""Tests for the deterministic capability registry."""

import pytest

from rop.capabilities.registry import (
    HELP_ALIASES,
    HELP_IDENTIFIER,
    HELP_RESPONSE,
    Capability,
    CapabilityRegistry,
    RegistryError,
    build_default_registry,
    normalize_phrase,
)


def _registry() -> CapabilityRegistry:
    return build_default_registry()


def test_default_registry_contains_only_help() -> None:
    registry = _registry()
    capabilities = registry.capabilities()
    assert len(capabilities) == 1
    assert capabilities[0].identifier == HELP_IDENTIFIER


@pytest.mark.parametrize("alias", HELP_ALIASES)
def test_every_help_alias_matches_help(alias: str) -> None:
    registry = _registry()
    capability = registry.match(alias)
    assert capability is not None
    assert capability.identifier == HELP_IDENTIFIER


@pytest.mark.parametrize("alias", HELP_ALIASES)
def test_alias_normalizes_case_and_whitespace(alias: str) -> None:
    registry = _registry()
    upper = alias.upper()
    padded = f"  {alias}  "
    collapsed = alias.replace(" ", "   ")
    for variant in (upper, padded, collapsed):
        capability = registry.match(variant)
        assert capability is not None, f"failed to match variant: {variant!r}"
        assert capability.identifier == HELP_IDENTIFIER


@pytest.mark.parametrize("alias", HELP_ALIASES)
def test_alias_normalizes_trailing_punctuation(alias: str) -> None:
    registry = _registry()
    for suffix in (".", "!", "?", "!!!", " .."):
        capability = registry.match(alias + suffix)
        assert capability is not None, f"failed trailing: {alias!r} + {suffix!r}"
        assert capability.identifier == HELP_IDENTIFIER


@pytest.mark.parametrize(
    "message",
    [
        "help me create a reminder",
        "help me",
        "please help",
        "can you help me",
        "what can you do and save a note",
        "show capabilities for notes",
        "list capabilities of the model",
        "capabilities",
        "help me now",
        "what can you do now",
        "what can you do and help me",
    ],
)
def test_unregistered_or_ambiguous_phrases_do_not_match_help(
    message: str,
) -> None:
    registry = _registry()
    assert registry.match(message) is None, f"unexpectedly matched: {message!r}"


def test_exact_substring_is_not_enough() -> None:
    registry = _registry()
    assert registry.match("help me create a reminder") is None
    assert registry.match("what can you do and save a note") is None


def test_empty_message_does_not_match() -> None:
    registry = _registry()
    assert registry.match("") is None
    assert registry.match("   ") is None
    assert registry.match("\t\n") is None


def test_duplicate_identifier_is_rejected() -> None:
    registry = CapabilityRegistry()
    first = Capability(
        identifier="alpha",
        description="first",
        aliases=("alpha",),
        response="alpha response",
    )
    registry.register(first)
    duplicate = Capability(
        identifier="alpha",
        description="second",
        aliases=("other",),
        response="other response",
    )
    with pytest.raises(RegistryError):
        registry.register(duplicate)


def test_duplicate_alias_within_capability_is_rejected() -> None:
    registry = CapabilityRegistry()
    capability = Capability(
        identifier="beta",
        description="test",
        aliases=("beta", "Beta", "BETA"),
        response="x",
    )
    with pytest.raises(RegistryError):
        registry.register(capability)


def test_duplicate_alias_across_capabilities_is_rejected() -> None:
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            identifier="gamma",
            description="first",
            aliases=("shared phrase",),
            response="x",
        )
    )
    with pytest.raises(RegistryError):
        registry.register(
            Capability(
                identifier="delta",
                description="second",
                aliases=("Shared Phrase",),
                response="y",
            )
        )


def test_empty_identifier_is_rejected() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(RegistryError):
        registry.register(
            Capability(
                identifier="",
                description="x",
                aliases=("x",),
                response="x",
            )
        )


def test_empty_alias_is_rejected() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(RegistryError):
        registry.register(
            Capability(
                identifier="epsilon",
                description="x",
                aliases=("   ",),
                response="x",
            )
        )


def test_capability_requires_at_least_one_alias() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(RegistryError):
        registry.register(
            Capability(
                identifier="zeta",
                description="x",
                aliases=(),
                response="x",
            )
        )


def test_normalize_phrase_is_idempotent() -> None:
    for raw in ("Help", "  HELP  ", "help!!", "What Can You Do?"):
        once = normalize_phrase(raw)
        twice = normalize_phrase(once)
        assert once == twice


def test_help_response_is_truthful() -> None:
    lower = HELP_RESPONSE.lower()
    assert "not yet available" in lower or "not yet" in lower
    assert "reminders" in lower
    assert "notes" in lower or "tasks" in lower


# --- identifier format validation -------------------------------------------


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        "   ",
        "\t",
        "\n",
        "help ",
        " help",
    ],
)
def test_blank_identifier_is_rejected(identifier: str) -> None:
    registry = CapabilityRegistry()
    with pytest.raises(RegistryError):
        registry.register(
            Capability(
                identifier=identifier,
                description="x",
                aliases=("some-alias",),
                response="x",
            )
        )


@pytest.mark.parametrize(
    "identifier",
    [
        "Help",
        "HELP",
        "HelpCap",
        "help cap",
        "help.cap",
        "help/cap",
        "help:cap",
        "help!",
        "help?",
        "1help",
        "_help",
        "-help",
        "help\u00e9",
        "help@home",
    ],
)
def test_invalid_identifier_format_is_rejected(identifier: str) -> None:
    registry = CapabilityRegistry()
    with pytest.raises(RegistryError):
        registry.register(
            Capability(
                identifier=identifier,
                description="x",
                aliases=("some-alias",),
                response="x",
            )
        )


@pytest.mark.parametrize(
    "identifier",
    [
        "help",
        "help2",
        "a",
        "abc",
        "list-capabilities",
        "list_capabilities",
        "x1-y2_z3",
        "a-b-c",
        "a_b_c",
    ],
)
def test_valid_identifier_format_is_accepted(identifier: str) -> None:
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            identifier=identifier,
            description="x",
            aliases=(f"alias-{identifier}",),
            response="ok",
        )
    )
    assert registry.capabilities()[0].identifier == identifier


def test_rejected_identifier_leaves_registry_unchanged() -> None:
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            identifier="alpha",
            description="first",
            aliases=("alpha-alias",),
            response="alpha",
        )
    )
    before_ids = {c.identifier for c in registry.capabilities()}
    before_len = len(registry)

    with pytest.raises(RegistryError):
        registry.register(
            Capability(
                identifier="Bad-Identifier",
                description="bad",
                aliases=("brand-new-alias",),
                response="bad",
            )
        )

    after_ids = {c.identifier for c in registry.capabilities()}
    assert after_ids == before_ids
    assert len(registry) == before_len

    # The rejected capability's alias must not be reserved: it can be
    # registered later by a capability with a valid identifier.
    registry.register(
        Capability(
            identifier="beta",
            description="second",
            aliases=("brand-new-alias",),
            response="beta",
        )
    )
    assert registry.match("brand-new-alias") is not None


def test_rejected_identifier_does_not_reserve_identifier() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(RegistryError):
        registry.register(
            Capability(
                identifier="UPPER",
                description="bad",
                aliases=("some-alias",),
                response="bad",
            )
        )
    # The uppercase identifier was rejected, so a valid variant is free.
    registry.register(
        Capability(
            identifier="upper",
            description="ok",
            aliases=("some-alias",),
            response="ok",
        )
    )
    assert registry.capabilities()[0].identifier == "upper"


# --- complete-string identifier matching ------------------------------------


@pytest.mark.parametrize(
    "identifier",
    [
        "help\n",
        "help\r",
        "help\r\n",
        "help\n\n",
        "help\r\r",
        "help \n",
        "\nhelp",
        "help\t",
    ],
)
def test_identifier_with_trailing_or_leading_whitespace_is_rejected(
    identifier: str,
) -> None:
    registry = CapabilityRegistry()
    with pytest.raises(RegistryError):
        registry.register(
            Capability(
                identifier=identifier,
                description="x",
                aliases=("some-alias",),
                response="x",
            )
        )


def test_identifier_with_trailing_newline_does_not_reserve_identifier() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(RegistryError):
        registry.register(
            Capability(
                identifier="help\n",
                description="bad",
                aliases=("some-alias",),
                response="bad",
            )
        )
    # "help" itself must still be free after the rejected registration.
    registry.register(
        Capability(
            identifier="help",
            description="ok",
            aliases=("some-alias",),
            response="ok",
        )
    )
    assert registry.capabilities()[0].identifier == "help"


def test_identifier_with_trailing_newline_does_not_reserve_alias() -> None:
    registry = CapabilityRegistry()
    with pytest.raises(RegistryError):
        registry.register(
            Capability(
                identifier="help\n",
                description="bad",
                aliases=("brand-new-alias",),
                response="bad",
            )
        )
    registry.register(
        Capability(
            identifier="other",
            description="ok",
            aliases=("brand-new-alias",),
            response="ok",
        )
    )
    assert registry.match("brand-new-alias") is not None


def test_valid_identifier_still_accepted_after_fullmatch_change() -> None:
    for identifier in ("help", "help2", "list-capabilities", "list_capabilities"):
        local = CapabilityRegistry()
        local.register(
            Capability(
                identifier=identifier,
                description="x",
                aliases=(f"alias-{identifier}",),
                response="ok",
            )
        )
        assert local.capabilities()[0].identifier == identifier
