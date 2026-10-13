# Stage 8 Tokenizer and Vocabulary (Task 208)

Project-controlled, deterministic text tokenization and
training-partition vocabulary construction over the standard
library only. No pretrained tokenizer, vocabulary, merge table,
checkpoint, embedding, model, training, network, download, or
GPU exists anywhere in this path.

## Tokenization rules (tokenizer v1.0)

- Unicode NFC; case preserved exactly.
- Whitespace runs separate words and produce no tokens. Empty
  and whitespace-only inputs validly yield zero tokens.
- Alphanumeric runs (Unicode letters and digits, excluding
  underscore) form one token each: words, numbers, and mixed
  runs such as `abc123` stay whole.
- An ASCII apostrophe between two alphanumerics stays inside
  the word (`don't` is one token); any other apostrophe is a
  single-character token. Non-ASCII apostrophes are always
  punctuation. A trailing possessive (`dogs'`) splits.
- Every other non-whitespace character -- punctuation, symbols,
  underscore, emoji -- is one token each. CJK Unified Ideographs
  (extensions A–F and compatibility ranges) are always individual
  tokens in v1: CJK text without spaces tokenizes per character,
  a documented v1 limitation. Letters of other scripts (for
  example accented Latin) still form word runs.
- Literal reserved spellings (`<pad>`, `<unk>`) tokenize as
  ordinary pieces; spelling can never produce a reserved ID.
- Lone surrogates and non-string inputs are rejected with a
  typed, safe error. Nothing is stringified, coerced, or
  silently repaired.

## Reserved tokens and unknown handling

Reserved IDs, in fixed order: `<pad>` = 0, `<unk>` = 1.
Unseen tokens map to `<unk>` deterministically. Extending the
reserved set requires a tokenizer version change.

## Sequence limits

`TokenizerConfig.max_sequence_length` (1–512) bounds every
encoded output; overlong inputs keep their first tokens
(head truncation). The limit is validated at configuration
time; encoding never exceeds it.

## Vocabulary construction

`build_vocabulary(result, tokenizer_config, policy)` reads
training records exclusively through
`partition_records(result, "train")`. There is no parameter,
path, or record list selecting any other partition, and no code
path reads outside the validated `PreparationResult`.
Validation/test text cannot affect membership, frequencies,
ordering, size, or hashes.

Ordering: reserved tokens first in fixed order, then ordinary
tokens by descending frequency with Unicode code-point order as
the deterministic tie-break. `min_frequency` (default 1) drops
rare tokens; `max_vocab_size` (default unbounded, minimum 2)
caps total entries including reserved tokens. Reserved
spellings are filtered from ordinary entries even when frequent.
An empty training partition yields a reserved-only vocabulary;
nothing is invented from other partitions to compensate.

## Metadata, versions, and hashes

- Tokenizer v1.0, vocabulary v1.0, and vocabulary policy v1.0 are
  recorded in metadata. Any tokenization behavior change requires a
  tokenizer version change; any change to ordering, limits, or
  eligibility rules requires a policy version change.
- Canonical forms (sorted-key compact JSON, SHA-256, Task 104
  scheme): configuration =
  `{tokenizer_version, normalization, preserve_case,
  max_sequence_length, reserved_tokens}`; vocabulary =
  `{vocabulary_version, tokens}`. Exact field lists, no more.
- Metadata records both hashes plus vocabulary size, limits,
  dataset ID, dataset integrity hash, split assignment hash,
  and `data_scope: synthetic-test-only`. Building refuses
  non-test-scoped manifests. A vocabulary necessarily contains
  token strings; it never copies training records, secrets, or
  private paths.
- `verify_vocabulary` recomputes the vocabulary hash from the
  tokens (and the configuration hash when given a config);
  caller-supplied hashes are never trusted. It rejects
  incompatible versions, missing/reordered reserved entries,
  duplicates, size mismatches, and corrupt hashes.

## Limitations

- Per-character CJK, no subword merging, no case folding, no
  semantic understanding, no truth or clinical evaluation.
- Near-duplicate or paraphrased training text yields distinct
  tokens; the vocabulary reflects byte-level distinctions only.
- Current datasets are synthetic-only; no authorized real
  dataset or production model vocabulary exists. Thresholds for
  learned-component acceptance remain pending under the
  Task 206 protocol.
