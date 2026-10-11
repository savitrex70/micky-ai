"""Task 206 baseline evaluation-harness tests; no model, network, or dataset."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rop.evaluation import (
    _metric_value,
    assign_splits_deterministically,
    compare_systems,
    evaluate_predictions,
)
from rop.schemas.evaluation_harness import (
    CandidatePrediction,
    EvaluationHarnessError,
    EvaluationMetricConfiguration,
    EvaluationMetricKind,
    EvaluationRunConfiguration,
    EvaluationSplit,
    EvaluationSplitManifest,
    EvaluationTaskDefinition,
    EvaluationTaskKind,
    reject_tuning_references,
)

LABELS = ("ANION_GAP_HIGH", "POTASSIUM_HIGH")
TASK_ID = "task-labtag-1"
DATASET_ID = "synthetic-lab-tag-fixtures"

# Predeclared before any outcome: macro-F1 >= 0.5, abstention <= 0.5,
# invalid-reference rate == 0 (zero tolerance).


def _metric_configuration() -> dict:
    return {
        "contract_version": "1",
        "configuration_id": "metric-conf-1",
        "task_id": TASK_ID,
        "thresholds": [
            {
                "metric": EvaluationMetricKind.ABSTENTION_RATE,
                "minimum": 0.0,
                "maximum": 0.5,
            },
            {
                "metric": EvaluationMetricKind.INVALID_EVIDENCE_REFERENCE_RATE,
                "minimum": 0.0,
                "maximum": 0.0,
            },
            {
                "metric": EvaluationMetricKind.MACRO_F1,
                "minimum": 0.5,
                "maximum": 1.0,
            },
        ],
        "minimum_examples_per_class": 2,
    }


def _task() -> EvaluationTaskDefinition:
    return EvaluationTaskDefinition.model_validate(
        {
            "contract_version": "1",
            "task_id": TASK_ID,
            "task_kind": EvaluationTaskKind.TAG_CLASSIFICATION,
            "labels": sorted(LABELS),
            "description": "Tag a lab observation with its bounded category.",
        }
    )


def _split_manifest(
    entries: list[tuple[str, str, list[str]]]
) -> EvaluationSplitManifest:
    return EvaluationSplitManifest.model_validate(
        {
            "contract_version": "1",
            "dataset_id": DATASET_ID,
            "dataset_snapshot_hash": "c" * 64,
            "task_id": TASK_ID,
            "entries": [
                {
                    "example_id": example_id,
                    "split": split,
                    "expected_labels": sorted(expected),
                }
                for example_id, split, expected in entries
            ],
        }
    )


def _run_configuration(
    manifest: EvaluationSplitManifest,
    evaluated_splits: tuple[EvaluationSplit, ...] = (EvaluationSplit.TEST,),
) -> EvaluationRunConfiguration:
    return EvaluationRunConfiguration.model_validate(
        {
            "contract_version": "1",
            "run_id": "run-1",
            "task": _task().model_dump(mode="json"),
            "metric_configuration": _metric_configuration(),
            "split_manifest": manifest.model_dump(mode="json"),
            "evaluated_splits": evaluated_splits,
        }
    )


def _manifest() -> EvaluationSplitManifest:
    return _split_manifest(
        [
            ("example-1", "TEST", ["ANION_GAP_HIGH"]),
            ("example-2", "TEST", ["POTASSIUM_HIGH"]),
            ("example-3", "TEST", ["ANION_GAP_HIGH"]),
            ("example-4", "TEST", ["POTASSIUM_HIGH"]),
        ]
    )


def _prediction(
    example_id: str, labels: list[str], **patch: object
) -> CandidatePrediction:
    value = {
        "example_id": example_id,
        "predicted_labels": sorted(labels),
        "abstained": False,
        "latency_ms": 1.0,
    }
    value.update(patch)
    return CandidatePrediction.model_validate(value)


# --- split assignment -----------------------------------------------------


def test_split_assignment_is_deterministic_and_repeatable() -> None:
    ids = tuple(f"example-{i}" for i in range(50))
    first = assign_splits_deterministically(
        example_ids=ids, train_ratio=0.6, validation_ratio=0.2
    )
    second = assign_splits_deterministically(
        example_ids=ids, train_ratio=0.6, validation_ratio=0.2
    )
    assert first == second


def test_split_assignment_rejects_impossible_ratios() -> None:
    with pytest.raises(EvaluationHarnessError):
        assign_splits_deterministically(
            example_ids=("a",), train_ratio=1.5, validation_ratio=0.2
        )
    with pytest.raises(EvaluationHarnessError):
        assign_splits_deterministically(
            example_ids=("a",), train_ratio=0.9, validation_ratio=0.2
        )


def test_split_assignment_uses_every_partition() -> None:
    entries = assign_splits_deterministically(
        example_ids=tuple(f"example-{i}" for i in range(200)),
        train_ratio=0.5,
        validation_ratio=0.25,
    )
    splits = {entry["split"] for entry in entries}
    assert splits == {
        EvaluationSplit.TRAIN,
        EvaluationSplit.VALIDATION,
        EvaluationSplit.TEST,
    }


# --- metric configuration --------------------------------------------------


def test_metric_configuration_requires_the_zero_tolerance_metric() -> None:
    configuration = _metric_configuration()
    configuration["thresholds"] = [
        threshold
        for threshold in configuration["thresholds"]
        if threshold["metric"] != EvaluationMetricKind.INVALID_EVIDENCE_REFERENCE_RATE
    ]
    with pytest.raises(ValidationError, match="zero-tolerance"):
        EvaluationMetricConfiguration.model_validate(configuration)


def test_zero_tolerance_metric_must_cap_at_zero() -> None:
    configuration = _metric_configuration()
    for threshold in configuration["thresholds"]:
        if threshold["metric"] == EvaluationMetricKind.INVALID_EVIDENCE_REFERENCE_RATE:
            threshold["maximum"] = 0.05
    with pytest.raises(ValidationError, match="capped at 0.0"):
        EvaluationMetricConfiguration.model_validate(configuration)


def test_thresholds_must_be_canonically_sorted_and_unique() -> None:
    configuration = _metric_configuration()
    configuration["thresholds"] = list(reversed(configuration["thresholds"]))
    with pytest.raises(ValidationError, match="sorted"):
        import rop.schemas.evaluation_harness as schemas

        schemas.EvaluationMetricConfiguration.model_validate(configuration)


# --- evaluation mechanics ---------------------------------------------------


def test_perfect_predictions_score_full_metrics() -> None:
    manifest = _manifest()
    predictions = tuple(
        _prediction(example_id, expected)
        for example_id, expected in [
            ("example-1", ["ANION_GAP_HIGH"]),
            ("example-2", ["POTASSIUM_HIGH"]),
            ("example-3", ["ANION_GAP_HIGH"]),
            ("example-4", ["POTASSIUM_HIGH"]),
        ]
    )
    outcome = evaluate_predictions(
        manifest=manifest, predictions=predictions, labels=LABELS, system_id="baseline"
    )
    assert outcome.macro_f1 == 1.0
    assert outcome.balanced_accuracy == 1.0
    assert outcome.coverage == 1.0
    assert outcome.abstention_rate == 0.0
    assert outcome.invalid_evidence_reference_rate == 0.0


def test_missing_predictions_count_as_abstentions_not_passes() -> None:
    manifest = _manifest()
    predictions = (_prediction("example-1", ["ANION_GAP_HIGH"]),)
    outcome = evaluate_predictions(
        manifest=manifest, predictions=predictions, labels=LABELS, system_id="baseline"
    )
    assert outcome.abstention_rate == 0.75
    assert outcome.coverage == 0.25
    assert outcome.macro_f1 < 1.0


def test_invalid_evidence_references_are_counted_and_gated() -> None:
    manifest = _manifest()
    predictions = (
        _prediction("example-1", ["ANION_GAP_HIGH"]),
        _prediction("example-2", ["NOT_A_LABEL"], invalid=True),
        _prediction("example-3", ["ANION_GAP_HIGH"]),
        _prediction("example-4", ["POTASSIUM_HIGH"]),
    )
    outcome = evaluate_predictions(
        manifest=manifest, predictions=predictions, labels=LABELS, system_id="candidate"
    )
    assert outcome.invalid_evidence_reference_rate == 0.25


def test_duplicate_predictions_are_rejected() -> None:
    manifest = _manifest()
    with pytest.raises(EvaluationHarnessError, match="repeat"):
        evaluate_predictions(
            manifest=manifest,
            predictions=(
                _prediction("example-1", ["ANION_GAP_HIGH"]),
                _prediction("example-1", ["POTASSIUM_HIGH"]),
            ),
            labels=LABELS,
            system_id="baseline",
        )


def test_predictions_outside_the_manifest_are_rejected() -> None:
    manifest = _manifest()
    with pytest.raises(EvaluationHarnessError, match="outside"):
        evaluate_predictions(
            manifest=manifest,
            predictions=(_prediction("example-999", ["ANION_GAP_HIGH"]),),
            labels=LABELS,
            system_id="baseline",
        )


# --- comparison report ------------------------------------------------------


def test_candidate_that_improves_baseline_is_accepted() -> None:
    manifest = _manifest()
    baseline = tuple(
        _prediction(example_id, [])  # baseline predicts nothing
        for example_id, _ in [
            ("example-1", None),
            ("example-2", None),
            ("example-3", None),
            ("example-4", None),
        ]
    )
    candidate = (
        _prediction("example-1", ["ANION_GAP_HIGH"]),
        _prediction("example-2", ["POTASSIUM_HIGH"]),
        _prediction("example-3", ["ANION_GAP_HIGH"]),
        _prediction("example-4", ["POTASSIUM_HIGH"]),
    )
    report = compare_systems(
        run_configuration=_run_configuration(manifest),
        baseline_predictions=baseline,
        candidate_predictions=candidate,
    )
    assert report.candidate_improves_macro_f1 is True
    assert report.safety_failure is False
    assert report.accepted is True
    assert any("Synthetic fixture demonstration" in item for item in report.limitations)
    assert any(
        "Candidate system is untested placeholder output" in item
        for item in report.limitations
    )


def test_safety_failure_is_never_accepted_even_with_perfect_metrics() -> None:
    manifest = _manifest()
    baseline = tuple(
        _prediction(example_id, [])
        for example_id, _ in [
            ("example-1", None),
            ("example-2", None),
            ("example-3", None),
            ("example-4", None),
        ]
    )
    candidate = (
        _prediction("example-1", ["ANION_GAP_HIGH"], invalid=True),
        _prediction("example-2", ["POTASSIUM_HIGH"]),
        _prediction("example-3", ["ANION_GAP_HIGH"]),
        _prediction("example-4", ["POTASSIUM_HIGH"]),
    )
    report = compare_systems(
        run_configuration=_run_configuration(manifest),
        baseline_predictions=baseline,
        candidate_predictions=candidate,
    )
    assert report.safety_failure is True
    assert report.accepted is False


def test_candidate_that_loses_to_baseline_is_not_accepted() -> None:
    manifest = _manifest()
    baseline = (
        _prediction("example-1", ["ANION_GAP_HIGH"]),
        _prediction("example-2", ["POTASSIUM_HIGH"]),
        _prediction("example-3", ["ANION_GAP_HIGH"]),
        _prediction("example-4", ["POTASSIUM_HIGH"]),
    )
    candidate = tuple(
        _prediction(example_id, [])
        for example_id, _ in [
            ("example-1", None),
            ("example-2", None),
            ("example-3", None),
            ("example-4", None),
        ]
    )
    report = compare_systems(
        run_configuration=_run_configuration(manifest),
        baseline_predictions=baseline,
        candidate_predictions=candidate,
    )
    assert report.candidate_improves_macro_f1 is False
    assert report.accepted is False


def test_report_rejects_a_safety_failure_marked_accepted() -> None:
    baseline = evaluate_predictions(
        manifest=_manifest(),
        predictions=(),
        labels=LABELS,
        system_id="baseline",
    )
    candidate_payload = baseline.model_dump(mode="json")
    candidate_payload["system_id"] = "candidate"
    candidate_payload["invalid_evidence_reference_rate"] = 0.5
    with pytest.raises(ValidationError, match="safety failure"):
        import rop.schemas.evaluation_harness as schemas

        schemas.EvaluationComparisonReport.model_validate(
            {
                "contract_version": "1",
                "run_id": "run-1",
                "run_configuration_hash": "a" * 64,
                "dataset_id": DATASET_ID,
                "dataset_snapshot_hash": "c" * 64,
                "confusion_matrix_scalar": 0,
                "baseline": baseline.model_dump(mode="json"),
                "candidate": candidate_payload,
                "candidate_improves_macro_f1": True,
                "safety_failure": True,
                "accepted": True,
                "limitations": [],
            }
        )


def test_report_requires_improvement_for_acceptance() -> None:
    baseline = evaluate_predictions(
        manifest=_manifest(), predictions=(), labels=LABELS, system_id="baseline"
    )
    payload = baseline.model_dump(mode="json")
    with pytest.raises(ValidationError, match="improve"):
        import rop.schemas.evaluation_harness as schemas

        schemas.EvaluationComparisonReport.model_validate(
            {
                "contract_version": "1",
                "run_id": "run-1",
                "run_configuration_hash": "a" * 64,
                "dataset_id": DATASET_ID,
                "dataset_snapshot_hash": "c" * 64,
                "confusion_matrix_scalar": 0,
                "baseline": payload,
                "candidate": payload,
                "candidate_improves_macro_f1": False,
                "safety_failure": False,
                "accepted": True,
                "limitations": [],
            }
        )


# --- reproducibility --------------------------------------------------------


def test_run_configuration_hash_is_stable_and_sensitive_to_inputs() -> None:
    from rop.schemas.evaluation_harness import canonical_examples_digest

    first = canonical_examples_digest(_run_configuration(_manifest()))
    second = canonical_examples_digest(_run_configuration(_manifest()))
    assert first == second
    third = canonical_examples_digest(
        _run_configuration(
            _split_manifest(
                [
                    ("example-1", "TRAIN", ["ANION_GAP_HIGH"]),
                    ("example-2", "TRAIN", ["POTASSIUM_HIGH"]),
                    ("example-3", "TRAIN", ["ANION_GAP_HIGH"]),
                    ("example-4", "TRAIN", ["POTASSIUM_HIGH"]),
                ]
            )
        )
    )
    assert first != third


def test_rejected_tuning_keys_fail_closed() -> None:
    with pytest.raises(EvaluationHarnessError, match="TUNING_STATE_REJECTED"):
        reject_tuning_references({"threshold_override": 0.9})


def test_split_partition_list_is_deterministic() -> None:
    manifest = _manifest()
    entries = manifest.examples_for(EvaluationSplit.TEST)
    assert tuple(entry.example_id for entry in entries) == (
        "example-1",
        "example-2",
        "example-3",
        "example-4",
    )


def test_metric_value_helper_maps_every_metric_kind() -> None:
    manifest = _manifest()
    outcome = evaluate_predictions(
        manifest=manifest,
        predictions=(
            _prediction("example-1", ["ANION_GAP_HIGH"]),
            _prediction("example-2", ["POTASSIUM_HIGH"]),
            _prediction("example-3", ["ANION_GAP_HIGH"]),
            _prediction("example-4", ["POTASSIUM_HIGH"]),
        ),
        labels=LABELS,
        system_id="baseline",
    )
    assert _metric_value(EvaluationMetricKind.MACRO_F1, outcome) == 1.0
    assert _metric_value(EvaluationMetricKind.COVERAGE, outcome) == 1.0
    assert (
        _metric_value(EvaluationMetricKind.INVALID_EVIDENCE_REFERENCE_RATE, outcome)
        == 0.0
    )
