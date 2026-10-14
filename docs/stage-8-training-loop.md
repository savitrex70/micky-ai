# Stage 8 Training Loop (Task 210)

An explicit, bounded, deterministic training and validation loop for
the Task 209 `tiny-encoder-v1` model, over Task 207
`synthetic-test-only` data and the Task 208 vocabulary. This is
training-mechanics work: a completed run proves loop plumbing only and
establishes **no** model competence, no clinical validity, and no
real-world accuracy.

## Task and rationale

Stage 8's agreed roadmap Task 210 ("Implement reproducible training and
validation loop") requires seed/config capture, deterministic settings,
and explicit invalid-run failures before any artifact work (Task 211)
can proceed. This loop fills exactly that gap and nothing more.

## API

Production entry points live in `rop/training`:

- `run_training(result, *, model, vocabulary, tokenizer_config, config)`
  The only way to start training. Importing `rop.training` never trains;
  there is no background loop, scheduling, or startup wiring.
  - `result`: a validated Task 207 `PreparationResult` built by
    `prepare_dataset` under a `TrustedSourceRegistry`. The manifest
    must be `synthetic-test-only` and prepared with
    `operation="training"`.
  - `model`: a `NativeModel` from Task 209 `initialize_model`. Its
    deterministic initialization is verified (parameter count and init
    hash) before the first update; the model is trained in place and
    left in its original `train`/`eval` mode.
  - `vocabulary`: a Task 208 `Vocabulary`; its integrity is verified,
    and its identity fields (`dataset_id`, dataset integrity hash,
    split assignment hash) must agree with the manifest and split
    manifest — any disagreement is rejected.
  - `tokenizer_config`: a Task 208 `TokenizerConfig` (mapping accepted,
    strictly validated). Its `max_sequence_length` must not exceed the
    model's `max_seq_len`.
  - `config`: a validated `TrainingConfig` (mapping accepted).
- `build_training_dataset(result, *, vocabulary, tokenizer_config)`
  Encodes the two used partitions once, deterministically, and is the
  module's only consumer of `partition_records`. Returned examples
  carry `record_id`, `group_id`, token ids, and the class index from
  the manifest's sorted allowed labels.
- `NativeTrainingError(code, detail)`
  Typed failure with a stable code. Events raised by Task 207/208
  delegated checks are re-raised with their original code
  (`HASH_MISMATCH`, `SPLIT_INTEGRITY_FAILURE`, ...).

`TrainingConfig` fields (all required, booleans and numeric strings
rejected rather than coerced):

| Field           | Bounds                                | Notes                          |
| --------------- | ------------------------------------- | ------------------------------ |
| `epochs`        | 1..50                                 | hard bound `MAX_EPOCHS`        |
| `batch_size`    | 1..64                                 | hard bound `MAX_BATCH_SIZE`    |
| `learning_rate` | (0.0..1.0]                            | plain SGD, no momentum         |
| `seed`          | 0..2^32-1                             | seeds RNG for shuffle/dropout  |

Additional hard bounds: encoded partitions are capped at
`MAX_EXAMPLES_PER_PARTITION = 10_000` examples each; sequences longer
than the tokenizer's `max_sequence_length` are head-truncated by the
Task 208 contract, and batches are padded with the fixed `<pad>` id
within a batch; sequences must not exceed the model's `max_seq_len`.
Every example must encode to at least one token.

Exit codes for `NativeTrainingError` (stable codes, safe generic
messages): `INVALID_INPUT`, `INVALID_CONFIG`, `UNSUPPORTED_SCOPE`,
`OPERATION_NOT_PERMITTED`, `EMPTY_PARTITION`, `MALFORMED_EXAMPLE`,
`LABEL_UNKNOWN`, `INCOMPATIBLE_DATASET`, `INCOMPATIBLE_MODEL`,
`INCOMPATIBLE_VOCABULARY`, `INCOMPATIBLE_TOKENIZER`, `HASH_MISMATCH`,
`SPLIT_INTEGRITY_FAILURE`, `RESOURCE_LIMIT`, `NON_FINITE_LOSS`,
`NON_FINITE_GRADIENT`, `NON_FINITE_PARAMETER`, `NON_FINITE_METRIC`,
plus delegated Task 207 codes.

## Synthetic-only data boundary

- The loop accepts only `PreparationResult` values produced by the
  Task 207 pipeline; the manifest and split manifest both carry the
  `synthetic-test-only` taint, and the training API additionally
  requires `manifest.operation == "training"`.
- Dataset and split integrity are checked against the Task 208
  vocabulary metadata before any tensor exists: dataset id, dataset
  integrity hash, and split assignment hash must agree across
  manifest, split manifest, and vocabulary. Record-level digests are
  recomputed from content before encoding. A manifest hash alone does
  not authenticate authorization or provenance — trust remains
  containment through the Task 207 explicit registry, unchanged.
- Only `partition_records(result, "train")` is used for fitting. The
  validation partition is encoded once, evaluated per epoch, and never
  used for gradients, updates, epoch selection, stopping (none is
  implemented), hyperparameter choice (none is learned), or logging
  beyond the per-epoch metrics in the report.
- **The test partition is excluded from learning, never from all
  reading.** One narrow, pre-training integrity preflight inspects
  the complete retained record set (train, validation, and test
  records) to independently establish dataset and split integrity
  with the Task 207 verification contract. This preflight reads test
  records structurally only — identity, grouping, content digest,
  and hash recomputation — and never encodes them with the
  tokenizer/vocabulary path, constructs batches from them, computes
  training or validation metrics from them, uses them for model
  selection, stopping, or hyperparameters (none exist), or emits
  them in logging or in `TrainingReport`. Every other code path
  requests only the train and validation partitions.

## Verification order before fitting

`run_training` performs, in order, before any optimizer is created or
any model parameter is updated:

1. Strict type checks on the preparation result, model, vocabulary,
   tokenizer configuration, and training configuration.
2. Verification of the model's deterministic Task 209 initialization
   (parameter count and init hash).
3. **Independent dataset and split integrity verification** by reusing
   the Task 207 contract unchanged: the complete retained record set
   is collected from the `PreparationResult` schema itself, every
   record's canonical integrity representation is recomputed, and
   `verify_split` replays the deterministic group-hash assignment
   policy, checking membership, uniqueness, group confinement,
   partition coverage, counts, and byte-identical reproducibility.
   Nothing is trusted from the recorded hashes alone.
4. Cross-artifact identity and hash agreement: the recomputed dataset
   integrity hash must equal the recorded hashes in the dataset
   manifest, the split manifest, and the vocabulary metadata; dataset
   ids and split/vocabulary assignment hashes must agree; the split
   counts must match the encoded partition sizes; and leakage groups
   must not span partitions.
5. Model/vocabulary compatibility (vocabulary size, class count,
   sequence-length bound), then vocabulary integrity verification and
   encoding of the train and validation partitions.

Any failure at any step raises a stable `NativeTrainingError` code
(with delegated Task 207 failures converted, preserving the
`SPLIT_INTEGRITY_FAILURE` and `HASH_MISMATCH` semantics); no optimizer
is constructed and no parameter changes when the preflight fails,
verified by a spy-optimizer test.

## What each partition is used for

- **Complete retained records**: only the step-3 integrity preflight
  above.
- **Training partition**: gradient-based fitting (`loss.backward()`
  and `optimizer.step()` on its batches) and the per-epoch
  `train_loss` metric.
- **Validation partition**: per-epoch no-gradient, no-update
  evaluation producing `validation_loss` and `validation_accuracy`.
- **Test partition**: nothing else — not encoding, not fitting, not
  metrics, not selection or stopping (neither is implemented), not
  logging, and not the report.

Spy tests prove the per-call partition surface: a wrapped
`partition_records` records only `train` and `validation` requests in
the encode/fit/evaluate path, and the encoded dataset's ids are
exactly train ∪ validation ids, disjoint from test ids. The spy tests
do not (and cannot) prove that the integrity preflight ignores test
records — instead they prove that no other code path requests the test
partition and that a tampered test partition fails the preflight
before fitting.

## Per-epoch behavior

For each epoch: seeded permutation shuffle of the training examples
(dedicated `torch.Generator` seeded from `config.seed`), then for every
batch — padded to the batch's maximum sequence width with the `<pad>`
id — forward pass, `cross_entropy` loss over the model's logits and the
encoded class labels, backward pass, gradient finiteness check,
`SGD.step()`, parameter finiteness check. After the epoch, the
validation examples are evaluated in `eval()` mode under
`torch.no_grad()` with no optimizer steps and no parameter mutation;
`model.train()` is restored before the next epoch. Losses are summed
per batch and normalized by example counts, so the last short batch
does not bias the mean.

## Reproducibility and RNG behavior

- Initialization remains the Task 209 deterministic procedure and is
  used as-is; the loop never initializes weights itself.
- Around the whole run — success or failure — the loop preserves the
  caller's global CPU RNG state (`get_rng_state()` / `set_rng_state()`),
  seeds the global RNG from `config.seed` for dropout draws, and uses a
  dedicated, identically seeded generator for the epoch permutations,
  so shuffle order cannot depend on unrelated application activity.
  Task 209's RNG-preservation tests are untouched and still pass.
- No validation-only or early-stopping code path consumes randomness;
  evaluation is deterministic.
- Deterministic CPU behavior is enforced to the extent PyTorch
  supports: identical inputs, configuration, and identical runtime
  conditions (CPU device, same PyTorch build, same thread count)
  produce bitwise-identical reports, verified by test. This is the
  honest boundary: a fixed seed alone does not guarantee bit identity
  across library versions, thread counts, or hardware.

## Success is not competence

The report records structure — epochs, batches, finite losses, and
validation accuracy on synthetic held-out examples. `run_completed`
means every requested epoch finished with finite losses, gradients,
parameters, and metrics. It does not mean the model learned anything
useful, and no test in this task asserts meaningful predictive
accuracy. Model acceptance remains governed by the Task 206
predeclared thresholds and is never granted by the training loop.

## Failure behavior

Invalid inputs fail closed before tensors exist: wrong artifact types,
tampered manifests/splits/vocabularies, scope or operation mismatch,
cross-artifact hash disagreement, empty or oversized partitions,
unknown labels, digest mismatches, incompatible dimensions or sequence
limits, and out-of-bounds configuration all raise stable codes.
Non-finite loss during training or validation, non-finite gradients,
and non-finite parameters stop the run immediately. A report is
constructed only after every requested epoch completed; a failed or
partial run raises instead of returning, and the caller's RNG state is
restored even when raising.

## Explicit exclusions (Tasks 211–215)

This task does not implement model checkpointing, serialization,
artifact manifests, or save/load workflows (Task 211); a production
inference service or local inference subsystem (Task 212); an advisory
adapter into authoritative reasoning (Task 213); the offline
isolation/security/resource benchmark suite (Task 214); or the
end-to-end acceptance gate (Task 215). There are no pretrained
weights, model hubs, hosted APIs, external model providers, downloads,
hidden network calls, telemetry, or background training. No clinical
rules, diagnosis, treatment recommendations, or clinical-safety claims
exist in this path.

Run the focused tests with `pytest tests/test_native_training_loop.py -q`.
