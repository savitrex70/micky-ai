"""Typed deterministic parsers for user-facing assistant commands."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from rop.schemas.authorization import ProposedOperation


class CapabilityParseError(ValueError):
    """Expected missing or ambiguous user input that can be clarified."""

    def __init__(
        self,
        field_name: str,
        question: str,
        partial_operation: ProposedOperation | None = None,
        missing_fields: list[str] | None = None,
    ) -> None:
        self.field_name = field_name
        self.question = question
        self.partial_operation = partial_operation
        self.missing_fields = list(missing_fields or [field_name])
        super().__init__("required user information is missing")


class CapabilityParser(Protocol):
    """Parser interface attached to one explicitly registered capability."""

    def matches(self, message: str) -> bool:
        """Return whether this parser owns the message's explicit command."""
        ...

    def parse(
        self,
        message: str,
        *,
        pending_context: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> ProposedOperation:
        """Parse a command or resume its server-owned clarification."""
        ...


__all__ = ["CapabilityParseError", "CapabilityParser"]
