"""Task 214 benchmark tests use synthetic text and local-only inference."""

from __future__ import annotations

import hashlib
import tracemalloc

import pytest
from pydantic import ValidationError

import rop.native_benchmark as native_benchmark
from rop.native_artifacts import create_native_artifact
from rop.native_benchmark import (
    BENCHMARK_CONTRACT_VERSION,
    NativeBenchmarkConfig,
    NativeBenchmarkError,
    NativeBenchmarkReport,
    case_set_digest,
    run_native_benchmark,
)
from rop.native_inference import NativeInferenceConfig, NativeLocalInference
from rop.native_suggestion_validation import SuggestionValidationPolicy
from tests.test_native_artifacts import _artifact
from tests.test_native_training import LABEL_SPACE, _fixture, _train

TEXTS = ("synthetic one", "synthetic two")


def _inference_and_policy(artifact, vocabulary):
    inference = NativeLocalInference(
        artifact=artifact,
        vocabulary=vocabulary,
        labels=LABEL_SPACE,
        config=NativeInferenceConfig(top_k=2, minimum_probability=0.0),
    )
    policy = SuggestionValidationPolicy(
        task_id="synthetic-task",
        expected_model_version=artifact.model_config_payload.model_version,
        expected_vocabulary_hash=vocabulary.vocabulary_hash,
        allowed_labels=LABEL_SPACE,
        minimum_probability=0.0,
        maximum_suggestions=2,
    )
    return inference, policy


def _config(**patch):
    value = {
        "warmup_iterations": 1,
        "measured_iterations": 5,
        "latency_budget_ms": 60000.0,
        "peak_memory_budget_bytes": 10000000,
    }
    value.update(patch)
    return NativeBenchmarkConfig(**value)


def _setup(**config_patch):
    artifact, vocabulary = _artifact()
    inference, policy = _inference_and_policy(artifact, vocabulary)
    return inference, policy, _config(**config_patch), artifact


def _run(texts=TEXTS, **config_patch):
    inference, policy, config, artifact = _setup(**config_patch)
    return (
        run_native_benchmark(
            inference=inference, policy=policy, texts=texts, config=config
        ),
        artifact,
    )


def test_benchmark_reports_bounded_metrics_without_inputs():
    inference, policy, config, _ = _setup()
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
    dumped = report.model_dump_json()
    assert secret not in dumped
    assert hashlib.sha256(secret.encode()).hexdigest() not in dumped


def test_benchmark_output_digest_is_reproducible():
    first, _ = _run()
    second, _ = _run()
    assert first.output_digest == second.output_digest
    assert first.case_set_digest == second.case_set_digest
    assert first.artifact_hash == second.artifact_hash


def test_benchmark_rejects_empty_cases():
    inference, policy, config, _ = _setup()
    with pytest.raises(NativeBenchmarkError) as caught:
        run_native_benchmark(
            inference=inference, policy=policy, texts=(), config=config
        )
    assert caught.value.code == "CASE_COUNT_INVALID"


# --- artifact, configuration and workload identity ------------------------------


def test_report_binds_the_exact_artifact_from_the_inference_adapter():
    report, artifact = _run()
    assert report.artifact_hash == artifact.artifact_hash
    assert report.model_version == artifact.model_config_payload.model_version


def test_same_version_and_vocabulary_but_different_checkpoint_differs():
    fixture = _fixture()
    vocabulary, model_config = fixture[2], fixture[3]
    first_result = _train(fixture)
    other_config = fixture[5].model_copy(update={"epochs": 4})
    second_result = _train(fixture, training_config=other_config)
    artifacts = [
        create_native_artifact(
            model_config=model_config,
            parameters=result.parameters,
            training_report=result.report,
            vocabulary=vocabulary,
        )
        for result in (first_result, second_result)
    ]
    assert artifacts[0].artifact_hash != artifacts[1].artifact_hash
    assert (
        artifacts[0].model_config_payload.model_version
        == artifacts[1].model_config_payload.model_version
    )
    reports = []
    for artifact in artifacts:
        inference, policy = _inference_and_policy(artifact, vocabulary)
        reports.append(
            run_native_benchmark(
                inference=inference, policy=policy, texts=TEXTS, config=_config()
            )
        )
    assert reports[0].model_version == reports[1].model_version
    assert reports[0].vocabulary_hash == reports[1].vocabulary_hash
    assert reports[0].artifact_hash != reports[1].artifact_hash


def test_report_has_no_caller_supplied_artifact_identity_parameter():
    inference, policy, config, _ = _setup()
    with pytest.raises(TypeError):
        run_native_benchmark(  # type: ignore[call-arg]
            inference=inference,
            policy=policy,
            texts=TEXTS,
            config=config,
            artifact_hash="f" * 64,
        )


def test_configuration_hash_is_canonical_and_sensitive_to_every_field():
    base = _config()
    assert base.config_hash() == _config().config_hash()
    for patch in (
        {"warmup_iterations": 2},
        {"measured_iterations": 6},
        {"latency_budget_ms": 59999.0},
        {"peak_memory_budget_bytes": 10000001},
    ):
        assert _config(**patch).config_hash() != base.config_hash()
    report, _ = _run()
    assert report.benchmark_config_hash == _config().config_hash()


def test_report_records_the_declared_budgets_used_for_the_verdict():
    report, _ = _run(latency_budget_ms=1234.5, peak_memory_budget_bytes=7654321)
    assert report.declared_latency_budget_ms == 1234.5
    assert report.declared_peak_memory_budget_bytes == 7654321


def test_case_set_digest_is_order_sensitive_content_sensitive_and_private():
    first, _ = _run(texts=("synthetic one", "synthetic two"))
    swapped, _ = _run(texts=("synthetic two", "synthetic one"))
    changed, _ = _run(texts=("synthetic one", "synthetic three"))
    assert (
        len({first.case_set_digest, swapped.case_set_digest, changed.case_set_digest})
        == 3
    )
    assert "synthetic" not in first.model_dump_json()


# --- case coverage ---------------------------------------------------------------


def test_fewer_iterations_than_cases_is_rejected_not_silently_truncated():
    inference, policy, config, _ = _setup(measured_iterations=2)
    with pytest.raises(NativeBenchmarkError) as caught:
        run_native_benchmark(
            inference=inference,
            policy=policy,
            texts=("a one", "a two", "a three"),
            config=config,
        )
    assert caught.value.code == "CASE_COVERAGE_INSUFFICIENT"


def test_exact_coverage_and_cycling_report_exact_values():
    exact, _ = _run(texts=("a one", "a two", "a three"), measured_iterations=3)
    assert (exact.case_count, exact.cases_measured, exact.measured_iterations) == (
        3,
        3,
        3,
    )
    cycled, _ = _run(texts=("a one", "a two"), measured_iterations=7)
    assert (cycled.case_count, cycled.cases_measured, cycled.measured_iterations) == (
        2,
        2,
        7,
    )


def test_report_cannot_claim_coverage_it_did_not_measure():
    report, _ = _run()
    payload = report.model_dump()
    payload["cases_measured"] = (
        payload["case_count"] - 1 if payload["case_count"] > 1 else 1
    )
    payload["case_count"] = 3
    payload["measured_iterations"] = 2
    with pytest.raises(ValidationError):
        NativeBenchmarkReport.model_validate(payload)


def test_cases_rejected_by_inference_fail_without_leaking_text():
    inference, policy, config, _ = _setup()
    with pytest.raises(NativeBenchmarkError) as caught:
        run_native_benchmark(
            inference=inference, policy=policy, texts=("   ", "ok text"), config=config
        )
    assert caught.value.code == "CASE_REJECTED_BY_INFERENCE"
    assert "ok text" not in str(caught.value)
    assert "   " not in str(caught.value).split("]", 1)[1]


# --- budget semantics ------------------------------------------------------------


class _FakeClock:
    """Each measured call pair spans exactly one millisecond."""

    def __init__(self) -> None:
        self.now = 0
        self.calls = 0

    def __call__(self) -> int:
        self.calls += 1
        if self.calls % 2 == 0:
            self.now += 1_000_000
        return self.now


def test_latency_budget_boundary_is_inclusive(monkeypatch):
    for budget, expected in ((1.0, True), (0.999, False), (1.001, True)):
        monkeypatch.setattr(native_benchmark.time, "perf_counter_ns", _FakeClock())
        report, _ = _run(latency_budget_ms=budget)
        assert report.latency_max_ms == pytest.approx(1.0)
        assert report.within_declared_budgets is expected


def test_memory_budget_boundary_is_inclusive(monkeypatch):
    monkeypatch.setattr(
        native_benchmark.tracemalloc, "get_traced_memory", lambda: (0, 2048)
    )
    for budget, expected in ((2048, True), (2047, False), (4096, True)):
        report, _ = _run(peak_memory_budget_bytes=budget)
        assert report.peak_traced_memory_bytes == 2048
        assert report.within_declared_budgets is expected


def test_budget_verdict_cannot_be_forged_in_a_report():
    report, _ = _run(latency_budget_ms=60000.0)
    payload = report.model_dump()
    payload["declared_latency_budget_ms"] = 0.0001
    payload["latency_max_ms"] = 5.0
    payload["within_declared_budgets"] = True
    with pytest.raises(ValidationError):
        NativeBenchmarkReport.model_validate(payload)


# --- tracemalloc state ------------------------------------------------------------


def test_a_trace_started_by_the_benchmark_is_stopped():
    assert not tracemalloc.is_tracing()
    report, _ = _run()
    assert report.peak_traced_memory_bytes > 0
    assert not tracemalloc.is_tracing()


def test_active_tracing_is_rejected_without_changing_tracer_state(monkeypatch):
    inference, policy, config, _ = _setup()
    tracemalloc.start(3)
    try:
        # Raise the peak well above current usage so a reset would be visible.
        ballast = [bytes(1024) for _ in range(2000)]
        del ballast
        before_limit = tracemalloc.get_traceback_limit()
        _, peak_before = tracemalloc.get_traced_memory()

        def _forbidden(*_args, **_kwargs):
            raise AssertionError("benchmark mutated a pre-existing trace")

        monkeypatch.setattr(tracemalloc, "reset_peak", _forbidden)
        monkeypatch.setattr(tracemalloc, "stop", _forbidden)
        monkeypatch.setattr(tracemalloc, "start", _forbidden)

        with pytest.raises(NativeBenchmarkError) as caught:
            run_native_benchmark(
                inference=inference, policy=policy, texts=TEXTS, config=config
            )
        assert caught.value.code == "TRACEMALLOC_ALREADY_ACTIVE"
        assert tracemalloc.is_tracing()
        assert tracemalloc.get_traceback_limit() == before_limit
        _, peak_after = tracemalloc.get_traced_memory()
        assert peak_after >= peak_before
    finally:
        monkeypatch.undo()
        tracemalloc.stop()
    assert not tracemalloc.is_tracing()


def test_active_tracing_is_rejected_before_any_inference_runs():
    inference, policy, config, _ = _setup()
    calls = []
    original = inference.predict_text
    inference.predict_text = lambda text: calls.append(text) or original(text)
    tracemalloc.start()
    try:
        with pytest.raises(NativeBenchmarkError) as caught:
            run_native_benchmark(
                inference=inference, policy=policy, texts=TEXTS, config=config
            )
        assert caught.value.code == "TRACEMALLOC_ALREADY_ACTIVE"
    finally:
        tracemalloc.stop()
    assert calls == []


def test_trace_is_stopped_when_a_case_fails_mid_run():
    inference, policy, config, _ = _setup()
    assert not tracemalloc.is_tracing()
    with pytest.raises(NativeBenchmarkError) as caught:
        # Passes the identity probe, then fails once cycling hits the case
        # that tokenizes to nothing during measurement.
        run_native_benchmark(
            inference=inference,
            policy=policy,
            texts=("synthetic ok", "..."),
            config=config,
        )
    assert caught.value.code == "CASE_REJECTED_BY_INFERENCE"
    assert not tracemalloc.is_tracing()


def test_memory_is_described_as_traced_memory_not_process_memory():
    fields = set(NativeBenchmarkReport.model_fields)
    assert "peak_traced_memory_bytes" in fields
    assert not any("resident" in name or "rss" in name for name in fields)


# --- contract version and policy identity -------------------------------------------


def test_contract_version_is_three_and_old_shape_is_rejected():
    assert BENCHMARK_CONTRACT_VERSION == "3"
    report, _ = _run()
    assert report.contract_version == "3"
    assert "tracemalloc_was_active_on_entry" not in NativeBenchmarkReport.model_fields
    payload = report.model_dump()
    payload["contract_version"] = "2"
    with pytest.raises(ValidationError):
        NativeBenchmarkReport.model_validate(payload)
    payload = report.model_dump()
    payload.pop("policy_hash")
    with pytest.raises(ValidationError):
        NativeBenchmarkReport.model_validate(payload)
    payload = report.model_dump()
    payload["tracemalloc_was_active_on_entry"] = False
    with pytest.raises(ValidationError):
        NativeBenchmarkReport.model_validate(payload)


def test_report_binds_the_exact_policy_hash_from_the_policy_object():
    inference, policy, config, _ = _setup()
    report = run_native_benchmark(
        inference=inference, policy=policy, texts=TEXTS, config=config
    )
    assert report.policy_hash == policy.policy_hash()
    assert report.policy_hash in report.model_dump_json()


def test_different_policies_produce_different_report_policy_hashes():
    inference, policy, config, _ = _setup()
    other_policy = SuggestionValidationPolicy(
        task_id="other-synthetic-task",
        expected_model_version=policy.expected_model_version,
        expected_vocabulary_hash=policy.expected_vocabulary_hash,
        allowed_labels=policy.allowed_labels,
        minimum_probability=policy.minimum_probability,
        maximum_suggestions=policy.maximum_suggestions,
    )
    first = run_native_benchmark(
        inference=inference, policy=policy, texts=TEXTS, config=config
    )
    second = run_native_benchmark(
        inference=inference, policy=other_policy, texts=TEXTS, config=config
    )
    assert first.policy_hash != second.policy_hash
    assert second.policy_hash == other_policy.policy_hash()


def test_report_rejects_a_malformed_policy_hash():
    report, _ = _run()
    for bad in ("", "f" * 63, "F" * 64, "g" * 64):
        payload = report.model_dump()
        payload["policy_hash"] = bad
        with pytest.raises(ValidationError):
            NativeBenchmarkReport.model_validate(payload)


def test_policy_for_another_model_or_vocabulary_is_rejected():
    inference, policy, config, _ = _setup()
    wrong_model = SuggestionValidationPolicy(
        task_id=policy.task_id,
        expected_model_version="other-model",
        expected_vocabulary_hash=policy.expected_vocabulary_hash,
        allowed_labels=policy.allowed_labels,
        minimum_probability=policy.minimum_probability,
        maximum_suggestions=policy.maximum_suggestions,
    )
    with pytest.raises(NativeBenchmarkError) as caught:
        run_native_benchmark(
            inference=inference, policy=wrong_model, texts=TEXTS, config=config
        )
    assert caught.value.code == "MODEL_POLICY_MISMATCH"
    wrong_vocabulary = SuggestionValidationPolicy(
        task_id=policy.task_id,
        expected_model_version=policy.expected_model_version,
        expected_vocabulary_hash="b" * 64,
        allowed_labels=policy.allowed_labels,
        minimum_probability=policy.minimum_probability,
        maximum_suggestions=policy.maximum_suggestions,
    )
    with pytest.raises(NativeBenchmarkError) as caught:
        run_native_benchmark(
            inference=inference, policy=wrong_vocabulary, texts=TEXTS, config=config
        )
    assert caught.value.code == "VOCABULARY_POLICY_MISMATCH"
    assert not tracemalloc.is_tracing()


# --- public artifact-hash API ---------------------------------------------------------


def test_artifact_hash_is_a_public_read_only_inference_property():
    inference, _, _, artifact = _setup()
    assert isinstance(NativeLocalInference.artifact_hash, property)
    assert NativeLocalInference.artifact_hash.fset is None
    assert inference.artifact_hash == artifact.artifact_hash
    with pytest.raises(AttributeError):
        inference.artifact_hash = "f" * 64  # type: ignore[misc]


def test_report_artifact_hash_comes_from_the_public_property():
    artifact, vocabulary = _artifact()
    sentinel = "a" * 64

    class _Probe(NativeLocalInference):
        @property
        def artifact_hash(self) -> str:
            return sentinel

    probe = _Probe(
        artifact=artifact,
        vocabulary=vocabulary,
        labels=LABEL_SPACE,
        config=NativeInferenceConfig(top_k=2, minimum_probability=0.0),
    )
    _, policy = _inference_and_policy(artifact, vocabulary)
    report = run_native_benchmark(
        inference=probe, policy=policy, texts=TEXTS, config=_config()
    )
    assert report.artifact_hash == sentinel


# --- workload digest helper -----------------------------------------------------------


def test_public_case_set_digest_matches_the_report_and_is_sensitive():
    report, _ = _run()
    assert report.case_set_digest == case_set_digest(TEXTS)
    assert case_set_digest(TEXTS) != case_set_digest(tuple(reversed(TEXTS)))
    assert case_set_digest(TEXTS) != case_set_digest(TEXTS[:1])
    assert case_set_digest(TEXTS) != case_set_digest(("synthetic one", "synthetic 2"))
