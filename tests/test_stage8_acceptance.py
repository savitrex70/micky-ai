"""Task 215 end-to-end acceptance tests; synthetic fixtures must stay blocked."""

from __future__ import annotations

import pytest

from rop.native_benchmark import NativeBenchmarkConfig, run_native_benchmark
from rop.native_inference import NativeInferenceConfig, NativeLocalInference
from rop.native_suggestion_validation import SuggestionValidationPolicy
from rop.schemas.evaluation_harness import CandidatePrediction, EvaluationRunConfiguration, EvaluationSplitManifest
from rop.stage8_acceptance import Stage8AcceptanceError, run_stage8_acceptance_gate
from test_native_artifacts import _artifact
from test_native_training import _splits_and_manifest
from test_evaluation_harness import _metric_configuration, _task

LABELS = ("ANION_GAP_HIGH", "POTASSIUM_HIGH")


def _setup(snapshot_patch: str | None = None):
    artifact, vocabulary = _artifact()
    _, dataset_manifest, _, _, _, _ = _splits_and_manifest()
    snapshot_hash = snapshot_patch or dataset_manifest.dataset_fingerprint
    split_manifest = EvaluationSplitManifest(
        contract_version="1",
        dataset_id=dataset_manifest.dataset_id,
        dataset_snapshot_hash=snapshot_hash,
        task_id="task-labtag-1",
        entries=(
            {"example_id": "example-1", "split": "TEST", "expected_labels": ("ANION_GAP_HIGH",)},
            {"example_id": "example-2", "split": "TEST", "expected_labels": ("POTASSIUM_HIGH",)},
            {"example_id": "example-3", "split": "TEST", "expected_labels": ("ANION_GAP_HIGH",)},
            {"example_id": "example-4", "split": "TEST", "expected_labels": ("POTASSIUM_HIGH",)},
        ),
    )
    run_configuration = EvaluationRunConfiguration(
        contract_version="1",
        run_id="stage8-synthetic-run",
        task=_task(),
        metric_configuration=_metric_configuration(),
        split_manifest=split_manifest,
        evaluated_splits=("TEST",),
    )
    policy = SuggestionValidationPolicy(
        task_id="task-labtag-1",
        expected_model_version=artifact.model_config_payload.model_version,
        expected_vocabulary_hash=vocabulary.vocabulary_hash,
        allowed_labels=LABELS,
        minimum_probability=0.0,
        maximum_suggestions=2,
    )
    inference = NativeLocalInference(
        artifact=artifact,
        vocabulary=vocabulary,
        labels=LABELS,
        config=NativeInferenceConfig(top_k=2, minimum_probability=0.0),
    )
    texts = {
        "example-1": "synthetic anion gap",
        "example-2": "synthetic potassium",
        "example-3": "synthetic anion gap",
        "example-4": "synthetic potassium",
    }
    baseline = (
        CandidatePrediction(example_id="example-1", predicted_labels=("ANION_GAP_HIGH",), abstained=False, latency_ms=1.0),
        CandidatePrediction(example_id="example-2", predicted_labels=("POTASSIUM_HIGH",), abstained=False, latency_ms=1.0),
        CandidatePrediction(example_id="example-3", predicted_labels=("ANION_GAP_HIGH",), abstained=False, latency_ms=1.0),
        CandidatePrediction(example_id="example-4", predicted_labels=("POTASSIUM_HIGH",), abstained=False, latency_ms=1.0),
    )
    benchmark = run_native_benchmark(
        inference=inference,
        policy=policy,
        texts=tuple(texts.values()),
        config=NativeBenchmarkConfig(
            warmup_iterations=0,
            measured_iterations=2,
            latency_budget_ms=60000.0,
            peak_memory_budget_bytes=10000000,
        ),
    )
    return run_configuration, dataset_manifest, artifact, inference, policy, texts, baseline, benchmark


def test_stage8_gate_never_accepts_synthetic_dataset():
    run_configuration, dataset_manifest, artifact, inference, policy, texts, baseline, benchmark = _setup()
    report = run_stage8_acceptance_gate(
        run_configuration=run_configuration,
        dataset_manifest=dataset_manifest,
        artifact=artifact,
        inference=inference,
        policy=policy,
        texts_by_example_id=texts,
        baseline_predictions=baseline,
        benchmark=benchmark,
    )
    assert report.accepted is False
    assert report.authorized_real_data is False
    assert "REAL_AUTHORIZED_DATA_REQUIRED" in report.blockers
    assert report.evaluation.run_configuration_hash


def test_stage8_gate_rejects_detached_dataset_snapshot():
    run_configuration, dataset_manifest, artifact, inference, policy, texts, baseline, benchmark = _setup("f" * 64)
    with pytest.raises(Stage8AcceptanceError) as caught:
        run_stage8_acceptance_gate(
            run_configuration=run_configuration,
            dataset_manifest=dataset_manifest,
            artifact=artifact,
            inference=inference,
            policy=policy,
            texts_by_example_id=texts,
            baseline_predictions=baseline,
            benchmark=benchmark,
        )
    assert caught.value.code == "DATASET_BINDING_MISMATCH"


def test_stage8_gate_rejects_missing_test_text():
    run_configuration, dataset_manifest, artifact, inference, policy, texts, baseline, benchmark = _setup()
    texts.pop("example-1")
    with pytest.raises(Stage8AcceptanceError) as caught:
        run_stage8_acceptance_gate(
            run_configuration=run_configuration,
            dataset_manifest=dataset_manifest,
            artifact=artifact,
            inference=inference,
            policy=policy,
            texts_by_example_id=texts,
            baseline_predictions=baseline,
            benchmark=benchmark,
        )
    assert caught.value.code == "TEST_TEXT_SET_MISMATCH"
