"""Task 214: offline CPU latency and memory benchmark for local inference.

This measurement harness accepts an already-loaded local inference adapter.
It performs no network calls and does not persist inputs or outputs. Measurements
are descriptive; they are not clinical utility or release acceptance claims.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
import tracemalloc
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

from rop.native_inference import NativeLocalInference
from rop.native_suggestion_validation import SuggestionValidationPolicy, validate_suggestion_response

MAX_BENCHMARK_CASES = 10000


class NativeBenchmarkError(Exception):
    """Stable benchmark failure without raw text or environment details."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


class NativeBenchmarkConfig(BaseModel):
    """Bounded measurement repetitions and caller-declared budgets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    warmup_iterations: StrictInt = Field(ge=0, le=100)
    measured_iterations: StrictInt = Field(ge=1, le=10000)
    latency_budget_ms: StrictFloat = Field(gt=0.0, le=60000.0)
    peak_memory_budget_bytes: StrictInt = Field(ge=1024, le=2**31)


class NativeBenchmarkReport(BaseModel):
    """Privacy-safe benchmark summary; no prompts or predictions retained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = "1"
    model_version: StrictStr = Field(min_length=1, max_length=32)
    vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    case_count: StrictInt = Field(ge=1, le=MAX_BENCHMARK_CASES)
    warmup_iterations: StrictInt = Field(ge=0, le=100)
    measured_iterations: StrictInt = Field(ge=1, le=10000)
    latency_mean_ms: StrictFloat = Field(ge=0.0)
    latency_median_ms: StrictFloat = Field(ge=0.0)
    latency_p95_ms: StrictFloat = Field(ge=0.0)
    latency_max_ms: StrictFloat = Field(ge=0.0)
    peak_traced_memory_bytes: StrictInt = Field(ge=0)
    output_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    within_declared_budgets: StrictBool
    execution_mode: Literal["LOCAL_CPU_OFFLINE"] = "LOCAL_CPU_OFFLINE"
    clinical_utility_established: Literal[False] = False


def _percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1))
    return ordered[index]


def run_native_benchmark(
    *,
    inference: NativeLocalInference,
    policy: SuggestionValidationPolicy,
    texts: tuple[str, ...],
    config: NativeBenchmarkConfig,
) -> NativeBenchmarkReport:
    """Measure local tokenization, inference and strict validation end-to-end."""
    if not texts or len(texts) > MAX_BENCHMARK_CASES:
        raise NativeBenchmarkError("CASE_COUNT_INVALID", "benchmark requires a bounded nonempty case set")
    if any(not isinstance(value, str) for value in texts):
        raise NativeBenchmarkError("CASE_TYPE_INVALID", "all benchmark cases must be text strings")
    if inference._artifact.model_config_payload.model_version != policy.expected_model_version:
        raise NativeBenchmarkError("MODEL_POLICY_MISMATCH", "benchmark policy does not match the local model")
    if inference._vocabulary.vocabulary_hash != policy.expected_vocabulary_hash:
        raise NativeBenchmarkError("VOCABULARY_POLICY_MISMATCH", "benchmark policy does not match the local vocabulary")

    for index in range(config.warmup_iterations):
        response = inference.predict_text(texts[index % len(texts)])
        validate_suggestion_response(response, policy)

    elapsed_ms: list[float] = []
    output_digests: list[str] = []
    tracemalloc.start()
    try:
        for index in range(config.measured_iterations):
            text = texts[index % len(texts)]
            start = time.perf_counter_ns()
            response = inference.predict_text(text)
            validated = validate_suggestion_response(response, policy)
            elapsed_ms.append((time.perf_counter_ns() - start) / 1_000_000.0)
            output_digests.append(validated.result_hash)
        _, peak_memory = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    output_digest = hashlib.sha256(
        json.dumps(output_digests, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    mean_ms = statistics.fmean(elapsed_ms)
    median_ms = statistics.median(elapsed_ms)
    p95_ms = _percentile95(elapsed_ms)
    maximum_ms = max(elapsed_ms)
    within_budget = maximum_ms <= config.latency_budget_ms and peak_memory <= config.peak_memory_budget_bytes
    return NativeBenchmarkReport(
        model_version=inference._artifact.model_config_payload.model_version,
        vocabulary_hash=inference._vocabulary.vocabulary_hash,
        case_count=len(texts),
        warmup_iterations=config.warmup_iterations,
        measured_iterations=config.measured_iterations,
        latency_mean_ms=mean_ms,
        latency_median_ms=median_ms,
        latency_p95_ms=p95_ms,
        latency_max_ms=maximum_ms,
        peak_traced_memory_bytes=peak_memory,
        output_digest=output_digest,
        within_declared_budgets=within_budget,
    )


__all__ = [
    "NativeBenchmarkConfig",
    "NativeBenchmarkError",
    "NativeBenchmarkReport",
    "run_native_benchmark",
]
