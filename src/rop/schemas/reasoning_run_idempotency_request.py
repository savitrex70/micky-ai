"""Task 134: deterministic reasoning-run idempotency API contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReasoningRunIdempotentExecutionRequest(BaseModel):
    """Request body for the idempotent reasoning-run endpoint.

    A single optional SHA-256-shaped canonical input fingerprint. An
    omitted body (or explicit null) requests an unconditional new
    execution through the normal Task 127 ``known_input_fingerprint=None``
    behavior. Malformed fingerprints fail request validation (HTTP 422);
    they are never silently normalized.
    """

    model_config = ConfigDict(extra="forbid")

    known_input_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
