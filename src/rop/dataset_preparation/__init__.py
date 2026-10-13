"""Task 207 authorized dataset preparation pipeline.

Offline boundary that validates authorization, normalizes and
deduplicates records, and produces leakage-safe reproducible splits.
Authorization is never guessed: unknown or revoked sources are rejected
with stable reason codes. Raw content stays outside the pipeline; only
fingerprints and safe identifiers are handled here. No model, network,
or persistence.

Fingerprint scheme (``FINGERPRINT_SCHEME_VERSION``): record-set fingerprints
bind the full effective record (ID, group key, content fingerprint, labels
and privacy-safety status) through a domain-separated, length-prefixed
encoding. Every dataset and per-split fingerprint produced by an earlier
scheme (which hashed only ``record_id`` and ``content_fingerprint``) differs
from the new values. Downstream Task 208-215 branches that bind manifests,
vocabularies, training reports, artifacts or acceptance reports to these
fingerprints must be refreshed against this scheme and their identity-binding
tests rerun before approval.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pydantic import ValidationError

from rop.schemas.dataset_manifest import (
    DATASET_MANIFEST_CONTRACT_VERSION,
    RECORDS_FINGERPRINT_SCHEME_VERSION,
    AuthorizationStatus,
    DatasetManifest,
    DatasetRejectionCode,
    DatasetSourceDescriptor,
    PermittedPurpose,
    RawDatasetRecord,
    SplitCounts,
    validate_label_space,
)

# Stable transformation identifier for this pipeline version; recorded
# in every manifest so an auditor can pin the exact normalization.
NORMALIZATION_TRANSFORMATION_VERSION = "native-normalization-v1"
SPLIT_STRATEGY = "group-hash-v1"
# Identifies the record-set fingerprint encoding; part of the hashed domain and
# recorded in every manifest as ``fingerprint_scheme_version``.
FINGERPRINT_SCHEME_VERSION = RECORDS_FINGERPRINT_SCHEME_VERSION
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


def _require_valid_label_space(label_space: tuple[str, ...]) -> None:
    """Reject a malformed label space with a stable, content-free error."""
    try:
        validate_label_space(tuple(label_space))
        malformed = False
    except (ValueError, TypeError):
        malformed = True
    if malformed:
        # Raised outside the handler so nothing from the label space is chained.
        raise DatasetPreparationError(
            DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
            "the label space must be nonempty, unique, sorted and nonblank",
        )


def validate_records(
    records: Iterable[RawDatasetRecord], label_space: tuple[str, ...]
) -> tuple[RawDatasetRecord, ...]:
    """Reject unsafe, out-of-space or structurally invalid records."""
    _require_valid_label_space(label_space)
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

    Conflict policy (fail closed): identical normalized content carrying
    different labels is an unresolved annotation disagreement, so the
    pipeline raises ``DUPLICATE_CONTENT_LABEL_CONFLICT`` instead of silently
    keeping one annotation. Duplicates with identical labels collapse to the
    record with the lexically first ``record_id``, even when their group keys
    differ; the content then appears exactly once, so no leakage results.
    """
    by_fingerprint: dict[str, RawDatasetRecord] = {}
    for record in sorted(records, key=lambda item: item.record_id):
        kept = by_fingerprint.setdefault(record.content_fingerprint, record)
        if kept.labels != record.labels:
            raise DatasetPreparationError(
                DatasetRejectionCode.DUPLICATE_CONTENT_LABEL_CONFLICT,
                "identical content carries conflicting labels",
            )
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
    """Assemble the versioned, privacy-safe manifest for one snapshot.

    The effective split data is validated before anything is published, so a
    manually constructed ``PreparedSplits`` cannot yield a manifest that
    claims leakage safety it does not have. The source's authorization state
    is carried into the manifest unchanged; ``UNKNOWN`` or ``REVOKED`` never
    reads as training approval and requires a ``training_blocked_reason``.
    """
    all_records = splits.all_records()
    _validate_split_integrity(splits, label_space)
    label_distribution = {
        label: sum(1 for record in all_records if label in record.labels)
        for label in sorted(label_space)
    }
    train_groups = {record.group_key for record in splits.train}
    validation_groups = {record.group_key for record in splits.validation}
    test_groups = {record.group_key for record in splits.test}

    split_fingerprints = tuple(
        sorted(
            (
                (name, records_fingerprint(records))
                for name, records in (
                    ("train", splits.train),
                    ("test", splits.test),
                    ("validation", splits.validation),
                )
            )
        )
    )
    dataset_fingerprint = records_fingerprint(all_records)

    return DatasetManifest.model_validate(
        {
            "contract_version": DATASET_MANIFEST_CONTRACT_VERSION,
            "dataset_id": dataset_id,
            "schema_version": schema_version,
            "label_space_version": label_space_version,
            "source": source.model_dump(mode="json"),
            "transformation_versions": [NORMALIZATION_TRANSFORMATION_VERSION],
            "split_strategy": SPLIT_STRATEGY,
            "fingerprint_scheme_version": FINGERPRINT_SCHEME_VERSION,
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


def _validate_split_integrity(
    splits: PreparedSplits, label_space: tuple[str, ...]
) -> None:
    """Fail closed on any violation of the leakage-safe split contract.

    Messages carry stable reason codes only; no identifier, group key or
    content ever appears in them.
    """
    _require_valid_label_space(label_space)
    named = (
        ("train", splits.train),
        ("validation", splits.validation),
        ("test", splits.test),
    )
    seen_ids: set[str] = set()
    split_of_fingerprint: dict[str, str] = {}
    labels_of_fingerprint: dict[str, tuple[str, ...]] = {}
    seen_fingerprints: set[str] = set()
    split_of_group: dict[str, str] = {}
    for split_name, records in named:
        for record in records:
            if not isinstance(record, RawDatasetRecord):
                raise DatasetPreparationError(
                    DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
                    "a split contains a malformed record",
                )
            try:
                RawDatasetRecord.model_validate(record.model_dump())
                malformed = False
            except ValidationError:
                malformed = True
            if malformed:
                raise DatasetPreparationError(
                    DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
                    "a split contains a malformed record",
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
            owner = split_of_group.setdefault(record.group_key, split_name)
            if owner != split_name:
                raise DatasetPreparationError(
                    DatasetRejectionCode.GROUP_CROSS_SPLIT,
                    "leakage detected: one group appears in more than one split",
                )

            if record.record_id in seen_ids:
                raise DatasetPreparationError(
                    DatasetRejectionCode.RECORD_STRUCTURE_INVALID,
                    "record identifiers must be unique across all splits",
                )
            seen_ids.add(record.record_id)
            fingerprint_owner = split_of_fingerprint.setdefault(
                record.content_fingerprint, split_name
            )
            if fingerprint_owner != split_name:
                raise DatasetPreparationError(
                    DatasetRejectionCode.CONTENT_CROSS_SPLIT,
                    "leakage detected: identical content appears in more than "
                    "one split",
                )
            known_labels = labels_of_fingerprint.setdefault(
                record.content_fingerprint, record.labels
            )
            if known_labels != record.labels:
                raise DatasetPreparationError(
                    DatasetRejectionCode.DUPLICATE_CONTENT_LABEL_CONFLICT,
                    "identical content carries conflicting labels",
                )
            # Cross-split and conflicting-label cases are reported above with
            # their own codes; what remains is identical content (with
            # identical labels) repeated inside a single split.
            if record.content_fingerprint in seen_fingerprints:
                raise DatasetPreparationError(
                    DatasetRejectionCode.DUPLICATE_CONTENT_IN_SPLIT,
                    "identical normalized content appears more than once; "
                    "deduplicate before building a manifest",
                )
            seen_fingerprints.add(record.content_fingerprint)


def _length_prefixed(value: str) -> bytes:
    raw = value.encode("utf-8")
    return len(raw).to_bytes(8, "big") + raw


def _encode_record(record: RawDatasetRecord) -> bytes:
    """Unambiguous encoding of the full effective record.

    Every variable-length field is length-prefixed and the label list is
    count-prefixed, so no two distinct records share an encoding.
    """
    return b"".join(
        (
            _length_prefixed(record.record_id),
            _length_prefixed(record.group_key),
            _length_prefixed(record.content_fingerprint),
            len(record.labels).to_bytes(8, "big"),
            *(_length_prefixed(label) for label in record.labels),
            b"\x01" if record.privacy_safe else b"\x00",
        )
    )


def records_fingerprint(records: tuple[RawDatasetRecord, ...]) -> str:
    """Deterministic fingerprint of the full effective record set.

    Domain-separated by ``FINGERPRINT_SCHEME_VERSION`` and independent of
    input order. It binds each record's ID, group key, content fingerprint,
    labels and privacy-safety status, so changing any of them changes the
    result. It exposes none of them: only the digest is returned.
    """
    digest = hashlib.sha256()
    digest.update(_length_prefixed(FINGERPRINT_SCHEME_VERSION))
    ordered = sorted(records, key=lambda item: item.record_id)
    digest.update(len(ordered).to_bytes(8, "big"))
    for record in ordered:
        encoded = _encode_record(record)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


__all__ = [
    "DatasetPreparationError",
    "FINGERPRINT_SCHEME_VERSION",
    "NORMALIZATION_TRANSFORMATION_VERSION",
    "PreparedSplits",
    "SPLIT_STRATEGY",
    "assign_group_safe_splits",
    "build_manifest",
    "content_fingerprint",
    "exact_deduplicate",
    "fit_transformation_on_train_only",
    "normalize_content",
    "records_fingerprint",
    "require_authorized_source",
    "validate_records",
]
