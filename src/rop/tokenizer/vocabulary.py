"""Task 208: deterministic training-partition vocabulary construction.

Builds versioned vocabularies exclusively from the Task 207
training partition, reached only through
``partition_records(result, "train")``. Validation and test text
can never influence membership, frequencies, ordering, or size:
the builder has no parameter, path, or record list that selects
any other partition, and no code path reads outside the
validated ``PreparationResult``.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rop.dataset_preparation.pipeline import partition_records
from rop.schemas.dataset_manifest import PreparationResult
from rop.schemas.tokenizer import (
    PAD_ID,
    RESERVED_TOKENS,
    TOKENIZER_VERSION,
    UNK_ID,
    VOCABULARY_VERSION,
    TokenizerConfig,
    Vocabulary,
    VocabularyMetadata,
)
from rop.tokenizer.tokenizer import TokenizerError, tokenize_text

VOCABULARY_POLICY_VERSION = "1.0"
"""Vocabulary construction policy version (Task 208).

Any change to ordering, limits, or eligibility rules requires a
policy version change.
"""

__all__ = [
    "VOCABULARY_POLICY_VERSION",
    "VocabularyPolicy",
    "build_vocabulary",
    "encode_text",
    "verify_vocabulary",
]


@dataclass(frozen=True)
class VocabularyPolicy:
    """Explicit vocabulary limits (Task 208).

    ``max_vocab_size`` bounds total entries including reserved
    tokens (``None`` means unbounded); ``min_frequency`` drops
    tokens seen fewer times. Both are validated; booleans and
    strings are rejected rather than coerced.
    """

    max_vocab_size: int | None = None
    min_frequency: int = 1

    def __post_init__(self) -> None:
        if self.max_vocab_size is not None:
            if isinstance(self.max_vocab_size, bool) or not isinstance(
                self.max_vocab_size, int
            ):
                raise ValueError("max_vocab_size is invalid")
            if self.max_vocab_size < len(RESERVED_TOKENS):
                raise ValueError("max_vocab_size is invalid")
        if isinstance(self.min_frequency, bool) or not isinstance(
            self.min_frequency, int
        ):
            raise ValueError("min_frequency is invalid")
        if self.min_frequency < 1:
            raise ValueError("min_frequency is invalid")


def _canonical_config_dict(config: TokenizerConfig) -> dict[str, Any]:
    """Canonical tokenizer configuration representation (v1.0)."""
    return {
        "tokenizer_version": config.tokenizer_version,
        "normalization": config.normalization,
        "preserve_case": config.preserve_case,
        "max_sequence_length": config.max_sequence_length,
        "reserved_tokens": list(RESERVED_TOKENS),
    }


def _canonical_vocab_dict(tokens: tuple[str, ...]) -> dict[str, Any]:
    """Canonical vocabulary representation (v1.0): version plus ordered tokens."""
    return {"vocabulary_version": VOCABULARY_VERSION, "tokens": list(tokens)}


def _canonical_metadata_dict(metadata: VocabularyMetadata) -> dict[str, Any]:
    """Canonical metadata representation (v1.0) for integrity hashing.

    Covers all security- and audit-relevant metadata fields except
    the metadata_integrity_hash itself. Field order is fixed by
    sorted-key JSON serialization.
    """
    return {
        "vocabulary_version": metadata.vocabulary_version,
        "tokenizer_version": metadata.tokenizer_version,
        "policy_version": metadata.policy_version,
        "tokenizer_config_hash": metadata.tokenizer_config_hash,
        "reserved_tokens": list(metadata.reserved_tokens),
        "vocabulary_size": metadata.vocabulary_size,
        "max_vocab_size": metadata.max_vocab_size,
        "min_frequency": metadata.min_frequency,
        "vocabulary_hash": metadata.vocabulary_hash,
        "dataset_id": metadata.dataset_id,
        "dataset_integrity_hash": metadata.dataset_integrity_hash,
        "split_assignment_hash": metadata.split_assignment_hash,
        "data_scope": metadata.data_scope,
    }


def _canonical_hash(canonical: dict[str, Any]) -> str:
    """SHA-256 over sorted-key compact JSON (Task 104 scheme)."""
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _checked_config(config: TokenizerConfig | Mapping[str, Any]) -> TokenizerConfig:
    """Validate a tokenizer configuration mapping eagerly and strictly."""
    if isinstance(config, TokenizerConfig):
        return config
    if not isinstance(config, Mapping):
        raise TokenizerError("INVALID_CONFIG", "tokenizer configuration is invalid")
    try:
        return TokenizerConfig.model_validate(dict(config))
    except Exception as exc:
        raise TokenizerError(
            "INVALID_CONFIG", "tokenizer configuration is invalid"
        ) from exc


def _checked_policy(
    policy: VocabularyPolicy | Mapping[str, Any] | None
) -> VocabularyPolicy:
    """Validate a vocabulary policy mapping eagerly and strictly."""
    if policy is None:
        return VocabularyPolicy()
    if isinstance(policy, VocabularyPolicy):
        return policy
    if not isinstance(policy, Mapping):
        raise TokenizerError("INVALID_CONFIG", "vocabulary policy is invalid")
    try:
        return VocabularyPolicy(**dict(policy))
    except (TypeError, ValueError) as exc:
        raise TokenizerError("INVALID_CONFIG", "vocabulary policy is invalid") from exc


def build_vocabulary(
    result: PreparationResult,
    *,
    tokenizer_config: TokenizerConfig | Mapping[str, Any],
    policy: VocabularyPolicy | Mapping[str, Any] | None = None,
) -> Vocabulary:
    """Fit a vocabulary on the training partition only (Task 208).

    Accepts the validated ``PreparationResult`` and reads training
    records exclusively via ``partition_records(result, "train")``.
    There is no parameter selecting another partition, path, or
    record list. Reserved spellings can never enter as ordinary
    entries; unseen tokens map to the unknown ID at encode time.
    An empty training partition yields a reserved-only vocabulary.
    """
    if not isinstance(result, PreparationResult):
        raise TokenizerError("INVALID_INPUT", "preparation result is invalid")
    manifest = result.dataset_manifest
    if manifest.authorization_kind != "synthetic-test-only":
        raise TokenizerError("UNSUPPORTED_SCOPE", "dataset scope is not supported")
    config = _checked_config(tokenizer_config)
    settings = _checked_policy(policy)
    training = partition_records(result, "train")
    counts: Counter[str] = Counter()
    for record in training:
        for token in tokenize_text(record.content_text):
            if token not in RESERVED_TOKENS:
                counts[token] += 1
    eligible = sorted(
        (token for token, count in counts.items() if count >= settings.min_frequency),
        key=lambda token: (-counts[token], token),
    )
    if settings.max_vocab_size is not None:
        eligible = eligible[: max(0, settings.max_vocab_size - len(RESERVED_TOKENS))]
    tokens = tuple(RESERVED_TOKENS) + tuple(eligible)
    vocabulary_hash = _canonical_hash(_canonical_vocab_dict(tokens))
    tokenizer_config_hash = _canonical_hash(_canonical_config_dict(config))
    metadata_dict_for_hash = {
        "vocabulary_version": VOCABULARY_VERSION,
        "tokenizer_version": TOKENIZER_VERSION,
        "policy_version": VOCABULARY_POLICY_VERSION,
        "tokenizer_config_hash": tokenizer_config_hash,
        "reserved_tokens": list(RESERVED_TOKENS),
        "vocabulary_size": len(tokens),
        "max_vocab_size": settings.max_vocab_size,
        "min_frequency": settings.min_frequency,
        "vocabulary_hash": vocabulary_hash,
        "dataset_id": manifest.dataset_id,
        "dataset_integrity_hash": manifest.record_integrity_hash,
        "split_assignment_hash": result.split_manifest.assignment_hash,
        "data_scope": "synthetic-test-only",
    }
    metadata_integrity_hash = _canonical_hash(metadata_dict_for_hash)
    metadata = VocabularyMetadata(
        vocabulary_version=VOCABULARY_VERSION,
        tokenizer_version=TOKENIZER_VERSION,
        policy_version=VOCABULARY_POLICY_VERSION,
        tokenizer_config_hash=tokenizer_config_hash,
        reserved_tokens=tuple(RESERVED_TOKENS),
        vocabulary_size=len(tokens),
        max_vocab_size=settings.max_vocab_size,
        min_frequency=settings.min_frequency,
        vocabulary_hash=vocabulary_hash,
        dataset_id=manifest.dataset_id,
        dataset_integrity_hash=manifest.record_integrity_hash,
        split_assignment_hash=result.split_manifest.assignment_hash,
        data_scope="synthetic-test-only",
        metadata_integrity_hash=metadata_integrity_hash,
    )
    return Vocabulary(metadata=metadata, tokens=tokens)


def verify_vocabulary(
    vocabulary: Vocabulary,
    *,
    tokenizer_config: TokenizerConfig | Mapping[str, Any] | None = None,
) -> None:
    """Independently verify a vocabulary object (Task 208).

    Always recomputes the vocabulary hash from the tokens and the
    metadata integrity hash from the metadata fields; never trusts
    caller-supplied hashes. With a tokenizer configuration supplied,
    additionally verifies the recorded configuration hash. Raises a
    typed error for any mismatch; returns ``None`` when valid.
    """
    if not isinstance(vocabulary, Vocabulary):
        raise TokenizerError("INCOMPATIBLE_VOCABULARY", "vocabulary is invalid")
    if (
        _canonical_hash(_canonical_vocab_dict(vocabulary.tokens))
        != vocabulary.metadata.vocabulary_hash
    ):
        raise TokenizerError("HASH_MISMATCH", "vocabulary hash does not match")
    expected_metadata_hash = _canonical_hash(
        _canonical_metadata_dict(vocabulary.metadata)
    )
    if expected_metadata_hash != vocabulary.metadata.metadata_integrity_hash:
        raise TokenizerError("HASH_MISMATCH", "metadata integrity hash does not match")
    if tokenizer_config is not None:
        config = _checked_config(tokenizer_config)
        if (
            _canonical_hash(_canonical_config_dict(config))
            != vocabulary.metadata.tokenizer_config_hash
        ):
            raise TokenizerError(
                "HASH_MISMATCH", "tokenizer configuration hash does not match"
            )


def encode_text(
    text: str,
    *,
    vocabulary: Vocabulary,
    tokenizer_config: TokenizerConfig | Mapping[str, Any],
) -> tuple[int, ...]:
    """Encode validated text to token IDs with head truncation.

    Tokens absent from the vocabulary map to the unknown ID;
    reserved IDs arise only from reserved entries and unknown
    mapping, never from literal spelling. Output length never
    exceeds the configured maximum; overlong inputs keep their
    first tokens deterministically.
    """
    if not isinstance(vocabulary, Vocabulary):
        raise TokenizerError("INCOMPATIBLE_VOCABULARY", "vocabulary is invalid")
    config = _checked_config(tokenizer_config)
    verify_vocabulary(vocabulary, tokenizer_config=config)
    table = {token: index for index, token in enumerate(vocabulary.tokens)}
    if (
        table.get(RESERVED_TOKENS[PAD_ID]) != PAD_ID
        or table.get(RESERVED_TOKENS[UNK_ID]) != UNK_ID
    ):
        raise TokenizerError("INCOMPATIBLE_VOCABULARY", "vocabulary is invalid")
    tokens = tokenize_text(text)[: config.max_sequence_length]
    return tuple(table.get(token, UNK_ID) for token in tokens)
