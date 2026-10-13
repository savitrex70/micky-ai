# Stage 8 Baseline Evaluation Protocol (v1.0)

**Status:** Active for deterministic baseline contract evaluation.
**Version:** `1.0`. Any threshold or metric change requires a reviewed
version bump before the affected final evaluation is run.
**Scope:** Tasks 202–205 deterministic engine only. No model, training
data, or dataset pipeline is evaluated here.

## 1. What the Task 206 work found

- The deterministic engine on `main` consists of: strict
  request/result/error contracts (Task 202), structured evidence and
  provenance records with content digests (Task 203), exact
  request/evidence binding (Task 204), and a composition service with
  explicit support rules (exact-content match), contradiction-pair
  rules (configured mutually exclusive expectations), and
  missing-information requirements (Task 205).
- A finding therefore means *"the configured content expectation was
  met by exactly these validated records"* — never clinical truth,
  real-world verification, or semantic understanding. The harness
  evaluates exactly these bounded semantics and must not present
  them as anything broader.
- `src/rop/evaluation/` exists but is empty; there is no prior
  evaluation utility to reuse. Conventions reused: Pydantic strict
  schemas (`extra="forbid"`, frozen, tuples), generic error
  messages, deterministic JSON, UUID5 identifiers, argparse CLIs
  (`python -m rop.cli`), pytest + Ruff + Black gates.
- The repository requires `ROP_*` settings for any import (see
  `tests/conftest.py`, `.env.example`). The harness needs the same
  dummy settings as every dev command, but opens no database
  session, connection, or network socket.
- **Data availability gate:** no approved or authorized real
  evaluation dataset exists in the repository. All Task 206
  evaluation is synthetic-only and labeled as contract/behavior
  testing. Real-data evaluation remains blocked pending Task 207
  authorization. No provenance, rights, sizes, or performance
  beyond the synthetic set are claimed.

## 2. Evaluation target

The deterministic composition service
(`NativeCompositionService`) at the recorded baseline revision,
driven through its public contract (`compose` over validated
`NativeEvidenceBinding`), configured per case by the checked-in
synthetic case set. Contract versions: Task 202/203/204 schemas as
on `main`; case-set version `1.0`; report schema version `1.0`.

## 3. Cases and labels

- Case sets are versioned JSON files with stable case identifiers,
  a schema version, per-case category, safe description, explicit
  composition configuration (support/contradiction rules,
  requirements), and independently authored expected outcomes
  (status, reason code, exact evidence references). Expectations
  are authored from the contracts, then verified by running the
  harness; a mismatch is investigated as a fixture or
  implementation defect, never resolved by copying outputs.
- Categories: `supported`, `contradiction`, `insufficient`,
  `abstention`, `invalid-input`.
- Inclusion: cases exercising all four result statuses and the
  §7 boundaries below. Exclusion: anything requiring a model,
  network, GPU, real patient data, or clinical judgment.
- Malformed case files are rejected whole: unknown fields,
  duplicate case IDs, unsupported statuses/reasons, empty sets.
  No partial success.
- Malformed engine inputs are `invalid-input` cases with an
  expected typed error invariant (`INVALID_BINDING`); they are
  counted separately and never scored as predictions.
- `UNREADABLE` records (empty content, empty digest) must never
  count as readable support or contradiction.
- Evaluation order is sorted case-ID order regardless of file
  order. Reports exclude timestamps entirely.

## 4. Status semantics under evaluation

- `SUPPORTED`/`RULE_MATCH`: the configured content expectation was
  met by exactly the cited records.
- `CONTRADICTED`/`RULE_CONTRADICTION_FOUND`: both sides of a
  configured mutually exclusive pair were met; refs are exact per
  side and disjoint. Different text alone is not a contradiction;
  a missing/unreadable side is not a contradiction.
- `INSUFFICIENT`/`EVIDENCE_MISSING`: a configured requirement is
  unmet; missing IDs are the stable symbolic requirement
  identifiers. Empty evidence is `INSUFFICIENT` only when a
  requirement establishes necessity, else `ABSTAINED`.
- `ABSTAINED`/`NO_JUSTIFIED_BASIS`: no rule applies or no
  predicate matched; carries no refs and no rule. Never disguised
  success; never scored as failure for declining.

## 5. Metrics (numerator / denominator / zero rule)

- **Status agreement:** matching statuses / valid cases. Empty
  valid set → null (threshold fails).
- **Reason-code agreement:** matching reasons / valid cases with
  an expected reason (all of them). Empty → null.
- **Evidence-reference exactness:** cases with exact
  supporting/contradicting/missing sets / valid cases. A status
  match with fabricated, detached, unrelated, or misclassified
  refs scores incorrect.
- **Unsupported-reference rate:** refs in results absent from the
  validated input set / total emitted refs. Zero emitted →
  rate `0.0` with `denominator_zero: true`. Target is **zero**;
  non-zero fails the integrity gate regardless of accuracy.
- **Contradiction:** correct (expected + exact), false (emitted but
  not expected). **Abstention:** correct, unjustified
  (expected abstain, got supported/contradicted).
  **Insufficiency:** correct, incorrect.
- **Coverage:** per-status counts; abstention rate =
  abstained / valid. Lower abstention is not automatically better.
- **Determinism:** every case evaluated twice per run; report
  bytes after canonical serialization must be identical across
  runs (no timestamps exist to exclude).
- **Integrity:** invalid-input passed/failed; unexpected errors
  (case ID + fixed label only) fail the run — reports marked
  invalid, never silently dropped.

## 6. Thresholds

Approved integrity/contract gates (must pass):

- `unsupported-references-zero`: unsupported count is zero.
- `invalid-input-all-pass`: every invalid-input case raises its
  expected typed error (and at least one such case exists).
- `run-valid`: no unexpected evaluation errors.

Provisional operational targets:

- `baseline-self-consistency`: status agreement is 1.0 on the
  synthetic set (guards fixture/implementation drift).
- `determinism`: repeat evaluation identical.

Pending (block final model acceptance; never default silently):

- `model-valid-contract-rate`, `model-fabricated-refs-zero`,
  `model-false-contradiction-rate`, `model-abstention-respect`,
  `model-accuracy-vs-baseline`, `model-repeatability-offline`,
  `model-resource-limits`. Each is `pending` with reason
  "pending task/data approval". A pending gate blocks acceptance;
  it is not zero, 100%, or any invented value.

A later threshold change requires a reviewed protocol version
change **before** the affected final evaluation is run. Thresholds
are never tuned after inspecting held-out results.

## 7. Held-out and leakage policy (for Task 207+)

Train/validation/final-test partitions kept separate; final test
records and labels excluded from training and tuning; grouping by
patient/source/document before splitting; deduplication before
splitting; data-dependent preprocessing fit on training only;
versioned split manifests with seed and grouping policy. Task 206
implements none of this pipeline — it only constrains future work.
Synthetic fixtures never establish real-world accuracy and never
replace an authorized held-out dataset.

## 8. Report and reproducibility

Machine-readable JSON report (schema `1.0`): versions, baseline
revision (or explicit `unresolved-baseline`), case-set ID/version/
SHA-256, counts, all §5 metrics, per-category outcomes,
distribution, determinism outcome, threshold statuses, model
acceptance (`evaluated: false`, `accepted: false` while no learned
component is evaluated), and a synthetic-only disclaimer. No
timestamps, no raw sensitive inputs, no credentials. Canonical
bytes = `json.dumps` with sorted keys and compact separators;
hashes are SHA-256 of exactly those bytes.

## 9. Running the harness

```powershell
Copy-Item .env.example .env   # once; dummy settings, no DB needed
python -m rop.evaluation --cases src/rop/evaluation/synthetic_cases_v1.json
python -m rop.evaluation --cases src/rop/evaluation/synthetic_cases_v1.json --report eval-report.json --baseline-revision <git-sha>
```

Exit `0` only when the run is valid and every decided threshold
passes; exit `1` otherwise (the report is still printed when the
evaluation completed). A standalone `rop.cli` subcommand was
deliberately not used: the shared CLI runner requires a database
session and `ROP_*` service configuration, while evaluation must
run session-free.

## 10. Known limitations and blocked gates

- Synthetic-only: no real-world accuracy or clinical-validity
  claim; no authorized dataset exists.
- Only exact-match/pair/requirement semantics are evaluated —
  the full breadth of future tasks is not covered.
- Pending model thresholds and Task 207 data authorization block
  any model acceptance. A passing baseline report means "harness
  contract tests passed", never "model accepted".
