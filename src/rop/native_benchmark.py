"""Task 214: offline CPU latency and memory benchmark for local inference.

This measurement harness accepts an already-loaded local inference adapter.
It performs no network calls and does not persist inputs or outputs. Measurements
are descriptive; they are not clinical utility or release acceptance claims.

The report is auditable: it names the exact artifact (taken from the validated
inference adapter, never from a caller-supplied string), a hash of the exact
benchmark configuration, the declared budgets used for the budget verdict, and
a privacy-safe digest of the ordered case set, and the hash of the strict
suggestion policy the benchmark validated against (taken from the policy object
itself). Coverage policy: every supplied case must be measured at least once,
so ``measured_iterations`` must be at least the number of cases; cases are then
cycled in order. Memory is Python ``tracemalloc`` traced memory, not
whole-process resident memory. ``tracemalloc`` is process-global, so a trace
that is already active is never reset, stopped or measured through: the
benchmark refuses to run (``TRACEMALLOC_ALREADY_ACTIVE``) rather than report a
peak contaminated by unrelated caller allocations.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
import tracemalloc
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from rop.native_inference import (
    NativeInferenceError,
    NativeInferenceResponse,
    NativeLocalInference,
)
from rop.native_suggestion_validation import (
    SuggestionValidationPolicy,
    validate_suggestion_response,
)

MAX_BENCHMARK_CASES = 10000
# Version 3 adds ``policy_hash`` to the report and removes
# ``tracemalloc_was_active_on_entry`` (an active trace is now rejected, so it
# could only ever be False).
BENCHMARK_CONTRACT_VERSION = "3"
_CONFIG_HASH_DOMAIN = "rop.native_benchmark.config.v3"
_CASE_SET_DOMAIN = "rop.native_benchmark.case_set.v3"


def _domain_hash(domain: str, payload: object) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(f"{domain}\n{body}".encode()).hexdigest()


class NativeBenchmarkError(Exception):
    """Stable benchmark failure without raw text or environment details."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


class NativeBenchmarkConfig(BaseModel):
    """Bounded measurement repetitions and caller-declared budgets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["3"] = BENCHMARK_CONTRACT_VERSION
    warmup_iterations: StrictInt = Field(ge=0, le=100)
    measured_iterations: StrictInt = Field(ge=1, le=10000)
    latency_budget_ms: StrictFloat = Field(gt=0.0, le=60000.0)
    peak_memory_budget_bytes: StrictInt = Field(ge=1024, le=2**31)

    def config_hash(self) -> str:
        """Canonical hash of the complete benchmark configuration."""
        return _domain_hash(_CONFIG_HASH_DOMAIN, self.model_dump(mode="json"))


class NativeBenchmarkReport(BaseModel):
    """Privacy-safe benchmark summary; no prompts or predictions retained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["3"] = BENCHMARK_CONTRACT_VERSION
    model_version: StrictStr = Field(min_length=1, max_length=32)
    vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    policy_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    benchmark_config_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    case_set_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    declared_latency_budget_ms: StrictFloat = Field(gt=0.0, le=60000.0)
    declared_peak_memory_budget_bytes: StrictInt = Field(ge=1024, le=2**31)
    case_count: StrictInt = Field(ge=1, le=MAX_BENCHMARK_CASES)
    cases_measured: StrictInt = Field(ge=1, le=MAX_BENCHMARK_CASES)
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

    @model_validator(mode="after")
    def _coverage_and_budget_verdict_are_truthful(self) -> NativeBenchmarkReport:
        if self.cases_measured != self.case_count:
            raise ValueError("every supplied case must have been measured")
        if self.measured_iterations < self.case_count:
            raise ValueError("measured iterations cannot cover every case")
        expected = (
            self.latency_max_ms <= self.declared_latency_budget_ms
            and self.peak_traced_memory_bytes <= self.declared_peak_memory_budget_bytes
        )
        if self.within_declared_budgets is not expected:
            raise ValueError("budget verdict contradicts the declared budgets")
        return self


def _percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1))
    return ordered[index]


def case_set_digest(texts: tuple[str, ...]) -> str:
    """Privacy-safe digest: ordered per-case SHA-256 digests, never raw text.

    Public so an acceptance gate can recompute the expected workload digest
    from its own held-out inputs and compare it to a benchmark report.
    """
    return _domain_hash(
        _CASE_SET_DOMAIN,
        [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts],
    )


def _score(inference: NativeLocalInference, text: str) -> NativeInferenceResponse:
    try:
        return inference.predict_text(text)
    except NativeInferenceError as error:
        # Carry only the stable code; never the case text.
        raise NativeBenchmarkError(
            "CASE_REJECTED_BY_INFERENCE",
            f"a benchmark case was rejected by inference ({error.code})",
        ) from None


def run_native_benchmark(
    *,
    inference: NativeLocalInference,
    policy: SuggestionValidationPolicy,
    texts: tuple[str, ...],
    config: NativeBenchmarkConfig,
) -> NativeBenchmarkReport:
    """Measure local tokenization, inference and strict validation end-to-end."""
    if not texts or len(texts) > MAX_BENCHMARK_CASES:
        raise NativeBenchmarkError(
            "CASE_COUNT_INVALID", "benchmark requires a bounded nonempty case set"
        )
    if any(not isinstance(value, str) for value in texts):
        raise NativeBenchmarkError(
            "CASE_TYPE_INVALID", "all benchmark cases must be text strings"
        )
    if config.measured_iterations < len(texts):
        raise NativeBenchmarkError(
            "CASE_COVERAGE_INSUFFICIENT",
            "measured iterations must cover every benchmark case at least once",
        )
    # tracemalloc is process-global. reset_peak() or stop() would mutate a
    # session owned by unrelated caller code, and measuring inside it would
    # include allocations this benchmark did not make, so refuse up front.
    if tracemalloc.is_tracing():
        raise NativeBenchmarkError(
            "TRACEMALLOC_ALREADY_ACTIVE",
            "a tracemalloc session is already active; the benchmark will not "
            "reset, stop or measure through it",
        )
    artifact_hash = inference.artifact_hash
    policy_hash = policy.policy_hash()
    identity_response = _score(inference, texts[0])
    if identity_response.model_version != policy.expected_model_version:
        raise NativeBenchmarkError(
            "MODEL_POLICY_MISMATCH", "benchmark policy does not match the local model"
        )
    if identity_response.vocabulary_hash != policy.expected_vocabulary_hash:
        raise NativeBenchmarkError(
            "VOCABULARY_POLICY_MISMATCH",
            "benchmark policy does not match the local vocabulary",
        )

    for index in range(config.warmup_iterations):
        response = _score(inference, texts[index % len(texts)])
        validate_suggestion_response(response, policy)

    elapsed_ms: list[float] = []
    output_digests: list[str] = []
    # No trace was active on entry (checked above), so this call owns the
    # session it starts and always stops it.
    tracemalloc.start()
    try:
        for index in range(config.measured_iterations):
            text = texts[index % len(texts)]
            start = time.perf_counter_ns()
            response = _score(inference, text)
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
    within_budget = (
        maximum_ms <= config.latency_budget_ms
        and peak_memory <= config.peak_memory_budget_bytes
    )
    return NativeBenchmarkReport(
        model_version=identity_response.model_version,
        vocabulary_hash=identity_response.vocabulary_hash,
        artifact_hash=artifact_hash,
        policy_hash=policy_hash,
        benchmark_config_hash=config.config_hash(),
        case_set_digest=case_set_digest(texts),
        declared_latency_budget_ms=config.latency_budget_ms,
        declared_peak_memory_budget_bytes=config.peak_memory_budget_bytes,
        case_count=len(texts),
        cases_measured=min(len(texts), config.measured_iterations),
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
    "BENCHMARK_CONTRACT_VERSION",
    "NativeBenchmarkConfig",
    "NativeBenchmarkError",
    "NativeBenchmarkReport",
    "case_set_digest",
    "run_native_benchmark",
]
