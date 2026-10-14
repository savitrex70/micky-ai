"""Task 210: explicit, bounded, deterministic training and validation loop.

A small, isolated training-mechanics module for the Task 209
``tiny-encoder-v1`` model over the Task 207 ``synthetic-test-only``
dataset scope and the Task 208 vocabulary. Training starts only
when ``run_training`` is explicitly called; importing this module
never trains, and there is no background loop, network call,
telemetry, download, checkpoint, or inference-service integration
here (Tasks 211-215 are explicitly out of scope).

Data boundary: fitting reads the validated ``PreparationResult``
through ``partition_records(result, "train")`` only, and validation
metrics are computed only from ``partition_records(result,
"validation")`` during no-gradient evaluation. Before any fitting,
the loop runs one narrow pre-training integrity preflight over the
complete retained record set to establish dataset and split integrity
with the Task 207 verification contract; this preflight inspects test
records structurally (identity, grouping, and hash recomputation)
but never encodes them, fits on them, evaluates on them, selects on
them, logs them, or reports them. Train and validation records are
never combined for fitting.

Determinism: training preserves the caller's global CPU RNG state
around the whole run; the loop seeds the global RNG from
``TrainingConfig.seed`` for dropout and uses a dedicated generator
seeded from the same value for permutation shuffling. Model
initialization remains the Task 209 deterministic procedure and is
verified before the first update. Identical inputs, configuration,
and supported runtime conditions (CPU, same PyTorch build, same
thread count) produce repeatable runs; any non-CPU execution is out
of scope.

Failure behavior: every rejection uses ``NativeTrainingError`` with
a stable code. Non-finite losses, gradients, parameters, or metrics
stop the run immediately with an explicit error; a report is
returned only for a fully completed, fully finite run.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import torch
import torch.nn.functional as F

from rop.dataset_preparation.pipeline import (
    DatasetPreparationError,
    dataset_integrity_hash,
    partition_records,
    verify_split,
)
from rop.native_model.native_model import (
    NativeModel,
    NativeModelError,
    verify_model,
)
from rop.schemas.dataset_manifest import DatasetRecord, PreparationResult
from rop.schemas.native_model import MODEL_ARCHITECTURE, MODEL_VERSION
from rop.schemas.tokenizer import (
    MAX_SEQUENCE_LENGTH_LIMIT,
    PAD_ID,
    TokenizerConfig,
    Vocabulary,
)
from rop.schemas.training import (
    MAX_EXAMPLES_PER_PARTITION,
    TRAINING_DISCLAIMER,
    EpochMetrics,
    NativeTrainingErrorCode,
    TrainingConfig,
    TrainingReport,
    canonical_sha256,
)
from rop.tokenizer.vocabulary import encode_text, verify_vocabulary

__all__ = [
    "NativeTrainingError",
    "build_training_dataset",
    "run_training",
]

_OPTIMIZER_CLS = torch.optim.SGD
"""Optimizer indirection point: SGD over the model's parameters with
plain learning rate. Tests may monkeypatch this module attribute to
spy on optimizer steps without touching production behavior."""


class NativeTrainingError(Exception):
    """A typed training failure with a safe, generic message."""

    def __init__(self, code: NativeTrainingErrorCode, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


@dataclass(frozen=True)
class EncodedExample:
    """One encoded training or validation example (Task 210)."""

    record_id: str
    group_id: str
    token_ids: tuple[int, ...]
    label_index: int


@dataclass(frozen=True)
class EncodedTrainingDataset:
    """Encoded partitions actually used by the loop (Task 210).

    Only the training and validation partitions are reachable from
    this value; no attribute, path, or parameter exposes test
    records.
    """

    train_examples: tuple[EncodedExample, ...]
    validation_examples: tuple[EncodedExample, ...]


def _checked_training_config(
    config: TrainingConfig | Mapping[str, Any],
) -> TrainingConfig:
    """Validate a training configuration mapping eagerly and strictly.

    Revalidates existing instances to prevent bypass via
    ``model_copy(update=...)``.
    """
    try:
        if isinstance(config, TrainingConfig):
            return TrainingConfig.model_validate(config.model_dump())
        if isinstance(config, Mapping):
            return TrainingConfig.model_validate(dict(config))
    except Exception as exc:
        raise NativeTrainingError(
            "INVALID_CONFIG", "training configuration is invalid"
        ) from exc
    raise NativeTrainingError("INVALID_CONFIG", "training configuration is invalid")


def _checked_tokenizer_config(
    tokenizer_config: TokenizerConfig | Mapping[str, Any],
) -> TokenizerConfig:
    """Validate a tokenizer configuration mapping eagerly and strictly."""
    if isinstance(tokenizer_config, TokenizerConfig):
        return tokenizer_config
    if isinstance(tokenizer_config, Mapping):
        try:
            return TokenizerConfig.model_validate(dict(tokenizer_config))
        except Exception as exc:
            raise NativeTrainingError(
                "INVALID_CONFIG", "tokenizer configuration is invalid"
            ) from exc
    raise NativeTrainingError("INVALID_CONFIG", "tokenizer configuration is invalid")


def build_training_dataset(
    result: PreparationResult,
    *,
    vocabulary: Vocabulary,
    tokenizer_config: TokenizerConfig | Mapping[str, Any],
) -> EncodedTrainingDataset:
    """Encode the training and validation partitions for the loop.

    Reads the validated ``PreparationResult`` exclusively through
    ``partition_records(result, "train")`` and
    ``partition_records(result, "validation")``; the test partition
    is never requested, decoded, or retained. Record content digests
    are recomputed to defeat in-memory tampering, labels are mapped
    to class indices through the manifest's sorted allowed labels,
    and empty or oversized partitions fail closed.
    """
    if not isinstance(result, PreparationResult):
        raise NativeTrainingError("INVALID_INPUT", "preparation result is invalid")
    if not isinstance(vocabulary, Vocabulary):
        raise NativeTrainingError("INVALID_INPUT", "vocabulary is invalid")
    config = _checked_tokenizer_config(tokenizer_config)
    manifest = result.dataset_manifest
    if manifest.authorization_kind != "synthetic-test-only":
        raise NativeTrainingError("UNSUPPORTED_SCOPE", "dataset scope is not supported")
    if manifest.operation != "training":
        raise NativeTrainingError(
            "OPERATION_NOT_PERMITTED", "dataset operation is not training"
        )
    try:
        verify_vocabulary(vocabulary, tokenizer_config=config)
    except Exception as exc:
        raise NativeTrainingError(
            "HASH_MISMATCH", "vocabulary integrity check failed"
        ) from exc
    allowed = tuple(sorted(manifest.allowed_labels))

    def _encode_partition(records: Any) -> tuple[EncodedExample, ...]:
        examples: list[EncodedExample] = []
        for record in records:
            if not 1 <= len(record.content_text) <= MAX_SEQUENCE_LENGTH_LIMIT * 16:
                raise NativeTrainingError(
                    "MALFORMED_EXAMPLE", "example content is malformed"
                )
            if hash_content(record.content_text) != record.content_hash:
                raise NativeTrainingError(
                    "MALFORMED_EXAMPLE", "example content digest does not match"
                )
            if record.label not in allowed:
                raise NativeTrainingError("LABEL_UNKNOWN", "example label is unknown")
            ids = encode_text(
                record.content_text,
                vocabulary=vocabulary,
                tokenizer_config=config,
            )
            if len(ids) == 0:
                raise NativeTrainingError(
                    "MALFORMED_EXAMPLE", "example encodes to zero tokens"
                )
            examples.append(
                EncodedExample(
                    record_id=record.record_id,
                    group_id=record.group_id,
                    token_ids=ids,
                    label_index=allowed.index(record.label),
                )
            )
        return tuple(examples)

    train_examples = _encode_partition(partition_records(result, "train"))
    validation_examples = _encode_partition(partition_records(result, "validation"))
    if not train_examples:
        raise NativeTrainingError("EMPTY_PARTITION", "training partition is empty")
    if not validation_examples:
        raise NativeTrainingError("EMPTY_PARTITION", "validation partition is empty")
    if len(train_examples) > MAX_EXAMPLES_PER_PARTITION:
        raise NativeTrainingError("RESOURCE_LIMIT", "training partition is too large")
    if len(validation_examples) > MAX_EXAMPLES_PER_PARTITION:
        raise NativeTrainingError("RESOURCE_LIMIT", "validation partition is too large")
    return EncodedTrainingDataset(
        train_examples=train_examples,
        validation_examples=validation_examples,
    )


def hash_content(content: str) -> str:
    """SHA-256 of the exact UTF-8 record content bytes."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _retained_records(result: PreparationResult) -> tuple[DatasetRecord, ...]:
    """Collect the complete retained record set from the schema itself.

    Used only by the pre-training integrity preflight. This path never
    calls ``partition_records(result, "test")`` and never feeds these
    records to encoding, fitting, evaluation, selection, or logging;
    the spy tests assert that partition remains true.
    """
    return tuple(
        record for partition in result.partitions for record in partition.records
    )


def _verify_dataset_integrity(result: PreparationResult) -> str:
    """Independently verify dataset and split integrity (Task 207).

    Reuses the Task 207 verification contract as-is: every retained
    record's canonical integrity representation is recomputed, the
    split assignments are replayed through the deterministic
    group-hash policy, and every Task 207 invariant is checked via
    ``verify_split``. Delegated failures are converted to the
    established ``NativeTrainingError`` contract with the meaningful
    stable code preserved. Returns the independently recomputed
    dataset integrity hash for cross-artifact comparison.
    """
    records = _retained_records(result)
    try:
        verify_split(result.split_manifest, records)
    except DatasetPreparationError as exc:
        raise NativeTrainingError(
            "SPLIT_INTEGRITY_FAILURE",
            "Task 207 split integrity verification failed",
        ) from exc
    hashes = {
        result.dataset_manifest.record_integrity_hash,
        result.split_manifest.dataset_integrity_hash,
    }
    if len(hashes) != 1 or hashes.pop() == "":
        raise NativeTrainingError(
            "HASH_MISMATCH", "recorded dataset integrity hashes disagree"
        )
    recomputed = dataset_integrity_hash(records)
    return recomputed


def _validate_cross_artifacts(
    result: PreparationResult,
    model: NativeModel,
    vocabulary: Vocabulary,
    tokenizer_config: TokenizerConfig,
) -> None:
    """Verify artifact identity, integrity, and mutual compatibility.

    Verification order: (1) independent Task 207 dataset and split
    integrity verification over the complete retained record set,
    (2) cross-artifact identity and hash agreement between the
    recomputed hash and every recorded hash, then (3) model/vocabulary
    compatibility. Nothing is encoded or fitted before all of these
    checks succeed.
    """
    manifest = result.dataset_manifest
    split = result.split_manifest
    metadata = vocabulary.metadata
    # Expected data scope and operation first, then independent
    # integrity verification over the complete retained record set.
    if manifest.authorization_kind != "synthetic-test-only":
        raise NativeTrainingError("UNSUPPORTED_SCOPE", "dataset scope is not supported")
    if manifest.operation != "training":
        raise NativeTrainingError(
            "OPERATION_NOT_PERMITTED", "dataset operation is not training"
        )
    recomputed_integrity = _verify_dataset_integrity(result)
    if not (manifest.dataset_id == split.dataset_id == metadata.dataset_id):
        raise NativeTrainingError(
            "INCOMPATIBLE_DATASET", "dataset identity does not agree"
        )
    if not (
        manifest.record_integrity_hash
        == split.dataset_integrity_hash
        == metadata.dataset_integrity_hash
        == recomputed_integrity
    ):
        raise NativeTrainingError(
            "HASH_MISMATCH", "recorded dataset integrity hashes disagree"
        )
    if split.assignment_hash != metadata.split_assignment_hash:
        raise NativeTrainingError(
            "HASH_MISMATCH", "recorded split assignment hashes disagree"
        )
    if split.authorization_kind != manifest.authorization_kind:
        raise NativeTrainingError(
            "HASH_MISMATCH", "recorded authorization kinds disagree"
        )
    if split.train_count != len(partition_records(result, "train")):
        raise NativeTrainingError(
            "SPLIT_INTEGRITY_FAILURE", "split training count does not match"
        )
    if split.validation_count != len(partition_records(result, "validation")):
        raise NativeTrainingError(
            "SPLIT_INTEGRITY_FAILURE", "split validation count does not match"
        )
    train_groups = {record.group_id for record in partition_records(result, "train")}
    validation_groups = {
        record.group_id for record in partition_records(result, "validation")
    }
    if train_groups & validation_groups:
        raise NativeTrainingError(
            "SPLIT_INTEGRITY_FAILURE", "a leakage group spans partitions"
        )
    if model.config.vocab_size != metadata.vocabulary_size:
        raise NativeTrainingError(
            "INCOMPATIBLE_VOCABULARY",
            "model vocabulary size does not match the fitted vocabulary",
        )
    if model.config.num_classes != len(manifest.allowed_labels):
        raise NativeTrainingError(
            "INCOMPATIBLE_MODEL",
            "model class count does not match the dataset label space",
        )
    if tokenizer_config.max_sequence_length > model.config.max_seq_len:
        raise NativeTrainingError(
            "INCOMPATIBLE_TOKENIZER",
            "tokenizer sequence length exceeds the model maximum",
        )


def _pad_batch(batch: list[EncodedExample]) -> torch.Tensor:
    """Stack token id tuples into one long tensor, padded with PAD_ID."""
    width = max(len(example.token_ids) for example in batch)
    rows = [
        list(example.token_ids) + [PAD_ID] * (width - len(example.token_ids))
        for example in batch
    ]
    return torch.tensor(rows, dtype=torch.long)


def run_training(
    result: PreparationResult,
    *,
    model: NativeModel,
    vocabulary: Vocabulary,
    tokenizer_config: TokenizerConfig | Mapping[str, Any],
    config: TrainingConfig | Mapping[str, Any],
) -> TrainingReport:
    """Run one explicit, bounded training and validation pass.

    Fitting touches only the training partition: every optimizer
    update, gradient computation, and training metric comes from
    training batches built via ``build_training_dataset``. The
    validation partition is evaluated once per epoch with no
    gradients and no optimizer updates. Before any fitting, one
    integrity preflight independently verifies the dataset and split
    over the complete retained record set (a structural check that
    touches test records but never encodes, fits, evaluates, selects,
    logs, or reports them); the encoding path still requests only the
    train and validation partitions.

    The model is trained in place and is left in its original
    ``training``/``eval`` mode; its deterministic Task 209
    initialization is verified before the first update. The caller's
    global CPU RNG state is preserved around the whole run whether
    it succeeds or fails.

    Returns a strictly validated ``TrainingReport`` only for a fully
    completed run; every failure raises ``NativeTrainingError`` (or
    a typed error it wraps) instead of a misleading report.
    """
    checked_config = _checked_training_config(config)
    if not isinstance(result, PreparationResult):
        raise NativeTrainingError("INVALID_INPUT", "preparation result is invalid")
    if not isinstance(model, NativeModel) or not model._initialized:
        raise NativeTrainingError("INVALID_INPUT", "model is invalid")
    if not isinstance(vocabulary, Vocabulary):
        raise NativeTrainingError("INVALID_INPUT", "vocabulary is invalid")
    checked_tokenizer_config = _checked_tokenizer_config(tokenizer_config)
    try:
        verify_model(model, config=model.config)
    except NativeModelError:
        raise NativeTrainingError(
            "INVALID_INPUT", "model initialization verification failed"
        ) from None
    _validate_cross_artifacts(result, model, vocabulary, checked_tokenizer_config)
    dataset = build_training_dataset(
        result,
        vocabulary=vocabulary,
        tokenizer_config=checked_tokenizer_config,
    )

    rng_state = torch.get_rng_state()
    try:
        torch.manual_seed(checked_config.seed)
        perm_generator = torch.Generator()
        perm_generator.manual_seed(checked_config.seed)
        optimizer = _OPTIMIZER_CLS(model.parameters(), lr=checked_config.learning_rate)
        initial_training_mode = model.training
        epoch_metrics: list[EpochMetrics] = []
        batches_completed = 0
        try:
            for epoch in range(1, checked_config.epochs + 1):
                train_loss = _train_one_epoch(
                    dataset.train_examples,
                    model=model,
                    optimizer=optimizer,
                    batch_size=checked_config.batch_size,
                    perm_generator=perm_generator,
                )
                for _loss, _n in train_loss:
                    batches_completed += 1
                batches = len(train_loss)
                weighted = sum(loss * float(n) for loss, n in train_loss)
                epoch_train_loss = weighted / float(len(dataset.train_examples))
                validation_loss, validation_accuracy = _evaluate_validation(
                    model,
                    dataset.validation_examples,
                    batch_size=checked_config.batch_size,
                )
                epoch_metrics.append(
                    EpochMetrics(
                        epoch=epoch,
                        train_loss=epoch_train_loss,
                        train_examples=len(dataset.train_examples),
                        train_batches=batches,
                        validation_loss=validation_loss,
                        validation_examples=len(dataset.validation_examples),
                        validation_batches=_batch_count(
                            len(dataset.validation_examples),
                            checked_config.batch_size,
                        ),
                        validation_accuracy=validation_accuracy,
                    )
                )
        finally:
            if initial_training_mode:
                model.train()
            else:
                model.eval()
        report = TrainingReport(
            run_completed=True,
            synthetic_only=True,
            disclaimer=TRAINING_DISCLAIMER,
            model_version=MODEL_VERSION,
            architecture=MODEL_ARCHITECTURE,
            model_config_hash=canonical_sha256(model.config.model_dump(mode="json")),
            model_init_seed=model.config.init_seed,
            dataset_id=result.dataset_manifest.dataset_id,
            dataset_integrity_hash=result.dataset_manifest.record_integrity_hash,
            split_assignment_hash=result.split_manifest.assignment_hash,
            vocabulary_hash=vocabulary.metadata.vocabulary_hash,
            authorization_kind=result.dataset_manifest.authorization_kind,
            epochs_requested=checked_config.epochs,
            batch_size=checked_config.batch_size,
            learning_rate=checked_config.learning_rate,
            seed=checked_config.seed,
            training_config_hash=checked_config.configuration_hash(),
            train_example_count=len(dataset.train_examples),
            validation_example_count=len(dataset.validation_examples),
            epochs_completed=checked_config.epochs,
            batches_completed=batches_completed,
            final_train_loss=epoch_metrics[-1].train_loss,
            final_validation_loss=epoch_metrics[-1].validation_loss,
            final_validation_accuracy=epoch_metrics[-1].validation_accuracy,
            epoch_metrics=tuple(epoch_metrics),
        )
        _validate_report_finiteness(report)
        return report
    finally:
        torch.set_rng_state(rng_state)


def _batch_count(size: int, batch_size: int) -> int:
    return (size + batch_size - 1) // batch_size


def _train_one_epoch(
    examples: tuple[EncodedExample, ...],
    *,
    model: NativeModel,
    optimizer: torch.optim.Optimizer,
    batch_size: int,
    perm_generator: torch.Generator,
) -> list[tuple[float, int]]:
    """Fit one epoch on the training partition and return batch losses."""
    model.train()
    order = torch.randperm(len(examples), generator=perm_generator).tolist()
    losses: list[tuple[float, int]] = []
    for start in range(0, len(examples), batch_size):
        batch = [examples[index] for index in order[start : start + batch_size]]
        token_ids = _pad_batch(batch)
        labels = torch.tensor(
            [example.label_index for example in batch], dtype=torch.long
        )
        logits = model(token_ids)
        loss = F.cross_entropy(logits, labels)
        if not torch.isfinite(loss).item():
            raise NativeTrainingError(
                "NON_FINITE_LOSS", "loss became non-finite during training"
            )
        optimizer.zero_grad()
        loss.backward()
        for name, parameter in model.named_parameters():
            if (
                parameter.grad is not None
                and not torch.all(torch.isfinite(parameter.grad)).item()
            ):
                raise NativeTrainingError(
                    "NON_FINITE_GRADIENT",
                    f"gradient became non-finite for {name!r}",
                )
        optimizer.step()
        for name, parameter in model.named_parameters():
            if not torch.all(torch.isfinite(parameter)).item():
                raise NativeTrainingError(
                    "NON_FINITE_PARAMETER",
                    f"parameter became non-finite for {name!r}",
                )
        losses.append((loss.item(), len(batch)))
    return losses


def _evaluate_validation(
    model: NativeModel,
    examples: tuple[EncodedExample, ...],
    *,
    batch_size: int,
) -> tuple[float, float]:
    """Evaluate the validation partition without gradients or updates."""
    model.eval()
    was_grad_enabled = torch.is_grad_enabled()
    torch.set_grad_enabled(False)
    try:
        total_loss = 0.0
        correct = 0
        for start in range(0, len(examples), batch_size):
            batch = list(examples[start : start + batch_size])
            token_ids = _pad_batch(batch)
            labels = torch.tensor(
                [example.label_index for example in batch], dtype=torch.long
            )
            logits = model(token_ids)
            loss = F.cross_entropy(
                logits,
                labels,
                reduction="sum",
            )
            if not torch.isfinite(loss).item():
                raise NativeTrainingError(
                    "NON_FINITE_LOSS",
                    "loss became non-finite during validation",
                )
            total_loss += float(loss.item())
            predictions = torch.argmax(logits, dim=1)
            correct += int((predictions == labels).sum().item())
        mean_loss = total_loss / float(len(examples))
        if not math.isfinite(mean_loss):
            raise NativeTrainingError(
                "NON_FINITE_METRIC", "validation metric became non-finite"
            )
        accuracy = correct / float(len(examples))
        if not math.isfinite(accuracy):
            raise NativeTrainingError(
                "NON_FINITE_METRIC", "validation metric became non-finite"
            )
        return mean_loss, accuracy
    finally:
        torch.set_grad_enabled(was_grad_enabled)


def _validate_report_finiteness(report: TrainingReport) -> None:
    """Fail closed if any report metric escaped as non-finite."""
    values = [report.final_train_loss, report.final_validation_loss]
    for entry in report.epoch_metrics:
        values.extend([entry.train_loss, entry.validation_loss])
    if any(not math.isfinite(value) for value in values):
        raise NativeTrainingError(
            "NON_FINITE_METRIC", "report metric became non-finite"
        )
