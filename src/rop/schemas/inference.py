"""Task 212: local CPU inference runtime contracts.

Data-only contracts for the explicitly invoked, in-process CPU
inference runtime over Task 211 checkpoint artifacts. No network,
external serving, downloads, or clinical logic live here.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_INFERENCE_BATCH_SIZE = 32
"""Conservative upper bound on inference batch size (bounded allocation)."""

MAX_INFERENCE_SEQUENCE_LENGTH = 512
"""Upper bound on a request sequence; the model config may impose less."""


def _reject_ambiguous_number(value: object, field_name: str) -> object:
    """Reject booleans and strings before lax numeric parsing."""
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError(f"{field_name} is invalid")
    return value


class InferenceSelection(BaseModel):
    """Explicit caller-supplied local artifact selection (Task 212).

    Only plain local file paths are accepted. Network locations,
    remote identifiers, and empty paths are rejected.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    checkpoint_path: str = Field(min_length=1, max_length=1024)
    manifest_path: str = Field(min_length=1, max_length=1024)

    @field_validator("checkpoint_path", "manifest_path", mode="before")
    @classmethod
    def _strict_path(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("artifact path is invalid")
        if not value or len(value) > 1024:
            raise ValueError("artifact path is invalid")
        if "://" in value or "\x00" in value:
            raise ValueError("artifact path is invalid")
        return value


class InferenceRequest(BaseModel):
    """Typed batch of token-ID sequences for one inference call (Task 212).

    Sequences use the Task 209 model's token-ID representation
    (integers in ``[0, vocab_size)``) and are validated before any
    tensor is allocated. Bounds here are global; the runtime also
    enforces the loaded model's own sequence limit and vocabulary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    token_id_sequences: Any = Field()

    @field_validator("token_id_sequences", mode="before")
    @classmethod
    def _strict_sequences(cls, value: object) -> object:
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            raise ValueError("token ID sequences are invalid")
        outer = list(value)
        if not 1 <= len(outer) <= MAX_INFERENCE_BATCH_SIZE:
            raise ValueError("token ID batch size is invalid")
        checked: list[tuple[int, ...]] = []
        for sequence in outer:
            if isinstance(sequence, str) or not isinstance(sequence, (list, tuple)):
                raise ValueError("token ID sequence is invalid")
            inner = list(sequence)
            if not 1 <= len(inner) <= MAX_INFERENCE_SEQUENCE_LENGTH:
                raise ValueError("token ID sequence length is invalid")
            for token_id in inner:
                if isinstance(token_id, bool) or not isinstance(token_id, int):
                    raise ValueError("token ID is invalid")
            checked.append(tuple(inner))
        return tuple(checked)


class InferenceResult(BaseModel):
    """Typed raw model output for one inference call (Task 212).

    This is untrusted model output, not evidence, not a finding, and
    not a trusted result. Rows correspond one-to-one with the request
    batch; each row holds one logit per model class.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1, max_length=64)
    batch_size: int = Field(ge=1, le=MAX_INFERENCE_BATCH_SIZE)
    sequence_length: int = Field(ge=1, le=MAX_INFERENCE_SEQUENCE_LENGTH)
    num_classes: int = Field(ge=2)
    logits: tuple[tuple[float, ...], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _strict_result(self) -> InferenceResult:
        if len(self.logits) != self.batch_size:
            raise ValueError("logits batch size does not match")
        for row in self.logits:
            if len(row) != self.num_classes:
                raise ValueError("logits row length does not match")
            for value in row:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("logit value is invalid")
                if not math.isfinite(float(value)):
                    raise ValueError("logit value is not finite")
        return self


InferenceErrorCode = Literal[
    "INVALID_INPUT",
    "INVALID_REQUEST",
    "ARTIFACT_MISSING",
    "ARTIFACT_INVALID",
    "INCOMPATIBLE_ARTIFACT",
    "RESOURCE_LIMIT",
    "INVALID_OUTPUT",
]


__all__ = [
    "MAX_INFERENCE_BATCH_SIZE",
    "MAX_INFERENCE_SEQUENCE_LENGTH",
    "InferenceErrorCode",
    "InferenceRequest",
    "InferenceResult",
    "InferenceSelection",
]
