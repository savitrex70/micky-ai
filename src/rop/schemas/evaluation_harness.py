"""Task 206: strict versioned configuration for the baseline evaluation harness."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

EVALUATION_CONTRACT_VERSION = "1"
MAX_LABELS = 32
MAX_EXAMPLES = 100000
MAX_REASON_LENGTH = 500
MIN_SPLIT_COUNT = 1
MAX_SPLIT_COUNT = 10000
# Latency thresholds are milliseconds; every other metric is a proportion.
MAX_LATENCY_THRESHOLD_MS = 3_600_000.0

# Zero-tolerance safety metric: an admitted invalid/detached evidence
# reference is an unconditional failure of any candidate or baseline run.
ZERO_TOLERANCE_METRIC = "INVALID_EVIDENCE_REFERENCE_RATE"


class EvaluationTaskKind(StrEnum):
    """Narrow, non-autonomous candidate task families."""

    LABEL_SUGGESTION = "LABEL_SUGGESTION"
    TAG_CLASSIFICATION = "TAG_CLASSIFICATION"


class EvaluationMetricKind(StrEnum):
    """Task-appropriate metrics; every field is deterministic."""

    MACRO_F1 = "MACRO_F1"
    PER_CLASS_PRECISION = "PER_CLASS_PRECISION"
    PER_CLASS_RECALL = "PER_CLASS_RECALL"
    BALANCED_ACCURACY = "BALANCED_ACCURACY"
    COVERAGE = "COVERAGE"
    ABSTENTION_RATE = "ABSTENTION_RATE"
    LATENCY_MS = "LATENCY_MS"
    INVALID_EVIDENCE_REFERENCE_RATE = "INVALID_EVIDENCE_REFERENCE_RATE"


class EvaluationSplit(StrEnum):
    """Explicit partition boundary; the test split stays locked."""

    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


class EvaluationManifestEntry(BaseModel):
    """One example bound to its canonical identifier, split and labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    example_id: StrictStr = Field(min_length=1, max_length=200)
    split: EvaluationSplit
    expected_labels: tuple[StrictStr, ...] = Field(max_length=MAX_LABELS)

    @field_validator("example_id")
    @classmethod
    def _nonblank_example_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("example_id must not be blank")
        return value

    @field_validator("expected_labels")
    @classmethod
    def _canonical_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("expected_labels must not contain duplicates")
        if value != tuple(sorted(value)):
            raise ValueError("expected_labels must be canonically sorted")
        return value


class EvaluationTaskDefinition(BaseModel):
    """Versioned, predeclared candidate task and label space."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"]
    task_id: StrictStr = Field(min_length=1, max_length=100)
    task_kind: EvaluationTaskKind
    labels: tuple[StrictStr, ...] = Field(min_length=2, max_length=MAX_LABELS)
    description: StrictStr = Field(max_length=MAX_REASON_LENGTH)

    @field_validator("task_id")
    @classmethod
    def _canonical_task_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task_id must not be blank")
        return value

    @field_validator("labels")
    @classmethod
    def _canonical_label_set(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("labels must not contain duplicates")
        if value != tuple(sorted(value)):
            raise ValueError("labels must be canonically sorted")
        if any(not label.strip() for label in value):
            raise ValueError("labels must not be blank")
        return value


class EvaluationMetricThreshold(BaseModel):
    """One predeclared acceptance threshold for one metric."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: EvaluationMetricKind
    minimum: StrictFloat | None = Field(ge=0.0)
    maximum: StrictFloat | None = Field(ge=0.0)

    @model_validator(mode="after")
    def _declared_bound(self) -> EvaluationMetricThreshold:
        if self.minimum is None and self.maximum is None:
            raise ValueError("a threshold must declare a minimum or maximum bound")
        # Metric-appropriate range: milliseconds for latency, [0, 1] otherwise.
        upper = (
            MAX_LATENCY_THRESHOLD_MS
            if self.metric == EvaluationMetricKind.LATENCY_MS
            else 1.0
        )
        for bound in (self.minimum, self.maximum):
            if bound is not None and not bound <= upper:
                raise ValueError(
                    "threshold bounds must stay within the metric's valid range"
                )
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("threshold minimum must not exceed maximum")
        return self


class EvaluationMetricConfiguration(BaseModel):
    """Versioned metric/threshold contract; thresholds precede evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"]
    configuration_id: StrictStr = Field(min_length=1, max_length=100)
    task_id: StrictStr = Field(min_length=1, max_length=100)
    thresholds: tuple[EvaluationMetricThreshold, ...] = Field(
        min_length=MIN_SPLIT_COUNT, max_length=32
    )
    minimum_examples_per_class: StrictInt = Field(ge=0, le=10000)

    @field_validator("thresholds")
    @classmethod
    def _unique_and_canonical_thresholds(
        cls, value: tuple[EvaluationMetricThreshold, ...]
    ) -> tuple[EvaluationMetricThreshold, ...]:
        metrics = [threshold.metric for threshold in value]
        if len(set(metrics)) != len(metrics):
            raise ValueError("thresholds must reference each metric at most once")
        if value != tuple(sorted(value, key=lambda threshold: threshold.metric.value)):
            raise ValueError("thresholds must be canonically sorted by metric")
        if ZERO_TOLERANCE_METRIC not in {item.value for item in metrics}:
            raise ValueError(
                "the zero-tolerance invalid-reference metric must be declared"
            )
        return value

    @model_validator(mode="after")
    def _zero_tolerance_is_zero(self) -> EvaluationMetricConfiguration:
        for threshold in self.thresholds:
            if threshold.metric == EvaluationMetricKind.INVALID_EVIDENCE_REFERENCE_RATE:
                if threshold.maximum != 0.0:
                    raise ValueError(
                        "the invalid-reference metric must be capped at 0.0"
                    )
        return self


class EvaluationSplitManifest(BaseModel):
    """Immutable split assignment for one evaluation dataset snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"]
    dataset_id: StrictStr = Field(min_length=1, max_length=200)
    dataset_snapshot_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: StrictStr = Field(min_length=1, max_length=100)
    entries: tuple[EvaluationManifestEntry, ...] = Field(
        min_length=MIN_SPLIT_COUNT, max_length=MAX_EXAMPLES
    )

    @field_validator("entries")
    @classmethod
    def _unique_and_canonical_entries(
        cls, value: tuple[EvaluationManifestEntry, ...]
    ) -> tuple[EvaluationManifestEntry, ...]:
        example_ids = [entry.example_id for entry in value]
        if len(set(example_ids)) != len(example_ids):
            raise ValueError("entries must use unique example identifiers")
        if value != tuple(
            sorted(value, key=lambda entry: (entry.split.value, entry.example_id))
        ):
            raise ValueError(
                "entries must be sorted canonically by split and example_id"
            )
        return value

    @model_validator(mode="after")
    def _split_boundaries_are_declared(self) -> EvaluationSplitManifest:
        splits = {entry.split for entry in self.entries}
        if not splits <= {
            EvaluationSplit.TRAIN,
            EvaluationSplit.VALIDATION,
            EvaluationSplit.TEST,
        }:
            raise ValueError("entries may declare only TRAIN/VALIDATION/TEST splits")
        return self

    def examples_for(
        self, split: EvaluationSplit
    ) -> tuple[EvaluationManifestEntry, ...]:
        """Deterministically list the entries of one partition."""
        return tuple(entry for entry in self.entries if entry.split == split)


class CandidatePrediction(BaseModel):
    """One candidate (or baseline) output for one example.

    ``invalid`` is the zero-tolerance trust signal: the prediction
    referenced evidence that the split did not supply.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    example_id: StrictStr = Field(min_length=1, max_length=200)
    predicted_labels: tuple[StrictStr, ...] = Field(max_length=MAX_LABELS)
    abstained: StrictBool
    latency_ms: StrictFloat | None = Field(ge=0.0)
    invalid: StrictBool = False

    @field_validator("predicted_labels")
    @classmethod
    def _canonical_predictions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("predicted_labels must not contain duplicates")
        if value != tuple(sorted(value)):
            raise ValueError("predicted_labels must be canonically sorted")
        return value

    @model_validator(mode="after")
    def _predictions_with_expected_null_guard(self) -> CandidatePrediction:
        # Abstaining must not coexist with predictions: state is explicit.
        if self.abstained and self.predicted_labels:
            raise ValueError("an abstaining prediction must not also predict labels")
        return self


class EvaluationRunConfiguration(BaseModel):
    """Everything needed to reproduce one run, before seeing outcomes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"]
    run_id: StrictStr = Field(min_length=1, max_length=100)
    task: EvaluationTaskDefinition
    metric_configuration: EvaluationMetricConfiguration
    split_manifest: EvaluationSplitManifest
    evaluated_splits: tuple[EvaluationSplit, ...] = Field(min_length=1)

    @field_validator("evaluated_splits")
    @classmethod
    def _canonical_splits(
        cls, value: tuple[EvaluationSplit, ...]
    ) -> tuple[EvaluationSplit, ...]:
        if len(set(value)) != len(value):
            raise ValueError("evaluated_splits must not repeat a split")
        if value != tuple(sorted(value, key=lambda split: split.value)):
            raise ValueError("evaluated_splits must be canonically sorted")
        return value

    @model_validator(mode="after")
    def _task_matches_configuration(self) -> EvaluationRunConfiguration:
        if self.metric_configuration.task_id != self.task.task_id:
            raise ValueError("metric configuration must target the declared task")
        if self.split_manifest.task_id != self.task.task_id:
            raise ValueError("split manifest must target the declared task")
        return self


class EvaluationClassReport(BaseModel):
    """Per-class outcome for one run; bounded and deterministic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: StrictStr = Field(min_length=1, max_length=100)
    true_positives: StrictInt = Field(ge=0)
    false_positives: StrictInt = Field(ge=0)
    false_negatives: StrictInt = Field(ge=0)
    precision: StrictFloat = Field(ge=0.0, le=1.0)
    recall: StrictFloat = Field(ge=0.0, le=1.0)


class RunOutcomeSummary(BaseModel):
    """One evaluated system outcome; no tuning inputs are carried here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    system_id: StrictStr = Field(min_length=1, max_length=100)
    macro_f1: StrictFloat = Field(ge=0.0, le=1.0)
    balanced_accuracy: StrictFloat = Field(ge=0.0, le=1.0)
    coverage: StrictFloat = Field(ge=0.0, le=1.0)
    abstention_rate: StrictFloat = Field(ge=0.0, le=1.0)
    invalid_evidence_reference_rate: StrictFloat = Field(ge=0.0, le=1.0)
    example_count: StrictInt = Field(ge=0)
    per_class: tuple[EvaluationClassReport, ...] = Field(max_length=MAX_LABELS)
    confusion_matrix: tuple[tuple[str, str, StrictInt], ...] = Field(max_length=1024)
    latency_ms_max: StrictFloat | None = Field(ge=0.0)

    @field_validator("per_class")
    @classmethod
    def _canonical_per_class(
        cls, value: tuple[EvaluationClassReport, ...]
    ) -> tuple[EvaluationClassReport, ...]:
        labels = [report.label for report in value]
        if len(set(labels)) != len(labels):
            raise ValueError("per-class reports must use unique labels")
        if value != tuple(sorted(value, key=lambda report: report.label)):
            raise ValueError("per-class reports must be canonically sorted")
        return value


class EvaluationComparisonReport(BaseModel):
    """Privacy-safe, versioned comparison of baseline vs candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"]
    run_id: StrictStr = Field(min_length=1, max_length=100)
    run_configuration_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_id: StrictStr = Field(min_length=1, max_length=200)
    dataset_snapshot_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    confusion_matrix_scalar: StrictInt = Field(ge=0)
    baseline: RunOutcomeSummary
    candidate: RunOutcomeSummary
    candidate_improves_macro_f1: StrictBool
    safety_failure: StrictBool
    accepted: StrictBool
    limitations: tuple[StrictStr, ...] = Field(max_length=32)

    @field_validator("limitations")
    @classmethod
    def _canonical_limitations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("limitations must not contain duplicates")
        if value != tuple(sorted(value)):
            raise ValueError("limitations must be canonically sorted")
        return value

    @model_validator(mode="after")
    def _acceptance_follows_predeclared_gate(self) -> EvaluationComparisonReport:
        if self.safety_failure and self.accepted:
            raise ValueError("a safety failure can never be accepted")
        if self.accepted and not self.candidate_improves_macro_f1:
            raise ValueError(
                "acceptance requires the candidate to improve the predeclared metric"
            )
        return self


class EvaluationHarnessError(Exception):
    """Typed harness error; carries only canonical, non-sensitive text."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


def reject_tuning_references(payload: dict[str, Any]) -> None:
    """Fail closed if a report payload smuggles post-hoc tuning state.

    The harness refuses keys that could carry test-set tuning decisions;
    threshold overrides always flow through the predeclared configuration.
    """
    forbidden = {
        "threshold_override",
        "post_hoc_threshold",
        "test_set_tuning",
        "tuned_thresholds",
        "model_selection_seed",
    }
    present = forbidden.intersection(payload.keys())
    if present:
        raise EvaluationHarnessError(
            "TUNING_STATE_REJECTED",
            "the run configuration carries forbidden tuning keys: "
            f"{sorted(present)[0]}",
        )


def canonical_examples_digest(
    run_configuration: EvaluationRunConfiguration,
) -> str:
    """Stable SHA-256 over the canonical run configuration JSON.

    Reports record this hash so an independent auditor can prove the
    same examples and splits were used before thresholds were compared.
    """
    import hashlib
    import json

    payload = json.dumps(
        run_configuration.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit("This module is not an executable entry point.")
