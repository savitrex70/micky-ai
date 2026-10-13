# Stage 8: native model acceptance gate

Stage 8 is complete only when Task 215's acceptance report passes. A trained
checkpoint, successful synthetic fixture run, or low local latency is not
acceptance by itself.

## Task boundaries

- **206 — Evaluation harness:** predeclared task, split, metrics, zero-tolerance
  invalid-reference rate, and deterministic comparison against the baseline.
- **207 — Dataset preparation:** explicit authorization, privacy-safe records,
  duplicate handling, group-disjoint splits, and a manifest. Unknown or
  unauthorized sources remain blocked.
- **208 — Tokenizer/vocabulary:** project-controlled tokenization and vocabulary
  fitted only on the authorized training split.
- **209 — Model:** seeded first-party embedding/mean-pooling/linear head; no
  pretrained weights or external model framework.
- **210 — Training:** deterministic offline training against the authorized
  training split; validation and test examples are rejected as training input.
- **211 — Artifacts:** canonical local checkpoint serialization, atomic writes,
  content integrity, and vocabulary/dataset lineage checks.
- **212 — Inference:** local CPU inference over the verified artifact; outputs
  are advisory label scores only.
- **213 — Output validation:** model/vocabulary identity, label-space, ordering,
  score threshold and cardinality are validated before use.
- **214 — Resource benchmark:** local latency and traced-memory measurements;
  benchmark results are descriptive, not evidence of clinical utility. The
  report (contract version 3) names the exact artifact, the strict suggestion
  policy hash, the configuration hash and a digest of the ordered case set. The
  benchmark refuses to run (`TRACEMALLOC_ALREADY_ACTIVE`) when a `tracemalloc`
  session is already active, so it never resets or measures through a trace
  owned by other code.
- **215 — Acceptance gate:** evaluates only the held-out TEST split, compares
  the candidate to the deterministic baseline, binds the run to the dataset,
  checkpoint, vocabulary, policy and benchmark, and requires every acceptance
  condition (report contract version 2).

## Acceptance identity binding

The gate takes a predeclared `expected_benchmark_config` and rejects a
benchmark that does not match every one of these:

- **Artifact:** the supplied artifact hash equals the inference adapter's
  artifact hash and `benchmark.artifact_hash`. Model version and vocabulary
  hash alone do not identify a checkpoint.
- **Label space:** the inference labels hash to the label-space hash recorded
  by training in the artifact.
- **Policy:** `benchmark.policy_hash` equals the gate policy's hash.
- **Configuration and budgets:** the benchmark's configuration hash, declared
  latency and memory budgets and repetition counts equal the predeclared
  configuration, so a report with caller-chosen budgets cannot pass.
- **Workload:** the benchmark case-set digest equals the digest of the held-out
  TEST texts in canonical TEST-entry order, and every TEST case was measured.

`Stage8AcceptanceReport` itself rejects a report whose evaluation, benchmark,
model, vocabulary, artifact or policy identities disagree, and requires its
blockers and `accepted` flag to follow exactly from the recorded real-data,
resource-budget and evaluation outcomes.

## Required owner-run validation

From the repository root with the project's Python 3.12 environment activated:

```powershell
pytest tests/test_native_model.py tests/test_native_training.py tests/test_native_artifacts.py tests/test_native_inference.py tests/test_native_suggestion_validation.py tests/test_native_benchmark.py tests/test_stage8_acceptance.py tests/test_evaluation_harness.py -q
pytest -q
ruff check .
black --check .
```

Run the commands against the final candidate commit after all stacked tasks have
been reviewed and their dependencies resolved. Record the exact commit SHA and
the actual command results. Do not substitute a subset of tests for the full
suite, and do not describe a command as passed unless its exit status confirms
success.

## Current data limitation

The repository currently has synthetic fixtures but no approved, real dataset
for this candidate task. Therefore the Stage 8 gate must keep acceptance false
until a real source has explicit authorization for both training and evaluation,
is declared non-synthetic, has no training-blocked reason, and the artifact's
training fingerprint matches the manifest's train split. The held-out TEST
split must remain separate from training and vocabulary fitting.

The model's outputs are untrusted advisory suggestions. Even a passing Stage 8
engineering gate would not establish clinical safety, clinical utility, or
permission to make clinical decisions. Those claims require a separate,
appropriate clinical validation process and are outside this task sequence.
