# Stage 8 Acceptance-Readiness Checklist (governance record)

**Status:** Readiness record only. Not an approval, not a sign-off, and
not Stage 8 acceptance. Every item below either points at evidence
that already exists in the repository or names the human decision
that is still pending. No dataset, authorization record, numeric
threshold, improvement margin, sample size, approver, or sign-off is
invented here.

This checklist consolidates — it does not restate — the authoritative
sources:

- `stage-8-native-intelligence-architecture.md` §9 (acceptance
  criteria), §6 and §10 (comparison and measured-value requirements)
- `stage-8-baseline-evaluation-protocol.md` §6 (protocol-version
  ordering), §7 (held-out and leakage policy)
- `stage-8-dataset-governance.md` ("Before real data can be
  admitted"; "Decision required before real-data work")
- `stage-8-model-thresholds-schedule.md` (PROPOSED, NOT APPROVED)
- `stage-8-local-inference-runtime.md` (dynamic offline enforcement)

## A. Dataset authorization and lineage

| Item | Status | Evidence / required action |
| --- | --- | --- |
| Leakage-safe split infrastructure, group binding, test-partition exclusion | DEMONSTRATED | `verify_split` (`src/rop/dataset_preparation/pipeline.py:577–599`); Task 210 preflight and `test_loop_never_requests_test_partition` |
| Governance process definition (rights, provenance, retention, privacy review, versioned splits) | DEMONSTRATED (as requirements) | `stage-8-dataset-governance.md`, "Before real data can be admitted" |
| Authorized real dataset + authorization/provenance record | UNFULFILLED — OWNER DECISION BLOCKED | No authorized real dataset or authorization record was identified in the repository evidence reviewed; external existence is unverified, not inferred. The `DatasetManifest` `authorization_kind` is restricted to `synthetic-test-only` (`src/rop/schemas/dataset_manifest.py:184,244`) and must not be bypassed. See the governance doc's "Decision required" section. |
| Documented permitted purpose, retention owner, lawful basis | UNFULFILLED | Depends entirely on the authorization decision above; the requirements are already written in the governance doc. |

## B. The seven model-specific thresholds (all `pending`, unapproved)

Definitions and proposed targets live only in
`stage-8-model-thresholds-schedule.md` (marked PROPOSED). Facts:

- They are live records with `pending` status in
  `src/rop/evaluation/harness.py:479–532`, reason `pending
  task/data approval`; they legitimately block model acceptance.
- They are deliberately not part of Task 215's mandatory integrity
  thresholds (`MANDATORY_EVALUATION_THRESHOLD_IDS`,
  `src/rop/schemas/acceptance.py`).
- Unlock requires: owner review of the proposed schedule → approved
  target values (For `model-accuracy-vs-baseline`: strict measurable
  improvement over the baseline, ties fail; the minimum margin and
  the uncertainty/evidence bar are review-predeclared numbers) → a
  reviewed protocol version bump → and only then, an authorized
  dataset per §A.

## C. Evaluation design evidence to predeclare (before any held-out inspection)

Unfulfilled by design — no real evaluation exists yet:

- Sample-size expectation and per-class reporting requirement:
  UNFULFILLED (must be set in the protocol bump; no number is
  invented here).
- Subgroup analysis requirement: DEFERRED-BY-DESIGN — architecture
  §4.11/§5 applies it only where authorized and statistically
  meaningful.
- Resource limits: the mechanism exists and is self-verifying —
  `BenchmarkConfig` budgets and `within_declared_budgets`
  (`src/rop/schemas/benchmark.py`); the budget VALUES for a real
  environment require review approval (traced-memory and
  offline-mode limitations documented in Task 214).

## D. Protocol ordering (already binding, unchanged)

The version-bump-before-final-evaluation rule is consistent across
sources: architecture §9 ("thresholds must be approved before final
evaluation", line 267), protocol header and §6 ("before the affected
final evaluation is run", line 9; "never tuned after inspecting
held-out results", line 179). No conflict found; Stage 8 acceptance
must respect this order in all future steps.

## E. Verification, reproducibility, regression, safety, sign-off

| Item | Status | Evidence |
| --- | --- | --- |
| Dynamic offline boundary enforcement | DEMONSTRATED | `tests/test_native_offline_boundary.py` (6 tests); static scans retained; limitation documented in `stage-8-local-inference-runtime.md` |
| Ownership (first-party init, hash-bound manifest), deterministic baseline, evidence integrity, contract enforcement, reproducibility | DEMONSTRATED (synthetic scope) | `native_model.py` seeded init; `artifacts/checkpoints.py` manifest; harness gates; Task 202–205 suites; 515-test Stage 8 run green; baseline CLI run exit 0 |
| Held-out model results vs baseline | BLOCKED-BY-PENDING (§A + §B) | Cannot be obtained until authorization and threshold approval exist; not inspected |
| Explicit final sign-off | UNFULFILLED — OWNER DECISION | The architecture's §9 requires explicit review and sign-off of end-to-end evaluation; no sign-off record exists and none may be created by this repository |

## F. Decision summary (project-owner items; not exercisable here)

1. Approve/define the reviewed real-data authorization contract and
   designate authorized source(s) + lawful basis (§A).
2. Approve or reject each proposed threshold definition/target; set
   the accuracy margin and uncertainty bar; approve a protocol
   version bump (§B, §C).
3. Provide the final review sign-off record after a legitimate
   held-out evaluation (§E).

The next authorized action after these decisions is stated in the
governance doc; it is not real-data evaluation and it is not Stage 9.
This document itself creates no acceptance: **Stage 8 remains NOT
accepted.**
