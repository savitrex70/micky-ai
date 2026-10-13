"""Task 208: project-controlled tokenizer and vocabulary contracts.

Data-only contracts for deterministic tokenization and
training-partition vocabulary construction. Token bytes are
project-owned logic over standard-library facilities only: no
pretrained tokenizer, vocabulary, merge table, or downloaded
artifact exists anywhere in this path.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TOKENIZER_VERSION = "1.0"
VOCABULARY_VERSION = "1.0"

RESERVED_TOKENS: tuple[str, str] = ("<pad>", "<unk>")
"""Fixed reserved tokens in ID order: pad is 0, unknown is 1."""

PAD_ID = 0
UNK_ID = 1

MAX_SEQUENCE_LENGTH_LIMIT = 512


def _reject_ambiguous_number(value: object, field_name: str) -> object:
    """Reject booleans and strings before lax numeric parsing."""
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError(f"{field_name} is invalid")
    return value


class TokenizerConfig(BaseModel):
    """Versioned tokenizer configuration (Task 208).

    v1 policy: Unicode NFC, case preserved, whitespace-separated
    words split into alphanumeric runs and single punctuation
    characters, interior ASCII apostrophes kept inside words,
    head truncation to ``max_sequence_length``. Any behavior
    change requires a version change.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tokenizer_version: Literal["1.0"]
    normalization: Literal["NFC"]
    preserve_case: Literal[True]
    max_sequence_length: int = Field(ge=1, le=MAX_SEQUENCE_LENGTH_LIMIT)

    @field_validator("max_sequence_length", mode="before")
    @classmethod
    def _strict_length(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "max_sequence_length")


class VocabularyMetadata(BaseModel):
    """Strict immutable vocabulary metadata (Task 208).

    ``data_scope`` records the trust scope of the originating
    dataset; only ``synthetic-test-only`` exists today. Token
    strings necessarily appear in the vocabulary artifact itself;
    training records are never copied into metadata.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    vocabulary_version: Literal["1.0"]
    tokenizer_version: Literal["1.0"]
    policy_version: Literal["1.0"]
    tokenizer_config_hash: str = Field(min_length=64, max_length=64)
    reserved_tokens: tuple[str, ...]
    vocabulary_size: int = Field(ge=2)
    max_vocab_size: int | None = Field(default=None, ge=2)
    min_frequency: int = Field(ge=1)
    vocabulary_hash: str = Field(min_length=64, max_length=64)
    dataset_id: str = Field(min_length=1, max_length=64)
    dataset_integrity_hash: str = Field(min_length=64, max_length=64)
    split_assignment_hash: str = Field(min_length=64, max_length=64)
    data_scope: Literal["synthetic-test-only"]

    @model_validator(mode="after")
    def _strict_metadata(self) -> VocabularyMetadata:
        if tuple(self.reserved_tokens) != tuple(RESERVED_TOKENS):
            raise ValueError("reserved_tokens is invalid")
        for name in (
            "tokenizer_config_hash",
            "vocabulary_hash",
            "dataset_integrity_hash",
            "split_assignment_hash",
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", getattr(self, name)):
                raise ValueError(f"{name} is invalid")
        return self


class Vocabulary(BaseModel):
    """One immutable fitted vocabulary: metadata plus ordered tokens.

    Token IDs are positional: ``tokens[0]`` is ID 0. Reserved
    tokens occupy the fixed leading positions in order.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: VocabularyMetadata
    tokens: tuple[str, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _strict_vocabulary(self) -> Vocabulary:
        if tuple(self.tokens[: len(RESERVED_TOKENS)]) != tuple(RESERVED_TOKENS):
            raise ValueError("reserved tokens are invalid")
        if len(set(self.tokens)) != len(self.tokens):
            raise ValueError("tokens must not contain duplicates")
        if len(self.tokens) != self.metadata.vocabulary_size:
            raise ValueError("vocabulary size is inconsistent")
        return self


__all__ = [
    "MAX_SEQUENCE_LENGTH_LIMIT",
    "PAD_ID",
    "RESERVED_TOKENS",
    "TOKENIZER_VERSION",
    "UNK_ID",
    "VOCABULARY_VERSION",
    "TokenizerConfig",
    "Vocabulary",
    "VocabularyMetadata",
]
