"""Task 209: project-owned native model contracts.

Data-only contracts for a small, randomly initialized encoder-style
Transformer for a narrow synthetic classification task. No pretrained
weights, tokenizer, vocabulary, or downloaded artifact exists in this
path.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MODEL_VERSION = "1.0"
"""Model architecture version. Any architectural change requires a version change."""

MODEL_ARCHITECTURE = "tiny-encoder-v1"
"""Fixed architecture identifier for the initial model."""

MAX_VOCAB_SIZE = 8192
"""Conservative upper bound for vocabulary size (including reserved tokens)."""

MAX_HIDDEN_DIM = 256
"""Conservative upper bound for hidden dimension."""

MAX_NUM_LAYERS = 4
"""Conservative upper bound for number of encoder layers."""

MAX_NUM_HEADS = 8
"""Conservative upper bound for number of attention heads."""

MAX_SEQ_LEN = 512
"""Conservative upper bound for maximum sequence length (matches tokenizer limit)."""

MAX_TOTAL_PARAMS = 500_000
"""Conservative upper bound for total trainable parameters."""

_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _reject_ambiguous_number(value: object, field_name: str) -> object:
    """Reject booleans and strings before lax numeric parsing."""
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError(f"{field_name} is invalid")
    return value


def _reject_ambiguous_float(value: object, field_name: str) -> object:
    """Reject booleans and strings before lax numeric parsing for floats."""
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError(f"{field_name} is invalid")
    return value


class NativeModelConfig(BaseModel):
    """Versioned native model configuration (Task 209).

    Defines a compact encoder-style Transformer for a narrow synthetic
    classification task. All parameters are randomly initialized from a
    documented seed. No pretrained components are used.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: Literal["1.0"]
    architecture: Literal["tiny-encoder-v1"]
    vocab_size: int = Field(ge=2, le=MAX_VOCAB_SIZE)
    hidden_dim: int = Field(ge=16, le=MAX_HIDDEN_DIM)
    num_layers: int = Field(ge=1, le=MAX_NUM_LAYERS)
    num_heads: int = Field(ge=1, le=MAX_NUM_HEADS)
    max_seq_len: int = Field(ge=1, le=MAX_SEQ_LEN)
    num_classes: int = Field(ge=2, le=128)
    dropout: float = Field(ge=0.0, le=0.5)
    init_seed: int = Field(ge=0, le=2**32 - 1)
    init_std: float = Field(gt=0.0, le=1.0)

    @field_validator(
        "vocab_size",
        "hidden_dim",
        "num_layers",
        "num_heads",
        "max_seq_len",
        "num_classes",
        "init_seed",
        mode="before",
    )
    @classmethod
    def _strict_int(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "integer field")

    @field_validator("dropout", "init_std", mode="before")
    @classmethod
    def _strict_float(cls, value: object) -> object:
        return _reject_ambiguous_float(value, "float field")

    @model_validator(mode="after")
    def _validate_architecture_constraints(self) -> NativeModelConfig:
        if self.hidden_dim % self.num_heads != 0:
            raise ValueError("hidden_dim must be divisible by num_heads")
        if self.num_heads > self.hidden_dim:
            raise ValueError("num_heads cannot exceed hidden_dim")
        return self


class NativeModelMetadata(BaseModel):
    """Immutable metadata for a constructed native model (Task 209).

    Records configuration, parameter count, and initialization hash.
    Does not contain model weights or training data.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: Literal["1.0"]
    architecture: Literal["tiny-encoder-v1"]
    config_hash: str = Field(min_length=64, max_length=64)
    parameter_count: int = Field(ge=0, le=MAX_TOTAL_PARAMS)
    init_seed: int
    init_hash: str = Field(min_length=64, max_length=64)
    data_scope: Literal["synthetic-test-only"]

    @model_validator(mode="after")
    def _validate_hashes(self) -> NativeModelMetadata:
        if not re.fullmatch(r"[0-9a-f]{64}", self.config_hash):
            raise ValueError("config_hash is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", self.init_hash):
            raise ValueError("init_hash is invalid")
        return self


class NativeModelSpec(BaseModel):
    """Complete native model specification: metadata plus parameter shapes.

    Weights themselves are not stored in the spec; they are produced
    deterministically by the initialization function.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: NativeModelMetadata
    parameter_shapes: dict[str, list[int]]

    @model_validator(mode="after")
    def _validate_shapes(self) -> NativeModelSpec:
        def _prod(shape: list[int]) -> int:
            result = 1
            for dim in shape:
                result *= dim
            return result

        total = sum(
            _prod(shape) if shape else 1 for shape in self.parameter_shapes.values()
        )
        if total != self.metadata.parameter_count:
            raise ValueError("parameter_shapes do not match parameter_count")
        return self


__all__ = [
    "MODEL_VERSION",
    "MODEL_ARCHITECTURE",
    "MAX_VOCAB_SIZE",
    "MAX_HIDDEN_DIM",
    "MAX_NUM_LAYERS",
    "MAX_NUM_HEADS",
    "MAX_SEQ_LEN",
    "MAX_TOTAL_PARAMS",
    "NativeModelConfig",
    "NativeModelMetadata",
    "NativeModelSpec",
]
