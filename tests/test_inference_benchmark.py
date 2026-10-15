"""Task 214: bounded offline inference benchmark tests.

Synthetic tests only: a stub model inside a hand-built inference
session, a synthetic vocabulary, and the strict Task 213 adapter with
synthetic SUPPORTED deterministic scaffolding minted by the benchmark.
No checkpoints, downloads, hosted services, patient data, or network.
"""

from __future__ import annotations

import tracemalloc
from uuid import UUID

import pytest
import torch
from pydantic import ValidationError

from rop.inference.advisory import AdvisoryAdapter, AdvisoryAdapterError
from rop.inference.benchmark import (
    BenchmarkError,
    policy_hash,
    run_inference_benchmark,
)
from rop.inference.runtime import InferenceSession
from rop.schemas.advisory import (
    AdvisoryAdapterResult,
    AdvisoryClassLabelMapping,
)
from rop.schemas.benchmark import (
    MAX_BENCHMARK_CASES,
    BenchmarkConfig,
    BenchmarkErrorCode,
    BenchmarkReport,
    case_set_digest,
)
from rop.schemas.inference import InferenceResult
from rop.schemas.tokenizer import Vocabulary

ARTIFACT_ID = "artifact-synthetic"
VOCAB_HASH = "c" * 64
VOCAB_SIZE = 8
APPROVED_LABELS = ("alpha", "beta", "gamma")


class _StubModel:
    """Deterministic stand-in for a loaded CPU model."""

    def __init__(self, logits: tuple[float, ...]) -> None:
        self._logits = tuple(logits)
        self.training = False
        self.calls = 0

    def eval(self) -> _StubModel:
        self.training = False
        return self

    def train(self, mode: bool = True) -> _StubModel:
        self.training = mode
        return self

    def __call__(self, token_ids: torch.Tensor) -> torch.Tensor:
        self.calls += 1
        batch = token_ids.shape[0]
        return torch.tensor([list(self._logits)] * batch, dtype=torch.float32)


class _FailingModel(_StubModel):
    """Succeeds for a fixed number of calls, then returns bad output."""

    def __init__(self, logits: tuple[float, ...], *, fail_after: int) -> None:
        super().__init__(logits)
        self._fail_after = fail_after

    def __call__(self, token_ids: torch.Tensor) -> torch.Tensor:
        self.calls += 1
        if self.calls > self._fail_after:
            return torch.tensor([[0.0, 0.0]], dtype=torch.float32)
        batch = token_ids.shape[0]
        return torch.tensor([list(self._logits)] * batch, dtype=torch.float32)


class _StepClock:
    """Deterministic perf_counter_ns replacement with per-iteration steps."""

    def __init__(self, step_ns: list[float]) -> None:
        self._steps = list(step_ns)
        self._time = 0.0
        self._calls = 0

    def __call__(self) -> float:
        if self._calls % 2 == 1:
            self._time += self._steps[(self._calls // 2) % len(self._steps)]
        self._calls += 1
        return self._time


def _session(model: _StubModel | None = None) -> InferenceSession:
    return InferenceSession(
        model=model if model is not None else _StubModel((2.0, 0.5, 1.0)),
        artifact_id=ARTIFACT_ID,
        vocab_size=VOCAB_SIZE,
        max_seq_len=16,
        num_classes=3,
    )


def _vocabulary() -> Vocabulary:
    return Vocabulary.model_validate(
        {
            "metadata": {
                "vocabulary_version": "1.0",
                "tokenizer_version": "1.0",
                "policy_version": "1.0",
                "tokenizer_config_hash": "d" * 64,
                "reserved_tokens": ["<pad>", "<unk>"],
                "vocabulary_size": VOCAB_SIZE,
                "max_vocab_size": 16,
                "min_frequency": 1,
                "vocabulary_hash": VOCAB_HASH,
                "dataset_id": "synthetic-bench",
                "dataset_integrity_hash": "e" * 64,
                "split_assignment_hash": "f" * 64,
                "data_scope": "synthetic-test-only",
                "metadata_integrity_hash": "a" * 64,
            },
            "tokens": ["<pad>", "<unk>"]
            + [f"tok-{index}" for index in range(2, VOCAB_SIZE)],
        }
    )


def _adapter() -> AdvisoryAdapter:
    return AdvisoryAdapter(
        class_label_mapping=AdvisoryClassLabelMapping.model_validate(
            {
                "contract_version": "1",
                "mapping_id": "task-214-synthetic-mapping",
                "num_classes": 3,
                "entries": [
                    {"class_index": 0, "label": "alpha"},
                    {"class_index": 2, "label": "beta"},
                ],
            }
        ),
        approved_labels=APPROVED_LABELS,
    )


def _config(**overrides: object) -> BenchmarkConfig:
    payload: dict[str, object] = {
        "warmup_iterations": 1,
        "measured_iterations": 4,
        "latency_budget_ms": 60000.0,
        "peak_memory_budget_bytes": 2**31,
    }
    payload.update(overrides)
    return BenchmarkConfig.model_validate(payload)


def _run(**overrides: object) -> BenchmarkReport:
    payload: dict[str, object] = {
        "session": _session(),
        "vocabulary": _vocabulary(),
        "adapter": _adapter(),
        "cases": [(2, 3), (4, 5, 6)],
        "config": _config(),
        "expected_artifact_id": ARTIFACT_ID,
        "expected_vocabulary_hash": VOCAB_HASH,
    }
    payload.update(overrides)
    return run_inference_benchmark(**payload)  # type: ignore[arg-type]


def test_valid_bounded_benchmark_execution() -> None:
    session = _session()
    report = _run(session=session)
    assert report.contract_version == "1"
    assert report.artifact_id == ARTIFACT_ID
    assert report.vocabulary_hash == VOCAB_HASH
    assert report.policy_hash == policy_hash(_adapter())
    assert report.case_count == 2
    assert report.cases_measured == 2
    assert report.warmup_iterations == 1
    assert report.measured_iterations == 4
    assert report.within_declared_budgets is True
    assert report.execution_mode == "LOCAL_CPU_OFFLINE"
    assert report.clinical_utility_established is False
    assert report.peak_traced_memory_bytes >= 0
    # Warm-up plus measured iterations each run inference once.
    assert session.model.calls == 5
    assert BenchmarkReport.model_validate(report.model_dump()) == report


def test_empty_and_oversized_case_sets_are_rejected() -> None:
    with pytest.raises(BenchmarkError) as raised:
        _run(cases=())
    assert raised.value.code == BenchmarkErrorCode.CASE_COUNT_INVALID
    with pytest.raises(BenchmarkError) as raised:
        _run(cases=tuple([(2,)] * (MAX_BENCHMARK_CASES + 1)))
    assert raised.value.code == BenchmarkErrorCode.CASE_COUNT_INVALID


def test_malformed_cases_are_rejected_without_case_content() -> None:
    with pytest.raises(BenchmarkError) as raised:
        _run(cases=("bad",))
    assert raised.value.code == BenchmarkErrorCode.CASE_TYPE_INVALID
    with pytest.raises(BenchmarkError) as raised:
        _run(cases=[(2, 999)])
    assert raised.value.code == BenchmarkErrorCode.CASE_VALUE_INVALID
    assert "999" not in str(raised.value)
    with pytest.raises(BenchmarkError) as raised:
        _run(cases=[(True, 2)])
    assert raised.value.code == BenchmarkErrorCode.CASE_VALUE_INVALID
    with pytest.raises(BenchmarkError) as raised:
        _run(cases=[()])
    assert raised.value.code == BenchmarkErrorCode.CASE_VALUE_INVALID


def test_insufficient_iteration_coverage_is_rejected() -> None:
    with pytest.raises(BenchmarkError) as raised:
        _run(config=_config(measured_iterations=1))
    assert raised.value.code == BenchmarkErrorCode.CASE_COVERAGE_INSUFFICIENT


def test_identity_mismatch_is_rejected() -> None:
    with pytest.raises(BenchmarkError) as raised:
        _run(expected_artifact_id="artifact-other")
    assert raised.value.code == BenchmarkErrorCode.MODEL_POLICY_MISMATCH
    with pytest.raises(BenchmarkError) as raised:
        _run(expected_vocabulary_hash="0" * 64)
    assert raised.value.code == BenchmarkErrorCode.VOCABULARY_POLICY_MISMATCH
    payload = _vocabulary().model_dump()
    payload["metadata"]["vocabulary_size"] = VOCAB_SIZE
    payload["tokens"] = payload["tokens"][:VOCAB_SIZE]
    other = Vocabulary.model_validate(payload)
    session = InferenceSession(
        model=_StubModel((2.0, 0.5, 1.0)),
        artifact_id=ARTIFACT_ID,
        vocab_size=VOCAB_SIZE + 1,
        max_seq_len=16,
        num_classes=3,
    )
    with pytest.raises(BenchmarkError) as raised:
        _run(session=session, vocabulary=other)
    assert raised.value.code == BenchmarkErrorCode.VOCABULARY_POLICY_MISMATCH


def test_strict_validation_is_applied_to_measured_outputs() -> None:
    # Winning class 1 is unmapped, so the strict boundary rejects it.
    with pytest.raises(BenchmarkError) as raised:
        _run(session=_session(_StubModel((0.0, 5.0, 0.0))))
    assert raised.value.code == BenchmarkErrorCode.CASE_REJECTED_BY_VALIDATION


def test_inference_rejection_is_reported_without_case_content() -> None:
    with pytest.raises(BenchmarkError) as raised:
        _run(session=_session(_StubModel((0.0,))))  # wrong class count
    assert raised.value.code == BenchmarkErrorCode.CASE_REJECTED_BY_INFERENCE


def test_report_identity_and_coverage() -> None:
    config = _config()
    report = _run(config=config)
    assert report.benchmark_config_hash == config.config_hash()
    assert report.case_set_digest == case_set_digest(((2, 3), (4, 5, 6)))
    assert report.cases_measured == report.case_count == 2
    assert report.declared_latency_budget_ms == 60000.0


def test_digests_are_deterministic_for_equivalent_inputs() -> None:
    first = _run()
    second = _run()
    assert first.benchmark_config_hash == second.benchmark_config_hash
    assert first.case_set_digest == second.case_set_digest
    assert first.output_digest == second.output_digest
    assert first.policy_hash == second.policy_hash


def test_report_carries_no_raw_content() -> None:
    report = _run()
    assert set(type(report).model_fields) == {
        "contract_version",
        "artifact_id",
        "vocabulary_hash",
        "policy_hash",
        "benchmark_config_hash",
        "case_set_digest",
        "declared_latency_budget_ms",
        "declared_peak_memory_budget_bytes",
        "case_count",
        "cases_measured",
        "warmup_iterations",
        "measured_iterations",
        "latency_mean_ms",
        "latency_median_ms",
        "latency_p95_ms",
        "latency_max_ms",
        "peak_traced_memory_bytes",
        "output_digest",
        "within_declared_budgets",
        "execution_mode",
        "clinical_utility_established",
    }
    dumped = report.model_dump_json()
    assert "tok-" not in dumped
    assert "prompt" not in dumped.lower()


def test_percentile_and_latency_relationships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _StepClock([1_000_000.0, 2_000_000.0, 3_000_000.0, 4_000_000.0])
    monkeypatch.setattr("rop.inference.benchmark.time.perf_counter_ns", clock)
    report = _run(config=_config(warmup_iterations=0))
    assert report.latency_mean_ms == pytest.approx(2.5)
    assert report.latency_median_ms == pytest.approx(2.5)
    assert report.latency_p95_ms == pytest.approx(4.0)
    assert report.latency_max_ms == pytest.approx(4.0)


def test_single_sample_latency_statistics_are_equal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _StepClock([2_000_000.0])
    monkeypatch.setattr("rop.inference.benchmark.time.perf_counter_ns", clock)
    report = _run(config=_config(warmup_iterations=0, measured_iterations=2))
    assert report.latency_mean_ms == pytest.approx(2.0)
    assert report.latency_median_ms == pytest.approx(2.0)
    assert report.latency_p95_ms == pytest.approx(2.0)
    assert report.latency_max_ms == pytest.approx(2.0)


def test_budget_verdicts_follow_measurements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _StepClock([1_000_000.0])
    monkeypatch.setattr("rop.inference.benchmark.time.perf_counter_ns", clock)
    within = _run(config=_config(warmup_iterations=0, latency_budget_ms=60000.0))
    assert within.within_declared_budgets is True
    over = _run(config=_config(warmup_iterations=0, latency_budget_ms=0.5))
    assert over.within_declared_budgets is False
    assert over.latency_max_ms == pytest.approx(1.0)


def test_invalid_numeric_values_and_inconsistent_reports() -> None:
    with pytest.raises(ValidationError):
        BenchmarkConfig.model_validate(
            {
                "warmup_iterations": 1,
                "measured_iterations": 4,
                "latency_budget_ms": float("nan"),
                "peak_memory_budget_bytes": 2**31,
            }
        )
    with pytest.raises(ValidationError):
        BenchmarkConfig.model_validate(
            {
                "warmup_iterations": 1,
                "measured_iterations": 4,
                "latency_budget_ms": float("inf"),
                "peak_memory_budget_bytes": 2**31,
            }
        )
    report = _run()
    flipped = report.model_dump()
    flipped["within_declared_budgets"] = not report.within_declared_budgets
    with pytest.raises(ValidationError):
        BenchmarkReport.model_validate(flipped)
    skewed = report.model_dump()
    skewed.update({"latency_median_ms": 9.0, "latency_p95_ms": 1.0})
    with pytest.raises(ValidationError):
        BenchmarkReport.model_validate(skewed)


def test_invalid_measurements_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _StepClock([-1_000_000.0])
    monkeypatch.setattr("rop.inference.benchmark.time.perf_counter_ns", clock)
    with pytest.raises(BenchmarkError) as raised:
        _run(config=_config(warmup_iterations=0))
    assert raised.value.code == BenchmarkErrorCode.INVALID_MEASUREMENT


def test_active_tracemalloc_is_rejected_without_disturbing_it() -> None:
    tracemalloc.start()
    try:
        assert tracemalloc.is_tracing()
        with pytest.raises(BenchmarkError) as raised:
            _run()
        assert raised.value.code == BenchmarkErrorCode.TRACEMALLOC_ALREADY_ACTIVE
        # The caller's session is untouched: still tracing, never stopped.
        assert tracemalloc.is_tracing()
    finally:
        tracemalloc.stop()


def test_owned_trace_is_stopped_when_measurement_fails() -> None:
    assert not tracemalloc.is_tracing()
    session = _session(_FailingModel((2.0, 0.5, 1.0), fail_after=2))
    with pytest.raises(BenchmarkError):
        _run(
            session=session, config=_config(warmup_iterations=1, measured_iterations=2)
        )
    assert not tracemalloc.is_tracing()


def test_existing_contracts_remain_unchanged() -> None:
    with pytest.raises(ValidationError):
        InferenceResult.model_validate(
            {
                "artifact_id": ARTIFACT_ID,
                "batch_size": 1,
                "sequence_length": 4,
                "num_classes": 3,
                "logits": ((float("nan"), 0.0, 0.0),),
            }
        )
    with pytest.raises(ValidationError):
        AdvisoryAdapterResult.model_validate(
            {
                "contract_version": "1",
                "artifact_id": ARTIFACT_ID,
                "request_id": UUID(int=1),
                "session_id": UUID(int=2),
                "context_fingerprint": "a" * 64,
                "admissible": True,
                "suggestion": {
                    "candidate_label": "alpha",
                    "softmax_score": 0.5,
                    "advisory_only": True,
                    "provenance": "fabricated",
                },
                "rejection_reason": None,
            }
        )
    with pytest.raises(AdvisoryAdapterError):
        AdvisoryAdapter(
            class_label_mapping="not-a-mapping",  # type: ignore[arg-type]
            approved_labels=APPROVED_LABELS,
        )
