"""Task 207 authorized dataset preparation pipeline.

Offline boundary that validates authorization, normalizes and
deduplicates records, and produces leakage-safe reproducible splits.
Authorization is never guessed: unknown or revoked sources are rejected
with stable reason codes. Raw content stays outside the pipeline; only
fingerprints and safe identifiers are handled here. No model, network,
or persistence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from rop.schemas.dataset_manifest import (
    AuthorizationStatus,
    DatasetManifest,
    DatasetRejectionCode,
    DatasetSourceDescriptor,
    PermittedPurpose,
    RawDatasetRecord,
    SplitCounts,
)

# Stable transformation identifier for this pipeline version; recorded
# in every manifest so an auditor can pin the exact normalization.
NORMALIZATION_TRANSFORMATION_VERSION = "native-normalization-v1"
SPLIT_STRATEGY = "group-hash-v1"
_HASH_SPACE = 16**16
MAX_RECORDS = 1_000_000


class DatasetPreparationError(Exception):
    """Typed, privacy-safe rejection carrying a stable reason code."""

    def __init__(self, code: DatasetRejectionCode, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code.value}] {detail}")


@dataclass(frozen=True)
class PreparedSplits:
    """Reproducible, group-disjoint train/validation/test partitions."""

    train: tuple[RawDatasetRecord, ...]
    validation: tuple[RawDatasetRecord, ...]
    test: tuple[RawDatasetRecord, ...]

    def all_records(self) -> tuple[RawDatasetRecord, ...]:
        return self.train + self.validation + self.test


def normalize_content(content: str) -> str:
    """Deterministic, reversible-by-no-one normalization of raw text.

    Unicode NFKC, casefolded, whitespace collapsed. Used only to derive
    a fingerprint; the normalized text is never persisted by the
    pipeline.
    """
    import unicodedata

    normalized = unicodedata.normalize("NFKC", content)
    folded = normalized.casefold()
    return " ".join(folded.split())


def content_fingerprint(content: str) -> str:
    """SHA-256 of the normalized content; exact-duplicate detector."""
    return hashlib.sha256(normalize_content(content).encode("utf-8")).hexdigest()


def require_authorized_source(
    source: DatasetSourceDescriptor, purpose: PermittedPurpose
) -> None:
    """Fail closed unless the source explicitly authorizes this purpose."""
    if source.authorization is AuthorizationStatus.UNKNOWN:
        raise DatasetPreparationError(
            DatasetRejectionCode.SOURCE_AUTHORIZATION_UNKNOWN,
            "authorization must be explicitly declared before use",
        )
    if source.authorization is not AuthorizationStatus.AUTHORIZED:
        raise DatasetPreparationError(
            DatasetRejectionCode.SOURCE_NOT_AUTHORIZED,
            "the source is not authorized for any purpose",
        )
    if purpose not in source.permitted_purposes:
        raise DatasetPreparationError(
            DatasetRejectionCode.PURPOSE_NOT_APPROVED,
            "the declared purpose is not in the permitted purposes",
        )


def validate_records(
    records: Iterable[RawDatasetRecord], label_space: tuple[str, ...]
) -> tuple[RawDatasetRecord, ...]:
    """Reject unsafe, out-of-space or structurally invalid records."""
    accepted: list[RawDatasetRecord] = []
    seen_ids: set[str] = set()
    for record in records:
        if len(accepted) >= MAX_RECORDS:
            raise DatasetPreparationError(
                DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
                "the record set exceeds the supported bound",
            )
        if not record.privacy_safe:
            raise DatasetPreparationError(
                DatasetRejectionCode.PRIVACY_UNSAFE,
                "records must be declared privacy-safe before preparation",
            )
        if any(label not in label_space for label in record.labels):
            raise DatasetPreparationError(
                DatasetRejectionCode.LABEL_OUT_OF_SPACE,
                "a record declares a label outside the declared label space",
            )
        if record.record_id in seen_ids:
            raise DatasetPreparationError(
                DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
                "record identifiers must be unique",
            )
        seen_ids.add(record.record_id)
        accepted.append(record)
    return tuple(accepted)


def exact_deduplicate(
    records: tuple[RawDatasetRecord, ...],
) -> tuple[RawDatasetRecord, ...]:
    """Keep the canonically first record of each fingerprint group.

    Exact duplicates only; near-duplicate judgement requires human
    review and is deliberately not guessed by this pipeline.
    """
    by_fingerprint: dict[str, RawDatasetRecord] = {}
    for record in sorted(records, key=lambda item: item.record_id):
        by_fingerprint.setdefault(record.content_fingerprint, record)
    return tuple(sorted(by_fingerprint.values(), key=lambda item: item.record_id))


def assign_group_safe_splits(
    records: tuple[RawDatasetRecord, ...],
    *,
    train_ratio: float,
    validation_ratio: float,
) -> PreparedSplits:
    """Reproducible split keyed on the group, never on the record.

    A group's records always land in the same split, so zero
    cross-split group leakage is enforced by construction. The hash of
    the group key selects the partition; no RNG is involved.
    """
    if not 0.0 < train_ratio < 1.0 or not 0.0 <= validation_ratio < 1.0:
        raise DatasetPreparationError(
            DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
            "split ratios must be in [0, 1) with train_ratio > 0",
        )
    if train_ratio + validation_ratio >= 1.0:
        raise DatasetPreparationError(
            DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
            "train and validation ratios must leave room for the test split",
        )

    buckets: dict[str, list[RawDatasetRecord]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    for record in sorted(records, key=lambda item: item.record_id):
        digest = hashlib.sha256(record.group_key.encode("utf-8")).hexdigest()
        position = int(digest[:16], 16) / float(_HASH_SPACE)
        if position < train_ratio:
            buckets["train"].append(record)
        elif position < train_ratio + validation_ratio:
            buckets["validation"].append(record)
        else:
            buckets["test"].append(record)

    return PreparedSplits(
        train=tuple(buckets["train"]),
        validation=tuple(buckets["validation"]),
        test=tuple(buckets["test"]),
    )


def fit_transformation_on_train_only(
    splits: PreparedSplits,
    fit: Callable[[tuple[RawDatasetRecord, ...]], dict[str, int]],
) -> dict[str, int]:
    """Fit any data-dependent transformation strictly on the train split."""
    return fit(splits.train)


def build_manifest(
    *,
    dataset_id: str,
    schema_version: str,
    label_space_version: str,
    source: DatasetSourceDescriptor,
    splits: PreparedSplits,
    label_space: tuple[str, ...],
    authorization_evidence_reference: str,
    training_blocked_reason: str | None = None,
) -> DatasetManifest:
    """Assemble the versioned, privacy-safe manifest for one snapshot."""
    all_records = splits.all_records()
    label_distribution = {
        label: sum(1 for record in all_records if label in record.labels)
        for label in sorted(label_space)
    }
    train_groups = {record.group_key for record in splits.train}
    validation_groups = {record.group_key for record in splits.validation}
    test_groups = {record.group_key for record in splits.test}
    if (
        train_groups & validation_groups
        or train_groups & test_groups
        or (validation_groups & test_groups)
    ):
        raise DatasetPreparationError(
            DatasetRejectionCode.GROUP_CROSS_SPLIT,
            "leakage detected: one group appears in more than one split",
        )

    split_fingerprints = tuple(
        sorted(
            (
                (name, _fingerprint_records(records))
                for name, records in (
                    ("train", splits.train),
                    ("test", splits.test),
                    ("validation", splits.validation),
                )
            )
        )
    )
    dataset_fingerprint = _fingerprint_records(all_records)

    return DatasetManifest.model_validate(
        {
            "contract_version": "1",
            "dataset_id": dataset_id,
            "schema_version": schema_version,
            "label_space_version": label_space_version,
            "source": source.model_dump(mode="json"),
            "transformation_versions": [NORMALIZATION_TRANSFORMATION_VERSION],
            "split_strategy": SPLIT_STRATEGY,
            "dataset_fingerprint": dataset_fingerprint,
            "split_fingerprints": split_fingerprints,
            "train_counts": SplitCounts(
                record_count=len(splits.train),
                group_count=len(train_groups),
            ).model_dump(mode="json"),
            "validation_counts": SplitCounts(
                record_count=len(splits.validation),
                group_count=len(validation_groups),
            ).model_dump(mode="json"),
            "test_counts": SplitCounts(
                record_count=len(splits.test),
                group_count=len(test_groups),
            ).model_dump(mode="json"),
            "label_distribution": [
                [label, count] for label, count in sorted(label_distribution.items())
            ],
            "authorization_evidence_reference": authorization_evidence_reference,
            "training_blocked_reason": training_blocked_reason,
        }
    )


def _fingerprint_records(records: tuple[RawDatasetRecord, ...]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item.record_id):
        digest.update(record.record_id.encode("utf-8"))
        digest.update(record.content_fingerprint.encode("utf-8"))
    return digest.hexdigest()


__all__ = [
    "DatasetPreparationError",
    "NORMALIZATION_TRANSFORMATION_VERSION",
    "PreparedSplits",
    "SPLIT_STRATEGY",
    "assign_group_safe_splits",
    "build_manifest",
    "content_fingerprint",
    "exact_deduplicate",
    "fit_transformation_on_train_only",
    "normalize_content",
    "require_authorized_source",
    "validate_records",
]
