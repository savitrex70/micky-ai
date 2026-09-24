"""Task 057: provider abstraction for the LLM reasoning boundary.

A minimal Protocol -- not a framework. The Task 057 service depends
only on this interface; the concrete Ollama implementation lives in a
separate module. Tests inject a fake provider so the unit suite never
needs a running model server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMReasoningProviderResponse:
    """A single provider response, before any ROP validation."""

    provider: str
    model: str
    text: str


class LLMReasoningProviderError(Exception):
    """The provider could not produce a response.

    Used for network failures, timeouts, non-200 responses, missing
    configuration, or any other condition where the provider never
    returned model text. The Task 057 service translates this into
    MODEL_UNAVAILABLE; it is never surfaced to callers raw.
    """


class LLMReasoningProvider(Protocol):
    """Structural interface the Task 057 service depends on."""

    provider_name: str
    model_name: str

    def generate_reasoning(
        self, request: LLMReasoningRequest
    ) -> LLMReasoningProviderResponse:
        ...


@dataclass(frozen=True)
class LLMReasoningRequest:
    """What the model is allowed to receive, and nothing else.

    Built exclusively from a validated Task 055 canonical context.
    Contains no database handles, no filesystem paths, no environment
    variables, no credentials, and no Python objects.
    """

    payload: dict[str, Any]
    context_fingerprint: str

    def to_model_json(self) -> dict[str, Any]:
        """Return the payload the provider serializes for the model."""
        return {
            **self.payload,
            "context_fingerprint": self.context_fingerprint,
        }
