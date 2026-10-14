"""Task 211: artifact manifest and checkpoint integrity contracts.

Data-only contracts for the minimal checkpoint representation of the
Task 209 ``tiny-encoder-v1`` model and its Task 210 training lineage.
No pretrained weights, external model files, downloads, inference, or
clinical logic live here.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ARTIFACT_MANIFEST_VERSION = "1.0"
"""Manifest schema version. Any contract change requires a version change."""

CHECKPOINT_FORMAT = "rop-raw-tensor-v1"
"""Checkpoint serialization format identifier (pickle-free raw tensors)."""

CHECKPOINT_FORMAT_VERSION = "1.0"
"""Checkpoint format version. Any layout change requires a version change."""

ARTIFACT_TYPE_MODEL_CHECKPOINT = "model-checkpoint"
"""The only artifact type supported by Task 211."""

MAX_ARTIFACT_ID_LENGTH = 64
MAX_CHECKPOINT_BYTES = 4_000_000
"""Conservative upper bound on checkpoint file size (500k params * 4B + header)."""

MAX_HEADER_BYTES = 256_000
"""Conservative upper bound on the checkpoint JSON header size."""

_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")


def _reject_ambiguous_number(value: object, field_name: str) -> object:
    """Reject booleans and strings before lax numeric parsing."""
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError(f"{field_name} is invalid")
    return value


class ArtifactManifest(BaseModel):
    """Strict immutable artifact manifest (Task 211).

    Identifies one ``model-checkpoint`` artifact and its full
    synthetic-test-only lineage. ``content_digest`` is the SHA-256 of
    the actual checkpoint bytes. ``manifest_digest`` is the SHA-256 of
    the canonical manifest representation excluding itself, keeping the
    two digests distinct to avoid circular hashing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: Literal["1.0"]
    artifact_type: Literal["model-checkpoint"]
    artifact_id: str = Field(min_length=1, max_length=MAX_ARTIFACT_ID_LENGTH)
    content_digest: str = Field(min_length=64, max_length=64)
    checkpoint_format: Literal["rop-raw-tensor-v1"]
    checkpoint_format_version: Literal["1.0"]
    model_version: Literal["1.0"]
    architecture: Literal["tiny-encoder-v1"]
    model_config_hash: str = Field(min_length=64, max_length=64)
    parameter_count: int = Field(ge=1)
    training_config_hash: str = Field(min_length=64, max_length=64)
    training_seed: int = Field(ge=0, le=2**32 - 1)
    model_init_seed: int = Field(ge=0, le=2**32 - 1)
    dataset_id: str = Field(min_length=1, max_length=64)
    dataset_integrity_hash: str = Field(min_length=64, max_length=64)
    split_assignment_hash: str = Field(min_length=64, max_length=64)
    vocabulary_hash: str = Field(min_length=64, max_length=64)
    tokenizer_config_hash: str = Field(min_length=64, max_length=64)
    data_scope: Literal["synthetic-test-only"]
    manifest_digest: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _strict_manifest(self) -> ArtifactManifest:
        if not _ID_RE.fullmatch(self.artifact_id):
            raise ValueError("artifact_id is invalid")
        if not _ID_RE.fullmatch(self.dataset_id):
            raise ValueError("dataset_id is invalid")
        for name in (
            "content_digest",
            "model_config_hash",
            "training_config_hash",
            "dataset_integrity_hash",
            "split_assignment_hash",
            "vocabulary_hash",
            "tokenizer_config_hash",
            "manifest_digest",
        ):
            if not _FINGERPRINT_RE.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} is invalid")
        return self


ArtifactErrorCode = Literal[
    "INVALID_INPUT",
    "INVALID_MANIFEST",
    "UNSUPPORTED_VERSION",
    "UNSUPPORTED_FORMAT",
    "WRONG_ARTIFACT_TYPE",
    "MISSING_METADATA",
    "HASH_MISMATCH",
    "MANIFEST_DIGEST_MISMATCH",
    "INCOMPATIBLE_MODEL",
    "INCOMPATIBLE_TRAINING",
    "INCOMPATIBLE_DATASET",
    "INCOMPATIBLE_VOCABULARY",
    "INCOMPATIBLE_TOKENIZER",
    "UNSUPPORTED_SCOPE",
    "OPERATION_NOT_PERMITTED",
    "SPLIT_INTEGRITY_FAILURE",
    "CORRUPT_CHECKPOINT",
]


__all__ = [
    "ARTIFACT_MANIFEST_VERSION",
    "ARTIFACT_TYPE_MODEL_CHECKPOINT",
    "CHECKPOINT_FORMAT",
    "CHECKPOINT_FORMAT_VERSION",
    "MAX_ARTIFACT_ID_LENGTH",
    "MAX_CHECKPOINT_BYTES",
    "MAX_HEADER_BYTES",
    "ArtifactErrorCode",
    "ArtifactManifest",
]
