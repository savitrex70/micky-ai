"""Deterministic capability registry for the local assistant.

The registry maps explicit, normalized request phrases to a small set of
registered capabilities. It performs no fuzzy matching, no substring
matching, no model inference, and no network access. Every match either
resolves to a single registered capability or to an explicit no-match.

The module is intentionally independent of FastAPI so its rules can be
tested without HTTP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rop.capabilities.parser import CapabilityParser

HELP_IDENTIFIER = "help"
HELP_DESCRIPTION = (
    "Explain what the assistant can currently do and what is not yet " "available."
)
HELP_ALIASES: tuple[str, ...] = (
    "help",
    "what can you do",
    "show capabilities",
    "list capabilities",
    "list available capabilities",
)
HELP_RESPONSE = (
    "The chat supports help plus explicit deterministic workspace commands. "
    "Use commands such as 'workspace list notes', 'workspace add note: title', "
    "or 'workspace search files: terms'. Every state-changing command requires "
    "server-side confirmation. Local file search is limited to folders you "
    "explicitly authorize. ROP clinical sessions remain separate records. "
    "General question answering and model-based reasoning are not yet available."
)

_WHITESPACE_RUN = re.compile(r"\s+")
_TRAILING_PUNCTUATION = ".!?"
_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class RegistryError(ValueError):
    """Raised for invalid registry configuration."""


@dataclass(frozen=True)
class Capability:
    """A single registered capability and its explicit request phrases."""

    identifier: str
    description: str
    aliases: tuple[str, ...]
    response: str
    parser: CapabilityParser | None = None


@dataclass
class CapabilityRegistry:
    """A deterministic, ordered map of normalized phrases to capabilities."""

    _by_phrase: dict[str, Capability] = field(default_factory=dict, init=False)
    _identifiers: set[str] = field(default_factory=set, init=False)
    _capabilities: list[Capability] = field(default_factory=list, init=False)

    def register(self, capability: Capability) -> None:
        if not capability.identifier:
            raise RegistryError("capability identifier must be non-empty")
        # ``fullmatch`` enforces a complete-string match. Using ``$`` alone
        # would accept a single trailing newline (``"help\n"``).
        if not _IDENTIFIER_PATTERN.fullmatch(capability.identifier):
            raise RegistryError(
                f"invalid capability identifier: {capability.identifier!r}; "
                "expected lowercase ASCII matching ^[a-z][a-z0-9_-]*$"
            )
        if capability.identifier in self._identifiers:
            raise RegistryError(
                f"duplicate capability identifier: {capability.identifier}"
            )
        if not capability.aliases and capability.parser is None:
            raise RegistryError(
                f"capability {capability.identifier} needs aliases or a parser"
            )

        normalized_aliases: list[str] = []
        seen_local: set[str] = set()
        for alias in capability.aliases:
            normalized = normalize_phrase(alias)
            if not normalized:
                raise RegistryError(
                    f"capability {capability.identifier} has an empty alias"
                )
            if normalized in seen_local:
                raise RegistryError(
                    f"capability {capability.identifier} repeats alias: "
                    f"{normalized!r}"
                )
            if normalized in self._by_phrase:
                raise RegistryError(
                    f"alias {normalized!r} is already registered to "
                    f"{self._by_phrase[normalized].identifier!r}"
                )
            seen_local.add(normalized)
            normalized_aliases.append(normalized)

        for normalized in normalized_aliases:
            self._by_phrase[normalized] = capability
        self._identifiers.add(capability.identifier)
        self._capabilities.append(capability)

    def match(self, message: str) -> Capability | None:
        """Return the single registered capability for ``message`` or None.

        Matching is exact after normalization. There is no partial or
        substring matching, so phrases such as ``help me create a reminder``
        do not resolve to the ``help`` capability.
        """
        normalized = normalize_phrase(message)
        if not normalized:
            return None
        return self._by_phrase.get(normalized)

    def match_parser(self, message: str) -> Capability | None:
        """Return a parser-backed capability that explicitly recognizes the command."""
        matches = [
            capability
            for capability in self._capabilities
            if capability.parser is not None and capability.parser.matches(message)
        ]
        if len(matches) > 1:
            raise RegistryError("request matches more than one registered parser")
        return matches[0] if matches else None

    def capabilities(self) -> tuple[Capability, ...]:
        return tuple(self._capabilities)

    def __len__(self) -> int:
        return len(self._capabilities)


def normalize_phrase(value: str) -> str:
    """Lowercase, collapse whitespace, and strip approved trailing punctuation."""
    collapsed = _WHITESPACE_RUN.sub(" ", value).strip()
    while collapsed and collapsed[-1] in _TRAILING_PUNCTUATION:
        collapsed = collapsed[:-1].rstrip()
    return collapsed.lower()


def build_default_registry() -> CapabilityRegistry:
    """Return a registry with the initial user-facing capabilities."""
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            identifier=HELP_IDENTIFIER,
            description=HELP_DESCRIPTION,
            aliases=HELP_ALIASES,
            response=HELP_RESPONSE,
        )
    )
    return registry
