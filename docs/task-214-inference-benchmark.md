# Task 214 — Bounded Offline Inference Benchmark

A deterministic measurement tool for the existing locally owned
inference pipeline. It measures the Task 212 local CPU inference path
together with the Task 213 strict suggestion-validation boundary and
returns an auditable, privacy-safe report. It is not a model-training
system, and a passing benchmark is not evidence of model accuracy,
safety, clinical utility, or Stage 8 acceptance.

## What the benchmark accepts and returns

`run_inference_benchmark()` in `src/rop/inference/benchmark.py` accepts:

- one initialized `InferenceSession` (Task 212) — the already-loaded
  local model; artifact identity is read from the session, never from
  a caller string;
- one validated `Vocabulary` (Task 208) whose size must agree with the
  session and whose hash must match the caller's expectation;
- one constructed `AdvisoryAdapter` (Task 213) — the strict validation
  policy; the report binds a canonical hash of its validated mapping;
- an ordered tuple of benchmark cases (token-ID sequences);
- a validated `BenchmarkConfig` (workload bounds and declared budgets);
- the expected artifact ID and vocabulary hash the session and
  vocabulary are checked against before any expensive inference runs.

It returns a frozen, strict `BenchmarkReport` (`src/rop/schemas/benchmark.py`)
and writes nothing to disk.

## Local-only execution

The module imports no network, provider, serving, download, or
persistence facilities. That is a property of the code paths exercised
here, not a proof about the surrounding process; the report declares
`execution_mode="LOCAL_CPU_OFFLINE"` as a description of how the
measurement ran.

## Bounded workload

`BenchmarkConfig` fixes warm-up iterations (0–100), measured iterations
(1–10000), a latency budget, and a memory budget, with an explicit
rejection of empty inputs, oversized workloads, and any workload where
measured iterations cannot cover every supplied case at least once
(cases are cycled in order). Limits are validated before inference runs.

## Statistics and memory

End-to-end latency per measured iteration covers inference plus strict
validation. The report gives mean, median, p95, and maximum. p95 is the
nearest-rank 95th percentile (`ceil(0.95 * n)`), always one of the
measured samples. The mean is clamped to the maximum to absorb at most
one ulp of `fmean` rounding on near-identical samples; this treatment
is documented here and tested.

Memory is Python `tracemalloc` traced memory — labeled
`peak_traced_memory_bytes` — not process RSS or system memory. A trace
that is already active is refused (`TRACEMALLOC_ALREADY_ACTIVE`)
rather than reset, stopped, or measured through. A session the
benchmark starts is always stopped, including on failure.

Declared budgets are caller expectations used only for the report's
`within_declared_budgets` verdict, which the report schema recomputes
from the measurements. They are not system-enforced limits.

## Identity, validation, and privacy

Every measured output passes through the real `AdvisoryAdapter.propose`
boundary — identity matching, evidence binding, status gating, and
mapping checks all execute. Inference rejections and strict-validation
rejections fail the benchmark with sanitized codes; they are never
converted into a successful report, and messages carry only stable
codes, never case content.

Deterministic validation contexts used during measurement are
synthetic SUPPORTED scaffolding bound to each case's request identity
(Task 202 shapes, fixed benchmark evidence). They exist so the strict
path executes for real; they are not reasoning outcomes.

The report carries digests only: a domain-separated SHA-256
configuration hash, an ordered case-set digest, a policy hash, and an
output digest over the validated outputs. Canonical serialization is
sorted-key compact JSON; Python's `hash()` is never used for
persistent identities. No prompts, case content, predictions, secrets,
or machine details are retained, and `clinical_utility_established`
is the literal `False`.

## Tests

`tests/test_inference_benchmark.py` uses a stub model, a synthetic
vocabulary, and the real Task 212/213 path. It covers valid execution,
case-set and coverage rejection, identity mismatch, strict-validation
and inference rejection, report identity and digests, percentile
relationships via a deterministic clock, both budget verdicts, invalid
numerics and inconsistent reports, tracemalloc refusal and cleanup,
message privacy, and unchanged Task 212/213 contracts. No checkpoints,
downloads, hosted services, or network access are required.
