"""Task 214 benchmark tests use synthetic text and local-only inference."""

from __future__ import annotations

import pytest

from rop.native_benchmark import NativeBenchmarkConfig, NativeBenchmarkError, run_native_benchmark
from rop.native_inference import NativeInferenceConfig, NativeLocalInference
from rop.native_suggestion_validation import SuggestionValidationPolicy
from test_native_artifacts import _artifact


def _setup():
    artifact, vocabulary = _artifact()
    inference = NativeLocalInference(
        artifact=artifact,
        vocabulary=vocabulary,
        labels=("ANION_GAP_HIGH", "POTASSIUM_HIGH"),
        config=NativeInferenceConfig(top_k=2, minimum_probability=0.0),
    )
    policy = SuggestionValidationPolicy(
        task_id="synthetic-task",
        expected_model_version=artifact.model_config_payload.model_version,
        expected_vocabulary_hash=vocabulary.vocabulary_hash,
        allowed_labels=("ANION_GAP_HIGH", "POTASSIUM_HIGH"),
        minimum_probability=0.0,
        maximum_suggestions=2,
    )
    config = NativeBenchmarkConfig(
        warmup_iterations=1,
        measured_iterations=5,
        latency_budget_ms=60000.0,
        peak_memory_budget_bytes=10000000,
    )
    return inference, policy, config


def test_benchmark_reports_bounded_metrics_without_inputs():
    inference, policy, config = _setup()
    secret = "synthetic private sentinel"
    report = run_native_benchmark(
        inference=inference,
        policy=policy,
        texts=(secret, "another synthetic example"),
        config=config,
    )
    assert report.execution_mode == "LOCAL_CPU_OFFLINE"
    assert report.clinical_utility_established is False
    assert report.measured_iterations == 5
    assert report.latency_mean_ms >= 0.0
    assert report.latency_p95_ms >= 0.0
    assert report.peak_traced_memory_bytes > 0
    assert secret not in report.model_dump_json()


def test_benchmark_output_digest_is_reproducible():
    inference, policy, config = _setup()
    first = run_native_benchmark(
        inference=inference,
        policy=policy,
        texts=("synthetic one", "synthetic two"),
        config=config,
    )
    second = run_native_benchmark(
        inference=inference,
        policy=policy,
        texts=("synthetic one", "synthetic two"),
        config=config,
    )
    assert first.output_digest == second.output_digest


def test_benchmark_rejects_empty_cases():
    inference, policy, config = _setup()
    with pytest.raises(NativeBenchmarkError) as caught:
        run_native_benchmark(inference=inference, policy=policy, texts=(), config=config)
    assert caught.value.code == "CASE_COUNT_INVALID"
