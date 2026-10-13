"""Stage 8 dataset governance and preparation (Task 207).

Offline, deterministic preparation of governed datasets: source
authorization checks, versioned normalization and validation,
exact and near-duplicate quarantine, leakage-safe group-hash
splits, and independent split-integrity verification. No model,
tokenizer, training, network, download, persistence, clock reads,
or global state lives here.
"""

from rop.dataset_preparation.pipeline import (
    DEDUP_POLICY_VERSION,
    NEAR_DUPLICATE_JACCARD_THRESHOLD,
    NORMALIZATION_RULES,
    SPLIT_POLICY_NAME,
    TRANSFORM_VERSION,
    DatasetPreparationError,
    RejectionCode,
    canonical_json_bytes,
    check_authorization,
    deduplicate_records,
    normalize_content,
    partition_records,
    prepare_dataset,
    record_content_hash,
    split_records,
    validate_record,
    verify_split,
)

__all__ = [
    "DEDUP_POLICY_VERSION",
    "NEAR_DUPLICATE_JACCARD_THRESHOLD",
    "NORMALIZATION_RULES",
    "SPLIT_POLICY_NAME",
    "TRANSFORM_VERSION",
    "DatasetPreparationError",
    "RejectionCode",
    "canonical_json_bytes",
    "check_authorization",
    "deduplicate_records",
    "normalize_content",
    "partition_records",
    "prepare_dataset",
    "record_content_hash",
    "split_records",
    "validate_record",
    "verify_split",
]
