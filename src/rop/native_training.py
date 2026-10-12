"""Task 210: deterministic, offline training for the first-party native model.

Training uses only the project's own model, authorized Task 207 train split,
and Task 208 vocabulary. No shuffle, network, pretrained weights, or external
numerical framework is used. Validation/test examples are never accepted here.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr

from rop.dataset_preparation import PreparedSplits, records_fingerprint
from rop.native_model import NativeModelParameters
from rop.schemas.dataset_manifest import (
    AuthorizationStatus,
    DatasetManifest,
    PermittedPurpose,
)
from rop.schemas.native_model import NativeModelConfig
from rop.tokenization import Vocabulary


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
        cls,
        record_id: str,
        token_ids: tuple[int, ...],
        label_ids: tuple[int, ...],
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

    contract_version: Literal["1"] = "1"
    model_version: StrictStr = Field(min_length=1, max_length=32)
    dataset_fingerprint: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    initialization_seed: StrictInt = Field(ge=0)
    epochs_completed: StrictInt = Field(ge=1, le=500)
    example_count: StrictInt = Field(ge=1, le=100000)
    learning_rate: StrictFloat = Field(gt=0.0, le=1.0)
    initial_binary_cross_entropy: StrictFloat = Field(ge=0.0)
    final_binary_cross_entropy: StrictFloat = Field(ge=0.0)
    parameters_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


def _parameter_hash(parameters: NativeModelParameters) -> str:
    payload = {
        "embedding": parameters.embedding,
        "head_weight": parameters.head_weight,
        "head_bias": parameters.head_bias,
    }
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-min(value, 60.0)))
    exp_value = math.exp(max(value, -60.0))
    return exp_value / (1.0 + exp_value)


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
            probability = min(max(_sigmoid(logit), 1e-12), 1.0 - 1e-12)
            target = 1.0 if label in targets else 0.0
            total -= target * math.log(probability) + (1.0 - target) * math.log(1.0 - probability)
    return total / (len(examples) * config.num_labels)


def train_native_model(
    *,
    model_config: NativeModelConfig,
    training_config: NativeTrainingConfig,
    initial_parameters: NativeModelParameters,
    examples: tuple[NativeTrainingExample, ...],
    splits: PreparedSplits,
    manifest: DatasetManifest,
    vocabulary: Vocabulary,
) -> NativeTrainingResult:
    """Train deterministically on exactly the authorized training split."""
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
        dict(manifest.split_fingerprints).get("train") != fingerprint
        or vocabulary.training_fingerprint != fingerprint
    ):
        raise NativeTrainingError(
            "TRAINING_FINGERPRINT_MISMATCH",
            "the manifest, vocabulary, and training split are not bound",
        )
    expected_ids = tuple(sorted(record.record_id for record in splits.train))
    supplied_ids = tuple(sorted(example.record_id for example in examples))
    if not expected_ids or expected_ids != supplied_ids:
        raise NativeTrainingError("TRAINING_SPLIT_MISMATCH", "examples must cover exactly the declared training split")
    if len(examples) > training_config.max_examples:
        raise NativeTrainingError("TRAINING_BOUND_EXCEEDED", "the training example count exceeds the configured bound")
    if (
        len(initial_parameters.embedding) != model_config.vocab_size
        or any(
            len(row) != model_config.embedding_dim
            for row in initial_parameters.embedding
        )
        or len(initial_parameters.head_weight) != model_config.num_labels
        or any(
            len(row) != model_config.embedding_dim
            for row in initial_parameters.head_weight
        )
        or len(initial_parameters.head_bias) != model_config.num_labels
    ):
        raise NativeTrainingError(
            "PARAMETER_SHAPE_MISMATCH",
            "initial parameter dimensions do not match the model configuration",
        )
    parameter_values = [
        value
        for row in initial_parameters.embedding
        for value in row
    ] + [
        value
        for row in initial_parameters.head_weight
        for value in row
    ] + list(initial_parameters.head_bias)
    if not all(math.isfinite(value) for value in parameter_values):
        raise NativeTrainingError(
            "NON_FINITE_INITIAL_PARAMETER",
            "initial parameters must be finite",
        )
    for example in examples:
        if any(token < 0 or token >= model_config.vocab_size for token in example.token_ids):
            raise NativeTrainingError(
                "TOKEN_ID_OUT_OF_RANGE",
                "a training token is outside the configured vocabulary",
            )
        if any(label < 0 or label >= model_config.num_labels for label in example.label_ids):
            raise NativeTrainingError(
                "LABEL_ID_OUT_OF_RANGE",
                "a training label is outside the configured label space",
            )
    if len(vocabulary.tokens) != model_config.vocab_size:
        raise NativeTrainingError(
            "VOCABULARY_SHAPE_MISMATCH",
            "the vocabulary size does not match the model configuration",
        )

    embedding = [list(row) for row in initial_parameters.embedding]
    weights = [list(row) for row in initial_parameters.head_weight]
    bias = list(initial_parameters.head_bias)
    initial_loss = _loss(initial_parameters, examples, model_config)
    for _ in range(training_config.epochs):
        for example in examples:
            token_ids = example.token_ids[: model_config.max_sequence_length]
            pooled = (
                [
                    sum(embedding[token][axis] for token in token_ids)
                    / len(token_ids)
                    for axis in range(model_config.embedding_dim)
                ]
                if token_ids
                else [0.0] * model_config.embedding_dim
            )
            targets = set(example.label_ids)
            grad_pooled = [0.0] * model_config.embedding_dim
            for label in range(model_config.num_labels):
                logit = sum(weights[label][axis] * pooled[axis] for axis in range(model_config.embedding_dim)) + bias[label]
                delta = _sigmoid(logit) - (1.0 if label in targets else 0.0)
                delta = max(-training_config.gradient_clip, min(training_config.gradient_clip, delta))
                previous_weights = tuple(weights[label])
                for axis in range(model_config.embedding_dim):
                    grad_pooled[axis] += delta * previous_weights[axis]
                    grad = delta * pooled[axis]
                    clipped_grad = max(
                        -training_config.gradient_clip,
                        min(training_config.gradient_clip, grad),
                    )
                    weights[label][axis] -= (
                        training_config.learning_rate * clipped_grad
                    )
                bias[label] -= training_config.learning_rate * delta
            if token_ids:
                for token in token_ids:
                    for axis in range(model_config.embedding_dim):
                        grad = grad_pooled[axis] / len(token_ids)
                        clipped_grad = max(
                            -training_config.gradient_clip,
                            min(training_config.gradient_clip, grad),
                        )
                        embedding[token][axis] -= (
                            training_config.learning_rate * clipped_grad
                        )
    parameters = NativeModelParameters(
        embedding=tuple(tuple(row) for row in embedding),
        head_weight=tuple(tuple(row) for row in weights),
        head_bias=tuple(bias),
    )
    if (
        not all(
            math.isfinite(value)
            for row in parameters.embedding
            for value in row
        )
        or not all(
            math.isfinite(value)
            for row in parameters.head_weight
            for value in row
        )
        or not all(math.isfinite(value) for value in parameters.head_bias)
    ):
        raise NativeTrainingError(
            "NON_FINITE_TRAINED_PARAMETER",
            "training produced a non-finite parameter",
        )
    final_loss = _loss(parameters, examples, model_config)
    report = NativeTrainingReport(
        model_version=model_config.model_version,
        dataset_fingerprint=fingerprint,
        vocabulary_hash=vocabulary.vocabulary_hash,
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
    "train_native_model",
]
