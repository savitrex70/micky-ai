"""Task 207: offline dataset-governance preparation pipeline.

Pure, deterministic, offline preparation of governed datasets:
authorization checks against an explicitly injected registry,
versioned normalization and validation with safe rejection
accounting, exact and near-duplicate quarantine before
partitioning, leakage-safe group-hash splits, and independent
split-integrity verification.

Trust model: records and manifests are untrusted caller input for
shape; trust comes only from membership in the explicitly
injected authorization registry, which the application must
compose from reviewed configuration. There is no
``authorized: true`` field anywhere -- supplying one is rejected
as an unknown field and changes nothing. Synthetic test sources
(use the ``synthetic-test-`` namespace) are refused by the
production path unless the caller explicitly opts into test mode.
Approval-reference authenticity cannot be verified in-process and
is documented as depending on registry composition.

No model, tokenizer, training, network, download, persistence,
clock reads, or global state lives here. Diagnostics carry
record identifiers and reason codes only -- never content,
credentials, paths, or secrets.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from rop.schemas.dataset_authorization import (
    TEST_SOURCE_PREFIX,
    DataSourceAuthorization,
)
from rop.schemas.dataset_manifest import (
    DEDUP_POLICY_VERSION,
    MAX_CONTENT_LENGTH,
    SPLIT_POLICY_NAME,
    TRANSFORM_VERSION,
    DatasetManifest,
    DatasetRecord,
    GroupAssignment,
    LabelCount,
    PartitionRecords,
    PreparationResult,
    RejectionCount,
    RejectionDiagnostic,
    SplitConfig,
    SplitManifest,
)

NORMALIZATION_RULES = "unicode-NFC-strip-collapse-whitespace-v1"
"""Versioned normalization policy: NFC, strip, collapse whitespace runs."""

NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.8
"""Word-bigram Jaccard threshold for near-duplicate grouping (policy v1.0).

Bag-of-words similarity only: insensitive to word order and
negation, unstable on very short texts. It does not establish
semantic equivalence. Documented limitation, tested boundaries.
"""

RejectionCode = Literal[
    "UNKNOWN_SOURCE",
    "AUTHORIZATION_INVALID",
    "AUTHORIZATION_NOT_APPROVED",
    "AUTHORIZATION_EXPIRED",
    "PURPOSE_MISMATCH",
    "OPERATION_NOT_PERMITTED",
    "AUTHORIZATION_RESTRICTED",
    "TEST_SOURCE_NOT_PERMITTED",
    "MALFORMED_RECORD",
    "DUPLICATE_RECORD_ID",
    "MISSING_GROUP",
    "MISSING_PROVENANCE",
    "UNSUPPORTED_LABEL",
    "PROHIBITED_CONTENT",
    "EMPTY_CONTENT",
    "OVERSIZED_CONTENT",
    "CORRUPT_UNICODE",
    "DIGEST_MISMATCH",
    "EXACT_DUPLICATE",
    "NEAR_DUPLICATE",
    "LABEL_CONFLICT",
    "INSUFFICIENT_GROUPS",
    "INVALID_CONFIG",
    "INVALID_SPLIT_CONFIG",
    "SPLIT_INTEGRITY_FAILURE",
]

_CREDENTIAL_PATTERNS = (
    r"api[_-]?key\s*[:=]\s*\S+",
    r"api[_-]?secret\s*[:=]\s*\S+",
    r"access[_-]?token\s*[:=]\s*\S+",
    r"password\s*[:=]\s*\S+",
    r"passwd\s*[:=]\s*\S+",
    r"secret\s*[:=]\s*\S+",
    r"token\s*[:=]\s*\S+",
    r"private[_-]?key\s*[:=]\s*\S+",
)
_PATH_PATTERNS = (
    r"/etc/",
    r"/root/",
    r"/home/",
    r"/var/",
    r"C:\\",
    r"C:/",
)
_PROHIBITED_RES = tuple(
    re.compile(p, re.IGNORECASE) for p in _CREDENTIAL_PATTERNS
) + tuple(re.compile(p) for p in _PATH_PATTERNS)


class DatasetPreparationError(Exception):
    """A typed dataset-preparation failure carrying a safe reason code.

    Messages are generic and contain no record content,
    credentials, paths, secrets, or sensitive identifiers.
    """

    def __init__(self, code: RejectionCode, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


def canonical_json_bytes(value: Any) -> bytes:
    """Canonical bytes: sorted keys, compact separators (Task 104 scheme)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def normalize_content(text: str) -> str:
    """Apply the versioned normalization policy to record content.

    Unicode NFC, strip leading/trailing whitespace, collapse every
    internal whitespace run to a single space. Case is preserved:
    folding case could silently merge distinct meanings.
    """
    if not isinstance(text, str):
        raise DatasetPreparationError("MALFORMED_RECORD", "record content is invalid")
    try:
        normalized = unicodedata.normalize("NFC", text)
    except (UnicodeError, ValueError):
        raise DatasetPreparationError(
            "CORRUPT_UNICODE", "record content is invalid"
        ) from None
    collapsed = re.sub(r"\s+", " ", normalized).strip()
    try:
        collapsed.encode("utf-8")
    except UnicodeEncodeError:
        raise DatasetPreparationError(
            "CORRUPT_UNICODE", "record content is invalid"
        ) from None
    return collapsed


def record_content_hash(content: str) -> str:
    """SHA-256 hex digest of the exact UTF-8 bytes (Task 203 semantics)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _has_prohibited_content(content: str) -> bool:
    """Detect credential assignments and absolute paths in content."""
    return any(pattern.search(content) is not None for pattern in _PROHIBITED_RES)


def check_authorization(
    entry: DataSourceAuthorization,
    *,
    purpose: str,
    operation: str,
    as_of: str,
    allow_test_sources: bool = False,
) -> None:
    """Verify one registry authorization for one requested use.

    Raises ``DatasetPreparationError`` with a specific safe code
    for unknown, non-approved, expired, mismatched, restricted, or
    test-only authorization. ``as_of`` is an explicit ``YYYY-MM-DD``
    reference date; no clock is read.
    """
    if entry.source_id.startswith(TEST_SOURCE_PREFIX) and not allow_test_sources:
        raise DatasetPreparationError(
            "TEST_SOURCE_NOT_PERMITTED", "test authorization is not permitted here"
        )
    if entry.status != "APPROVED":
        raise DatasetPreparationError(
            "AUTHORIZATION_NOT_APPROVED", "source authorization is not approved"
        )
    if entry.valid_until is not None and as_of > entry.valid_until:
        raise DatasetPreparationError(
            "AUTHORIZATION_EXPIRED", "source authorization has expired"
        )
    if entry.intended_purpose != purpose:
        raise DatasetPreparationError(
            "PURPOSE_MISMATCH", "source authorization purpose does not match"
        )
    if operation not in entry.permitted_operations:
        raise DatasetPreparationError(
            "OPERATION_NOT_PERMITTED", "source authorization operation not permitted"
        )
    if entry.restrictions:
        raise DatasetPreparationError(
            "AUTHORIZATION_RESTRICTED",
            "source authorization carries unevaluated restrictions",
        )


def _record_id_of(raw: Mapping[str, Any]) -> str | None:
    value = raw.get("record_id")
    return value if isinstance(value, str) and value else None


def validate_record(
    raw: Mapping[str, Any],
    *,
    allowed_labels: tuple[str, ...],
    authorizations: Mapping[str, DataSourceAuthorization],
    purpose: str,
    operation: str,
    as_of: str,
    allow_test_sources: bool = False,
) -> DatasetRecord:
    """Validate and normalize one raw input mapping into a ``DatasetRecord``.

    Order: source membership, authorization validity, presence of
    binding identifiers, normalization, content policy, label
    allow-list, digest verification, strict schema validation.
    Every failure raises ``DatasetPreparationError`` naming only a
    safe code; raw content never escapes.
    """
    if not isinstance(raw, Mapping):
        raise DatasetPreparationError("MALFORMED_RECORD", "record is invalid")
    data = dict(raw)
    source_id = data.get("source_id")
    entry = authorizations.get(source_id) if isinstance(source_id, str) else None
    if entry is None:
        raise DatasetPreparationError("UNKNOWN_SOURCE", "record source is unknown")
    if not isinstance(entry, DataSourceAuthorization):
        raise DatasetPreparationError(
            "AUTHORIZATION_INVALID", "source authorization is invalid"
        )
    check_authorization(
        entry,
        purpose=purpose,
        operation=operation,
        as_of=as_of,
        allow_test_sources=allow_test_sources,
    )
    record_id = data.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise DatasetPreparationError("MALFORMED_RECORD", "record is invalid")
    group_id = data.get("group_id")
    if not isinstance(group_id, str) or not group_id:
        raise DatasetPreparationError("MISSING_GROUP", "record group is missing")
    provenance_ref = data.get("provenance_ref")
    if not isinstance(provenance_ref, str) or not provenance_ref:
        raise DatasetPreparationError(
            "MISSING_PROVENANCE", "record provenance is missing"
        )
    try:
        normalized = normalize_content(data.get("content_text", ""))
    except DatasetPreparationError:
        raise
    if not normalized:
        raise DatasetPreparationError("EMPTY_CONTENT", "record content is empty")
    if len(normalized) > MAX_CONTENT_LENGTH:
        raise DatasetPreparationError(
            "OVERSIZED_CONTENT", "record content is too large"
        )
    if _has_prohibited_content(normalized):
        raise DatasetPreparationError(
            "PROHIBITED_CONTENT", "record content is not permitted"
        )
    label = data.get("label")
    if label not in allowed_labels:
        raise DatasetPreparationError(
            "UNSUPPORTED_LABEL", "record label is unsupported"
        )
    candidate = dict(data)
    candidate["content_text"] = normalized
    candidate.setdefault("content_hash", record_content_hash(normalized))
    if candidate["content_hash"] != record_content_hash(normalized):
        raise DatasetPreparationError("DIGEST_MISMATCH", "record digest does not match")
    try:
        return DatasetRecord.model_validate(candidate)
    except Exception as exc:
        raise DatasetPreparationError("MALFORMED_RECORD", "record is invalid") from exc


def _shingles(content: str) -> set[str]:
    """Word bigrams for near-duplicate comparison, unigrams when too short."""
    tokens = content.split(" ")
    if len(tokens) < 2:
        return set(tokens)
    # Intentionally unequal lengths: bigrams of consecutive tokens.
    return {" ".join(pair) for pair in zip(tokens, tokens[1:], strict=False)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def deduplicate_records(
    records: Sequence[DatasetRecord],
) -> tuple[tuple[DatasetRecord, ...], tuple[RejectionDiagnostic, ...]]:
    """Quarantine exact and near-duplicates before partitioning.

    Exact groups share a content hash; near groups are bigram
    Jaccard components at or above the policy threshold. A group
    whose members disagree on labels is quarantined whole with
    ``LABEL_CONFLICT`` -- no preferred label is ever selected.
    Otherwise the smallest record identifier is retained and the
    rest are quarantined as exact or near duplicates. Deterministic
    in input order: results depend only on record contents.
    """
    ordered = sorted(records, key=lambda record: record.record_id)
    rejections: list[RejectionDiagnostic] = []
    survivors: list[DatasetRecord] = []

    by_hash: dict[str, list[DatasetRecord]] = {}
    for record in ordered:
        by_hash.setdefault(record.content_hash, []).append(record)
    exact_kept: list[DatasetRecord] = []
    for group in by_hash.values():
        labels = {record.label for record in group}
        if len(labels) > 1:
            rejections.extend(
                RejectionDiagnostic(record_id=record.record_id, code="LABEL_CONFLICT")
                for record in group
            )
            continue
        exact_kept.append(group[0])
        rejections.extend(
            RejectionDiagnostic(record_id=record.record_id, code="EXACT_DUPLICATE")
            for record in group[1:]
        )

    parent: dict[str, str] = {
        record.record_id: record.record_id for record in exact_kept
    }

    def _find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def _union(left: str, right: str) -> None:
        root_left, root_right = _find(left), _find(right)
        if root_left == root_right:
            return
        if root_left < root_right:
            parent[root_right] = root_left
        else:
            parent[root_left] = root_right

    shingle_sets = {
        record.record_id: _shingles(record.content_text) for record in exact_kept
    }
    for index, left in enumerate(exact_kept):
        for right in exact_kept[index + 1 :]:
            if _jaccard(
                shingle_sets[left.record_id], shingle_sets[right.record_id]
            ) >= (NEAR_DUPLICATE_JACCARD_THRESHOLD):
                _union(left.record_id, right.record_id)

    components: dict[str, list[DatasetRecord]] = {}
    for record in exact_kept:
        components.setdefault(_find(record.record_id), []).append(record)
    for group in components.values():
        if len(group) == 1:
            survivors.append(group[0])
            continue
        labels = {record.label for record in group}
        if len(labels) > 1:
            rejections.extend(
                RejectionDiagnostic(record_id=record.record_id, code="LABEL_CONFLICT")
                for record in group
            )
            continue
        kept = min(group, key=lambda record: record.record_id)
        survivors.append(kept)
        rejections.extend(
            RejectionDiagnostic(record_id=record.record_id, code="NEAR_DUPLICATE")
            for record in group
            if record.record_id != kept.record_id
        )

    survivors.sort(key=lambda record: record.record_id)
    rejections.sort(key=lambda entry: (entry.record_id or "", entry.code))
    return tuple(survivors), tuple(rejections)


def _assignment_value(seed: int, group_id: str) -> float:
    digest = hashlib.sha256(
        f"dataset-split-assignment-v1|{seed}|{group_id}".encode()
    ).hexdigest()
    return int(digest, 16) / 2**256


def split_records(
    records: Sequence[DatasetRecord],
    config: SplitConfig,
    *,
    dataset_id: str,
    dataset_content_hash: str,
) -> SplitManifest:
    """Assign leakage groups to partitions by seeded group hash.

    Every group lands in exactly one partition; related records
    never cross boundaries. Fails closed with
    ``INSUFFICIENT_GROUPS`` when fewer groups exist than partitions
    with a nonzero ratio, instead of relaxing the grouping policy.
    """
    groups = sorted({record.group_id for record in records})
    ratios = (
        ("train", config.train_ratio),
        ("validation", config.validation_ratio),
        ("test", config.test_ratio),
    )
    nonzero = sum(1 for _, ratio in ratios if ratio > 0)
    if len(groups) < nonzero:
        raise DatasetPreparationError(
            "INSUFFICIENT_GROUPS", "split constraints cannot be satisfied"
        )
    cutoffs: list[tuple[str, float]] = []
    cumulative = 0.0
    for name, ratio in ratios:
        cumulative += ratio
        cutoffs.append((name, cumulative))
    assignments: list[GroupAssignment] = []
    for group_id in groups:
        value = _assignment_value(config.seed, group_id)
        chosen = cutoffs[-1][0]
        for name, cutoff in cutoffs:
            if value < cutoff:
                chosen = name
                break
        assignments.append(GroupAssignment(group_id=group_id, partition=chosen))  # type: ignore[arg-type]
    counts = {"train": 0, "validation": 0, "test": 0}
    group_partition = {entry.group_id: entry.partition for entry in assignments}
    for record in records:
        counts[group_partition[record.group_id]] += 1
    assignment_hash = hashlib.sha256(
        canonical_json_bytes(
            {
                "policy": SPLIT_POLICY_NAME,
                "seed": config.seed,
                "ratios": [
                    config.train_ratio,
                    config.validation_ratio,
                    config.test_ratio,
                ],
                "assignments": [
                    {"group_id": entry.group_id, "partition": entry.partition}
                    for entry in assignments
                ],
                "dataset_content_hash": dataset_content_hash,
            }
        )
    ).hexdigest()
    return SplitManifest(
        dataset_id=dataset_id,
        manifest_version="1.0",
        split_policy=SPLIT_POLICY_NAME,
        seed=config.seed,
        train_ratio=config.train_ratio,
        validation_ratio=config.validation_ratio,
        test_ratio=config.test_ratio,
        assignments=tuple(assignments),
        train_count=counts["train"],
        validation_count=counts["validation"],
        test_count=counts["test"],
        assignment_hash=assignment_hash,
        dataset_content_hash=dataset_content_hash,
    )


def verify_split(
    split: SplitManifest,
    records: Sequence[DatasetRecord],
    *,
    dataset_content_hash: str,
) -> None:
    """Independently verify every split-integrity invariant.

    Raises ``DatasetPreparationError`` with code
    ``SPLIT_INTEGRITY_FAILURE`` for any violation; the message
    carries no record content.
    """

    def _fail() -> None:
        raise DatasetPreparationError(
            "SPLIT_INTEGRITY_FAILURE", "split integrity check failed"
        )

    by_id = {record.record_id: record for record in records}
    if len(by_id) != len(records):
        _fail()
    group_partition: dict[str, str] = {}
    for entry in split.assignments:
        if entry.group_id in group_partition:
            _fail()
        group_partition[entry.group_id] = entry.partition
    record_groups = {record.group_id for record in records}
    if set(group_partition) != record_groups:
        _fail()
    counts = {"train": 0, "validation": 0, "test": 0}
    for record in records:
        partition = group_partition[record.group_id]
        counts[partition] += 1
    if (
        counts["train"] != split.train_count
        or counts["validation"] != split.validation_count
        or counts["test"] != split.test_count
    ):
        _fail()
    if split.dataset_content_hash != dataset_content_hash:
        _fail()
    recomputed = split_records(
        records,
        SplitConfig(
            seed=split.seed,
            train_ratio=split.train_ratio,
            validation_ratio=split.validation_ratio,
            test_ratio=split.test_ratio,
        ),
        dataset_id=split.dataset_id,
        dataset_content_hash=dataset_content_hash,
    )
    if recomputed.assignment_hash != split.assignment_hash or [
        (entry.group_id, entry.partition) for entry in recomputed.assignments
    ] != [(entry.group_id, entry.partition) for entry in split.assignments]:
        _fail()


def _dataset_content_hash(records: Sequence[DatasetRecord]) -> str:
    return hashlib.sha256(
        canonical_json_bytes(sorted(record.content_hash for record in records))
    ).hexdigest()


def prepare_dataset(
    *,
    records: Sequence[Mapping[str, Any]],
    authorizations: Mapping[str, Any],
    dataset_id: str,
    purpose: str,
    operation: str,
    as_of: str,
    allowed_labels: Sequence[str],
    grouping_unit: str,
    split_config: SplitConfig | Mapping[str, Any],
    allow_test_sources: bool = False,
) -> PreparationResult:
    """Run the full offline preparation pipeline deterministically.

    Validates the authorization registry shape, then per record:
    authorization, validation, and normalization. Deduplicates
    survivors, splits by leakage group, builds versioned manifests,
    and independently verifies the split before returning. Any
    unexpected condition fails closed with a safe typed error.
    """
    if not isinstance(dataset_id, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9_.-]{0,63}", dataset_id
    ):
        raise DatasetPreparationError("INVALID_CONFIG", "dataset identifier is invalid")
    if not isinstance(purpose, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9_.-]{0,63}", purpose
    ):
        raise DatasetPreparationError("INVALID_CONFIG", "purpose is invalid")
    if operation not in ("training", "validation", "evaluation"):
        raise DatasetPreparationError("INVALID_CONFIG", "operation is invalid")
    if not isinstance(as_of, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        raise DatasetPreparationError("INVALID_CONFIG", "reference date is invalid")
    try:
        datetime.date.fromisoformat(as_of)
    except ValueError:
        raise DatasetPreparationError(
            "INVALID_CONFIG", "reference date is invalid"
        ) from None
    if not isinstance(grouping_unit, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9 .,;:_()/-]{0,119}", grouping_unit
    ):
        raise DatasetPreparationError("INVALID_CONFIG", "grouping unit is invalid")
    labels = tuple(allowed_labels) if isinstance(allowed_labels, Sequence) else ()
    if isinstance(allowed_labels, str):
        raise DatasetPreparationError("INVALID_CONFIG", "allowed labels are invalid")
    if (
        not labels
        or len(labels) > 32
        or any(not isinstance(label, str) for label in labels)
        or any(
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", label)
            for label in labels
            if isinstance(label, str)
        )
        or len(set(labels)) != len(labels)
        or list(labels) != sorted(labels)
    ):
        raise DatasetPreparationError("INVALID_CONFIG", "allowed labels are invalid")
    if not isinstance(split_config, SplitConfig):
        try:
            split_config = SplitConfig.model_validate(dict(split_config))
        except Exception as exc:
            raise DatasetPreparationError(
                "INVALID_SPLIT_CONFIG", "split configuration is invalid"
            ) from exc
    if not isinstance(authorizations, Mapping):
        raise DatasetPreparationError(
            "AUTHORIZATION_INVALID", "authorization registry is invalid"
        )
    registry: dict[str, DataSourceAuthorization] = {}
    for source_id, entry in authorizations.items():
        if not isinstance(source_id, str):
            raise DatasetPreparationError(
                "AUTHORIZATION_INVALID", "authorization registry is invalid"
            )
        try:
            validated = (
                entry
                if isinstance(entry, DataSourceAuthorization)
                else DataSourceAuthorization.model_validate(dict(entry))
            )
        except Exception as exc:
            raise DatasetPreparationError(
                "AUTHORIZATION_INVALID", "source authorization is invalid"
            ) from exc
        if validated.source_id != source_id:
            raise DatasetPreparationError(
                "AUTHORIZATION_INVALID", "source authorization is invalid"
            )
        registry[source_id] = validated

    accepted: list[DatasetRecord] = []
    rejections: list[RejectionDiagnostic] = []
    seen_ids: set[str] = set()
    for raw in records:
        candidate_id = _record_id_of(raw) if isinstance(raw, Mapping) else None
        try:
            record = validate_record(
                raw,
                allowed_labels=labels,
                authorizations=registry,
                purpose=purpose,
                operation=operation,
                as_of=as_of,
                allow_test_sources=allow_test_sources,
            )
            if record.record_id in seen_ids:
                raise DatasetPreparationError(
                    "DUPLICATE_RECORD_ID", "record identifier is duplicated"
                )
            seen_ids.add(record.record_id)
            accepted.append(record)
        except DatasetPreparationError as exc:
            rejections.append(
                RejectionDiagnostic(record_id=candidate_id, code=exc.code)
            )

    kept, duplicate_rejections = deduplicate_records(accepted)
    rejections.extend(duplicate_rejections)

    content_hash = _dataset_content_hash(kept)
    try:
        split = split_records(
            kept, split_config, dataset_id=dataset_id, dataset_content_hash=content_hash
        )
    except DatasetPreparationError as exc:
        if exc.code == "INSUFFICIENT_GROUPS":
            raise
        raise DatasetPreparationError(
            "INVALID_SPLIT_CONFIG", "split configuration is invalid"
        ) from exc

    label_counts = sorted(
        {record.label for record in kept},
    )
    rejection_tally: dict[str, int] = {}
    for entry in rejections:
        rejection_tally[entry.code] = rejection_tally.get(entry.code, 0) + 1
    dataset_manifest = DatasetManifest(
        dataset_id=dataset_id,
        manifest_version="1.0",
        source_ids=tuple(sorted({record.source_id for record in kept})),
        purpose=purpose,
        operation=operation,  # type: ignore[arg-type]
        allowed_labels=labels,
        transform_version="1.0",
        dedup_policy_version="1.0",
        grouping_unit=grouping_unit,
        split_config=split_config,
        label_counts=tuple(
            LabelCount(
                label=label,
                count=sum(1 for record in kept if record.label == label),
            )
            for label in label_counts
        ),
        rejection_counts=tuple(
            RejectionCount(code=code, count=rejection_tally[code])
            for code in sorted(rejection_tally)
        ),
        record_count=len(kept),
        content_chain_hash=content_hash,
    )
    verify_split(split, kept, dataset_content_hash=content_hash)

    group_partition = {entry.group_id: entry.partition for entry in split.assignments}
    partitions: list[PartitionRecords] = []
    for partition in ("train", "validation", "test"):
        members = sorted(
            (
                record
                for record in kept
                if group_partition[record.group_id] == partition
            ),
            key=lambda record: record.record_id,
        )
        partitions.append(
            PartitionRecords(partition=partition, records=tuple(members))  # type: ignore[arg-type]
        )
    rejections.sort(key=lambda entry: (entry.record_id or "", entry.code))
    return PreparationResult(
        dataset_manifest=dataset_manifest,
        split_manifest=split,
        partitions=tuple(partitions),
        rejections=tuple(rejections),
    )


def partition_records(
    result: PreparationResult, partition: Literal["train", "validation", "test"]
) -> tuple[DatasetRecord, ...]:
    """Return only the records assigned to one partition.

    The test partition is held back by construction: callers
    training on ``partition_records(result, "train")`` never
    receive validation or test records through this accessor.
    """
    for entry in result.partitions:
        if entry.partition == partition:
            return entry.records
    raise DatasetPreparationError("INVALID_CONFIG", "partition is invalid")


__all__ = [
    "DEDUP_POLICY_VERSION",
    "NEAR_DUPLICATE_JACCARD_THRESHOLD",
    "NORMALIZATION_RULES",
    "SPLIT_POLICY_NAME",
    "TRANSFORM_VERSION",
    "DatasetPreparationError",
    "RejectionCode",
    "normalize_content",
    "canonical_json_bytes",
    "record_content_hash",
    "check_authorization",
    "validate_record",
    "deduplicate_records",
    "split_records",
    "verify_split",
    "prepare_dataset",
    "partition_records",
]
