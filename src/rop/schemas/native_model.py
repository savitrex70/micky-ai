"""Task 209 strict bounded configuration for the first-party model.

The model serves only the Task 206 bounded label-suggestion task. It
makes no clinical decisions, generates no trusted evidence, assigns no
identity, and declares no certification. This module defines no model
weights; it is configuration only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
)

NATIVE_MODEL_CONTRACT_VERSION = "1"
# Hard bounds; a configuration outside them is rejected, never clamped.
MAX_VOCAB_SIZE = 100000
MAX_EMBEDDING_DIM = 64
MAX_NUM_LABELS = 32
MAX_SEQUENCE_LENGTH = 4096


class NativeModelConfig(BaseModel):
    """Versioned, immutable, bounded model configuration.

    ``architecture`` is pinned to the smallest design justified by the
    bounded label-suggestion task: a token-embedding table, mean
    pooling, and one linear multi-label head. A Transformer is not
    justified at this task scale and is rejected by the contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    architecture: Literal["EMBEDDING_MEAN_LINEAR"] = "EMBEDDING_MEAN_LINEAR"
    vocab_size: StrictInt = Field(ge=2, le=MAX_VOCAB_SIZE)
    embedding_dim: StrictInt = Field(ge=1, le=MAX_EMBEDDING_DIM)
    num_labels: StrictInt = Field(ge=2, le=MAX_NUM_LABELS)
    max_sequence_length: StrictInt = Field(ge=1, le=MAX_SEQUENCE_LENGTH)
    initialization_seed: StrictInt = Field(ge=0, le=2**32 - 1)
    model_version: StrictStr = Field(min_length=1, max_length=32)

    @field_validator("model_version")
    @classmethod
    def _canonical_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model_version must not be blank")
        return value


__all__ = [
    "MAX_EMBEDDING_DIM",
    "MAX_NUM_LABELS",
    "MAX_SEQUENCE_LENGTH",
    "MAX_VOCAB_SIZE",
    "NATIVE_MODEL_CONTRACT_VERSION",
    "NativeModelConfig",
]
