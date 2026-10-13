"""Task 210: bounded training-loop contracts.

Data-only contracts for the explicitly invoked, resource-bounded
training and validation loop over the Task 209 model. No
checkpointing, serialization, inference service, network, GPU,
or clinical logic lives here.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TRAINING_CONFIG_VERSION = "1"
TRAINING_REPORT_VERSION = "1"
TRAINING_LOOP_VERSION = "training-loop-v1"

MIN_EPOCHS = 1
MAX_EPOCHS = 50
"""Upper bound on epochs per run: the loop is a bounded plumbing tool,
not an unbounded fitting service."""

MIN_BATCH_SIZE = 1
MAX_BATCH_SIZE = 64
"""Upper bound on batch size: conservative CPU memory budget."""

MAX_LEARNING_RATE = 1.0
"""Upper bound on the optimizer learning rate."""

MAX_EXAMPLES_PER_PARTITION = 10_000
"""Upper bound on encoded examples accepted for one partition."""

TRAINING_DISCLAIMER = (
    "Synthetic-test-only bounded training loop. Successful completion "
    "establishes no model competence, no clinical validity, and no "
    "real-world accuracy."
)

_FINITE_NOTE = "value must be a finite number"


def _reject_ambiguous_number(value: object, field_name: str) -> object:
    """Reject booleans and strings before lax numeric parsing."""
    if isinstance(value, (bool, str)):
        raise ValueError(f"{field_name} is invalid")
    return value


def canonical_sha256(value: Any) -> str:
    """SHA-256 over sorted-key compact JSON (Task 104/104a scheme)."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class TrainingConfig(BaseModel):
    """Explicit, strictly validated training configuration (Task 210).

    Every field is required, bounded, and rejected when ambiguous
    (booleans and numeric strings are refused rather than coerced).
    ``configuration_hash`` fingerprints the whole configuration for
    the report.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = TRAINING_CONFIG_VERSION
    epochs: int = Field(ge=MIN_EPOCHS, le=MAX_EPOCHS)
    batch_size: int = Field(ge=MIN_BATCH_SIZE, le=MAX_BATCH_SIZE)
    learning_rate: float = Field(gt=0.0, le=MAX_LEARNING_RATE)
    seed: int = Field(ge=0, le=2**32 - 1)

    @field_validator("epochs", "batch_size", "seed", mode="before")
    @classmethod
    def _strict_int(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "integer field")

    @field_validator("learning_rate", mode="before")
    @classmethod
    def _strict_float(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "float field")

    def configuration_hash(self) -> str:
        """Deterministic digest over the full validated configuration."""
        return canonical_sha256(self.model_dump(mode="json"))


class EpochMetrics(BaseModel):
    """One epoch's training and validation metrics (Task 210).

    ``train_*`` metrics come from gradient-fitted batches on the
    training partition; ``validation_*`` metrics come from
    no-gradient evaluation on the validation partition. Both are
    finite by construction; the validator refuses non-finite values
    so a failed computation can never surface as a valid report.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    epoch: int = Field(ge=1)
    train_loss: float
    train_examples: int = Field(ge=1)
    train_batches: int = Field(ge=1)
    validation_loss: float
    validation_examples: int = Field(ge=1)
    validation_batches: int = Field(ge=1)
    validation_accuracy: float

    @field_validator(
        "epoch",
        "train_examples",
        "train_batches",
        "validation_examples",
        "validation_batches",
        mode="before",
    )
    @classmethod
    def _strict_int(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "integer field")

    @field_validator(
        "train_loss", "validation_loss", "validation_accuracy", mode="before"
    )
    @classmethod
    def _strict_float(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "float field")

    @model_validator(mode="after")
    def _strict_metrics(self) -> EpochMetrics:
        if not math.isfinite(self.train_loss):
            raise ValueError("train_loss " + _FINITE_NOTE)
        if not math.isfinite(self.validation_loss):
            raise ValueError("validation_loss " + _FINITE_NOTE)
        if not math.isfinite(self.validation_accuracy):
            raise ValueError("validation_accuracy " + _FINITE_NOTE)
        if not 0.0 <= self.validation_accuracy <= 1.0:
            raise ValueError("validation_accuracy is invalid")
        return self


class TrainingReport(BaseModel):
    """Strictly validated structured report of one completed run (Task 210).

    Reports are produced only after every requested epoch finished
    with finite losses, gradients, parameters, and metrics; any
    failure raises instead of returning. The report never reads or
    records the test partition.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_version: Literal["1"] = TRAINING_REPORT_VERSION
    loop_version: Literal[TRAINING_LOOP_VERSION] = TRAINING_LOOP_VERSION
    run_completed: Literal[True]
    synthetic_only: Literal[True]
    disclaimer: str = TRAINING_DISCLAIMER
    model_version: Literal["1.0"]
    architecture: Literal["tiny-encoder-v1"]
    model_config_hash: str = Field(min_length=64, max_length=64)
    model_init_seed: int = Field(ge=0, le=2**32 - 1)
    dataset_id: str = Field(min_length=1, max_length=64)
    dataset_integrity_hash: str = Field(min_length=64, max_length=64)
    split_assignment_hash: str = Field(min_length=64, max_length=64)
    vocabulary_hash: str = Field(min_length=64, max_length=64)
    authorization_kind: Literal["synthetic-test-only"]
    epochs_requested: int = Field(ge=MIN_EPOCHS, le=MAX_EPOCHS)
    batch_size: int = Field(ge=MIN_BATCH_SIZE, le=MAX_BATCH_SIZE)
    learning_rate: float
    seed: int = Field(ge=0, le=2**32 - 1)
    training_config_hash: str = Field(min_length=64, max_length=64)
    train_example_count: int = Field(ge=1)
    validation_example_count: int = Field(ge=1)
    epochs_completed: int
    batches_completed: int
    final_train_loss: float
    final_validation_loss: float
    final_validation_accuracy: float
    epoch_metrics: tuple[EpochMetrics, ...] = Field(min_length=1)

    @field_validator(
        "final_train_loss",
        "final_validation_loss",
        "final_validation_accuracy",
        mode="before",
    )
    @classmethod
    def _strict_float(cls, value: object) -> object:
        return _reject_ambiguous_number(value, "float field")

    @model_validator(mode="after")
    def _strict_report(self) -> TrainingReport:
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0.0:
            raise ValueError("learning_rate is invalid")
        if self.epochs_completed != self.epochs_requested:
            raise ValueError("epochs_completed must equal epochs_requested")
        if len(self.epoch_metrics) != self.epochs_completed:
            raise ValueError("epoch_metrics must cover every completed epoch")
        for name in (
            "final_train_loss",
            "final_validation_loss",
            "final_validation_accuracy",
        ):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} {_FINITE_NOTE}")
        batches = sum(entry.train_batches for entry in self.epoch_metrics)
        if self.batches_completed != batches:
            raise ValueError("batches_completed must equal summed epoch batches")
        last = self.epoch_metrics[-1]
        if self.final_train_loss != last.train_loss:
            raise ValueError("final_train_loss must equal the last epoch value")
        if self.final_validation_loss != last.validation_loss:
            raise ValueError("final_validation_loss must equal the last epoch value")
        if self.final_validation_accuracy != last.validation_accuracy:
            raise ValueError(
                "final_validation_accuracy must equal the last epoch value"
            )
        return self


NativeTrainingErrorCode = Literal[
    "INVALID_INPUT",
    "INVALID_CONFIG",
    "UNSUPPORTED_SCOPE",
    "OPERATION_NOT_PERMITTED",
    "EMPTY_PARTITION",
    "MALFORMED_EXAMPLE",
    "LABEL_UNKNOWN",
    "INCOMPATIBLE_DATASET",
    "INCOMPATIBLE_MODEL",
    "INCOMPATIBLE_VOCABULARY",
    "INCOMPATIBLE_TOKENIZER",
    "HASH_MISMATCH",
    "SPLIT_INTEGRITY_FAILURE",
    "RESOURCE_LIMIT",
    "NON_FINITE_LOSS",
    "NON_FINITE_GRADIENT",
    "NON_FINITE_PARAMETER",
    "NON_FINITE_METRIC",
]


__all__ = [
    "MAX_BATCH_SIZE",
    "MAX_EPOCHS",
    "MAX_EXAMPLES_PER_PARTITION",
    "MAX_LEARNING_RATE",
    "TRAINING_CONFIG_VERSION",
    "TRAINING_REPORT_VERSION",
    "TRAINING_LOOP_VERSION",
    "TRAINING_DISCLAIMER",
    "EpochMetrics",
    "NativeTrainingErrorCode",
    "TrainingConfig",
    "TrainingReport",
    "canonical_sha256",
]
