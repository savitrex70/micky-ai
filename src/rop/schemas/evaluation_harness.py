"""Task 206: strict versioned configuration for the baseline evaluation harness."""

from __future__ import annotations

from enum import StrEnum
import math
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
# The report now embeds the predeclared metric contract and validates all
# derived per-label binary counts; configuration contracts remain at version 1.
EVALUATION_REPORT_CONTRACT_VERSION = "3"
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


def _metrics_close(actual: float, expected: float) -> bool:
    """Deterministic metric comparison policy: rel_tol=1e-12, abs_tol=1e-12."""
    return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


class EvaluationClassReport(BaseModel):
    """Per-class outcome; zero-denominator precision and recall are 0.0."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: StrictStr = Field(min_length=1, max_length=100)
    true_positives: StrictInt = Field(ge=0)
    false_positives: StrictInt = Field(ge=0)
    false_negatives: StrictInt = Field(ge=0)
    true_negatives: StrictInt = Field(ge=0)
    precision: StrictFloat = Field(ge=0.0, le=1.0)
    recall: StrictFloat = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _metrics_match_counts(self) -> EvaluationClassReport:
        predicted = self.true_positives + self.false_positives
        actual = self.true_positives + self.false_negatives
        precision = self.true_positives / predicted if predicted else 0.0
        recall = self.true_positives / actual if actual else 0.0
        if not _metrics_close(self.precision, precision):
            raise ValueError("precision must match TP/(TP+FP); zero denominator means 0.0")
        if not _metrics_close(self.recall, recall):
            raise ValueError("recall must match TP/(TP+FN); zero denominator means 0.0")
        return self


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
    abstention_count: StrictInt = Field(ge=0)
    invalid_reference_count: StrictInt = Field(ge=0)
    labels: tuple[StrictStr, ...] = Field(min_length=2, max_length=MAX_LABELS)
    per_class: tuple[EvaluationClassReport, ...] = Field(max_length=MAX_LABELS)
    # Diagnostic expected/predicted co-occurrence, not a conventional confusion matrix.
    label_cooccurrence_counts: tuple[tuple[str, str, StrictInt], ...] = Field(max_length=1024)
    # Per label: (label, TP, FP, FN, TN), one binary decision per example.
    binary_confusion: tuple[tuple[StrictStr, StrictInt, StrictInt, StrictInt, StrictInt], ...] = Field(max_length=MAX_LABELS)
    latency_ms_max: StrictFloat | None = Field(ge=0.0)

    @field_validator("labels")
    @classmethod
    def _canonical_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or value != tuple(sorted(value)) or any(not label.strip() for label in value):
            raise ValueError("summary labels must be unique, nonblank and canonically sorted")
        return value

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

    @field_validator("label_cooccurrence_counts")
    @classmethod
    def _canonical_cooccurrence(cls, value):
        keys = [(expected, predicted) for expected, predicted, _ in value]
        if any(count < 1 for _, _, count in value) or len(set(keys)) != len(keys):
            raise ValueError("co-occurrence cells must be unique and positive")
        if value != tuple(sorted(value)):
            raise ValueError("co-occurrence cells must be canonically sorted")
        return value

    @field_validator("binary_confusion")
    @classmethod
    def _canonical_binary_confusion(cls, value):
        labels = [row[0] for row in value]
        if len(set(labels)) != len(labels) or labels != sorted(labels):
            raise ValueError("binary confusion labels must be unique and sorted")
        return value

    @model_validator(mode="after")
    def _summary_metrics_match_counts(self) -> RunOutcomeSummary:
        if self.abstention_count > self.example_count or self.invalid_reference_count > self.example_count:
            raise ValueError("outcome counts cannot exceed example_count")
        if tuple(r.label for r in self.per_class) != self.labels:
            raise ValueError("per-class reports must exactly match declared labels")
        if tuple(row[0] for row in self.binary_confusion) != self.labels:
            raise ValueError("binary confusion must exactly match declared labels")
        expected_binary = tuple((r.label, r.true_positives, r.false_positives, r.false_negatives, r.true_negatives) for r in self.per_class)
        if self.binary_confusion != expected_binary:
            raise ValueError("binary confusion counts must match per-class counts")
        f1_values = []
        recalls = []
        for r in self.per_class:
            denom = r.precision + r.recall
            f1_values.append(2 * r.precision * r.recall / denom if denom else 0.0)
            recalls.append(r.recall)
        macro_f1 = sum(f1_values) / len(f1_values) if f1_values else 0.0
        balanced_accuracy = sum(recalls) / len(recalls) if recalls else 0.0
        coverage = (self.example_count - self.abstention_count) / self.example_count if self.example_count else 0.0
        abstention_rate = self.abstention_count / self.example_count if self.example_count else 0.0
        invalid_rate = self.invalid_reference_count / self.example_count if self.example_count else 0.0
        for actual, expected, name in ((self.macro_f1, macro_f1, "macro_f1"), (self.balanced_accuracy, balanced_accuracy, "balanced_accuracy"), (self.coverage, coverage, "coverage"), (self.abstention_rate, abstention_rate, "abstention_rate"), (self.invalid_evidence_reference_rate, invalid_rate, "invalid-reference rate")):
            if not _metrics_close(actual, expected):
                raise ValueError(f"{name} must match recorded sufficient counts")
        for r in self.per_class:
            if r.true_positives + r.false_negatives > self.example_count or r.true_positives + r.false_positives > self.example_count:
                raise ValueError("per-class counts exceed example_count")
            if r.true_positives + r.false_negatives + r.true_negatives + r.false_positives != self.example_count:
                raise ValueError("binary confusion counts must account for every example")
        return self


def threshold_violated(threshold: EvaluationMetricThreshold, value: float) -> bool:
    """Evaluate every declared bound; neither bound is ever skipped."""
    if threshold.minimum is not None and value < threshold.minimum:
        return True
    return threshold.maximum is not None and value > threshold.maximum


_METRIC_FIELDS: dict[EvaluationMetricKind, str] = {
    EvaluationMetricKind.MACRO_F1: "macro_f1",
    EvaluationMetricKind.BALANCED_ACCURACY: "balanced_accuracy",
    EvaluationMetricKind.COVERAGE: "coverage",
    EvaluationMetricKind.ABSTENTION_RATE: "abstention_rate",
    EvaluationMetricKind.INVALID_EVIDENCE_REFERENCE_RATE: (
        "invalid_evidence_reference_rate"
    ),
    EvaluationMetricKind.PER_CLASS_PRECISION: "per_class",
    EvaluationMetricKind.PER_CLASS_RECALL: "per_class",
    EvaluationMetricKind.LATENCY_MS: "latency_ms_max",
}


def metric_value(
    metric_kind: EvaluationMetricKind, outcome: RunOutcomeSummary
) -> float:
    """Read the scalar for one metric kind from an outcome summary."""
    if metric_kind in (
        EvaluationMetricKind.PER_CLASS_PRECISION,
        EvaluationMetricKind.PER_CLASS_RECALL,
    ):
        # Class-floor over the declared per-class reports.
        values = [
            (
                report.precision
                if metric_kind == EvaluationMetricKind.PER_CLASS_PRECISION
                else report.recall
            )
            for report in outcome.per_class
        ]
        return min(values) if values else 0.0
    field_name = _METRIC_FIELDS[metric_kind]
    value = getattr(outcome, field_name)
    return float(value) if value is not None else 0.0


def observed_metric_value(
    metric_kind: EvaluationMetricKind, outcome: RunOutcomeSummary
) -> float | None:
    """Observed value for a gate; ``None`` when a declared latency is unmeasured."""
    if (
        metric_kind == EvaluationMetricKind.LATENCY_MS
        and outcome.latency_ms_max is None
    ):
        return None
    return metric_value(metric_kind, outcome)


class EvaluationGateResult(BaseModel):
    """One predeclared metric gate: observed candidate value, bounds, verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: EvaluationMetricKind
    observed_value: StrictFloat | None
    minimum: StrictFloat | None = Field(ge=0.0)
    maximum: StrictFloat | None = Field(ge=0.0)
    passed: StrictBool

    @model_validator(mode="after")
    def _bounds_are_a_valid_threshold(self) -> EvaluationGateResult:
        # Reuse the predeclared-threshold rules so a forged gate cannot carry
        # an out-of-range or inverted bound pair.
        EvaluationMetricThreshold(
            metric=self.metric, minimum=self.minimum, maximum=self.maximum
        )
        return self


class EvaluationComparisonReport(BaseModel):
    """Privacy-safe, versioned comparison of baseline vs candidate.

    Every derived field is recomputed from the embedded outcomes and the
    recorded gate results; none of them is trusted as supplied.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["3"]
    run_id: StrictStr = Field(min_length=1, max_length=100)
    task: EvaluationTaskDefinition
    run_configuration_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    metric_configuration: EvaluationMetricConfiguration
    metric_configuration_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_id: StrictStr = Field(min_length=1, max_length=200)
    dataset_snapshot_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_label_cooccurrence_total: StrictInt = Field(ge=0)
    candidate_label_cooccurrence_total: StrictInt = Field(ge=0)
    baseline: RunOutcomeSummary
    candidate: RunOutcomeSummary
    gate_results: tuple[EvaluationGateResult, ...] = Field(min_length=1, max_length=32)
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

    @field_validator("gate_results")
    @classmethod
    def _canonical_gate_results(
        cls, value: tuple[EvaluationGateResult, ...]
    ) -> tuple[EvaluationGateResult, ...]:
        metrics = [gate.metric for gate in value]
        if len(set(metrics)) != len(metrics):
            raise ValueError("gate results must reference each metric at most once")
        if value != tuple(sorted(value, key=lambda gate: gate.metric.value)):
            raise ValueError("gate results must be canonically sorted by metric")
        zero_tolerance = [
            gate
            for gate in value
            if gate.metric == EvaluationMetricKind.INVALID_EVIDENCE_REFERENCE_RATE
        ]
        if len(zero_tolerance) != 1 or zero_tolerance[0].maximum != 0.0:
            raise ValueError(
                "gate results must record the zero-tolerance metric capped at 0.0"
            )
        return value

    @model_validator(mode="after")
    def _derived_fields_match_the_embedded_outcomes(
        self,
    ) -> EvaluationComparisonReport:
        # These totals count diagnostic co-occurrence cells, not examples.
        if self.baseline_label_cooccurrence_total != sum(count for _, _, count in self.baseline.label_cooccurrence_counts):
            raise ValueError("baseline co-occurrence total must equal its diagnostic cell sum")
        if self.candidate_label_cooccurrence_total != sum(count for _, _, count in self.candidate.label_cooccurrence_counts):
            raise ValueError("candidate co-occurrence total must equal its diagnostic cell sum")
        if self.metric_configuration_hash != canonical_metric_configuration_digest(self.metric_configuration):
            raise ValueError("metric configuration identity does not match canonical configuration")
        if self.task.task_id != self.metric_configuration.task_id:
            raise ValueError("task definition and metric configuration identities must match")
        if self.baseline.labels != self.task.labels or self.candidate.labels != self.task.labels:
            raise ValueError("outcome labels must exactly match the evaluated task label space")
        declared = {item.metric: item for item in self.metric_configuration.thresholds}
        recorded = {gate.metric: gate for gate in self.gate_results}
        if set(recorded) != set(declared) or len(recorded) != len(self.gate_results):
            raise ValueError("gate results must exactly match all declared metrics")
        for metric, threshold in declared.items():
            gate = recorded[metric]
            if gate.minimum != threshold.minimum or gate.maximum != threshold.maximum:
                raise ValueError("recorded gate bounds must match declared thresholds")

        # 2. The improvement flag follows the scores, never a supplied Boolean.
        improves = self.candidate.macro_f1 > self.baseline.macro_f1
        if self.candidate_improves_macro_f1 != improves:
            raise ValueError(
                "candidate_improves_macro_f1 must match the embedded macro-F1 scores"
            )

        # 3. Zero-tolerance safety is derived from both embedded systems.
        safety_failure = (
            self.baseline.invalid_evidence_reference_rate > 0.0
            or self.candidate.invalid_evidence_reference_rate > 0.0
        )
        if self.safety_failure != safety_failure:
            raise ValueError(
                "safety_failure must match the embedded invalid-reference rates"
            )

        # 4. Every recorded gate is recomputed from the candidate outcome.
        for gate in self.gate_results:
            observed = observed_metric_value(gate.metric, self.candidate)
            if gate.observed_value != observed:
                raise ValueError(
                    "a gate's observed value must match the candidate outcome"
                )
            threshold = EvaluationMetricThreshold(
                metric=gate.metric, minimum=gate.minimum, maximum=gate.maximum
            )
            should_pass = observed is not None and not threshold_violated(
                threshold, observed
            )
            if gate.passed != should_pass:
                raise ValueError("a gate's verdict must match its bounds")

        # 5. Acceptance is the conjunction of its recorded parts, nothing else.
        if self.safety_failure and self.accepted:
            raise ValueError("a safety failure can never be accepted")
        if self.accepted and not self.candidate_improves_macro_f1:
            raise ValueError(
                "acceptance requires the candidate to improve the predeclared metric"
            )
        expected_accepted = (
            not safety_failure
            and improves
            and all(gate.passed for gate in self.gate_results)
        )
        if self.accepted != expected_accepted:
            raise ValueError(
                "accepted must equal the safety state, the baseline comparison "
                "and every recorded gate verdict"
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


def canonical_metric_configuration_digest(configuration: EvaluationMetricConfiguration) -> str:
    """SHA-256 of the canonical, predeclared metric configuration."""
    import hashlib
    import json

    payload = json.dumps(configuration.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
