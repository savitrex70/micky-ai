"""Task 214: bounded offline inference benchmark contracts.

Data-only contracts for measuring the existing Task 212 local inference
path together with the Task 213 strict suggestion-validation boundary.
No runtime, no model, no network, and no clinical logic live here.

A benchmark case is an ordered tuple of token IDs. The report carries
only digests, statistics, budgets, and identity bindings — never raw
case content, predictions, prompts, secrets, or key material. The
case-set digest is a keyed HMAC, not a plain hash: unkeyed hashing
would leave low-entropy case content guessable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
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

BENCHMARK_CONTRACT_VERSION = "1"
MAX_BENCHMARK_CASES = 10000
MAX_WARMUP_ITERATIONS = 100
MAX_MEASURED_ITERATIONS = 10000
MAX_LATENCY_BUDGET_MS = 60000.0
MIN_MEMORY_BUDGET_BYTES = 1024
MAX_MEMORY_BUDGET_BYTES = 2**31

_CONFIG_HASH_DOMAIN = "rop.benchmark.config.v1"
_CASE_SET_DOMAIN = "rop.benchmark.case_set.v2"
_OUTPUT_DOMAIN = "rop.benchmark.output.v1"

MIN_CASE_SET_KEY_BYTES = 16
MAX_CASE_SET_KEY_BYTES = 256


class BenchmarkErrorCode(StrEnum):
    """Stable, sanitized benchmark failure codes (Task 214)."""

    INVALID_INPUT = "INVALID_INPUT"
    INVALID_CONFIG = "INVALID_CONFIG"
    CASE_COUNT_INVALID = "CASE_COUNT_INVALID"
    CASE_TYPE_INVALID = "CASE_TYPE_INVALID"
    CASE_VALUE_INVALID = "CASE_VALUE_INVALID"
    CASE_COVERAGE_INSUFFICIENT = "CASE_COVERAGE_INSUFFICIENT"
    MODEL_POLICY_MISMATCH = "MODEL_POLICY_MISMATCH"
    VOCABULARY_POLICY_MISMATCH = "VOCABULARY_POLICY_MISMATCH"
    CASE_REJECTED_BY_INFERENCE = "CASE_REJECTED_BY_INFERENCE"
    CASE_REJECTED_BY_VALIDATION = "CASE_REJECTED_BY_VALIDATION"
    INVALID_MEASUREMENT = "INVALID_MEASUREMENT"
    TRACEMALLOC_ALREADY_ACTIVE = "TRACEMALLOC_ALREADY_ACTIVE"


def _domain_hash(domain: str, payload: object) -> str:
    """SHA-256 over a domain prefix plus canonical JSON.

    Canonical form is sorted-key compact JSON with ``allow_nan=False``,
    so NaN and infinity can never be hashed into a persistent identity.
    Python's built-in ``hash()`` is never used for persistent digests.
    """
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(f"{domain}\n{body}".encode()).hexdigest()


def case_set_digest(cases: tuple[list[int], ...], *, key: bytes) -> str:
    """Keyed, privacy-preserving digest of the ordered benchmark case set.

    A plain hash of each low-entropy case would be guessable, so this is
    an HMAC-SHA-256 keyed by a caller-supplied secret over the domain
    prefix plus the canonical JSON of the entire ordered case set. The
    key is never included in any report, log, or error. Authorized
    verification recomputes this function over the same ordered cases
    with the same key, which the caller distributes out of band.
    """
    if (
        not isinstance(key, bytes)
        or isinstance(key, bool)
        or not MIN_CASE_SET_KEY_BYTES <= len(key) <= MAX_CASE_SET_KEY_BYTES
    ):
        raise ValueError("case-set digest key is invalid")
    body = json.dumps(
        [list(case) for case in cases],
        separators=(",", ":"),
        allow_nan=False,
    )
    return hmac.new(
        key, f"{_CASE_SET_DOMAIN}\n{body}".encode(), hashlib.sha256
    ).hexdigest()


def output_digest(output_hashes: list[str]) -> str:
    """Deterministic digest of the ordered validated-output hashes."""
    return _domain_hash(_OUTPUT_DOMAIN, output_hashes)


class BenchmarkConfig(BaseModel):
    """Bounded workload repetitions and caller-declared budgets.

    Budgets are declared expectations used only for the report's
    budget verdict. They are not system-enforced resource limits.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = BENCHMARK_CONTRACT_VERSION
    warmup_iterations: StrictInt = Field(ge=0, le=MAX_WARMUP_ITERATIONS)
    measured_iterations: StrictInt = Field(ge=1, le=MAX_MEASURED_ITERATIONS)
    latency_budget_ms: StrictFloat = Field(gt=0.0, le=MAX_LATENCY_BUDGET_MS)
    peak_memory_budget_bytes: StrictInt = Field(
        ge=MIN_MEMORY_BUDGET_BYTES, le=MAX_MEMORY_BUDGET_BYTES
    )

    def config_hash(self) -> str:
        """Canonical hash of the complete benchmark configuration."""
        return _domain_hash(_CONFIG_HASH_DOMAIN, self.model_dump(mode="json"))


class BenchmarkReport(BaseModel):
    """Validated, immutable, privacy-safe benchmark report.

    Identity fields are bound to the actual validated inference
    artifact, vocabulary, and validation policy — never to
    caller-supplied identity strings. No prompts, case content,
    predictions, secrets, or machine-specific details are retained.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["1"] = BENCHMARK_CONTRACT_VERSION
    artifact_id: StrictStr = Field(min_length=1, max_length=64)
    vocabulary_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    policy_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    benchmark_config_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    case_set_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    declared_latency_budget_ms: StrictFloat = Field(gt=0.0, le=MAX_LATENCY_BUDGET_MS)
    declared_peak_memory_budget_bytes: StrictInt = Field(
        ge=MIN_MEMORY_BUDGET_BYTES, le=MAX_MEMORY_BUDGET_BYTES
    )
    case_count: StrictInt = Field(ge=1, le=MAX_BENCHMARK_CASES)
    cases_measured: StrictInt = Field(ge=1, le=MAX_BENCHMARK_CASES)
    warmup_iterations: StrictInt = Field(ge=0, le=MAX_WARMUP_ITERATIONS)
    measured_iterations: StrictInt = Field(ge=1, le=MAX_MEASURED_ITERATIONS)
    latency_mean_ms: StrictFloat = Field(ge=0.0, allow_inf_nan=False)
    latency_median_ms: StrictFloat = Field(ge=0.0, allow_inf_nan=False)
    latency_p95_ms: StrictFloat = Field(ge=0.0, allow_inf_nan=False)
    latency_max_ms: StrictFloat = Field(ge=0.0, allow_inf_nan=False)
    peak_traced_memory_bytes: StrictInt = Field(ge=0)
    output_digest: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    within_declared_budgets: StrictBool
    execution_mode: Literal["LOCAL_CPU_OFFLINE"] = "LOCAL_CPU_OFFLINE"
    clinical_utility_established: Literal[False] = False

    @model_validator(mode="after")
    def _report_is_truthful(self) -> BenchmarkReport:
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
        self._latency_statistics_describe_one_sample_set()
        self._config_hash_matches_recorded_configuration()
        return self

    def _latency_statistics_describe_one_sample_set(self) -> None:
        """Reject only relationships no single sample set can produce.

        The mean is deliberately not ordered against the median or p95:
        a skewed sample set can put it on either side of both.
        """
        statistics_ms = (
            self.latency_mean_ms,
            self.latency_median_ms,
            self.latency_p95_ms,
            self.latency_max_ms,
        )
        if not all(
            isinstance(value, float)
            and value == value
            and value != float("inf")
            and value != float("-inf")
            and value >= 0.0
            for value in statistics_ms
        ):
            raise ValueError("latency statistics must be finite and nonnegative")
        if (
            self.latency_median_ms > self.latency_p95_ms
            or self.latency_p95_ms > self.latency_max_ms
            or self.latency_mean_ms > self.latency_max_ms
        ):
            raise ValueError(
                "latency statistics are inconsistent: median <= p95 <= max and "
                "mean <= max must hold"
            )

    def _config_hash_matches_recorded_configuration(self) -> None:
        """The recorded configuration fields must reproduce the hash."""
        recorded = BenchmarkConfig(
            contract_version=self.contract_version,
            warmup_iterations=self.warmup_iterations,
            measured_iterations=self.measured_iterations,
            latency_budget_ms=self.declared_latency_budget_ms,
            peak_memory_budget_bytes=self.declared_peak_memory_budget_bytes,
        )
        if recorded.config_hash() != self.benchmark_config_hash:
            raise ValueError(
                "benchmark configuration hash does not match the recorded configuration"
            )


__all__ = [
    "BENCHMARK_CONTRACT_VERSION",
    "MAX_BENCHMARK_CASES",
    "MAX_CASE_SET_KEY_BYTES",
    "MAX_MEASURED_ITERATIONS",
    "MAX_WARMUP_ITERATIONS",
    "MIN_CASE_SET_KEY_BYTES",
    "BenchmarkConfig",
    "BenchmarkErrorCode",
    "BenchmarkReport",
    "case_set_digest",
    "output_digest",
]
