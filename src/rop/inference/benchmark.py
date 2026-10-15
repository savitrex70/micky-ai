"""Task 214: bounded offline benchmark for local inference plus validation.

Measurement harness over the existing Task 212 local CPU inference path
and the Task 213 strict suggestion-validation boundary. It accepts an
already-initialized local inference session, a validated vocabulary, and
a constructed strict validation adapter, then measures the
inference-plus-validation operation end to end and returns an auditable,
privacy-safe report.

Local-only by construction: this module imports no network, provider,
serving, download, or persistence facilities and performs no I/O. That
is a property of the code paths exercised here, not a proof about the
surrounding process.

Memory is Python ``tracemalloc`` traced memory, not process RSS or
total system memory. ``tracemalloc`` is process-global, so a trace that
is already active is never reset, stopped, or measured through: the
benchmark refuses to run rather than report a peak contaminated by
unrelated caller allocations. A session the benchmark starts itself is
always stopped, including on failure.

Deterministic validation contexts used during measurement are synthetic
SUPPORTED scaffolding bound to each case's request identity. They exist
so the strict path — identity matching, evidence binding, and status
gating — executes for real on every measured output. They are not real
reasoning outcomes and carry no evidential weight.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import time
import tracemalloc
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from rop.inference.advisory import AdvisoryAdapter, AdvisoryAdapterError
from rop.inference.runtime import InferenceError, InferenceSession, run_inference
from rop.schemas.advisory import AdvisoryAdapterResult
from rop.schemas.benchmark import (
    MAX_BENCHMARK_CASES,
    MAX_CASE_SET_KEY_BYTES,
    MIN_CASE_SET_KEY_BYTES,
    BenchmarkConfig,
    BenchmarkErrorCode,
    BenchmarkReport,
    case_set_digest,
    output_digest,
)
from rop.schemas.inference import MAX_INFERENCE_SEQUENCE_LENGTH, InferenceRequest
from rop.schemas.native_reasoning import (
    NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
    NATIVE_REASONING_RESULT_SOURCE_TASK_202,
    NativeReasoningRequest,
    NativeReasoningResult,
)
from rop.schemas.tokenizer import Vocabulary

__all__ = [
    "BenchmarkError",
    "policy_hash",
    "run_inference_benchmark",
]

_BENCHMARK_ID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://github.com/savitrex70/micky-ai/task-214-benchmark"
)
_BENCHMARK_SESSION_ID = uuid.uuid5(_BENCHMARK_ID_NAMESPACE, "benchmark-session")
_BENCHMARK_FINGERPRINT = "b" * 64
_BENCHMARK_EVIDENCE_ID = uuid.uuid5(_BENCHMARK_ID_NAMESPACE, "benchmark-evidence")
_BENCHMARK_TASK_ID = "benchmark-measured-v1"
_BENCHMARK_RULE_ID = "benchmark-support-v1"
_POLICY_HASH_DOMAIN = "rop.benchmark.policy.v1"


class BenchmarkError(Exception):
    """A typed benchmark failure with a static, sanitized message."""

    def __init__(self, code: BenchmarkErrorCode, detail: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {detail}")


def policy_hash(adapter: AdvisoryAdapter) -> str:
    """Canonical identity hash of the adapter's validated mapping.

    Taken from the adapter object itself, never from a caller string,
    so the report binds the policy that actually validated the outputs.
    """
    body = json.dumps(
        adapter.mapping.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(f"{_POLICY_HASH_DOMAIN}\n{body}".encode()).hexdigest()


def _percentile95(values: list[float]) -> float:
    """Nearest-rank 95th percentile: the sorted value at rank ceil(0.95 * n).

    Deterministic and always one of the measured samples, so it can never
    fall below the median or exceed the maximum of the same sample set.
    """
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1))
    return ordered[index]


def _checked_config(value: object) -> BenchmarkConfig:
    if not isinstance(value, BenchmarkConfig):
        raise BenchmarkError(
            BenchmarkErrorCode.INVALID_CONFIG, "benchmark configuration is invalid"
        )
    try:
        return BenchmarkConfig.model_validate(value.model_dump())
    except ValidationError:
        raise BenchmarkError(
            BenchmarkErrorCode.INVALID_CONFIG, "benchmark configuration is invalid"
        ) from None


def _checked_session(value: object) -> InferenceSession:
    if not isinstance(value, InferenceSession):
        raise BenchmarkError(
            BenchmarkErrorCode.INVALID_INPUT, "benchmark inference session is invalid"
        )
    return value


def _checked_vocabulary(value: object) -> Vocabulary:
    if not isinstance(value, Vocabulary):
        raise BenchmarkError(
            BenchmarkErrorCode.INVALID_INPUT, "benchmark vocabulary is invalid"
        )
    try:
        return Vocabulary.model_validate(value.model_dump())
    except ValidationError:
        raise BenchmarkError(
            BenchmarkErrorCode.INVALID_INPUT, "benchmark vocabulary is invalid"
        ) from None


def _checked_adapter(value: object) -> AdvisoryAdapter:
    if not isinstance(value, AdvisoryAdapter):
        raise BenchmarkError(
            BenchmarkErrorCode.INVALID_INPUT, "benchmark validation policy is invalid"
        )
    return value


def _checked_expected_artifact(value: object) -> str:
    if (
        not isinstance(value, str)
        or isinstance(value, bool)
        or not 1 <= len(value) <= 64
    ):
        raise BenchmarkError(
            BenchmarkErrorCode.INVALID_CONFIG, "benchmark artifact identity is invalid"
        )
    return value


def _checked_expected_vocabulary_hash(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise BenchmarkError(
            BenchmarkErrorCode.INVALID_CONFIG,
            "benchmark vocabulary identity is invalid",
        )
    return value


def _checked_case_set_key(value: object) -> bytes:
    if (
        not isinstance(value, bytes)
        or isinstance(value, bool)
        or not MIN_CASE_SET_KEY_BYTES <= len(value) <= MAX_CASE_SET_KEY_BYTES
    ):
        # Never echo key material: the message carries no key content.
        raise BenchmarkError(
            BenchmarkErrorCode.INVALID_CONFIG, "benchmark case-set key is invalid"
        )
    return value


def _checked_cases(
    value: object, *, vocab_size: int, max_seq_len: int
) -> tuple[list[int], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise BenchmarkError(
            BenchmarkErrorCode.CASE_COUNT_INVALID,
            "benchmark requires a bounded nonempty case set",
        )
    cases = tuple(value)
    if not cases or len(cases) > MAX_BENCHMARK_CASES:
        raise BenchmarkError(
            BenchmarkErrorCode.CASE_COUNT_INVALID,
            "benchmark requires a bounded nonempty case set",
        )
    checked: list[list[int]] = []
    for case in cases:
        if isinstance(case, (str, bytes)) or not isinstance(case, Sequence):
            raise BenchmarkError(
                BenchmarkErrorCode.CASE_TYPE_INVALID,
                "all benchmark cases must be token-id sequences",
            )
        tokens = list(case)
        if not tokens or len(tokens) > min(max_seq_len, MAX_INFERENCE_SEQUENCE_LENGTH):
            raise BenchmarkError(
                BenchmarkErrorCode.CASE_VALUE_INVALID,
                "a benchmark case has an invalid sequence length",
            )
        for token_id in tokens:
            if (
                isinstance(token_id, bool)
                or not isinstance(token_id, int)
                or not 0 <= token_id < vocab_size
            ):
                raise BenchmarkError(
                    BenchmarkErrorCode.CASE_VALUE_INVALID,
                    "a benchmark case holds an invalid token id",
                )
        checked.append(tokens)
    return tuple(checked)


def _deterministic_context(
    case_index: int,
) -> tuple[NativeReasoningRequest, NativeReasoningResult]:
    """Synthetic SUPPORTED context bound to one case's request identity."""
    request_id = uuid.uuid5(_BENCHMARK_ID_NAMESPACE, f"case-request-{case_index}")
    request = NativeReasoningRequest(
        request_id=request_id,
        session_id=_BENCHMARK_SESSION_ID,
        context_fingerprint=_BENCHMARK_FINGERPRINT,
        task_id=_BENCHMARK_TASK_ID,
        evidence_ids=(_BENCHMARK_EVIDENCE_ID,),
        request_source=NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
    )
    result = NativeReasoningResult(
        result_id=uuid.uuid5(_BENCHMARK_ID_NAMESPACE, f"case-result-{case_index}"),
        request_id=request_id,
        session_id=_BENCHMARK_SESSION_ID,
        context_fingerprint=_BENCHMARK_FINGERPRINT,
        status="SUPPORTED",
        reason_code="RULE_MATCH",
        uncertainty=0.5,
        supporting_evidence_ids=(_BENCHMARK_EVIDENCE_ID,),
        contradicting_evidence_ids=(),
        missing_information_ids=(),
        rule_id=_BENCHMARK_RULE_ID,
        suggestion_text=None,
        result_source=NATIVE_REASONING_RESULT_SOURCE_TASK_202,
    )
    return request, result


def _run_inference(session: InferenceSession, tokens: list[int]) -> Any:
    try:
        return run_inference(
            session, InferenceRequest(token_id_sequences=[tuple(tokens)])
        )
    except InferenceError as error:
        # Carry only the stable code; never the case content.
        raise BenchmarkError(
            BenchmarkErrorCode.CASE_REJECTED_BY_INFERENCE,
            f"a benchmark case was rejected by inference ({error.code})",
        ) from None


def _run_validated(
    session: InferenceSession,
    adapter: AdvisoryAdapter,
    tokens: list[int],
    case_index: int,
) -> AdvisoryAdapterResult:
    inference_result = _run_inference(session, tokens)
    request, deterministic = _deterministic_context(case_index)
    try:
        outcome = adapter.propose(
            inference_result=inference_result,
            request=request,
            deterministic_result=deterministic,
        )
    except AdvisoryAdapterError as error:
        raise BenchmarkError(
            BenchmarkErrorCode.CASE_REJECTED_BY_VALIDATION,
            f"a benchmark output was rejected by strict validation ({error.code})",
        ) from None
    if not outcome.admissible:
        raise BenchmarkError(
            BenchmarkErrorCode.CASE_REJECTED_BY_VALIDATION,
            "a benchmark output was rejected by strict validation "
            f"({outcome.rejection_reason})",
        )
    return outcome


def run_inference_benchmark(
    *,
    session: InferenceSession,
    vocabulary: Vocabulary,
    adapter: AdvisoryAdapter,
    cases: Sequence[Sequence[int]],
    config: BenchmarkConfig,
    expected_artifact_id: str,
    expected_vocabulary_hash: str,
    case_set_key: bytes,
) -> BenchmarkReport:
    """Measure local inference plus strict validation and report auditable results.

    Identity is validated before any expensive inference runs: the
    session's artifact, the vocabulary's size and hash, and the
    caller's expectations must agree, and every measured output must
    pass the strict validation boundary. The returned report binds the
    actual identities and carries only digests — never case content.

    ``case_set_key`` is the caller-managed HMAC secret for the
    case-set digest: it must be 16–256 bytes, is never written to the
    report, logs, or errors, and authorized verification recomputes
    the digest with the same key obtained out of band.
    """
    checked_session = _checked_session(session)
    checked_vocabulary = _checked_vocabulary(vocabulary)
    checked_adapter = _checked_adapter(adapter)
    checked_config = _checked_config(config)
    wanted_artifact = _checked_expected_artifact(expected_artifact_id)
    wanted_vocabulary_hash = _checked_expected_vocabulary_hash(expected_vocabulary_hash)
    checked_key = _checked_case_set_key(case_set_key)
    checked_cases = _checked_cases(
        cases,
        vocab_size=checked_session.vocab_size,
        max_seq_len=checked_session.max_seq_len,
    )
    if checked_config.measured_iterations < len(checked_cases):
        raise BenchmarkError(
            BenchmarkErrorCode.CASE_COVERAGE_INSUFFICIENT,
            "measured iterations must cover every benchmark case at least once",
        )
    if checked_session.artifact_id != wanted_artifact:
        raise BenchmarkError(
            BenchmarkErrorCode.MODEL_POLICY_MISMATCH,
            "benchmark policy does not match the local model",
        )
    if (
        checked_vocabulary.metadata.vocabulary_size != checked_session.vocab_size
        or checked_vocabulary.metadata.vocabulary_hash != wanted_vocabulary_hash
    ):
        raise BenchmarkError(
            BenchmarkErrorCode.VOCABULARY_POLICY_MISMATCH,
            "benchmark policy does not match the local vocabulary",
        )
    # tracemalloc is process-global. reset_peak() or stop() would mutate a
    # session owned by unrelated caller code, and measuring inside it would
    # include allocations this benchmark did not make, so refuse up front.
    if tracemalloc.is_tracing():
        raise BenchmarkError(
            BenchmarkErrorCode.TRACEMALLOC_ALREADY_ACTIVE,
            "a tracemalloc session is already active; the benchmark will not "
            "reset, stop or measure through it",
        )

    bound_policy_hash = policy_hash(checked_adapter)

    for offset in range(checked_config.warmup_iterations):
        index = offset % len(checked_cases)
        _run_validated(checked_session, checked_adapter, checked_cases[index], index)

    elapsed_ms: list[float] = []
    output_hashes: list[str] = []
    # No trace was active on entry (checked above), so this call owns the
    # session it starts and always stops it, including on failure.
    tracemalloc.start()
    try:
        for offset in range(checked_config.measured_iterations):
            index = offset % len(checked_cases)
            start = time.perf_counter_ns()
            validated = _run_validated(
                checked_session, checked_adapter, checked_cases[index], index
            )
            elapsed_ms.append((time.perf_counter_ns() - start) / 1_000_000.0)
            output_hashes.append(
                hashlib.sha256(validated.model_dump_json().encode()).hexdigest()
            )
        _, peak_memory = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    if not all(math.isfinite(value) and value >= 0.0 for value in elapsed_ms):
        raise BenchmarkError(
            BenchmarkErrorCode.INVALID_MEASUREMENT,
            "benchmark measurements are invalid",
        )
    maximum_ms = max(elapsed_ms)
    # fmean can round one ulp above the maximum for near-identical samples;
    # clamp to the maximum so the report stays self-consistent.
    mean_ms = min(statistics.fmean(elapsed_ms), maximum_ms)
    median_ms = statistics.median(elapsed_ms)
    p95_ms = _percentile95(elapsed_ms)
    within_budget = (
        maximum_ms <= checked_config.latency_budget_ms
        and peak_memory <= checked_config.peak_memory_budget_bytes
    )
    canonical_cases = tuple(checked_cases)
    try:
        return BenchmarkReport(
            artifact_id=checked_session.artifact_id,
            vocabulary_hash=checked_vocabulary.metadata.vocabulary_hash,
            policy_hash=bound_policy_hash,
            benchmark_config_hash=checked_config.config_hash(),
            case_set_digest=case_set_digest(canonical_cases, key=checked_key),
            declared_latency_budget_ms=checked_config.latency_budget_ms,
            declared_peak_memory_budget_bytes=checked_config.peak_memory_budget_bytes,
            case_count=len(checked_cases),
            cases_measured=len(checked_cases),
            warmup_iterations=checked_config.warmup_iterations,
            measured_iterations=checked_config.measured_iterations,
            latency_mean_ms=mean_ms,
            latency_median_ms=median_ms,
            latency_p95_ms=p95_ms,
            latency_max_ms=maximum_ms,
            peak_traced_memory_bytes=peak_memory,
            output_digest=output_digest(output_hashes),
            within_declared_budgets=within_budget,
        )
    except ValidationError:
        raise BenchmarkError(
            BenchmarkErrorCode.INVALID_MEASUREMENT,
            "benchmark measurements are invalid",
        ) from None


__all__ = [
    "BenchmarkError",
    "policy_hash",
    "run_inference_benchmark",
]
