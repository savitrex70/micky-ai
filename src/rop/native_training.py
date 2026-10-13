"""Task 210: deterministic, offline training for the first-party native model.

Training uses only the project's own model, authorized Task 207 train split,
and Task 208 vocabulary. No shuffle, network, pretrained weights, or external
numerical framework is used. Validation/test examples are never accepted here.

Binding performed at this boundary (all fail closed with stable codes and
never echo raw text):

* initial parameters must equal, element for element, the deterministic
  initialization the first-party ``NativeModel`` produces for the declared
  configuration and seed; shapes and finiteness are checked first;
* the label-to-ID mapping is canonical: the sorted declared label space, so
  ID ``i`` is always the ``i``-th label in sorted order for a given task;
* every example's ``label_ids`` must equal the canonical IDs of its record's
  declared labels, and every example's ``token_ids`` must equal the project
  tokenizer's encoding of text whose canonical fingerprint matches the
  record. Raw text is transient: it is read, hashed and encoded, never stored.

Optimization: per-example (batch size 1) SGD on the summed binary cross
entropy over labels. All gradients for one example are computed from the
pre-update parameter snapshot, and only then applied. Embedding gradients
are aggregated per distinct token (a token repeated k times in an n-token
sequence receives k/n of the pooled gradient). Gradient clipping is
element-wise on each final parameter gradient (weight, bias and aggregated
embedding component) to ``[-gradient_clip, gradient_clip]`` before the
learning rate is applied; the error signal itself is not clipped.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from rop.dataset_preparation import (
    FINGERPRINT_SCHEME_VERSION,
    PreparedSplits,
    content_fingerprint,
    records_fingerprint,
)
from rop.native_model import NativeModel, NativeModelParameters, stable_sigmoid
from rop.schemas.dataset_manifest import (
    AuthorizationStatus,
    DatasetManifest,
    PermittedPurpose,
)
from rop.schemas.native_model import NativeModelConfig
from rop.tokenization import Vocabulary, encode_text

# The training report names the canonical label-space identity it trained
# against, so a different (even equally sorted, equally sized) label set can
# never be substituted for the head's output indices at inference time.
LABEL_SPACE_SCHEME_VERSION = "native-label-space-v1"
LABEL_SPACE_HASH_DOMAIN = "rop.native.label-space.v1"
NATIVE_TRAINING_REPORT_CONTRACT_VERSION = "2"


class NativeTrainingError(Exception):
    """Canonical, privacy-safe training failure."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


class NativeTrainingConfig(BaseModel):
    """Immutable bounded optimization configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    epochs: StrictInt = Field(ge=1, le=500)
    learning_rate: StrictFloat = Field(gt=0.0, le=1.0)
    max_examples: StrictInt = Field(ge=1, le=100000)
    gradient_clip: StrictFloat = Field(gt=0.0, le=100.0)


class NativeTrainingExample(BaseModel):
    """One safe, tokenized training example; no raw text is retained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: StrictStr = Field(min_length=1, max_length=200)
    token_ids: tuple[StrictInt, ...] = Field(max_length=4096)
    label_ids: tuple[StrictInt, ...] = Field(max_length=32)

    @classmethod
    def canonical(
        cls, record_id: str, token_ids: tuple[int, ...], label_ids: tuple[int, ...]
    ) -> NativeTrainingExample:
        return cls(
            record_id=record_id,
            token_ids=token_ids,
            label_ids=tuple(sorted(set(label_ids))),
        )


@dataclass(frozen=True)
class NativeTrainingResult:
    """In-memory trained parameters plus reproducibility evidence."""

    parameters: NativeModelParameters
    report: NativeTrainingReport


class NativeTrainingReport(BaseModel):
    """Privacy-safe record of the deterministic training run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["2"] = "2"
    model_version: StrictStr = Field(min_length=1, max_length=32)
    dataset_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    # Canonical label map: ``label_map[i]`` is the label of head index ``i``.
    label_space_scheme_version: Literal["native-label-space-v1"] = (
        "native-label-space-v1"
    )
    label_map: tuple[StrictStr, ...] = Field(min_length=2, max_length=32)
    label_space_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    initialization_seed: StrictInt = Field(ge=0)
    epochs_completed: StrictInt = Field(ge=1, le=500)
    example_count: StrictInt = Field(ge=1, le=100000)
    learning_rate: StrictFloat = Field(gt=0.0, le=1.0)
    initial_binary_cross_entropy: StrictFloat = Field(ge=0.0)
    final_binary_cross_entropy: StrictFloat = Field(ge=0.0)
    parameters_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _label_space_hash_matches_label_map(self) -> NativeTrainingReport:
        # Recomputed, never trusted: the recorded hash must be the identity of
        # exactly the recorded canonical label map.
        try:
            expected = label_space_hash(self.label_map)
            valid = True
        except NativeTrainingError:
            expected = ""
            valid = False
        if not valid:
            raise ValueError("label_map must be a canonical label space")
        if self.label_space_hash != expected:
            raise ValueError("label_space_hash must match the recorded label_map")
        return self


def _length_prefixed(value: str) -> bytes:
    raw = value.encode("utf-8")
    return len(raw).to_bytes(8, "big") + raw


def _parameter_hash(parameters: NativeModelParameters) -> str:
    payload = {
        "embedding": parameters.embedding,
        "head_weight": parameters.head_weight,
        "head_bias": parameters.head_bias,
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def canonical_label_mapping(label_space: tuple[str, ...]) -> dict[str, int]:
    """Canonical label -> head index mapping for a declared label space.

    The label space must be a non-empty tuple of unique, nonblank strings;
    IDs are assigned in sorted order, so the mapping is identical across
    runs, training, inference and policy for the same task configuration.
    """
    if (
        not isinstance(label_space, tuple)
        or len(label_space) < 2
        or any(not isinstance(label, str) or not label.strip() for label in label_space)
        or len(set(label_space)) != len(label_space)
        or label_space != tuple(sorted(label_space))
    ):
        raise NativeTrainingError(
            "LABEL_SPACE_INVALID",
            "the label space must be unique, nonblank and canonically sorted",
        )
    return {label: index for index, label in enumerate(label_space)}


def label_space_hash(label_space: tuple[str, ...]) -> str:
    """Domain-separated SHA-256 identity of a canonical label space.

    The label space is validated by :func:`canonical_label_mapping` first, so
    only the sorted, unique, nonblank space that defines the head indices can
    be hashed. The encoding is length-prefixed and index-bound: a domain tag,
    the label count, then ``(index, label)`` pairs in head order. Different
    label sets of the same size therefore hash differently, and no two
    distinct label spaces share an encoding.
    """
    mapping = canonical_label_mapping(label_space)
    digest = hashlib.sha256()
    digest.update(_length_prefixed(LABEL_SPACE_HASH_DOMAIN))
    digest.update(len(mapping).to_bytes(8, "big"))
    for label, index in mapping.items():
        digest.update(index.to_bytes(8, "big"))
        digest.update(_length_prefixed(label))
    return digest.hexdigest()


def _clip(value: float, bound: float) -> float:
    return max(-bound, min(bound, value))


def _loss(
    parameters: NativeModelParameters,
    examples: tuple[NativeTrainingExample, ...],
    config: NativeModelConfig,
) -> float:
    total = 0.0
    for example in examples:
        ids = example.token_ids[: config.max_sequence_length]
        pooled = (
            [
                sum(parameters.embedding[token][axis] for token in ids) / len(ids)
                for axis in range(config.embedding_dim)
            ]
            if ids
            else [0.0] * config.embedding_dim
        )
        targets = set(example.label_ids)
        for label, weights in enumerate(parameters.head_weight):
            logit = (
                sum(
                    weight * value
                    for weight, value in zip(weights, pooled, strict=True)
                )
                + parameters.head_bias[label]
            )
            probability = min(max(stable_sigmoid(logit), 1e-12), 1.0 - 1e-12)
            target = 1.0 if label in targets else 0.0
            total -= target * math.log(probability) + (1.0 - target) * math.log(
                1.0 - probability
            )
    return total / (len(examples) * config.num_labels)


def _validate_initial_parameters(
    initial: NativeModelParameters, model_config: NativeModelConfig
) -> None:
    """Shape, finiteness, then exact first-party seeded-initialization check."""
    dimension = model_config.embedding_dim
    if (
        len(initial.embedding) != model_config.vocab_size
        or len(initial.head_weight) != model_config.num_labels
        or len(initial.head_bias) != model_config.num_labels
        or any(len(row) != dimension for row in initial.embedding)
        or any(len(row) != dimension for row in initial.head_weight)
    ):
        raise NativeTrainingError(
            "PARAMETER_SHAPE_MISMATCH",
            "initial parameter dimensions do not match the model configuration",
        )
    values = (
        [value for row in initial.embedding for value in row]
        + [value for row in initial.head_weight for value in row]
        + list(initial.head_bias)
    )
    if not all(isinstance(value, float) and math.isfinite(value) for value in values):
        raise NativeTrainingError(
            "NON_FINITE_INITIAL_PARAMETER",
            "initial parameters must be finite floating-point values",
        )
    if initial != NativeModel.reproducible(model_config):
        raise NativeTrainingError(
            "INITIALIZATION_MISMATCH",
            "initial parameters are not the deterministic first-party "
            "initialization for the declared configuration and seed",
        )


def _validate_example_bindings(
    *,
    examples: tuple[NativeTrainingExample, ...],
    splits: PreparedSplits,
    training_texts: dict[str, str],
    vocabulary: Vocabulary,
    mapping: dict[str, int],
    model_config: NativeModelConfig,
) -> None:
    """Bind every example to its record's labels, text fingerprint and tokens."""
    records = {record.record_id: record for record in splits.train}
    if len(records) != len(splits.train):
        raise NativeTrainingError(
            "TRAINING_SPLIT_MISMATCH", "the training split repeats a record"
        )
    if set(training_texts) != set(records):
        raise NativeTrainingError(
            "TRAINING_TEXT_MISMATCH",
            "training texts must cover exactly the declared training split",
        )
    for example in sorted(examples, key=lambda item: item.record_id):
        record = records[example.record_id]
        if any(label not in mapping for label in record.labels):
            raise NativeTrainingError(
                "LABEL_NOT_IN_LABEL_SPACE",
                "a record label is outside the declared label space",
            )
        if len(set(example.label_ids)) != len(example.label_ids):
            raise NativeTrainingError(
                "LABEL_MAPPING_MISMATCH", "an example repeats a label identifier"
            )
        if any(
            label < 0 or label >= model_config.num_labels for label in example.label_ids
        ):
            raise NativeTrainingError(
                "LABEL_ID_OUT_OF_RANGE",
                "a training label is outside the configured label space",
            )
        expected_labels = tuple(sorted(mapping[label] for label in record.labels))
        if tuple(example.label_ids) != expected_labels:
            raise NativeTrainingError(
                "LABEL_MAPPING_MISMATCH",
                "example label identifiers do not match the record labels",
            )
        if any(
            token < 0 or token >= model_config.vocab_size for token in example.token_ids
        ):
            raise NativeTrainingError(
                "TOKEN_ID_OUT_OF_RANGE",
                "a training token is outside the configured vocabulary",
            )
        text = training_texts[example.record_id]
        if not isinstance(text, str) or content_fingerprint(text) != (
            record.content_fingerprint
        ):
            raise NativeTrainingError(
                "TEXT_FINGERPRINT_MISMATCH",
                "a training text does not match its authorized record",
            )
        if tuple(example.token_ids) != encode_text(text, vocabulary):
            raise NativeTrainingError(
                "TOKEN_BINDING_MISMATCH",
                "example token identifiers do not match the project tokenizer",
            )


def train_native_model(
    *,
    model_config: NativeModelConfig,
    training_config: NativeTrainingConfig,
    initial_parameters: NativeModelParameters,
    examples: tuple[NativeTrainingExample, ...],
    splits: PreparedSplits,
    manifest: DatasetManifest,
    vocabulary: Vocabulary,
    label_space: tuple[str, ...],
    training_texts: dict[str, str],
) -> NativeTrainingResult:
    """Train deterministically on exactly the authorized training split.

    ``training_texts`` maps training record IDs to raw text and is used only
    to verify bindings; it is neither stored nor reported. ``label_space`` is
    the task's declared label tuple; see :func:`canonical_label_mapping`.
    """
    if (
        manifest.source.authorization is not AuthorizationStatus.AUTHORIZED
        or PermittedPurpose.TRAINING not in manifest.source.permitted_purposes
        or manifest.training_blocked_reason is not None
    ):
        raise NativeTrainingError(
            "TRAINING_NOT_AUTHORIZED",
            "the dataset manifest does not authorize training",
        )
    fingerprint = records_fingerprint(splits.train)
    if (
        manifest.fingerprint_scheme_version != FINGERPRINT_SCHEME_VERSION
        or dict(manifest.split_fingerprints).get("train") != fingerprint
        or vocabulary.training_fingerprint != fingerprint
    ):
        raise NativeTrainingError(
            "TRAINING_FINGERPRINT_MISMATCH",
            "the manifest, vocabulary, and training split are not bound",
        )
    expected_ids = tuple(sorted(record.record_id for record in splits.train))
    supplied_ids = tuple(sorted(example.record_id for example in examples))
    if not expected_ids or expected_ids != supplied_ids:
        raise NativeTrainingError(
            "TRAINING_SPLIT_MISMATCH",
            "examples must cover exactly the declared training split",
        )
    if len(examples) > training_config.max_examples:
        raise NativeTrainingError(
            "TRAINING_BOUND_EXCEEDED",
            "the training example count exceeds the configured bound",
        )
    if len(vocabulary.tokens) != model_config.vocab_size:
        raise NativeTrainingError(
            "VOCABULARY_SHAPE_MISMATCH",
            "the vocabulary size does not match the model configuration",
        )
    mapping = canonical_label_mapping(label_space)
    if len(mapping) != model_config.num_labels:
        raise NativeTrainingError(
            "LABEL_SPACE_MISMATCH",
            "the label space size does not match the model configuration",
        )
    _validate_initial_parameters(initial_parameters, model_config)
    _validate_example_bindings(
        examples=examples,
        splits=splits,
        training_texts=training_texts,
        vocabulary=vocabulary,
        mapping=mapping,
        model_config=model_config,
    )

    dimension = model_config.embedding_dim
    clip = training_config.gradient_clip
    rate = training_config.learning_rate
    embedding = [list(row) for row in initial_parameters.embedding]
    weights = [list(row) for row in initial_parameters.head_weight]
    bias = list(initial_parameters.head_bias)
    initial_loss = _loss(initial_parameters, examples, model_config)
    for _ in range(training_config.epochs):
        for example in examples:
            token_ids = example.token_ids[: model_config.max_sequence_length]
            if token_ids:
                pooled = [
                    sum(embedding[token][axis] for token in token_ids) / len(token_ids)
                    for axis in range(dimension)
                ]
            else:
                pooled = [0.0] * dimension
            targets = set(example.label_ids)
            # Pass 1: every gradient comes from the pre-update snapshot.
            deltas = []
            for label in range(model_config.num_labels):
                logit = (
                    sum(
                        weights[label][axis] * pooled[axis] for axis in range(dimension)
                    )
                    + bias[label]
                )
                deltas.append(
                    stable_sigmoid(logit) - (1.0 if label in targets else 0.0)
                )
            grad_pooled = [
                sum(
                    deltas[label] * weights[label][axis] for label in range(len(deltas))
                )
                for axis in range(dimension)
            ]
            token_counts: dict[int, int] = {}
            for token in token_ids:
                token_counts[token] = token_counts.get(token, 0) + 1
            # Pass 2: apply updates deterministically (labels, then sorted tokens).
            for label, delta in enumerate(deltas):
                for axis in range(dimension):
                    weights[label][axis] -= rate * _clip(delta * pooled[axis], clip)
                bias[label] -= rate * _clip(delta, clip)
            for token in sorted(token_counts):
                share = token_counts[token] / len(token_ids)
                for axis in range(dimension):
                    embedding[token][axis] -= rate * _clip(
                        grad_pooled[axis] * share, clip
                    )
    parameters = NativeModelParameters(
        embedding=tuple(tuple(row) for row in embedding),
        head_weight=tuple(tuple(row) for row in weights),
        head_bias=tuple(bias),
    )
    if (
        not all(math.isfinite(value) for row in parameters.embedding for value in row)
        or not all(
            math.isfinite(value) for row in parameters.head_weight for value in row
        )
        or not all(math.isfinite(value) for value in parameters.head_bias)
    ):
        raise NativeTrainingError(
            "NON_FINITE_TRAINED_PARAMETER", "training produced a non-finite parameter"
        )
    final_loss = _loss(parameters, examples, model_config)
    report = NativeTrainingReport(
        model_version=model_config.model_version,
        dataset_fingerprint=fingerprint,
        vocabulary_hash=vocabulary.vocabulary_hash,
        # Derived from the validated canonical mapping used for the head, not
        # accepted from the caller.
        label_map=tuple(mapping),
        label_space_hash=label_space_hash(tuple(mapping)),
        initialization_seed=model_config.initialization_seed,
        epochs_completed=training_config.epochs,
        example_count=len(examples),
        learning_rate=training_config.learning_rate,
        initial_binary_cross_entropy=initial_loss,
        final_binary_cross_entropy=final_loss,
        parameters_hash=_parameter_hash(parameters),
    )
    return NativeTrainingResult(parameters=parameters, report=report)


__all__ = [
    "NativeTrainingConfig",
    "NativeTrainingError",
    "NativeTrainingExample",
    "NativeTrainingReport",
    "NativeTrainingResult",
    "LABEL_SPACE_SCHEME_VERSION",
    "NATIVE_TRAINING_REPORT_CONTRACT_VERSION",
    "canonical_label_mapping",
    "label_space_hash",
    "train_native_model",
]
