# Stage 8 Artifact Manifests and Checkpoints (Task 211)

A narrow, secure artifact-manifest and checkpoint-integrity contract
for the Task 209 `tiny-encoder-v1` model and Task 210 training
lineage. No pretrained weights, external model files, downloads,
network access, inference, or clinical logic live here. A completed
verification proves structural integrity only and establishes **no**
model competence, no clinical validity, and no real-world accuracy.

## Contract and version

- Manifest schema: `ArtifactManifest`, version `1.0`.
- Artifact type: `model-checkpoint` (the only supported type).
- Checkpoint format: `rop-raw-tensor-v1`, format version `1.0`.
- Scope: `synthetic-test-only` (the only supported scope).

## Which bytes and metadata are hashed

- **Content digest** (`content_digest`): SHA-256 over the exact
  checkpoint bytes produced by `build_checkpoint_bytes()`.
- **Manifest digest** (`manifest_digest`): SHA-256 over the canonical
  manifest representation (sorted-key compact JSON, Task 104 scheme)
  covering every lineage field **except** `manifest_digest` itself:
  `manifest_version`, `artifact_type`, `artifact_id`,
  `content_digest`, `checkpoint_format`,
  `checkpoint_format_version`, `model_version`, `architecture`,
  `model_config_hash`, `parameter_count`, `training_config_hash`,
  `training_seed`, `model_init_seed`, `dataset_id`,
  `dataset_integrity_hash`, `split_assignment_hash`,
  `vocabulary_hash`, `tokenizer_config_hash`, `data_scope`.

The two digests are deliberately distinct: the content digest binds
the weight bytes, while the manifest digest binds the recorded
lineage. There is no circular hashing.

## Checkpoint layout

`build_checkpoint_bytes()` serializes an initialized model without
pickling (format version `2.0`):

```
8-byte magic "ROPCHK01"
+ 4-byte big-endian header length
+ sorted-key compact JSON header
+ concatenated little-endian float32 payload (sorted parameter-name order)
```

The JSON header records `checkpoint_format`,
`checkpoint_format_version`, `architecture`, `model_version`,
`model_config_hash` (the canonical Task 209 configuration
fingerprint), `parameter_count`, and per-parameter
`dtype`/`shape`/`offset`/`nbytes`. Only `float32` parameters are
supported. The header accepts exactly these fields; unexpected
fields, non-integer numerics (booleans included), empty names, and
non-contiguous offsets are rejected. Total size is bounded by
`MAX_CHECKPOINT_BYTES` (4 MB); headers by `MAX_HEADER_BYTES`.

Format `1.0` bytes (no embedded fingerprint) are rejected with
`UNSUPPORTED_VERSION`, never reinterpreted.

## Verification order and failure behavior

`verify_artifact()` performs, in order, before any model state is
touched:

1. Strict type checks and schema revalidation (defeats
   `model_copy(update=...)` bypass).
2. Artifact-type, manifest-version, and scope checks with precise
   codes (`WRONG_ARTIFACT_TYPE`, `UNSUPPORTED_VERSION`,
   `UNSUPPORTED_SCOPE`).
3. Manifest-digest recomputation (`MANIFEST_DIGEST_MISMATCH`).
4. Content-digest recomputation from the actual bytes
   (`HASH_MISMATCH`).
5. Checkpoint structure validation — magic, version, header fields,
   offsets, payload size (`UNSUPPORTED_FORMAT`,
   `UNSUPPORTED_VERSION`, `CORRUPT_CHECKPOINT`). Pickle bytes
   (`torch.save` output) and random bytes are rejected here without
   any deserialization.
6. Lineage cross-checks against the authoritative objects passed by
   the caller — model config (hash, seed, estimated count, plus the
   checkpoint's embedded fingerprint, architecture, version, and
   complete parameter layout derived from the config via the Task 209
   construction contract), training config, preparation result
   (including an independent `verify_split` replay), vocabulary, and
   tokenizer config (`INCOMPATIBLE_MODEL`, `INCOMPATIBLE_TRAINING`,
   `INCOMPATIBLE_DATASET`, `INCOMPATIBLE_VOCABULARY`,
   `INCOMPATIBLE_TOKENIZER`, `SPLIT_INTEGRITY_FAILURE`). Parameter
   count alone is never accepted as proof of compatibility.

`apply_checkpoint_to_model()` parses and validates the full header,
checks architecture, version, and the embedded fingerprint against
the target model, decodes every tensor into temporary storage,
checks finiteness, and only then copies state into the model. A
failure leaves model parameters unchanged (tested by snapshot
comparison).

Every failure raises `ArtifactError` with a stable code and a safe,
generic message. Nothing is silently repaired or reinterpreted.

## Serialization and loading safety

- The checkpoint format contains **no pickle, no code, and no
  object graph** — only a JSON header and raw float32 bytes.
- Loading never calls `torch.load`, `pickle`, `eval`, or `exec`.
- Tensors are reconstructed with `torch.frombuffer(...).clone()`.
- `torch.save` output is explicitly rejected with
  `UNSUPPORTED_FORMAT`.
- Files are read with size caps (`MAX_CHECKPOINT_BYTES`); paths are
  explicit caller-supplied local paths only. There is no download,
  fetch, or path discovery.

Limitation: byte order is the platform native little-endian float32
representation; cross-endian portability is out of scope. The format
also carries no optimizer state — resuming training is a Task 211
non-goal; checkpoints capture weights plus lineage only.

## Artifact lineage and synthetic-only restrictions

- Manifests record model, training, dataset/split, vocabulary, and
  tokenizer identities as hashes bound to the authoritative Task
  207–210 contracts.
- Mutually matching but jointly forged metadata is rejected whenever
  an authoritative source is available: verification compares every
  lineage field against the caller-supplied dataset result,
  vocabulary, configs, and recomputed hashes — not merely for
  internal consistency.
- Only `synthetic-test-only` artifacts are supported; non-training
  operations are rejected (`OPERATION_NOT_PERMITTED`).
- The test partition is never encoded or fitted; integrity preflight
  semantics from Task 210 are unchanged.

## What integrity verification proves (and does not prove)

- Proves: the checkpoint bytes are exactly what the manifest
  describes; the manifest metadata is unaltered; the recorded
  lineage matches the supplied authoritative artifacts.
- Does **not** prove: data authorization, provenance truth,
  semantic correctness, model competence, or safety. A digest is an
  integrity statement relative to the verification process only.

## Relation to neighboring tasks

- Tasks 209–210: unchanged; the manifest layer consumes their
  public contracts (model config hashes, training config hashes,
  dataset/split/vocabulary identities) without duplicating their
  canonical hashing schemes.
- Tasks 212–215: untouched. No inference runtime, advisory adapter,
  offline benchmark suite, or acceptance gate is implemented here.

Run the focused tests with
`pytest tests/test_artifact_manifests_checkpoints.py -q`.
