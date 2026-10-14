# Stage 8 Local CPU Inference Runtime (Task 212)

An explicitly invoked, in-process CPU runtime for the Task 209
`tiny-encoder-v1` model from a caller-selected Task 211 checkpoint.
Importing the runtime never loads weights and never runs inference.
A completed run proves plumbing only and establishes **no** model
competence, no clinical validity, and no real-world accuracy.

## Explicit artifact selection

The caller supplies an `InferenceSelection` with two plain local
file paths: `checkpoint_path` and `manifest_path`. The runtime never
searches for a model, reads process configuration for a location,
contacts a remote endpoint, or substitutes a replacement. Network
locations (`://`), empty paths, and missing files are rejected
(`ARTIFACT_MISSING` for absent files).

`load_inference_session()` performs, in order:

1. Strict type validation of the selection and every lineage object
   (model/training configs, preparation result, vocabulary,
   tokenizer config).
2. File reads through Task 211 `load_artifact_files()` (size caps,
   JSON/schema checks only — no tensor work).
3. Full Task 211 `verify_artifact()` against the supplied
   authoritative lineage (manifest digest, content digest,
   checkpoint structure and fingerprint, dataset/split replay,
   vocabulary and tokenizer agreement).
4. Explicit Task 209 `initialize_model()` construction from the
   validated configuration (no global-RNG side effects).
5. Checkpoint application through the approved Task 211 safe API.
6. CPU float32 confirmation; the model is left in evaluation mode.

Any verification failure raises a stable `InferenceError`
(`ARTIFACT_MISSING`, `ARTIFACT_INVALID`, or
`INCOMPATIBLE_ARTIFACT`) before any inference. Nothing is repaired
or reinterpreted.

## CPU-only execution and bounds

- CPU only. Parameters must be float32 on CPU; there is no device
  selection and no GPU path. The absence of a GPU changes nothing.
- Inference runs under `torch.no_grad()` with the model forced to
  evaluation mode (the caller's mode is restored afterwards). No
  optimizer exists in the runtime, so parameters cannot be updated.
- Requests carry token-ID sequences (`InferenceRequest`), validated
  before any tensor allocation: non-empty batch (at most
  `MAX_INFERENCE_BATCH_SIZE = 32` sequences), non-empty sequences
  (at most 512 IDs globally and at most the model's `max_seq_len`),
  genuine integers only (booleans, strings, and floats rejected),
  every ID inside `[0, vocab_size)` — out-of-range IDs are rejected,
  never clamped.
- Allocation is bounded by the validated batch and sequence limits.
  Violations raise `INVALID_REQUEST` or `RESOURCE_LIMIT`.
- No raw-text handling: callers supply token IDs in the Task 209
  representation (the Task 208 tokenizer remains the approved
  text→ID path and is out of scope here).

## Output and failure semantics

`run_inference()` returns an `InferenceResult` of raw logits —
untrusted model output, explicitly not evidence, findings,
confidence, labels, or clinical content. The boundary checks output
rank and dimensions against the request and architecture, and
rejects non-finite values (`INVALID_OUTPUT`). Malformed output is
never reshaped into a plausible result. Errors carry stable codes
with safe generic messages; raw inputs and checkpoint bytes never
appear in them.

## Optionality

The runtime activates only when a caller builds a session and calls
`run_inference()`. The deterministic path (dataset preparation,
vocabulary, baseline evaluation) works with no artifact selected
and no session constructed. A missing, corrupt, or incompatible
artifact yields a controlled `InferenceError`, never a silent
fallback and never a fabricated success. The runtime is not wired
into authoritative reasoning or Stage 7 publication paths; semantic
output validation and advisory integration belong to Task 213.

Run the focused tests with
`pytest tests/test_local_inference_runtime.py -q`.
