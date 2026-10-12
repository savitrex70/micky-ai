"""Task 206: reproducible baseline evaluation harness.

Compares the deterministic baseline with any future candidate on the
same examples and splits, under a predeclared metric configuration.
Thresholds are set before examining held-out outcomes; the harness
records the configuration hash so tuning cannot be silently rebranded
as independent evaluation. No model training, no network, no external
datasets.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from rop.schemas.evaluation_harness import (
    EVALUATION_CONTRACT_VERSION,
    ZERO_TOLERANCE_METRIC,
    CandidatePrediction,
    EvaluationComparisonReport,
    EvaluationHarnessError,
    EvaluationManifestEntry,
    EvaluationMetricKind,
    EvaluationMetricThreshold,
    EvaluationRunConfiguration,
    EvaluationSplit,
    EvaluationSplitManifest,
    RunOutcomeSummary,
    canonical_examples_digest,
)


@dataclass(frozen=True)
class _Counters:
    true_positives: int
    false_positives: int
    false_negatives: int


def assign_splits_deterministically(
    *,
    example_ids: tuple[str, ...],
    train_ratio: float,
    validation_ratio: float,
) -> tuple[EvaluationManifestEntry, ...]:
    """Bind example IDs to splits with a stable hash, never an RNG.

    Returns validated ``EvaluationManifestEntry`` objects (not a complete
    ``EvaluationSplitManifest``), ordered canonically by ``(split,
    example_id)`` so they can be placed in a manifest directly. Each entry
    carries empty ``expected_labels``; the caller must supply ground truth
    (for example via ``entry.model_copy(update={"expected_labels": ...})``)
    and the dataset identity and snapshot hash this function does not know.

    The assignment is a pure function of the example identifier, so any
    later re-run reproduces the exact same partition. Duplicate example
    IDs are rejected because they would silently collapse into one example.
    """
    import hashlib

    if not 0.0 < train_ratio < 1.0:
        raise EvaluationHarnessError(
            "SPLIT_RATIO_INVALID", "train_ratio must be in (0,1)"
        )
    if not 0.0 <= validation_ratio < 1.0 or train_ratio + validation_ratio >= 1.0:
        raise EvaluationHarnessError(
            "SPLIT_RATIO_INVALID", "train+validation must stay below 1"
        )
    if len(set(example_ids)) != len(example_ids):
        raise EvaluationHarnessError(
            "DUPLICATE_EXAMPLE_ID", "example identifiers must be unique"
        )

    entries: list[EvaluationManifestEntry] = []
    entry_invalid = False
    for example_id in example_ids:
        digest = hashlib.sha256(example_id.encode("utf-8")).hexdigest()
        # First 16 hex digits mod 10^16 / 10^16 in [0,1)
        position = int(digest[:16], 16) / float(16**16)
        if position < train_ratio:
            split = EvaluationSplit.TRAIN
        elif position < train_ratio + validation_ratio:
            split = EvaluationSplit.VALIDATION
        else:
            split = EvaluationSplit.TEST
        try:
            entries.append(
                EvaluationManifestEntry(
                    example_id=example_id, split=split, expected_labels=()
                )
            )
        except ValidationError:
            entry_invalid = True
            break
    if entry_invalid:
        # Raised outside the handler so the original text (which could echo
        # the identifier) is neither chained nor surfaced.
        raise EvaluationHarnessError(
            "EXAMPLE_ID_INVALID", "an example identifier is not a valid identifier"
        )
    return tuple(sorted(entries, key=lambda e: (e.split.value, e.example_id)))


def _label_counters(
    expected: frozenset[str],
    predicted: frozenset[str],
    label: str,
) -> _Counters:
    return _Counters(
        true_positives=int(label in expected and label in predicted),
        false_positives=int(label not in expected and label in predicted),
        false_negatives=int(label in expected and label not in predicted),
    )


def _validate_ground_truth(
    manifest: EvaluationSplitManifest, labels: tuple[str, ...]
) -> None:
    """Reject ground truth outside the declared label space; never trim it."""
    label_space = frozenset(labels)
    for entry in manifest.entries:
        if not frozenset(entry.expected_labels) <= label_space:
            raise EvaluationHarnessError(
                "GROUND_TRUTH_LABEL_UNKNOWN",
                "ground truth uses labels outside the declared task labels",
            )


def _validate_class_counts(
    manifest: EvaluationSplitManifest,
    labels: tuple[str, ...],
    minimum_examples_per_class: int,
) -> None:
    """Enforce the predeclared per-class minimum on the evaluated split."""
    for label in labels:
        count = sum(1 for entry in manifest.entries if label in entry.expected_labels)
        if count < minimum_examples_per_class:
            raise EvaluationHarnessError(
                "CLASS_COUNT_INSUFFICIENT",
                "the evaluated split does not meet the predeclared minimum "
                "examples per class",
            )


def evaluate_predictions(
    *,
    manifest: EvaluationSplitManifest,
    predictions: tuple[CandidatePrediction, ...],
    labels: tuple[str, ...],
    system_id: str,
) -> RunOutcomeSummary:
    """Score one system's predictions against one split's expected labels.

    Deterministic, side-effect free, and privacy safe: only canonical
    identifiers and aggregate counts leave the function.
    """
    from collections import Counter

    manifest_by_id = {entry.example_id: entry for entry in manifest.entries}
    prediction_by_id = {prediction.example_id: prediction for prediction in predictions}
    if len(prediction_by_id) != len(predictions):
        raise EvaluationHarnessError(
            "DUPLICATE_PREDICTIONS", "a prediction must not repeat an example"
        )

    unknown = set(prediction_by_id) - set(manifest_by_id)
    if unknown:
        raise EvaluationHarnessError(
            "UNKNOWN_EXAMPLE", "predictions reference examples outside the manifest"
        )

    expected_label_set = frozenset(labels)
    _validate_ground_truth(manifest, labels)
    tp_fp_fn: dict[str, _Counters] = {}
    confusion_counts: Counter[tuple[str, str]] = Counter()
    example_count = 0
    abstentions = 0
    invalid_references = 0
    latency_max: float | None = None

    def add_counts(label: str, counters: _Counters) -> None:
        previous = tp_fp_fn.get(label, _Counters(0, 0, 0))
        tp_fp_fn[label] = _Counters(
            previous.true_positives + counters.true_positives,
            previous.false_positives + counters.false_positives,
            previous.false_negatives + counters.false_negatives,
        )

    def record_abstention(expected: tuple[str, ...]) -> None:
        for expected_label in expected:
            confusion_counts[(expected_label, "<ABSTAIN>")] += 1
            add_counts(expected_label, _Counters(0, 0, 1))

    for example_id, entry in sorted(manifest_by_id.items()):
        example_count += 1
        prediction = prediction_by_id.get(example_id)
        if prediction is None:
            # Missing predictions are abstentions, never silent passes.
            abstentions += 1
            record_abstention(entry.expected_labels)
            continue

        # Safety first: an invalid reference is counted once per example
        # before any abstention fast path can skip it.
        if prediction.invalid or any(
            predicted_label not in expected_label_set
            for predicted_label in prediction.predicted_labels
        ):
            # An out-of-label-space prediction is itself a detached
            # reference; counted once per example, never double counted.
            invalid_references += 1

        if prediction.abstained:
            abstentions += 1
            record_abstention(entry.expected_labels)
            continue

        # Every cell below is derived from this example's own label sets.
        predicted_set = frozenset(prediction.predicted_labels) & expected_label_set
        expected_set = frozenset(entry.expected_labels)

        for label in sorted(expected_set | predicted_set):
            add_counts(label, _label_counters(expected_set, predicted_set, label))
        for expected_label in sorted(expected_set):
            if predicted_set:
                for predicted_label in sorted(predicted_set):
                    confusion_counts[(expected_label, predicted_label)] += 1
            else:
                confusion_counts[(expected_label, "<NONE>")] += 1
        if not expected_set:
            # False positives on an example with no expected labels.
            for predicted_label in sorted(predicted_set):
                confusion_counts[("<none>", predicted_label)] += 1
        if prediction.latency_ms is not None:
            latency_max = max(latency_max or 0.0, prediction.latency_ms)

    per_class = []
    f1_scores: list[float] = []
    recalls: list[float] = []
    for label in sorted(labels):
        counts = tp_fp_fn.get(label, _Counters(0, 0, 0))
        precision = (
            counts.true_positives / (counts.true_positives + counts.false_positives)
            if (counts.true_positives + counts.false_positives) > 0
            else 0.0
        )
        recall = (
            counts.true_positives / (counts.true_positives + counts.false_negatives)
            if (counts.true_positives + counts.false_negatives) > 0
            else 0.0
        )
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        f1_scores.append(f1)
        recalls.append(recall)
        per_class.append(
            {
                "label": label,
                "true_positives": counts.true_positives,
                "false_positives": counts.false_positives,
                "false_negatives": counts.false_negatives,
                "precision": precision,
                "recall": recall,
            }
        )

    macro_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0.0
    balanced_accuracy = sum(recalls) / len(recalls) if recalls else 0.0
    coverage = (example_count - abstentions) / example_count if example_count else 0.0
    abstention_rate = abstentions / example_count if example_count else 0.0
    invalid_rate = invalid_references / example_count if example_count else 0.0

    return RunOutcomeSummary.model_validate(
        {
            "system_id": system_id,
            "macro_f1": macro_f1,
            "balanced_accuracy": balanced_accuracy,
            "coverage": coverage,
            "abstention_rate": abstention_rate,
            "invalid_evidence_reference_rate": invalid_rate,
            "example_count": example_count,
            "per_class": per_class,
            "confusion_matrix": tuple(
                sorted(
                    (expected, predicted, count)
                    for (expected, predicted), count in confusion_counts.items()
                )
            ),
            "latency_ms_max": latency_max,
        }
    )


def compare_systems(
    *,
    run_configuration: EvaluationRunConfiguration,
    baseline_predictions: tuple[CandidatePrediction, ...],
    candidate_predictions: tuple[CandidatePrediction, ...],
    baseline_system_id: str = "deterministic-baseline",
    candidate_system_id: str = "candidate",
    limitations: tuple[str, ...] = (
        "Synthetic fixture demonstration; no authorized real dataset.",
        "Candidate system is untested placeholder output; "
        "comparison is mechanical only.",
    ),
) -> EvaluationComparisonReport:
    """Compare two systems under the predeclared configuration.

    ``accepted`` is computed strictly from the predeclared thresholds
    and zero-tolerance safety requirements on the candidate. A safety
    failure can never be repaired post hoc by a better F1.
    """
    full_manifest = run_configuration.split_manifest
    labels = run_configuration.task.labels

    # Split binding: only the explicitly declared evaluated splits may be
    # scored; TEST is never read for tuning, only for the final gate.
    evaluated_entries = tuple(
        entry
        for split in run_configuration.evaluated_splits
        for entry in full_manifest.examples_for(split)
    )
    if not evaluated_entries:
        raise EvaluationHarnessError(
            "EVALUATED_SPLIT_EMPTY", "the declared evaluated splits hold no examples"
        )
    manifest = EvaluationSplitManifest.model_validate(
        {
            "contract_version": "1",
            "dataset_id": full_manifest.dataset_id,
            "dataset_snapshot_hash": full_manifest.dataset_snapshot_hash,
            "task_id": full_manifest.task_id,
            "entries": evaluated_entries,
        }
    )

    # Predeclared requirements fail closed before any outcome is computed.
    _validate_ground_truth(manifest, labels)
    _validate_class_counts(
        manifest,
        labels,
        run_configuration.metric_configuration.minimum_examples_per_class,
    )

    baseline_outcome = evaluate_predictions(
        manifest=manifest,
        predictions=baseline_predictions,
        labels=labels,
        system_id=baseline_system_id,
    )
    candidate_outcome = evaluate_predictions(
        manifest=manifest,
        predictions=candidate_predictions,
        labels=labels,
        system_id=candidate_system_id,
    )

    thresholds = {
        threshold.metric: threshold
        for threshold in run_configuration.metric_configuration.thresholds
    }

    # Zero-tolerance safety gate: evaluated first, regardless of quality.
    # An invalid reference in the baseline or the candidate run fails it.
    safety_failure = (
        baseline_outcome.invalid_evidence_reference_rate > 0.0
        or candidate_outcome.invalid_evidence_reference_rate > 0.0
    )

    metric_failures: list[str] = []
    for metric_kind, threshold in thresholds.items():
        if metric_kind == EvaluationMetricKind.INVALID_EVIDENCE_REFERENCE_RATE:
            continue  # already enforced by the zero-tolerance gate
        if (
            metric_kind == EvaluationMetricKind.LATENCY_MS
            and candidate_outcome.latency_ms_max is None
        ):
            # A declared latency bound cannot be verified without a
            # measurement, so it fails closed instead of passing silently.
            metric_failures.append(metric_kind.value)
            continue
        value = _metric_value(metric_kind, candidate_outcome)
        if _threshold_violated(threshold, value):
            metric_failures.append(metric_kind.value)

    improves = candidate_outcome.macro_f1 > baseline_outcome.macro_f1
    safety_configuration = thresholds[
        EvaluationMetricKind.INVALID_EVIDENCE_REFERENCE_RATE
    ]
    safety_cap_is_zero = safety_configuration.maximum == 0.0
    if not safety_cap_is_zero:
        raise EvaluationHarnessError(
            "SAFETY_MISCONFIGURED", "the zero-tolerance cap must be exactly 0.0"
        )

    accepted = not safety_failure and not metric_failures and improves

    return EvaluationComparisonReport.model_validate(
        {
            "contract_version": EVALUATION_CONTRACT_VERSION,
            "run_id": run_configuration.run_id,
            "run_configuration_hash": canonical_examples_digest(run_configuration),
            "dataset_id": manifest.dataset_id,
            "dataset_snapshot_hash": manifest.dataset_snapshot_hash,
            "confusion_matrix_scalar": sum(
                count for _, _, count in baseline_outcome.confusion_matrix
            ),
            "baseline": baseline_outcome.model_dump(),
            "candidate": candidate_outcome.model_dump(),
            "candidate_improves_macro_f1": improves,
            "safety_failure": safety_failure,
            "accepted": accepted,
            "limitations": sorted(limitations),
        }
    )


def _threshold_violated(threshold: EvaluationMetricThreshold, value: float) -> bool:
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


def _metric_value(
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


__all__ = [
    "ZERO_TOLERANCE_METRIC",
    "assign_splits_deterministically",
    "compare_systems",
    "evaluate_predictions",
]
