"""Task 207 strict contracts for authorized dataset manifests.

An offline data-preparation boundary: authorization, purpose, privacy
and provenance are declared and validated before any record is
accepted. The pipeline never guesses authorization and never stores raw
private content — records carry stable identifiers and content
fingerprints only. No model, network, or database access.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

DATASET_MANIFEST_CONTRACT_VERSION = "1"
MAX_RECORDS = 1000000
MAX_LABELS = 256
MAX_TRANSFORMATION_VERSIONS = 64
MAX_SAFE_ID_LENGTH = 200


class AuthorizationStatus(StrEnum):
    """Declared rights state; UNKNOWN is never treated as authorization."""

    AUTHORIZED = "AUTHORIZED"
    UNKNOWN = "UNKNOWN"
    REVOKED = "REVOKED"


class PermittedPurpose(StrEnum):
    """Explicitly enumerated permitted purposes."""

    TRAINING = "TRAINING"
    VALIDATION = "VALIDATION"
    EVALUATION = "EVALUATION"
    SYNTHETIC_TESTING = "SYNTHETIC_TESTING"


class DatasetRejectionCode(StrEnum):
    """Stable reason codes; no raw content appears in any message."""

    SOURCE_AUTHORIZATION_UNKNOWN = "SOURCE_AUTHORIZATION_UNKNOWN"
    SOURCE_NOT_AUTHORIZED = "SOURCE_NOT_AUTHORIZED"
    PURPOSE_NOT_APPROVED = "PURPOSE_NOT_APPROVED"
    LABEL_OUT_OF_SPACE = "LABEL_OUT_OF_SPACE"
    RECORD_STRUCTURE_INVALID = "RECORD_STRUCTURE_INVALID"
    PRIVACY_UNSAFE = "PRIVACY_UNSAFE"
    GROUP_CROSS_SPLIT = "GROUP_CROSS_SPLIT"
    CONTENT_CROSS_SPLIT = "CONTENT_CROSS_SPLIT"
    DUPLICATE_CONTENT_LABEL_CONFLICT = "DUPLICATE_CONTENT_LABEL_CONFLICT"


class DatasetSourceDescriptor(BaseModel):
    """One declared dataset source with its authorization state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: StrictStr = Field(min_length=1, max_length=MAX_SAFE_ID_LENGTH)
    authorization: AuthorizationStatus
    permitted_purposes: tuple[PermittedPurpose, ...] = Field(
        min_length=1, max_length=len(PermittedPurpose)
    )
    provenance_reference: StrictStr = Field(min_length=1, max_length=500)
    is_synthetic: StrictBool = False

    @field_validator("source_id", "provenance_reference")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("fields must not be blank")
        if any(ord(character) < 32 for character in value):
            raise ValueError("fields must not contain control characters")
        return value

    @field_validator("permitted_purposes")
    @classmethod
    def _canonical_purposes(
        cls, value: tuple[PermittedPurpose, ...]
    ) -> tuple[PermittedPurpose, ...]:
        if len(set(value)) != len(value):
            raise ValueError("permitted_purposes must not repeat a purpose")
        if value != tuple(sorted(value, key=lambda purpose: purpose.value)):
            raise ValueError("permitted_purposes must be canonically sorted")
        return value


class RawDatasetRecord(BaseModel):
    """One record's safe projection; raw text never leaves the boundary.

    ``content_fingerprint`` is the SHA-256 of the normalized content, so
    exact-duplicate detection works without retaining the content
    itself. ``group_key`` is the leakage-relevant unit (subject,
    document, source) when lawfully known.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: StrictStr = Field(min_length=1, max_length=MAX_SAFE_ID_LENGTH)
    group_key: StrictStr = Field(min_length=1, max_length=MAX_SAFE_ID_LENGTH)
    content_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    labels: tuple[StrictStr, ...] = Field(min_length=1, max_length=MAX_LABELS)
    privacy_safe: StrictBool

    @field_validator("record_id", "group_key")
    @classmethod
    def _safe_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifiers must not be blank")
        if any(ord(character) < 32 for character in value):
            raise ValueError("identifiers must not contain control characters")
        return value

    @field_validator("labels")
    @classmethod
    def _canonical_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("labels must not contain duplicates")
        if value != tuple(sorted(value)):
            raise ValueError("labels must be canonically sorted")
        return value


class SplitCounts(BaseModel):
    """Deterministic example and group counts for one split."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_count: StrictInt = Field(ge=0)
    group_count: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def _groups_within_records(self) -> SplitCounts:
        if self.group_count > self.record_count:
            raise ValueError("a split cannot have more groups than records")
        return self


class DatasetManifest(BaseModel):
    """Versioned manifest describing one prepared dataset snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"]
    dataset_id: StrictStr = Field(min_length=1, max_length=MAX_SAFE_ID_LENGTH)
    schema_version: StrictStr = Field(min_length=1, max_length=32)
    label_space_version: StrictStr = Field(min_length=1, max_length=32)
    source: DatasetSourceDescriptor
    transformation_versions: tuple[StrictStr, ...] = Field(
        max_length=MAX_TRANSFORMATION_VERSIONS
    )
    split_strategy: StrictStr = Field(min_length=1, max_length=100)
    dataset_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    split_fingerprints: tuple[tuple[str, str], ...] = Field(max_length=8)
    train_counts: SplitCounts
    validation_counts: SplitCounts
    test_counts: SplitCounts
    label_distribution: tuple[tuple[str, StrictInt], ...] = Field(max_length=MAX_LABELS)
    authorization_evidence_reference: StrictStr = Field(min_length=1, max_length=500)
    training_blocked_reason: StrictStr | None = Field(max_length=500)

    @field_validator("dataset_id", "authorization_evidence_reference")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("fields must not be blank")
        if any(ord(character) < 32 for character in value):
            raise ValueError("fields must not contain control characters")
        return value

    @field_validator("transformation_versions")
    @classmethod
    def _canonical_versions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("transformation_versions must not repeat a version")
        if value != tuple(sorted(value)):
            raise ValueError("transformation_versions must be canonically sorted")
        return value

    @field_validator("split_fingerprints")
    @classmethod
    def _canonical_split_fingerprints(
        cls, value: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, str], ...]:
        names = [pair[0] for pair in value]
        if len(set(names)) != len(names):
            raise ValueError("split_fingerprints must not repeat a split name")
        if value != tuple(sorted(value)):
            raise ValueError("split_fingerprints must be canonically sorted")
        return value

    @field_validator("label_distribution")
    @classmethod
    def _canonical_distribution(
        cls, value: tuple[tuple[str, StrictInt], ...]
    ) -> tuple[tuple[str, StrictInt], ...]:
        names = [pair[0] for pair in value]
        if len(set(names)) != len(names):
            raise ValueError("label_distribution must not repeat a label")
        if value != tuple(sorted(value)):
            raise ValueError("label_distribution must be canonically sorted")
        if any(count < 0 for _, count in value):
            raise ValueError("label_distribution counts must be non-negative")
        return value

    @model_validator(mode="after")
    def _authorization_gate(self) -> DatasetManifest:
        if (
            self.source.authorization is not AuthorizationStatus.AUTHORIZED
            and self.training_blocked_reason is None
        ):
            raise ValueError(
                "an unauthorized or unknown source must declare why training "
                "is blocked"
            )
        return self


__all__ = [
    "AuthorizationStatus",
    "DATASET_MANIFEST_CONTRACT_VERSION",
    "DatasetManifest",
    "DatasetRejectionCode",
    "DatasetSourceDescriptor",
    "PermittedPurpose",
    "RawDatasetRecord",
    "SplitCounts",
]
