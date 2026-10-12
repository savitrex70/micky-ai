"""Task 208 project-controlled tokenizer and vocabulary builder.

A small, fully documented, deterministic tokenizer for the bounded
Task 206 candidate task. The vocabulary is fit only against the records
of the authorized training split declared by a valid Task 207 dataset
manifest; validation and test data are refused for vocabulary fitting.
No pretrained tokenizer, vocabulary, merges, embeddings or model
artifacts are used or downloaded. Diagnostics never contain raw text.
No network, training, or persistence beyond local artifact files.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from rop.dataset_preparation import (
    PreparedSplits,
    content_fingerprint,
    records_fingerprint,
)
from rop.schemas.dataset_manifest import (
    AuthorizationStatus,
    DatasetManifest,
    PermittedPurpose,
)

TOKENIZER_CONTRACT_VERSION = "1"
RESERVED_PAD = "<PAD>"
RESERVED_UNK = "<UNK>"
# Reserved identifiers live only in the vocabulary, never in tokenized
# text: token boundaries strip punctuation, so "<PAD>" in raw text can
# never collide with the reserved token.
RESERVED_TOKENS: tuple[str, ...] = (RESERVED_PAD, RESERVED_UNK)
RESERVED_UNK_ID = 1
MAX_VOCAB_SIZE = 100000
MAX_TOKEN_LENGTH = 128
MAX_SEQUENCE_LENGTH = 4096


class TokenizerErrorCode(StrEnum):
    """Stable, privacy-safe error codes; no raw text in any message."""

    CONFIG_INVALID = "CONFIG_INVALID"
    EMPTY_TRAINING_INPUT = "EMPTY_TRAINING_INPUT"
    UNAUTHORIZED_SOURCE = "UNAUTHORIZED_SOURCE"
    VOCABULARY_INPUT_OUTSIDE_TRAIN_SPLIT = "VOCABULARY_INPUT_OUTSIDE_TRAIN_SPLIT"
    MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
    TEXT_FINGERPRINT_MISMATCH = "TEXT_FINGERPRINT_MISMATCH"
    CORRUPT_VOCABULARY = "CORRUPT_VOCABULARY"
    INVALID_TEXT = "INVALID_TEXT"


class TokenizerError(Exception):
    """Typed tokenizer failure carrying a canonical code only."""

    def __init__(self, code: TokenizerErrorCode, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code.value}] {detail}")


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TokenizerConfig(BaseModel):
    """Versioned, immutable tokenizer configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    unicode_normalization: Literal["NFKC"] = "NFKC"
    casefold: StrictBool = True
    max_token_length: StrictInt = Field(ge=1, le=MAX_TOKEN_LENGTH)
    max_sequence_length: StrictInt = Field(ge=1, le=MAX_SEQUENCE_LENGTH)
    max_vocab_size: StrictInt = Field(ge=len(RESERVED_TOKENS), le=MAX_VOCAB_SIZE)
    min_frequency: StrictInt = Field(ge=1)

    def config_hash(self) -> str:
        """Deterministic hash over the canonical configuration payload."""
        return _sha256_hex(_canonical_json(self.model_dump(mode="json")))


class Vocabulary(BaseModel):
    """Immutable vocabulary bound to its configuration and train split."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    config: TokenizerConfig
    config_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    tokens: tuple[StrictStr, ...] = Field(min_length=len(RESERVED_TOKENS))
    training_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    training_record_count: StrictInt = Field(ge=1)
    vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("tokens")
    @classmethod
    def _reserved_integrity_and_order(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value[: len(RESERVED_TOKENS)] != RESERVED_TOKENS:
            raise ValueError("reserved tokens must lead the vocabulary")
        if len(set(value)) != len(value):
            raise ValueError("vocabulary tokens must be unique")
        if any(not token or len(token) > MAX_TOKEN_LENGTH for token in value):
            raise ValueError("vocabulary tokens must be nonblank and bounded")
        remainder = value[len(RESERVED_TOKENS) :]
        if set(remainder) & set(RESERVED_TOKENS):
            raise ValueError("reserved tokens must not repeat in the vocabulary")
        if remainder != tuple(sorted(remainder)):
            raise ValueError("vocabulary tokens must be canonically ordered")
        return value

    @model_validator(mode="after")
    def _hashes_are_coherent(self) -> Vocabulary:
        if self.config_hash != self.config.config_hash():
            raise ValueError("config_hash must match the stored configuration")
        expected = _sha256_hex(
            _canonical_json(
                {
                    "config_hash": self.config_hash,
                    "tokens": list(self.tokens),
                    "training_fingerprint": self.training_fingerprint,
                }
            )
        )
        if self.vocabulary_hash != expected:
            raise ValueError("vocabulary_hash does not match its contents")
        return self

    def token_to_id(self, token: str) -> int | None:
        """Canonical identifier for a token, or None when out of vocabulary."""
        try:
            return self.tokens.index(token)
        except ValueError:
            return None


def tokenize_text(text: str, config: TokenizerConfig) -> tuple[str, ...]:
    """Deterministic tokenization: NFKC, casefold, alnum boundaries.

    Every token is truncated to ``config.max_token_length``; whitespace
    and punctuation are dropped as boundaries. Empty or whitespace-only
    text yields an empty tuple. Raw text never appears in errors.
    """
    if not isinstance(text, str):
        raise TokenizerError(
            TokenizerErrorCode.INVALID_TEXT,
            "text must be a string",
        )
    normalized = unicodedata.normalize(config.unicode_normalization, text)
    if config.casefold:
        normalized = normalized.casefold()
    tokens: list[str] = []
    current: list[str] = []
    for character in normalized:
        if character.isalnum():
            current.append(character)
        elif current:
            tokens.append("".join(current)[: config.max_token_length])
            current = []
    if current:
        tokens.append("".join(current)[: config.max_token_length])
    return tuple(tokens)


def build_vocabulary(
    *,
    splits: PreparedSplits,
    manifest: DatasetManifest,
    config: TokenizerConfig,
    training_texts: dict[str, str],
) -> Vocabulary:
    """Fit a vocabulary on the authorized training split only.

    ``training_texts`` maps training record identifiers to raw text; the
    identifier set must equal the train split exactly, so validation or
    test records can never influence the vocabulary. The manifest must
    authorize training and its recorded train fingerprint must match
    the supplied splits.

    Each supplied text is also bound to its record: the Task 207 canonical
    normalized-content fingerprint of the text must equal the record's
    declared ``content_fingerprint``. A text that differs in canonical
    content (case, spacing and Unicode compatibility forms are normalized
    away) is rejected before any token is counted, so the vocabulary can
    only be fit on the exact authorized content. Errors carry codes only,
    never raw text or record identifiers.
    """
    if (
        manifest.source.authorization is not AuthorizationStatus.AUTHORIZED
        or PermittedPurpose.TRAINING not in manifest.source.permitted_purposes
        or manifest.training_blocked_reason is not None
    ):
        raise TokenizerError(
            TokenizerErrorCode.UNAUTHORIZED_SOURCE,
            "the dataset manifest does not authorize training",
        )

    train_ids = {record.record_id for record in splits.train}
    if not train_ids:
        raise TokenizerError(
            TokenizerErrorCode.EMPTY_TRAINING_INPUT,
            "the training split contains no records",
        )
    supplied_ids = set(training_texts)
    if supplied_ids != train_ids:
        raise TokenizerError(
            TokenizerErrorCode.VOCABULARY_INPUT_OUTSIDE_TRAIN_SPLIT,
            "training texts must cover exactly the training split records",
        )

    expected_fingerprint = records_fingerprint(splits.train)
    recorded = dict(manifest.split_fingerprints).get("train")
    if recorded != expected_fingerprint:
        raise TokenizerError(
            TokenizerErrorCode.MANIFEST_MISMATCH,
            "the supplied training split does not match the manifest",
        )

    # Bind every text to its authorized record before any token is counted.
    fingerprint_by_id = {
        record.record_id: record.content_fingerprint for record in splits.train
    }
    for record_id in sorted(training_texts):
        text = training_texts[record_id]
        if not isinstance(text, str):
            raise TokenizerError(
                TokenizerErrorCode.INVALID_TEXT,
                "text must be a string",
            )
        if content_fingerprint(text) != fingerprint_by_id[record_id]:
            raise TokenizerError(
                TokenizerErrorCode.TEXT_FINGERPRINT_MISMATCH,
                "a training text does not match its authorized record",
            )

    counter: Counter[str] = Counter()
    for record_id in sorted(training_texts):
        counter.update(tokenize_text(training_texts[record_id], config))

    candidates = [
        (token, count)
        for token, count in counter.items()
        if count >= config.min_frequency
    ]
    # Deterministic ordering: frequency descending, token ascending as
    # the tie-break; the cap keeps the reserved prefix intact.
    candidates.sort(key=lambda pair: (-pair[1], pair[0]))
    kept = [
        token for token, _ in candidates[: config.max_vocab_size - len(RESERVED_TOKENS)]
    ]
    tokens = RESERVED_TOKENS + tuple(sorted(kept))

    payload = {
        "contract_version": TOKENIZER_CONTRACT_VERSION,
        "config": config.model_dump(mode="json"),
        "config_hash": config.config_hash(),
        "tokens": list(tokens),
        "training_fingerprint": expected_fingerprint,
        "training_record_count": len(splits.train),
        "vocabulary_hash": "",
    }
    provisional = _sha256_hex(
        _canonical_json(
            {
                "config_hash": payload["config_hash"],
                "tokens": payload["tokens"],
                "training_fingerprint": payload["training_fingerprint"],
            }
        )
    )
    payload["vocabulary_hash"] = provisional
    # Round-trip through the strict contract so a malformed build can
    # never be published.
    return Vocabulary.model_validate(payload)


def serialize_vocabulary(vocabulary: Vocabulary) -> str:
    """Canonical JSON serialization; stable across runs and platforms."""
    return _canonical_json(vocabulary.model_dump(mode="json"))


def parse_vocabulary(payload: str) -> Vocabulary:
    """Parse a serialized vocabulary; corrupt input fails closed."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # `from None` keeps raw artifact text out of any traceback chain.
        raise TokenizerError(
            TokenizerErrorCode.CORRUPT_VOCABULARY,
            "the artifact is not valid JSON",
        ) from None
    try:
        return Vocabulary.model_validate(data)
    except ValidationError:
        raise TokenizerError(
            TokenizerErrorCode.CORRUPT_VOCABULARY,
            "the artifact does not satisfy the vocabulary contract",
        ) from None


def save_vocabulary(vocabulary: Vocabulary, directory: Path) -> Path:
    """Write the artifact to a caller-chosen local directory.

    Artifacts are data-derived and must live outside source control;
    tests use temporary directories. The filename carries the
    vocabulary hash so a mismatched copy is detectable on sight.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"vocabulary-{vocabulary.vocabulary_hash[:16]}.json"
    path.write_text(serialize_vocabulary(vocabulary), encoding="utf-8")
    return path


def load_vocabulary(path: Path) -> Vocabulary:
    """Load and validate one vocabulary artifact from local storage."""
    try:
        payload = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise TokenizerError(
            TokenizerErrorCode.CORRUPT_VOCABULARY,
            "the artifact could not be read as UTF-8 text",
        ) from None
    return parse_vocabulary(payload)


def encode_text(text: str, vocabulary: Vocabulary) -> tuple[int, ...]:
    """Encode text to bounded token identifiers.

    Unknown tokens map to the reserved ``<UNK>`` identifier; sequences
    longer than the configured limit are deterministically truncated.
    """
    if not isinstance(text, str):
        raise TokenizerError(
            TokenizerErrorCode.INVALID_TEXT,
            "text must be a string",
        )
    mapping = {token: index for index, token in enumerate(vocabulary.tokens)}
    tokens = tokenize_text(text, vocabulary.config)
    identifiers = [
        mapping.get(token, RESERVED_UNK_ID)
        for token in tokens[: vocabulary.config.max_sequence_length]
    ]
    return tuple(identifiers)


__all__ = [
    "RESERVED_PAD",
    "RESERVED_TOKENS",
    "RESERVED_UNK",
    "RESERVED_UNK_ID",
    "TOKENIZER_CONTRACT_VERSION",
    "TokenizerConfig",
    "TokenizerError",
    "TokenizerErrorCode",
    "Vocabulary",
    "build_vocabulary",
    "encode_text",
    "load_vocabulary",
    "parse_vocabulary",
    "save_vocabulary",
    "serialize_vocabulary",
    "tokenize_text",
]
