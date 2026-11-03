# Repository Governance and Corrective Review — 2026-11-03

Repository: `savitrex70/micky-ai`
Authorized write target: `main` only
Starting `main` SHA: `1ab4864da9c0bc48268eb3d3ab18eaabcf6eb332`
Review status: **NOT APPROVED — corrective work is partial; owner-side acceptance remains outstanding.**

## Scope and execution boundary

This review used GitHub's remote repository interface only. No local checkout, worktree, local files, local commands, pytest invocation, PostgreSQL instance, Windows host, or Git bundle was accessed. No local state was changed. The owner retains all local work and pytest execution.

## Remote governance inventory

- The GitHub branch listing returned only `main`; no non-main remote branch was returned for this repository at review time.
- The open pull-request search returned zero open pull requests.
- With no non-main branch returned, there was no candidate non-main ref to bundle or delete. No branch or release ref was deleted.
- No local branches, uncommitted changes, or local refs were inspected; those are intentionally left to the owner.
- The branch API reports `protected: true`, but its embedded protection details report `enabled: false`, enforcement `off`, and no required status checks. The dedicated protection endpoint returned 403 (integration permission limitation). Therefore the requested required-check and branch-rule configuration is **not verified and must be treated as incomplete**.

## Task 057 provider-boundary audit

Remote source inspection and repository code search support these findings:

- `LLMReasoningProvider` is a generic Protocol/data boundary, not a concrete provider implementation.
- `LLMReasoningService` accepts a provider only through explicit constructor injection. Its default is `None`; the reasoning service fails closed with `MODEL_UNAVAILABLE` when a usable context exists and no provider was injected.
- `reasoning_run_stage_7_entry.py` constructs the default service as part of a Stage 7 boundary audit and checks that the provider parameter is injectable and the default provider is absent. This is an audit/check path, not provider activation.
- `reasoning_run_stage_7_dispatch.py` likewise requires explicit provider injection and fails closed when none is supplied.
- The inspected production services contain no concrete provider module or provider auto-selection configuration. Tests exercise the generic seam with test fakes. No external provider invocation or automatic fallback was found in the inspected paths.
- The separate `src/rop/inference/runtime.py` path loads the project-owned native model; it is not an external provider integration.

This is a source/search audit, not a runtime network-denial test. The owner should retain the existing fake-provider boundary and the no-provider fail-closed behavior. No external provider, Ollama runtime, hosted inference, model download, or automatic fallback was added.

## Stage 8 parameter-count reconciliation

The implementation's `_estimate_parameter_count` documents and computes the per-layer count as:

`12 × hidden_dim² + 13 × hidden_dim`.

The derivation is:

- Multi-head attention: packed input projection `3h² + 3h`, plus output projection `h² + h`, total `4h² + 4h`.
- Two LayerNorms: `4h` (each has weight and bias).
- Feed-forward: `Linear(h, 4h)` contributes `4h² + 4h`; `Linear(4h, h)` contributes `4h² + h`; total `8h² + 5h`.
- Per encoder layer: `(4h² + 4h) + 4h + (8h² + 5h) = 12h² + 13h`.

The implementation formula is internally consistent. The Stage 8 model document contained an incorrect FFN bias term (`8h`) and did not state the complete per-layer formula. This review corrects that documentation without changing architecture or model code. Stage 8 model acceptance remains blocked: authorized real data and approved model-specific thresholds/evidence are still pending.

## Stage 10 corpus and evidence reconciliation

- The current versioned fixture is documented as 43 intent cases and 30 regression mappings.
- The Stage 10 implementation record also contained a stale 39-case result from an earlier corpus/revision. The 39-case result is historical and cannot be represented as execution of the current 43-case fixture.
- This review corrects the record to distinguish the earlier 39-case historical metrics from the current 43-case fixture. No current 43-case metrics are asserted unless they are produced by an evaluator run against the current fixture and exact SHA.
- The fixed corpus measures only enumerated synthetic phrase behavior. It does not establish general language understanding, independent validation, clinical validity, or product acceptance.
- Stage 10 closeout remains **NOT APPROVED** until Stage 9 product acceptance is completed.

## Preserved acceptance boundaries and blockers

- Stage 8: **NOT ACCEPTED**. Synthetic-only evidence does not replace authorized real data, predeclared approved thresholds, and held-out model acceptance.
- Stage 9: **NOT APPROVED**. Owner-target browser/end-to-end walkthrough, OS-level outbound-network-denial evidence, and measured startup/resource observations remain outstanding.
- Stage 10: implementation evidence is separate from product acceptance; closeout remains **NOT APPROVED** while Stage 9 remains open.
- Existing privacy, clinical/personal-data separation, authorization, confirmation, idempotency, offline-boundary, provenance, and audit guarantees are not intentionally weakened by this documentation-only correction.
- No full or focused pytest, Ruff, Black, Stage 10 evaluator, PostgreSQL migration, Windows retrieval, or local test command was run in this review. The owner explicitly retains local and pytest validation.

## Changes made by this review

- Correct the Stage 8 FFN parameter/bias formula and show the per-layer derivation.
- Correct Stage 10 documentation so the historical 39-case metrics are not confused with the current 43-case fixture.
- Add this dated governance and corrective-review record.

## Verification and final verdict

Starting SHA: `1ab4864da9c0bc48268eb3d3ab18eaabcf6eb332`
Correction commit containing the three review artifacts: `99c83fcd5bcfb51b7a943262a55e65f3eefd09a0`.
Remote CI for correction commit `99c83fcd5bcfb51b7a943262a55e65f3eefd09a0`: run `41709984847` was created by the push and was queued when this report was prepared. Its final result must be checked separately; CI is not a substitute for owner-side acceptance evidence.

**Verdict: NOT APPROVED.** The documentation corrections do not resolve incomplete branch protection, Stage 8 data/threshold blockers, Stage 9 owner-side evidence, or Stage 10 product closeout. No claim of local validation or full assignment completion is made.
