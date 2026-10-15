# Task 215 — End-to-End Evaluation Acceptance Gate

A deterministic, fail-closed acceptance decision over existing
validated evidence: a Task 214 benchmark report and a Task 206
baseline evaluation report, evaluated under a versioned acceptance
policy. `evaluate_acceptance()` in `src/rop/evaluation/acceptance.py`
returns an immutable `AcceptanceReport` (`src/rop/schemas/acceptance.py`)
with decision `PASS` or `FAIL`.

## What acceptance means

Acceptance means all 15 mandatory criteria evaluated to pass on the
supplied evidence:

- benchmark contract supported, revalidated, and pinned to the exact
  evidence hash the policy accepts;
- benchmark artifact, vocabulary, policy, configuration, and case-set
  identities match the policy;
- benchmark measurements within declared budgets (a resource result
  only — not inference quality);
- benchmark declares local offline execution;
- evaluation contract supported, revalidated, and pinned;
- evaluation case set matches the policy;
- evaluation run completed cleanly (`run_valid`, no errors);
- every required threshold passed (missing counts as failure).
  Five Task 206 baseline integrity gates are mandatory regardless of
  what the policy lists — `unsupported-references-zero`,
  `invalid-input-all-pass`, `run-valid`, `baseline-self-consistency`,
  and `determinism` — each must be present with status `passed`.
  Caller-supplied required thresholds are strictly additive and can
  never replace or omit these. Pending model-evaluation thresholds
  are never required and never fabricated as passed;
- determinism repeat evidence complete with no divergence;
- no input claims clinical utility or prior acceptance;
- evidence acknowledged as synthetic-scope with a stated disclaimer.

Anything missing, invalid, mismatched, or contradictory is a `FAIL`,
never a warning that still permits acceptance. Structurally invalid
evidence (failed revalidation) raises a sanitized `AcceptanceError`
instead of producing a decision.

## What acceptance does not establish

PASS establishes no model accuracy, safety, clinical utility, or
readiness. The limitations are part of every report: traced memory is
not process RSS, offline mode describes the exercised code path, the
benchmark's deterministic contexts are measurement scaffolding rather
than reasoning evidence, and the evaluation evidence is synthetic-scope
only.

## Threshold evidence must be unambiguous

Every threshold ID in the evaluation report must be unique. Duplicate
IDs are rejected before any decision (`EVIDENCE_INVALID`: evaluation
threshold identifiers are not unique), because a dictionary lookup
would otherwise silently let a later duplicate record win regardless
of status or order. The uniqueness check lives in Task 215 because
the approved Task 206 report schema permits repeated IDs and its
public contract was not modified for this gate; list ordering is
never trusted.

## Identity and auditability

Expectations come from the `AcceptancePolicy`; bound values come from
the revalidated reports. Report hashes use existing canonical
functions (`report_sha256`, `canonical_json_bytes`). The gate digest
binds policy, exact evidence hashes, criterion outcomes, and decision,
so a decision can be independently rechecked from the same inputs.
No raw inputs are retained; error messages carry only stable codes.

## Boundaries preserved

The gate performs no inference and no validation of its own: Task 212
and Task 213 boundaries are never bypassed, weakened, or duplicated.
Advisory suggestions are never treated as decisions. No network,
providers, downloads, serving, persistence, or clinical logic exists
in this path.

## Tests

`tests/test_acceptance_gate.py` uses benchmark evidence from the real
Task 214 runner over a stub model plus hand-built Task 206 reports,
all labeled synthetic. It covers passing evidence, missing evidence,
unsupported versions, every identity mismatch, caller-supplied
identity substitution, unknown fields, contradictory reports, failed
and missing criteria, determinism, sanitized failures, recorded
limitations, and Task 212/213 regression. No network, downloads, or
real data are required.
