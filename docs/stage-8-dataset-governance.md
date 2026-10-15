# Stage 8 Dataset Governance (Task 207)

Offline dataset-governance and preparation infrastructure. This
is infrastructure only: ROP has no approved real dataset, and no
real-data evaluation, training, or model work is authorized by
this task.

## Authorization trust model

- A `DataSourceAuthorization` record describes source, origin,
  license basis, purpose, operations, retention notes,
  restrictions, status, approval reference, and optional expiry.
  Shape validation never equals authentication: constructing the
  model directly proves nothing.
- Trust is containment, not verification. The preparation API
  accepts only a `TrustedSourceRegistry`, which today can express
  solely the `synthetic-test-only` kind with test-namespaced
  entries. Raw mappings, manifest fields, booleans, and bare
  authorization models passed to the preparation API are rejected
  outright. The `synthetic-test-` prefix is a namespace
  convention that keeps fixtures from colliding with future real
  identifiers -- it proves nothing about an approval and is
  never represented as authentication. What the prefix plus the
  registry kind do enforce is test-only containment: a test-only
  registry cannot authorize a production-named dataset
  (identifiers must carry the `synthetic-` scope), and every
  manifest produced carries `authorization_kind:
  synthetic-test-only` permanently. Fabricated approvals
  therefore yield, at most, test-marked fixtures -- never
  production-trusted artifacts. There is no production
  composition path: manufacturing one would require a reviewed
  approval-verification mechanism that does not exist, so
  preparing non-test data fails closed.
- Every record's source must resolve to a registry entry that is
  `APPROVED`, purpose- and operation-matched, unexpired as of the
  explicit reference date, and restriction-free. Anything else
  fails closed before the record is admitted.
- Approval-reference authenticity cannot be verified in-process;
  it depends on registry composition, documented here as a
  limitation. Non-empty `restrictions` and `retention_notes` are
  audit metadata only: entries carrying unevaluated restrictions
  are refused for automated preparation, and retention is not
  enforced by the offline pipeline.

## What is and is not trusted

Trusted after validation: record identifiers, group bindings,
normalized content bytes covered by a verified digest, and
governance metadata from the injected registry. Never trusted:
caller-supplied approval flags, provenance authenticity, or the
real-world meaning of labels. Hashing proves byte integrity, not
authenticity, authorization, de-identification, or privacy.

## Validation and normalization (transform v1.0)

Unicode NFC, strip, collapse whitespace runs to one space; case
preserved. Order per record: source membership, authorization
validity, identifier presence, normalization, content policy
(credentials/absolute paths rejected), label allow-list,
digest verification, strict schema validation. Rejections carry
record id plus a bounded reason code only -- never content,
credentials, paths, or secrets. Record identifiers are compared
verbatim and never normalized, so references cannot detach.

## Duplicates (policy v1.0)

Exact groups share a content hash; near groups are word-bigram
Jaccard components at threshold 0.8. Label disagreement
quarantines the whole group (`LABEL_CONFLICT`); otherwise the
smallest record id is retained. Provenance differences do not
rescue duplication. Near-duplicate detection is bag-of-words
only: order- and negation-blind, unstable on short texts, and
not a semantic-equivalence claim. Pairwise comparison bounds
scaling; production use would need blocking (out of scope).

## Splits (policy group-hash-partition-v1)

Groups (by validated `group_id`, whose meaning is declared per
run in `grouping_unit`) are assigned by seeded hash to exactly
one partition; related records never cross boundaries. Two
explicit guards replace silent behavior: fewer groups than
nonzero-ratio partitions fails closed (`INSUFFICIENT_GROUPS`),
and a requested nonzero-ratio partition left empty by hash
assignment fails closed (`EMPTY_PARTITION`) instead of shipping
an unusable held-out split, retuning the seed, or falling back
to record-level splitting. Ratios are approximate by design
(whole groups cannot match exact proportions) and zero-ratio
partitions are legitimately empty. No stratification is
performed: rare-label coverage is reported, not guaranteed.
Test records are held back by construction -- train through the
`partition_records(result, "train")` accessor, which cannot yield
validation or test records. Split integrity (membership,
uniqueness, group confinement, partition coverage, counts,
hashes, byte-identical reproduction, no silent re-entry of
rejected records) is verified independently before the result is
returned.

## Manifests and hashes

`DatasetManifest` (v2.1) carries identifiers, policy versions,
counts, label/rejection tallies, and a record-integrity hash
binding every retained record's identity, source, group, label,
validated content digest, and provenance reference (raw content
never embedded). Both manifests carry `authorization_kind:
synthetic-test-only`, permanently marking their trust scope.
`SplitManifest` (v1.1) carries the policy, seed,
ratios, sorted group assignments, partition counts, and the
assignment hash bound to the dataset integrity hash. The v1
content-only hash is not interchangeable: old manifests fail
verification under the new code. No raw content. Canonical bytes
are sorted-key compact JSON with SHA-256 (the Task 104 scheme);
hashed assignment strings carry a domain-separation prefix.

## Privacy and repository safeguards

Synthetic fixtures use unmistakable `synthetic-test-*`
identifiers. Sentinel injection tests prove rejection paths never
echo sensitive strings. No artifact directories are introduced:
preparation is pure in-memory with no file output, so no
`.gitignore` change was needed. Never commit real data,
credentials, or private records; suitability for real data
additionally requires reviewed registry composition, currently
absent.

## Running the synthetic tests

```powershell
Copy-Item .env.example .env   # once; dummy settings only
pytest tests/test_dataset_preparation.py -q
ruff check src/rop/dataset_preparation src/rop/schemas/dataset_authorization.py src/rop/schemas/dataset_manifest.py tests/test_dataset_preparation.py
black --check src/rop/dataset_preparation src/rop/schemas/dataset_authorization.py src/rop/schemas/dataset_manifest.py tests/test_dataset_preparation.py
```

## Before real data can be admitted

Reviewed registry composition from authenticated approval
sources; documented lawful basis per source; retention/deletion
procedure with an enforcing owner; privacy review with leakage
scans; Task 207 split-manifest versioning for the approved
partitions; and Task 208+ readiness. None exists today: all
preparation remains synthetic-only.

## Decision required before real-data work (audit record)

The current contract expresses exactly one trust scope:
`authorization_kind: Literal["synthetic-test-only"]`
(`src/rop/schemas/dataset_manifest.py`). This restriction is
deliberate, and closing it for real data is not an engineering task
this repository can decide alone. The pending decision is the
project-owner approval to (a) define a reviewed, versioned
real-data authorization contract inside the existing Task 207
design — meeting every requirement listed in the previous section —
and (b) designate the specific authorized source(s) and legal
basis, before any dataset is acquired. Until that decision is made
and recorded, this contract must stay unchanged: no relabeled
synthetic data, no invented approvals, and no new authorization
scheme outside the reviewed design.
