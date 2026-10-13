"""Task 206 baseline evaluation-harness tests; no model, network, or dataset."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rop.evaluation import (
    _metric_value,
    _threshold_violated,
    assign_splits_deterministically,
    compare_systems,
    evaluate_predictions,
)
from rop.schemas.evaluation_harness import (
    EVALUATION_REPORT_CONTRACT_VERSION,
    MAX_LATENCY_THRESHOLD_MS,
    CandidatePrediction,
    EvaluationComparisonReport,
    EvaluationHarnessError,
    EvaluationManifestEntry,
    EvaluationMetricConfiguration,
    EvaluationMetricKind,
    EvaluationMetricThreshold,
    EvaluationRunConfiguration,
    EvaluationSplit,
    EvaluationSplitManifest,
    EvaluationTaskDefinition,
    EvaluationTaskKind,
    canonical_examples_digest,
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
    entries: list[tuple[str, str, list[str]]],
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
    splits = {entry.split for entry in entries}
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


def _report_payload(*, accepted: bool) -> dict:
    """A genuine report payload from the harness, ready to be forged."""
    candidate = _perfect() if accepted else _empty_baseline()
    report = compare_systems(
        run_configuration=_run_configuration(_manifest()),
        baseline_predictions=_empty_baseline(),
        candidate_predictions=candidate,
    )
    assert report.accepted is accepted
    return report.model_dump(mode="json")


def _forged(payload: dict, **patch: object) -> EvaluationComparisonReport:
    return EvaluationComparisonReport.model_validate({**payload, **patch})


def test_genuine_accepted_and_rejected_reports_round_trip() -> None:
    accepted = _report_payload(accepted=True)
    rejected = _report_payload(accepted=False)
    accepted_report = EvaluationComparisonReport.model_validate(accepted)
    rejected_report = EvaluationComparisonReport.model_validate(rejected)
    assert accepted_report.accepted is True
    assert rejected_report.accepted is False
    assert accepted["contract_version"] == EVALUATION_REPORT_CONTRACT_VERSION
    assert (
        accepted_report.run_configuration_hash
        == canonical_examples_digest(accepted_report.run_configuration)
    )
    assert accepted_report.model_dump(mode="json") == accepted


def test_report_rejects_the_previous_contract_version() -> None:
    with pytest.raises(ValidationError):
        _forged(_report_payload(accepted=True), contract_version="1")


def test_report_rejects_a_safety_failure_marked_accepted() -> None:
    payload = _report_payload(accepted=True)
    payload["candidate"]["invalid_evidence_reference_rate"] = 0.5
    safety = next(
        g
        for g in payload["gate_results"]
        if g["metric"] == "INVALID_EVIDENCE_REFERENCE_RATE"
    )
    safety["observed_value"] = 0.5
    safety["passed"] = False
    with pytest.raises(ValidationError, match="safety failure can never"):
        _forged(payload, safety_failure=True, accepted=True)


def test_report_requires_improvement_for_acceptance() -> None:
    payload = _report_payload(accepted=False)
    with pytest.raises(ValidationError, match="improve"):
        _forged(payload, accepted=True)


def test_forged_improvement_flag_is_rejected_in_both_directions() -> None:
    accepted = _report_payload(accepted=True)
    with pytest.raises(ValidationError, match="macro-F1"):
        _forged(accepted, candidate_improves_macro_f1=False, accepted=False)
    rejected = _report_payload(accepted=False)
    with pytest.raises(ValidationError, match="macro-F1"):
        _forged(rejected, candidate_improves_macro_f1=True)


def test_forged_improvement_flag_against_swapped_scores_is_rejected() -> None:
    payload = _report_payload(accepted=True)
    payload["baseline"], payload["candidate"] = (
        payload["candidate"],
        payload["baseline"],
    )
    # The flag still claims an improvement, but the scores now say otherwise.
    with pytest.raises(ValidationError, match="macro-F1"):
        EvaluationComparisonReport.model_validate(payload)


@pytest.mark.parametrize("system", ["baseline", "candidate"])
def test_misstated_safety_flag_is_rejected_in_both_directions(system: str) -> None:
    payload = _report_payload(accepted=True)
    # Claim a clean run while an embedded system has an invalid reference.
    payload[system]["invalid_evidence_reference_rate"] = 0.25
    with pytest.raises(ValidationError, match="safety_failure"):
        _forged(payload, safety_failure=False, accepted=False)
    # Claim a safety failure while both embedded systems are clean.
    clean = _report_payload(accepted=True)
    with pytest.raises(ValidationError, match="safety_failure"):
        _forged(clean, safety_failure=True, accepted=False)


def test_acceptance_cannot_be_claimed_while_a_recorded_gate_failed() -> None:
    payload = _report_payload(accepted=True)
    gates = payload["gate_results"]
    macro = next(gate for gate in gates if gate["metric"] == "MACRO_F1")
    # A recorded gate that failed its own bounds: observed below the minimum.
    macro["observed_value"] = 0.25
    macro["passed"] = False
    payload["candidate"]["macro_f1"] = 0.25
    payload["baseline"]["macro_f1"] = 0.0
    with pytest.raises(ValidationError, match="accepted must equal"):
        EvaluationComparisonReport.model_validate(payload)


def test_a_gate_verdict_cannot_contradict_its_own_bounds() -> None:
    payload = _report_payload(accepted=True)
    macro = next(g for g in payload["gate_results"] if g["metric"] == "MACRO_F1")
    macro["minimum"] = 1.0
    macro["maximum"] = 1.0
    macro["observed_value"] = 1.0
    payload["candidate"]["macro_f1"] = 1.0
    assert macro["passed"] is True  # still a consistent pass
    EvaluationComparisonReport.model_validate(payload)
    macro["minimum"] = 0.99
    macro["maximum"] = 0.99
    with pytest.raises(ValidationError, match="verdict"):
        EvaluationComparisonReport.model_validate(payload)


def test_a_gate_observed_value_must_match_the_candidate_outcome() -> None:
    payload = _report_payload(accepted=True)
    macro = next(g for g in payload["gate_results"] if g["metric"] == "MACRO_F1")
    macro["observed_value"] = 0.9
    with pytest.raises(ValidationError, match="observed value"):
        EvaluationComparisonReport.model_validate(payload)


def test_a_rejected_report_cannot_be_flipped_to_accepted_by_its_gates() -> None:
    # Every recorded gate and the comparison pass, so ``accepted=False`` is
    # itself inconsistent: acceptance is derived, not independently chosen.
    payload = _report_payload(accepted=True)
    with pytest.raises(ValidationError, match="accepted must equal"):
        _forged(payload, accepted=False)


def test_gate_results_must_be_unique_canonical_and_record_the_safety_cap() -> None:
    payload = _report_payload(accepted=True)
    gates = payload["gate_results"]
    with pytest.raises(ValidationError, match="canonically sorted"):
        _forged(payload, gate_results=list(reversed(gates)))
    with pytest.raises(ValidationError, match="at most once"):
        _forged(payload, gate_results=[gates[0], gates[0], *gates[1:]])
    without_safety = [
        g for g in gates if g["metric"] != "INVALID_EVIDENCE_REFERENCE_RATE"
    ]
    with pytest.raises(ValidationError, match="zero-tolerance"):
        _forged(payload, gate_results=without_safety)
    loosened = [
        {**g, "maximum": 0.5} if g["metric"] == "INVALID_EVIDENCE_REFERENCE_RATE" else g
        for g in gates
    ]
    with pytest.raises(ValidationError, match="zero-tolerance"):
        _forged(payload, gate_results=loosened)


def test_confusion_totals_are_checked_against_their_own_matrices() -> None:
    payload = _report_payload(accepted=True)
    with pytest.raises(ValidationError, match="baseline confusion total"):
        _forged(
            payload,
            baseline_label_cooccurrence_total=(
                payload["baseline_label_cooccurrence_total"] + 1
            ),
        )
    with pytest.raises(ValidationError, match="candidate confusion total"):
        _forged(
            payload,
            candidate_label_cooccurrence_total=(
                payload["candidate_label_cooccurrence_total"] + 1
            ),
        )
    assert "label_cooccurrence_counts_scalar" not in payload


def test_report_gate_results_cover_every_declared_threshold() -> None:
    payload = _report_payload(accepted=True)
    assert [gate["metric"] for gate in payload["gate_results"]] == [
        "ABSTENTION_RATE",
        "INVALID_EVIDENCE_REFERENCE_RATE",
        "MACRO_F1",
    ]
    assert all(gate["passed"] for gate in payload["gate_results"])


def test_unmeasured_latency_gate_is_recorded_as_a_failed_gate() -> None:
    latency = {
        "metric": EvaluationMetricKind.LATENCY_MS,
        "minimum": None,
        "maximum": 5.0,
    }
    candidate = tuple(
        _prediction(
            prediction.example_id, list(prediction.predicted_labels), latency_ms=None
        )
        for prediction in _perfect()
    )
    report = compare_systems(
        run_configuration=_custom_run_configuration(
            _manifest(), [latency, _safety_threshold()]
        ),
        baseline_predictions=_empty_baseline(),
        candidate_predictions=candidate,
    )
    gate = next(g for g in report.gate_results if g.metric.value == "LATENCY_MS")
    assert gate.observed_value is None and gate.passed is False
    assert report.accepted is False
    EvaluationComparisonReport.model_validate(report.model_dump(mode="json"))


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


# --- Task 206 correction: shared helpers ------------------------------------


def _custom_run_configuration(
    manifest: EvaluationSplitManifest,
    thresholds: list[dict],
    minimum_examples_per_class: int = 0,
    evaluated_splits: tuple[EvaluationSplit, ...] = (EvaluationSplit.TEST,),
) -> EvaluationRunConfiguration:
    metric_configuration = _metric_configuration()
    metric_configuration["thresholds"] = sorted(
        thresholds, key=lambda threshold: threshold["metric"].value
    )
    metric_configuration["minimum_examples_per_class"] = minimum_examples_per_class
    return EvaluationRunConfiguration.model_validate(
        {
            "contract_version": "1",
            "run_id": "run-1",
            "task": _task().model_dump(mode="json"),
            "metric_configuration": metric_configuration,
            "split_manifest": manifest.model_dump(mode="json"),
            "evaluated_splits": evaluated_splits,
        }
    )


def _safety_threshold() -> dict:
    return {
        "metric": EvaluationMetricKind.INVALID_EVIDENCE_REFERENCE_RATE,
        "minimum": 0.0,
        "maximum": 0.0,
    }


def _perfect() -> tuple[CandidatePrediction, ...]:
    return (
        _prediction("example-1", ["ANION_GAP_HIGH"]),
        _prediction("example-2", ["POTASSIUM_HIGH"]),
        _prediction("example-3", ["ANION_GAP_HIGH"]),
        _prediction("example-4", ["POTASSIUM_HIGH"]),
    )


def _empty_baseline() -> tuple[CandidatePrediction, ...]:
    return tuple(_prediction(f"example-{i}", []) for i in range(1, 5))


def _confusion(outcome) -> dict[tuple[str, str], int]:
    return {(row, col): count for row, col, count in outcome.label_cooccurrence_counts}


# --- A. confusion-matrix accounting -----------------------------------------


def test_example_without_expected_labels_records_its_own_false_positive() -> None:
    manifest = _split_manifest(
        [
            ("example-1", "TEST", []),
            ("example-2", "TEST", ["POTASSIUM_HIGH"]),
        ]
    )
    # The no-expected-label example is first in sorted order, so no predicted
    # label can be left over from an earlier example.
    outcome = evaluate_predictions(
        manifest=manifest,
        predictions=(
            _prediction("example-1", ["ANION_GAP_HIGH"]),
            _prediction("example-2", ["POTASSIUM_HIGH"]),
        ),
        labels=LABELS,
        system_id="candidate",
    )
    assert _confusion(outcome) == {
        ("<none>", "ANION_GAP_HIGH"): 1,
        ("POTASSIUM_HIGH", "POTASSIUM_HIGH"): 1,
    }
    reports = {report.label: report for report in outcome.per_class}
    assert reports["ANION_GAP_HIGH"].false_positives == 1


def test_false_positive_only_cell_uses_the_current_examples_prediction() -> None:
    manifest = _split_manifest(
        [
            ("example-1", "TEST", ["POTASSIUM_HIGH"]),
            ("example-2", "TEST", []),
            ("example-3", "TEST", []),
        ]
    )
    outcome = evaluate_predictions(
        manifest=manifest,
        predictions=(
            _prediction("example-1", ["POTASSIUM_HIGH"]),
            _prediction("example-2", ["ANION_GAP_HIGH"]),
            _prediction("example-3", ["ANION_GAP_HIGH", "POTASSIUM_HIGH"]),
        ),
        labels=LABELS,
        system_id="candidate",
    )
    assert _confusion(outcome) == {
        ("POTASSIUM_HIGH", "POTASSIUM_HIGH"): 1,
        ("<none>", "ANION_GAP_HIGH"): 2,
        ("<none>", "POTASSIUM_HIGH"): 1,
    }


def test_mixed_true_and_false_positives_fill_the_expected_cells() -> None:
    manifest = _split_manifest(
        [
            ("example-1", "TEST", ["ANION_GAP_HIGH"]),
            ("example-2", "TEST", ["POTASSIUM_HIGH"]),
            ("example-3", "TEST", []),
        ]
    )
    outcome = evaluate_predictions(
        manifest=manifest,
        predictions=(
            _prediction("example-1", ["ANION_GAP_HIGH", "POTASSIUM_HIGH"]),
            _prediction("example-2", []),
            _prediction("example-3", ["POTASSIUM_HIGH"]),
        ),
        labels=LABELS,
        system_id="candidate",
    )
    assert _confusion(outcome) == {
        ("ANION_GAP_HIGH", "ANION_GAP_HIGH"): 1,
        ("ANION_GAP_HIGH", "POTASSIUM_HIGH"): 1,
        ("POTASSIUM_HIGH", "<NONE>"): 1,
        ("<none>", "POTASSIUM_HIGH"): 1,
    }
    reports = {report.label: report for report in outcome.per_class}
    assert reports["ANION_GAP_HIGH"].true_positives == 1
    assert reports["POTASSIUM_HIGH"].false_positives == 2
    assert reports["POTASSIUM_HIGH"].false_negatives == 1


def test_abstained_examples_fill_the_abstain_column_only() -> None:
    manifest = _split_manifest(
        [
            ("example-1", "TEST", ["ANION_GAP_HIGH"]),
            ("example-2", "TEST", []),
            ("example-3", "TEST", ["POTASSIUM_HIGH"]),
        ]
    )
    outcome = evaluate_predictions(
        manifest=manifest,
        predictions=(
            _prediction("example-1", [], abstained=True),
            _prediction("example-2", [], abstained=True),
            _prediction("example-3", ["POTASSIUM_HIGH"]),
        ),
        labels=LABELS,
        system_id="candidate",
    )
    assert _confusion(outcome) == {
        ("ANION_GAP_HIGH", "<ABSTAIN>"): 1,
        ("POTASSIUM_HIGH", "POTASSIUM_HIGH"): 1,
    }
    assert outcome.abstention_rate == pytest.approx(2 / 3)


# --- B. every declared threshold is effective --------------------------------


def _outcome_with(**patch: float | None):
    base = evaluate_predictions(
        manifest=_manifest(),
        predictions=_perfect(),
        labels=LABELS,
        system_id="candidate",
    )
    return base.model_copy(update=patch)


PROPORTION_METRICS = [
    EvaluationMetricKind.MACRO_F1,
    EvaluationMetricKind.PER_CLASS_PRECISION,
    EvaluationMetricKind.PER_CLASS_RECALL,
    EvaluationMetricKind.BALANCED_ACCURACY,
    EvaluationMetricKind.COVERAGE,
    EvaluationMetricKind.ABSTENTION_RATE,
]


@pytest.mark.parametrize("metric", PROPORTION_METRICS)
def test_proportion_metric_minimum_and_maximum_both_affect_the_result(
    metric: EvaluationMetricKind,
) -> None:
    value = _metric_value(metric, _outcome_with())
    assert value in (0.0, 1.0)
    above = value + 0.25
    below = value - 0.25
    # A minimum above the observed value fails; one at the value passes.
    assert _threshold_violated(
        EvaluationMetricThreshold(metric=metric, minimum=min(above, 1.0), maximum=None),
        value,
    ) is (value < 1.0)
    assert not _threshold_violated(
        EvaluationMetricThreshold(metric=metric, minimum=value, maximum=None), value
    )
    # A maximum below the observed value fails; one at the value passes.
    assert _threshold_violated(
        EvaluationMetricThreshold(metric=metric, minimum=None, maximum=max(below, 0.0)),
        value,
    ) is (value > 0.0)
    assert not _threshold_violated(
        EvaluationMetricThreshold(metric=metric, minimum=None, maximum=value), value
    )


@pytest.mark.parametrize("metric", PROPORTION_METRICS)
def test_a_declared_maximum_below_a_perfect_value_rejects_a_candidate(
    metric: EvaluationMetricKind,
) -> None:
    # A perfect candidate has value 1.0 (0.0 for abstention); an impossible
    # opposite-direction bound must flip acceptance for every metric.
    manifest = _manifest()
    impossible = (
        {"metric": metric, "minimum": None, "maximum": 0.9}
        if metric != EvaluationMetricKind.ABSTENTION_RATE
        else {"metric": metric, "minimum": 0.1, "maximum": None}
    )
    report = compare_systems(
        run_configuration=_custom_run_configuration(
            manifest, [impossible, _safety_threshold()]
        ),
        baseline_predictions=_empty_baseline(),
        candidate_predictions=_perfect(),
    )
    assert report.candidate_improves_macro_f1 is True
    assert report.safety_failure is False
    assert report.accepted is False


def test_unbounded_directions_do_not_block_an_otherwise_perfect_candidate() -> None:
    report = compare_systems(
        run_configuration=_custom_run_configuration(
            _manifest(),
            [
                {"metric": metric, "minimum": 0.0, "maximum": 1.0}
                for metric in PROPORTION_METRICS
            ]
            + [_safety_threshold()],
        ),
        baseline_predictions=_empty_baseline(),
        candidate_predictions=_perfect(),
    )
    assert report.accepted is True


def test_latency_minimum_and_maximum_are_both_enforced_in_milliseconds() -> None:
    metric = EvaluationMetricKind.LATENCY_MS
    outcome = _outcome_with(latency_ms_max=250.0)
    value = _metric_value(metric, outcome)
    assert value == 250.0
    # Millisecond bounds far above 1.0 are valid for latency.
    assert not _threshold_violated(
        EvaluationMetricThreshold(metric=metric, minimum=100.0, maximum=500.0), value
    )
    assert _threshold_violated(
        EvaluationMetricThreshold(metric=metric, minimum=None, maximum=200.0), value
    )
    assert _threshold_violated(
        EvaluationMetricThreshold(metric=metric, minimum=300.0, maximum=None), value
    )


@pytest.mark.parametrize(
    ("bound", "expect_accepted"),
    [
        ({"minimum": None, "maximum": 0.5}, False),
        ({"minimum": None, "maximum": 5.0}, True),
        ({"minimum": 2.0, "maximum": None}, False),
        ({"minimum": 0.5, "maximum": None}, True),
    ],
)
def test_latency_bounds_decide_acceptance_end_to_end(
    bound: dict, expect_accepted: bool
) -> None:
    # Every candidate prediction reports 1.0 ms.
    report = compare_systems(
        run_configuration=_custom_run_configuration(
            _manifest(),
            [{"metric": EvaluationMetricKind.LATENCY_MS, **bound}, _safety_threshold()],
        ),
        baseline_predictions=_empty_baseline(),
        candidate_predictions=_perfect(),
    )
    assert report.accepted is expect_accepted


def test_declared_latency_bound_without_a_measurement_fails_closed() -> None:
    candidate = tuple(
        _prediction(f"example-{i}", label, latency_ms=None)
        for i, label in zip(
            range(1, 5),
            (
                ["ANION_GAP_HIGH"],
                ["POTASSIUM_HIGH"],
                ["ANION_GAP_HIGH"],
                ["POTASSIUM_HIGH"],
            ),
            strict=True,
        )
    )
    report = compare_systems(
        run_configuration=_custom_run_configuration(
            _manifest(),
            [
                {
                    "metric": EvaluationMetricKind.LATENCY_MS,
                    "minimum": None,
                    "maximum": 1000.0,
                },
                _safety_threshold(),
            ],
        ),
        baseline_predictions=_empty_baseline(),
        candidate_predictions=candidate,
    )
    assert report.accepted is False


def test_threshold_ranges_are_metric_appropriate() -> None:
    latency = EvaluationMetricKind.LATENCY_MS
    EvaluationMetricThreshold(metric=latency, minimum=None, maximum=1500.0)
    EvaluationMetricThreshold(
        metric=latency, minimum=None, maximum=MAX_LATENCY_THRESHOLD_MS
    )
    with pytest.raises(ValidationError, match="valid range"):
        EvaluationMetricThreshold(
            metric=latency, minimum=None, maximum=MAX_LATENCY_THRESHOLD_MS + 1.0
        )
    with pytest.raises(ValidationError):
        EvaluationMetricThreshold(metric=latency, minimum=-1.0, maximum=None)
    for metric in PROPORTION_METRICS:
        with pytest.raises(ValidationError, match="valid range"):
            EvaluationMetricThreshold(metric=metric, minimum=None, maximum=1.5)
        with pytest.raises(ValidationError, match="valid range"):
            EvaluationMetricThreshold(metric=metric, minimum=1.5, maximum=None)


def test_measured_zero_latency_is_not_mistaken_for_missing() -> None:
    outcome = evaluate_predictions(
        manifest=_manifest(),
        predictions=tuple(
            _prediction(f"example-{i}", [], latency_ms=0.0) for i in range(1, 5)
        ),
        labels=LABELS,
        system_id="baseline",
    )
    assert outcome.latency_ms_max == 0.0


# --- C. class-count requirement and ground-truth labels ----------------------


def test_minimum_examples_per_class_is_enforced_before_evaluation() -> None:
    manifest = _split_manifest(
        [
            ("example-1", "TEST", ["ANION_GAP_HIGH"]),
            ("example-2", "TEST", ["ANION_GAP_HIGH"]),
            ("example-3", "TEST", ["POTASSIUM_HIGH"]),
        ]
    )
    configuration = _custom_run_configuration(
        manifest,
        [_safety_threshold()],
        minimum_examples_per_class=2,
    )
    with pytest.raises(EvaluationHarnessError, match="CLASS_COUNT_INSUFFICIENT"):
        compare_systems(
            run_configuration=configuration,
            baseline_predictions=(),
            candidate_predictions=(),
        )


def test_class_count_error_is_safe_and_names_no_identifiers() -> None:
    manifest = _split_manifest(
        [("secret-example-id", "TEST", ["ANION_GAP_HIGH"])],
    )
    configuration = _custom_run_configuration(
        manifest, [_safety_threshold()], minimum_examples_per_class=2
    )
    with pytest.raises(EvaluationHarnessError) as raised:
        compare_systems(
            run_configuration=configuration,
            baseline_predictions=(),
            candidate_predictions=(),
        )
    assert "secret-example-id" not in str(raised.value)
    assert "ANION_GAP_HIGH" not in str(raised.value)


def test_class_count_applies_only_to_the_declared_evaluated_split() -> None:
    manifest = _split_manifest(
        [
            ("example-1", "TEST", ["ANION_GAP_HIGH"]),
            ("example-2", "TEST", ["POTASSIUM_HIGH"]),
            ("example-3", "TRAIN", ["ANION_GAP_HIGH"]),
            ("example-4", "TRAIN", ["POTASSIUM_HIGH"]),
        ]
    )
    # TRAIN+TEST together would satisfy 2 per class; TEST alone does not.
    configuration = _custom_run_configuration(
        manifest, [_safety_threshold()], minimum_examples_per_class=2
    )
    with pytest.raises(EvaluationHarnessError, match="CLASS_COUNT_INSUFFICIENT"):
        compare_systems(
            run_configuration=configuration,
            baseline_predictions=(),
            candidate_predictions=(),
        )


def test_minimum_examples_per_class_exactly_met_is_accepted_for_evaluation() -> None:
    report = compare_systems(
        run_configuration=_custom_run_configuration(
            _manifest(), [_safety_threshold()], minimum_examples_per_class=2
        ),
        baseline_predictions=_empty_baseline(),
        candidate_predictions=_perfect(),
    )
    assert report.accepted is True


def test_ground_truth_outside_the_task_labels_is_rejected_not_trimmed() -> None:
    manifest = _split_manifest(
        [
            ("example-1", "TEST", ["ANION_GAP_HIGH", "UNDECLARED_LABEL"]),
            ("example-2", "TEST", ["POTASSIUM_HIGH"]),
        ]
    )
    with pytest.raises(EvaluationHarnessError, match="GROUND_TRUTH_LABEL_UNKNOWN"):
        evaluate_predictions(
            manifest=manifest,
            predictions=(),
            labels=LABELS,
            system_id="baseline",
        )
    with pytest.raises(EvaluationHarnessError, match="GROUND_TRUTH_LABEL_UNKNOWN"):
        compare_systems(
            run_configuration=_custom_run_configuration(
                manifest, [_safety_threshold()]
            ),
            baseline_predictions=(),
            candidate_predictions=(),
        )


def test_empty_evaluated_split_fails_with_a_stable_error() -> None:
    configuration = _custom_run_configuration(
        _manifest(),
        [_safety_threshold()],
        evaluated_splits=(EvaluationSplit.VALIDATION,),
    )
    with pytest.raises(EvaluationHarnessError, match="EVALUATED_SPLIT_EMPTY"):
        compare_systems(
            run_configuration=configuration,
            baseline_predictions=(),
            candidate_predictions=(),
        )


# --- D. zero-tolerance safety gate for both systems --------------------------


def test_invalid_reference_in_the_baseline_blocks_acceptance() -> None:
    baseline = (
        _prediction("example-1", [], invalid=True),
        _prediction("example-2", []),
        _prediction("example-3", []),
        _prediction("example-4", []),
    )
    report = compare_systems(
        run_configuration=_run_configuration(_manifest()),
        baseline_predictions=baseline,
        candidate_predictions=_perfect(),
    )
    assert report.baseline.invalid_evidence_reference_rate == 0.25
    assert report.candidate.invalid_evidence_reference_rate == 0.0
    assert report.candidate_improves_macro_f1 is True
    assert report.safety_failure is True
    assert report.accepted is False


def test_abstained_invalid_prediction_still_increments_the_safety_counter() -> None:
    outcome = evaluate_predictions(
        manifest=_manifest(),
        predictions=(
            _prediction("example-1", [], abstained=True, invalid=True),
            _prediction("example-2", ["POTASSIUM_HIGH"]),
            _prediction("example-3", ["ANION_GAP_HIGH"]),
            _prediction("example-4", ["POTASSIUM_HIGH"]),
        ),
        labels=LABELS,
        system_id="candidate",
    )
    assert outcome.invalid_evidence_reference_rate == 0.25
    assert outcome.abstention_rate == 0.25


def test_abstained_invalid_candidate_cannot_be_accepted() -> None:
    candidate = (
        _prediction("example-1", [], abstained=True, invalid=True),
        _prediction("example-2", ["POTASSIUM_HIGH"]),
        _prediction("example-3", ["ANION_GAP_HIGH"]),
        _prediction("example-4", ["POTASSIUM_HIGH"]),
    )
    report = compare_systems(
        run_configuration=_run_configuration(_manifest()),
        baseline_predictions=_empty_baseline(),
        candidate_predictions=candidate,
    )
    assert report.safety_failure is True
    assert report.accepted is False


def test_clean_runs_for_both_systems_report_no_safety_failure() -> None:
    report = compare_systems(
        run_configuration=_run_configuration(_manifest()),
        baseline_predictions=_empty_baseline(),
        candidate_predictions=_perfect(),
    )
    assert report.safety_failure is False
    assert report.accepted is True


# --- E. split helper ----------------------------------------------------------


def test_split_helper_returns_validated_canonical_entries() -> None:
    ids = tuple(f"example-{i}" for i in range(30))
    entries = assign_splits_deterministically(
        example_ids=ids, train_ratio=0.5, validation_ratio=0.25
    )
    assert isinstance(entries, tuple)
    assert all(isinstance(entry, EvaluationManifestEntry) for entry in entries)
    assert {entry.example_id for entry in entries} == set(ids)
    assert all(entry.expected_labels == () for entry in entries)
    keys = [(entry.split.value, entry.example_id) for entry in entries]
    assert keys == sorted(keys)
    # The result is directly usable once the caller supplies identity+labels.
    EvaluationSplitManifest.model_validate(
        {
            "contract_version": "1",
            "dataset_id": DATASET_ID,
            "dataset_snapshot_hash": "c" * 64,
            "task_id": TASK_ID,
            "entries": entries,
        }
    )


def test_split_helper_is_stable_under_input_reordering() -> None:
    ids = tuple(f"example-{i}" for i in range(40))
    forward = assign_splits_deterministically(
        example_ids=ids, train_ratio=0.6, validation_ratio=0.2
    )
    reverse = assign_splits_deterministically(
        example_ids=tuple(reversed(ids)), train_ratio=0.6, validation_ratio=0.2
    )
    assert forward == reverse


def test_split_helper_rejects_duplicate_example_ids_without_echoing_them() -> None:
    with pytest.raises(EvaluationHarnessError, match="DUPLICATE_EXAMPLE_ID") as raised:
        assign_splits_deterministically(
            example_ids=("patient-secret-1", "patient-secret-1"),
            train_ratio=0.6,
            validation_ratio=0.2,
        )
    assert "patient-secret-1" not in str(raised.value)


def test_split_helper_rejects_invalid_identifiers_with_a_stable_error() -> None:
    with pytest.raises(EvaluationHarnessError, match="EXAMPLE_ID_INVALID"):
        assign_splits_deterministically(
            example_ids=("example-1", "   "), train_ratio=0.6, validation_ratio=0.2
        )


# --- F. final report and summary integrity regressions -----------------------

def _valid_accepted_report_payload() -> dict:
    report = compare_systems(
        run_configuration=_run_configuration(_manifest()),
        baseline_predictions=_empty_baseline(),
        candidate_predictions=_perfect(),
    )
    assert report.accepted is True
    return report.model_dump(mode="json")


@pytest.mark.parametrize(
    "mutation",
    [
        "remove_gate",
        "undeclared_gate",
        "changed_minimum",
        "changed_maximum",
        "changed_configuration_identity",
        "changed_task_label_space",
        "forged_acceptance",
    ],
)
def test_report_rejects_forged_or_incomplete_predeclared_gates(mutation: str) -> None:
    payload = _valid_accepted_report_payload()
    if mutation == "remove_gate":
        payload["gate_results"] = [
            g for g in payload["gate_results"] if g["metric"] != "MACRO_F1"
        ]
    elif mutation == "undeclared_gate":
        next(
            g for g in payload["gate_results"] if g["metric"] == "MACRO_F1"
        )["metric"] = "PER_CLASS_RECALL"
    elif mutation == "changed_minimum":
        next(
            g for g in payload["gate_results"] if g["metric"] == "MACRO_F1"
        )["minimum"] = 0.4
    elif mutation == "changed_maximum":
        next(
            g for g in payload["gate_results"] if g["metric"] == "MACRO_F1"
        )["maximum"] = 0.9
    elif mutation == "changed_configuration_identity":
        payload["metric_configuration"]["configuration_id"] = (
            "altered-without-new-digest"
        )
    elif mutation == "changed_task_label_space":
        payload["task"]["labels"] = ["ALTERNATE_A", "ALTERNATE_B"]
    else:
        payload["gate_results"] = [
            g for g in payload["gate_results"] if g["metric"] != "MACRO_F1"
        ]
        payload["accepted"] = True
    with pytest.raises(ValidationError):
        EvaluationComparisonReport.model_validate(payload)


def test_summary_rejects_counts_that_disagree_with_precision_and_recall() -> None:
    outcome = evaluate_predictions(
        manifest=_manifest(),
        predictions=_perfect(),
        labels=LABELS,
        system_id="candidate",
    )
    payload = outcome.model_dump(mode="json")
    payload["per_class"][0]["true_positives"] += 1
    with pytest.raises(ValidationError):
        type(outcome).model_validate(payload)


def test_summary_rejects_forged_macro_f1_and_coverage() -> None:
    outcome = evaluate_predictions(
        manifest=_manifest(),
        predictions=_perfect(),
        labels=LABELS,
        system_id="candidate",
    )
    payload = outcome.model_dump(mode="json")
    payload["macro_f1"] = 0.25
    with pytest.raises(ValidationError):
        type(outcome).model_validate(payload)
    payload = outcome.model_dump(mode="json")
    payload["coverage"] = 0.5
    with pytest.raises(ValidationError):
        type(outcome).model_validate(payload)


def test_binary_confusion_counts_abstentions_as_negative_predictions() -> None:
    outcome = evaluate_predictions(
        manifest=_manifest(),
        predictions=tuple(
            _prediction(f"example-{i}", [], abstained=True)
            for i in range(1, 5)
        ),
        labels=LABELS,
        system_id="candidate",
    )
    assert outcome.abstention_count == outcome.example_count == 4
    assert outcome.coverage == 0.0
    assert outcome.abstention_rate == 1.0
    for row in outcome.binary_confusion:
        _, tp, fp, fn, tn = row
        assert tp == fp == tn == 0
        assert fn == 2
        assert tp + fp + fn + tn == outcome.example_count


def test_binary_confusion_zero_predicted_and_zero_actual_positives_are_valid() -> None:
    zero_predicted = evaluate_predictions(
        manifest=_manifest(),
        predictions=tuple(
            _prediction(f"example-{i}", []) for i in range(1, 5)
        ),
        labels=LABELS,
        system_id="candidate",
    )
    assert all(row.precision == 0.0 for row in zero_predicted.per_class)
    empty_expected = _split_manifest(
        [(f"example-{i}", "TEST", []) for i in range(1, 5)]
    )
    zero_actual = evaluate_predictions(
        manifest=empty_expected,
        predictions=tuple(
            _prediction(f"example-{i}", []) for i in range(1, 5)
        ),
        labels=LABELS,
        system_id="candidate",
    )
    assert all(row.recall == 0.0 for row in zero_actual.per_class)
    assert all(row.true_negatives == 4 for row in zero_actual.per_class)
    assert sum(count for _, _, count in zero_actual.label_cooccurrence_counts) == 0


@pytest.mark.parametrize(
    ("expected", "predicted", "expected_counts"),
    [
        (["A"], ["A", "B"], {"A": (1, 0, 0, 0), "B": (0, 1, 0, 0), "C": (0, 0, 0, 1)}),
        (
            ["A", "B"],
            ["A", "C"],
            {
                "A": (1, 0, 0, 0),
                "B": (0, 0, 1, 0),
                "C": (0, 1, 0, 0),
            },
        ),
        (["A"], ["B"], {"A": (0, 0, 1, 0), "B": (0, 1, 0, 0), "C": (0, 0, 0, 1)}),
        ([], ["B", "C"], {"A": (0, 0, 0, 1), "B": (0, 1, 0, 0), "C": (0, 1, 0, 0)}),
    ],
)
def test_binary_confusion_semantics_for_multilabel_edges(
    expected, predicted, expected_counts
) -> None:
    manifest = _split_manifest([("example-1", "TEST", expected)])
    outcome = evaluate_predictions(
        manifest=manifest,
        predictions=(_prediction("example-1", predicted),),
        labels=("A", "B", "C"),
        system_id="candidate",
    )
    actual = {
        row.label: (
            row.true_positives,
            row.false_positives,
            row.false_negatives,
            row.true_negatives,
        )
        for row in outcome.per_class
    }
    assert actual == expected_counts
    assert tuple(row[0] for row in outcome.binary_confusion) == ("A", "B", "C")
    assert all(
        sum(row[1:]) == outcome.example_count for row in outcome.binary_confusion
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "run_configuration_hash",
        "evaluated_splits",
        "dataset_snapshot",
        "manifest_entry",
        "expected_labels",
        "configuration_manifest_entry",
        "configuration_expected_labels",
        "run_id",
        "task",
        "metric_configuration",
    ],
)
def test_report_rejects_run_identity_or_cohort_tampering(mutation: str) -> None:
    payload = _report_payload(accepted=True)
    if mutation == "run_configuration_hash":
        payload["run_configuration_hash"] = "d" * 64
    elif mutation == "evaluated_splits":
        payload["run_configuration"]["evaluated_splits"] = ["VALIDATION"]
    elif mutation == "dataset_snapshot":
        payload["run_configuration"]["split_manifest"][
            "dataset_snapshot_hash"
        ] = "e" * 64
    elif mutation == "manifest_entry":
        payload["evaluated_manifest"]["entries"][0]["example_id"] = "tampered-example"
    elif mutation == "expected_labels":
        payload["evaluated_manifest"]["entries"][0]["expected_labels"] = [
            "POTASSIUM_HIGH"
        ]
    elif mutation == "configuration_manifest_entry":
        payload["run_configuration"]["split_manifest"]["entries"][0][
            "example_id"
        ] = "tampered-config-example"
    elif mutation == "configuration_expected_labels":
        payload["run_configuration"]["split_manifest"]["entries"][0][
            "expected_labels"
        ] = ["POTASSIUM_HIGH"]
    elif mutation == "run_id":
        payload["run_id"] = "forged-run-id"
    elif mutation == "task":
        payload["task"]["task_id"] = "other-task"
    elif mutation == "metric_configuration":
        payload["metric_configuration"]["configuration_id"] = "other-metric-config"
    with pytest.raises(ValidationError):
        EvaluationComparisonReport.model_validate(payload)


def test_report_rejects_baseline_summary_from_a_smaller_cohort() -> None:
    payload = _report_payload(accepted=True)
    smaller = _split_manifest(
        [
            ("example-1", "TEST", ["ANION_GAP_HIGH"]),
            ("example-2", "TEST", ["POTASSIUM_HIGH"]),
        ]
    )
    small_summary = evaluate_predictions(
        manifest=smaller,
        predictions=(
            _prediction("example-1", ["ANION_GAP_HIGH"]),
            _prediction("example-2", ["POTASSIUM_HIGH"]),
        ),
        labels=LABELS,
        system_id="baseline",
    )
    payload["baseline"] = small_summary.model_dump(mode="json")
    with pytest.raises(
        ValidationError, match="evaluated manifest|evaluated cohort|example_count"
    ):
        EvaluationComparisonReport.model_validate(payload)


def test_report_rejects_outcome_count_changed_without_cohort_change() -> None:
    payload = _report_payload(accepted=True)
    payload["baseline"]["example_count"] = 3
    with pytest.raises(ValidationError):
        EvaluationComparisonReport.model_validate(payload)


def test_report_rejects_different_baseline_and_candidate_cohort_hashes() -> None:
    payload = _report_payload(accepted=True)
    payload["baseline"]["evaluated_cohort_hash"] = "a" * 64
    with pytest.raises(ValidationError, match="exact evaluated manifest"):
        EvaluationComparisonReport.model_validate(payload)


def test_predicting_every_label_has_perfect_recall_but_not_balanced_accuracy() -> None:
    outcome = evaluate_predictions(
        manifest=_manifest(),
        predictions=tuple(
            _prediction(f"example-{i}", list(LABELS)) for i in range(1, 5)
        ),
        labels=LABELS,
        system_id="always-positive",
    )
    assert all(row.recall == 1.0 for row in outcome.per_class)
    assert all(row.specificity == 0.0 for row in outcome.per_class)
    assert all(row.balanced_accuracy == 0.5 for row in outcome.per_class)
    assert outcome.balanced_accuracy == 0.5


@pytest.mark.parametrize(
    ("splits", "should_accept"),
    [
        ((EvaluationSplit.TRAIN,), False),
        ((EvaluationSplit.VALIDATION,), False),
        ((EvaluationSplit.TEST,), True),
        ((EvaluationSplit.TRAIN, EvaluationSplit.TEST), False),
        ((EvaluationSplit.VALIDATION, EvaluationSplit.TEST), False),
    ],
)
def test_only_test_only_run_can_be_accepted(splits, should_accept) -> None:
    manifest = _split_manifest(
        [
            (f"test-{i}", "TEST", [LABELS[(i - 1) % 2]])
            for i in range(1, 5)
        ]
        + [
            (f"train-{i}", "TRAIN", [LABELS[(i - 1) % 2]])
            for i in range(1, 5)
        ]
        + [
            (f"validation-{i}", "VALIDATION", [LABELS[(i - 1) % 2]])
            for i in range(1, 5)
        ]
    )
    configuration = _run_configuration(manifest, evaluated_splits=splits)
    entries = tuple(entry for entry in manifest.entries if entry.split in splits)
    baseline = tuple(
        _prediction(entry.example_id, []) for entry in entries
    )
    candidate = tuple(
        _prediction(entry.example_id, list(entry.expected_labels))
        for entry in entries
    )
    report = compare_systems(
        run_configuration=configuration,
        baseline_predictions=baseline,
        candidate_predictions=candidate,
    )
    assert report.accepted is should_accept
