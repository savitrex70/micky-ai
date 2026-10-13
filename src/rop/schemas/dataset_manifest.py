"""Task 207: strict dataset, record, and split manifest contracts.

Data-only contracts for governed dataset preparation. Records
carry normalized content with a verified content hash; manifests
carry identifiers, hashes, counts, and policy versions -- never
raw content, credentials, paths, or secrets. ``DatasetRecord``
instances must be built through the preparation pipeline, which
normalizes content before validation; the digest check here
verifies integrity of the supplied bytes only.
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DATASET_MANIFEST_VERSION = "2.1"
TRANSFORM_VERSION = "1.0"
DEDUP_POLICY_VERSION = "1.0"
SPLIT_POLICY_NAME = "group-hash-partition-v1"
SPLIT_MANIFEST_VERSION = "1.1"
RECORD_INTEGRITY_VERSION = "2.0"

MAX_CONTENT_LENGTH = 2000
MAX_SOURCE_REF_LENGTH = 255
MAX_LABELS = 32

_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")
_SOURCE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,254}")
_GROUPING_UNIT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,;:_()/-]{0,119}")

PartitionName = Literal["train", "validation", "test"]


def _rejects_unsafe_reference(value: str) -> bool:
    """Refuse traversal, absolute paths, and control characters."""
    if "\n" in value or "\r" in value or "\x00" in value:
        return True
    if ".." in value:
        return True
    if value.startswith("/"):
        return True
    if "\\" in value:
        return True
    if len(value) >= 2 and value[1] == ":":
        return True
    return False


def _reject_ambiguous_number(value: object, field_name: str) -> object:
    """Reject booleans and strings before lax numeric parsing."""
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError(f"{field_name} is invalid")
    return value


class SplitConfig(BaseModel):
    """Explicit, versioned split configuration (Task 207)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: int
    train_ratio: float
    validation_ratio: float
    test_ratio: float

    @field_validator("seed", mode="before")
    @classmethod
    def _check_seed(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "seed")

    @field_validator("train_ratio", "validation_ratio", "test_ratio", mode="before")
    @classmethod
    def _check_ratio(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "ratio")

    @model_validator(mode="after")
    def _strict_split(self) -> SplitConfig:
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise ValueError("seed is invalid")
        for name in ("train_ratio", "validation_ratio", "test_ratio"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)):
                raise ValueError(f"{name} is invalid")
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} is invalid")
        total = self.train_ratio + self.validation_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-9:
            raise ValueError("split ratios are invalid")
        return self


class DatasetRecord(BaseModel):
    """One validated, normalized dataset record (Task 207).

    ``content_text`` must already be in normalized form and
    ``content_hash`` must be its SHA-256 hex digest; the pipeline
    establishes both before validation. Identifiers are compared
    verbatim downstream and are never normalized.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=64)
    group_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=64)
    content_text: str = Field(max_length=MAX_CONTENT_LENGTH)
    content_hash: str = Field(min_length=64, max_length=64)
    provenance_ref: str = Field(min_length=1, max_length=MAX_SOURCE_REF_LENGTH)

    @model_validator(mode="after")
    def _strict_record(self) -> DatasetRecord:
        for name in ("record_id", "source_id", "group_id"):
            if not _ID_RE.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} is invalid")
        if not _LABEL_RE.fullmatch(self.label):
            raise ValueError("label is invalid")
        if not 1 <= len(self.content_text) <= MAX_CONTENT_LENGTH:
            raise ValueError("content_text is invalid")
        if "\n" in self.content_text or "\r" in self.content_text:
            raise ValueError("content_text is invalid")
        if not _FINGERPRINT_RE.fullmatch(self.content_hash):
            raise ValueError("content_hash is invalid")
        if (
            hashlib.sha256(self.content_text.encode("utf-8")).hexdigest()
            != self.content_hash
        ):
            raise ValueError("content_hash is invalid")
        if not _SOURCE_REF_RE.fullmatch(self.provenance_ref):
            raise ValueError("provenance_ref is invalid")
        if _rejects_unsafe_reference(self.provenance_ref):
            raise ValueError("provenance_ref is invalid")
        return self


class LabelCount(BaseModel):
    """One label and its retained-record count."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    count: int = Field(ge=0)


class RejectionCount(BaseModel):
    """One safe rejection reason code and its record count."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    count: int = Field(ge=0)


class GroupAssignment(BaseModel):
    """One leakage group's partition assignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    group_id: str
    partition: PartitionName


class DatasetManifest(BaseModel):
    """Versioned manifest of a prepared dataset (Task 207).

    ``authorization_kind`` records the trust scope the dataset was
    prepared under. Only ``synthetic-test-only`` exists: every
    manifest produced today is structurally marked test-scoped and
    cannot pass as production-authorized evidence. A production
    kind would require a new schema version and reviewed approval
    verification.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1, max_length=64)
    manifest_version: Literal["2.1"]
    authorization_kind: Literal["synthetic-test-only"]
    source_ids: tuple[str, ...] = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=64)
    operation: Literal["training", "validation", "evaluation"]
    allowed_labels: tuple[str, ...] = Field(min_length=1, max_length=MAX_LABELS)
    transform_version: Literal["1.0"]
    dedup_policy_version: Literal["1.0"]
    grouping_unit: str = Field(min_length=1, max_length=120)
    split_config: SplitConfig
    label_counts: tuple[LabelCount, ...]
    rejection_counts: tuple[RejectionCount, ...]
    record_count: int = Field(ge=0)
    record_integrity_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _strict_manifest(self) -> DatasetManifest:
        if not _ID_RE.fullmatch(self.dataset_id):
            raise ValueError("dataset_id is invalid")
        for source_id in self.source_ids:
            if not _ID_RE.fullmatch(source_id):
                raise ValueError("source_ids entry is invalid")
        if len(set(self.source_ids)) != len(self.source_ids) or list(
            self.source_ids
        ) != sorted(self.source_ids):
            raise ValueError("source_ids must be unique and sorted")
        if not _ID_RE.fullmatch(self.purpose):
            raise ValueError("purpose is invalid")
        for label in self.allowed_labels:
            if not _LABEL_RE.fullmatch(label):
                raise ValueError("allowed_labels entry is invalid")
        if len(set(self.allowed_labels)) != len(self.allowed_labels) or list(
            self.allowed_labels
        ) != sorted(self.allowed_labels):
            raise ValueError("allowed_labels must be unique and sorted")
        if not _GROUPING_UNIT_RE.fullmatch(self.grouping_unit):
            raise ValueError("grouping_unit is invalid")
        labels = [entry.label for entry in self.label_counts]
        if labels != sorted(labels) or len(set(labels)) != len(labels):
            raise ValueError("label_counts must be unique and sorted")
        if sum(entry.count for entry in self.label_counts) != self.record_count:
            raise ValueError("label_counts must agree with record_count")
        codes = [entry.code for entry in self.rejection_counts]
        if codes != sorted(codes) or len(set(codes)) != len(codes):
            raise ValueError("rejection_counts must be unique and sorted")
        if not _FINGERPRINT_RE.fullmatch(self.record_integrity_hash):
            raise ValueError("record_integrity_hash is invalid")
        return self


class SplitManifest(BaseModel):
    """Versioned manifest of leakage-safe partition assignments (Task 207).

    Carries the same ``authorization_kind`` taint as its dataset
    manifest: test-scoped splits cannot pass as production splits.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(min_length=1, max_length=64)
    manifest_version: Literal["1.1"]
    authorization_kind: Literal["synthetic-test-only"]
    split_policy: Literal["group-hash-partition-v1"]
    seed: int
    train_ratio: float
    validation_ratio: float
    test_ratio: float
    assignments: tuple[GroupAssignment, ...] = Field(min_length=1)
    train_count: int = Field(ge=0)
    validation_count: int = Field(ge=0)
    test_count: int = Field(ge=0)
    assignment_hash: str = Field(min_length=64, max_length=64)
    dataset_integrity_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def _strict_split_manifest(self) -> SplitManifest:
        if not _ID_RE.fullmatch(self.dataset_id):
            raise ValueError("dataset_id is invalid")
        groups = [entry.group_id for entry in self.assignments]
        if [entry.group_id for entry in self.assignments] != sorted(groups):
            raise ValueError("assignments must be sorted")
        if len(set(groups)) != len(groups):
            raise ValueError("assignments must not contain duplicates")
        for entry in self.assignments:
            if not _ID_RE.fullmatch(entry.group_id):
                raise ValueError("assignments entry is invalid")
        if not _FINGERPRINT_RE.fullmatch(self.assignment_hash):
            raise ValueError("assignment_hash is invalid")
        if not _FINGERPRINT_RE.fullmatch(self.dataset_integrity_hash):
            raise ValueError("dataset_integrity_hash is invalid")
        return self


class PartitionRecords(BaseModel):
    """The validated records assigned to one partition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    partition: PartitionName
    records: tuple[DatasetRecord, ...]

    @model_validator(mode="after")
    def _strict_partition(self) -> PartitionRecords:
        ids = [record.record_id for record in self.records]
        if ids != sorted(ids):
            raise ValueError("records must be sorted")
        if len(set(ids)) != len(ids):
            raise ValueError("records must not contain duplicates")
        return self


class RejectionDiagnostic(BaseModel):
    """One rejected input identified by record id (or unknown) and safe code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str | None
    code: str


class PreparationResult(BaseModel):
    """Complete deterministic output of dataset preparation (Task 207)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_manifest: DatasetManifest
    split_manifest: SplitManifest
    partitions: tuple[PartitionRecords, ...] = Field(min_length=3, max_length=3)
    rejections: tuple[RejectionDiagnostic, ...]

    @model_validator(mode="after")
    def _strict_result(self) -> PreparationResult:
        if [entry.partition for entry in self.partitions] != [
            "train",
            "validation",
            "test",
        ]:
            raise ValueError("partitions must cover train, validation, test in order")
        return self


__all__ = [
    "DATASET_MANIFEST_VERSION",
    "DEDUP_POLICY_VERSION",
    "MAX_CONTENT_LENGTH",
    "MAX_LABELS",
    "MAX_SOURCE_REF_LENGTH",
    "RECORD_INTEGRITY_VERSION",
    "SPLIT_MANIFEST_VERSION",
    "SPLIT_POLICY_NAME",
    "TRANSFORM_VERSION",
    "DatasetManifest",
    "DatasetRecord",
    "GroupAssignment",
    "LabelCount",
    "PartitionName",
    "PartitionRecords",
    "PreparationResult",
    "RejectionCount",
    "RejectionDiagnostic",
    "SplitConfig",
    "SplitManifest",
]
