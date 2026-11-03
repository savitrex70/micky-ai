# Repository Governance and Corrective Review — 2026-11-03

Repository: `savitrex70/micky-ai`
Authorized write target: `main` only
Reviewed main SHA (the exact revision validated by workflow run 41710017623): `9118490cf10e4e0b49892ae04217e9205709b874`
Report correction is committed directly to `main`; its resulting commit SHA is reported in the handoff accompanying this record.
Review status: **NOT APPROVED — repository CI passed, but Stage 8/9/10 acceptance evidence remains outstanding.**

## Scope and execution boundary

This review used GitHub's remote repository interface only. No owner-machine checkout, worktree, local files, local commands, local pytest invocation, browser walkthrough, or network-denial test was accessed. The audit container could not resolve github.com, so a bare clone and Git bundle could not be created; this failure and the absence of a bundle are documented in the branch-cleanup section. The owner retains all local work and local pytest execution. Remote GitHub Actions evidence is identified separately below and must not be interpreted as owner-machine acceptance evidence.

## Remote governance inventory and active rulesets

The remote branch inventory at the time of the original review returned exactly one branch, `main`, at SHA `9118490cf10e4e0b49892ae04217e9205709b874`, and zero open pull requests. That current inventory did not mean that no branches had been deleted. A subsequent branch-cleanup audit (documented below) reconciles the earlier historical inventory of 25 branches (main plus 24 non-main refs) with the current main-only inventory. It confirms deletion of those 24 non-main refs; the earlier statement that no branch had been deleted is superseded.

Two repository rulesets are active and target only `refs/heads/main`:

### Ruleset 26409138 — `main: prevent force-push and deletion`

- Enforcement: **active**.
- Rules: `deletion` and `non_fast_forward`.
- Bypass actors: **none**.
- Current owner bypass capability: **never**.
- Effect: main cannot be deleted or updated non-fast-forward; the owner cannot bypass these protections.
- This ruleset was not modified or weakened by this report correction.

### Ruleset 26409161 — `main: required status checks (owner direct-push bypass)`

- Enforcement: **active**.
- Required checks:
  - `Ruff`
  - `Black (24.10.0)`
  - `Tests (Python 3.12, PostgreSQL)`
  - `Windows retrieval (Python 3.12)`
- Bypass actor: user ID `222614714` (repository owner).
- Bypass mode: **`always`**.
- Current owner's bypass capability: **`always`**.

**Important enforcement qualification:** the required-check ruleset preserves the owner's ability to push directly to `main`, but it also means the owner can bypass the required checks. Therefore these checks are not an unconditional hard gate for owner pushes. The deletion and non-fast-forward protections in ruleset 26409138 remain separately active and non-bypassable by the owner.

The branch endpoint's legacy `protected` summary and embedded classic-protection fields are not an accurate substitute for inspecting these repository rulesets. The two ruleset detail records above are the governing evidence used for this review.


## Branch-cleanup audit correction — 2026-11-03

This section supersedes the earlier statement that no branches were deleted. The historical repository review recorded **25 remote branches: main plus 24 non-main branches**. The current GitHub GET /branches inventory returns only **main**, at the then-current main SHA 122f26afe08927318cee4b095effef1f0ec199d1. The difference is a real branch cleanup, not an inventory inconsistency.

### Reconciled deleted branch refs

GitHub PR issue-event records expose head_ref_deleted events for the following 24 refs. They map to PR #4 and PRs #6–#28, matching the historical count of 24 non-main refs. Each corresponding refs/heads/<name> ref is no longer present in the current branch inventory. The head commit remains reachable through the corresponding GitHub pull-request head ref refs/pull/<number>/head.

| PR | Deleted branch ref | Historical head commit |
|---:|---|---|
| #4 | arena/01a0d2b1-micky-ai | 9c0d463d446d24f284477b3a56536d9bc528c504 |
| #6 | automation/add-github-actions-ci | b45c831a440557c20776d1962dadf63f745551be |
| #7 | task-193-contradiction-precedence | 7e330846b849ff9e00a7e9e19ea7a28c14d3af6b |
| #8 | task-194-session-fingerprint-binding | c3853a0c2a9b02650fac359a6369008de68f69b4 |
| #9 | task-195-provenance-attribution-binding | fa851f25e4ae9349791a92b0a4508f01f821617a |
| #10 | task-196-handoff-child-source-integrity | 4eb43f7ce653591b9a7f67b6ab1b43f847cf9272 |
| #11 | task-197-blocked-source-forgery-precedence | 0c7c1f9a15eee8be4cb43ae107c775923710f9f1 |
| #12 | task-198-provider-isolation-evidence-privacy | 1c8898343bb88944ed40aaaf7b4f8563005864e0 |
| #13 | task-200-complete-stage7-integration | 62b493435965bd0abc62a879d4facde7c64298a4 |
| #14 | task-201-native-intelligence-architecture | 3b3c75d762ef147d8919108b7caa6f2bb3478220 |
| #15 | task-201-fix-stage7-gate-failures | 17eba68fb16cbb772d7a0a26674f00ceb9ec9717 |
| #16 | task-203-structured-evidence-provenance | bea304dbe481f55d54527f74fe561ef7bb509521 |
| #17 | task-204-deterministic-reasoning-composition | ccdd315be7d071842aa58d84840b2c3df1270bb0 |
| #18 | task-205-abstention-contradictions | 99726500f0aed754faea53ac4f68862288bbdc50 |
| #19 | task-206-baseline-evaluation-harness | 5c999bf088d29ecb398794653ddf747081401fae |
| #20 | task-207-authorized-dataset-pipeline | 203cddddd6308fa61e1131c6c53a10c5c46632e6 |
| #21 | task-208-project-tokenizer | 3a2880c5a4c53c0bb0dbfdb8ae947fb3f1c4cb43 |
| #22 | task-209-native-model-from-scratch | f95d8e1ab5209a3085cfbeb7ddd129bb8c179f2c |
| #23 | task-210-reproducible-native-training | 5305197bab577f0d45d8ef4983b4dbe68dbe6952 |
| #24 | task-211-native-artifact-integrity | 7836db8d874ea7c410708d08825a41acdd99485e |
| #25 | task-212-offline-local-inference | 78b94f94081c96163deff912ad7d816b543deeae |
| #26 | task-213-strict-suggestion-validation | 9152ec058f1d914d9c440fc140418a532ba96e79 |
| #27 | task-214-offline-resource-benchmarks | ceee6a501f18f0247da5e5ecdf6af651eedd4860 |
| #28 | task-215-stage8-acceptance-gate | 4e476d954d731b86f6272bcdb8a725eac40b52d4 |

PRs #19–#28 are all **closed and unmerged**. Their recorded head branches and SHAs are preserved in PR metadata. The wider 24-ref cleanup also included PR #4 (merged) and PRs #6–#13 and #15 (merged); PRs #14 and #16–#28 were closed unmerged. PR #5's branch unified-deterministic-reasoning-inspection-76f80 (head d9db78b10627c847abcfae0f8f42f8a6e43b8d4c) was deleted separately on 2026-10-04. PRs #1–#3 had their head refs deleted on 2026-09-24. Those earlier deletions are outside the 24-ref inventory reconciliation above.

### Deletion attribution

GitHub issue-event records attribute the head_ref_deleted events for PR #4 and PRs #6–#28 to account **savitrex70**, in a batch between **2026-11-02 23:33:01 UTC and 23:33:06 UTC**. PR #5's earlier deletion event is also attributed to savitrex70; PRs #1–#3 likewise show that account as actor for their September 24 deletions.

This establishes the GitHub account recorded as the actor. It does **not** establish whether the account action was performed interactively by the owner or by an agent/automation using credentials for that same account. The available PR issue events do not identify the human-or-agent operator, and no repository audit-log evidence identifying that operator was available. Therefore this audit does not attribute the deletions specifically to the assistant or to the owner personally.

### Recoverability and backup status

- Direct GitHub API reads of refs/pull/4/head and refs/pull/6/head through refs/pull/28/head returned the historical head commits. The closed PR head refs therefore remain fetchable from GitHub despite the deleted task branch refs. PR #5's head ref was also returned by the matching-refs listing.
- The historical commits are therefore recoverable from GitHub at the time of this audit. This is not the same as a locally held backup.
- No pre-existing Git bundle or equivalent backup was evidenced by the repository/PR records inspected.
- An attempt to create a bare clone and bundle in the audit container failed before cloning because the environment could not resolve github.com (Could not resolve host: github.com). No bundle was created. Consequently there is **no bundle path, SHA-256 digest, or bundle manifest** to report.
- No remote task branch was recreated or pushed. No Git history was rewritten, reset, amended, or force-pushed.

### PR disposition summary

PRs #19–#28: **10 closed, 0 merged, 10 unmerged**. Their historical head commits remain accessible through GitHub's pull-request refs. The branch cleanup removed the named task refs; it did not itself merge these PRs or move their commits onto main.


## CI evidence for exact commits

### Run 41710017623 — reviewed SHA

- Workflow: [CI run 41710017623](https://github.com/savitrex70/micky-ai/actions/runs/41710017623)
- Event/branch: push to `main`.
- Exact head SHA: `9118490cf10e4e0b49892ae04217e9205709b874`.
- Final run status: **completed / success**.
- All four jobs completed successfully:
  - `Tests (Python 3.12, PostgreSQL)` — success. The job initialized a disposable PostgreSQL service, applied migrations, ran the Stage 10 fixed-intent evaluation, and ran the full CI test suite.
  - `Windows retrieval (Python 3.12)` — success on a GitHub-hosted Windows runner; native Windows retrieval tests completed successfully.
  - `Black (24.10.0)` — success.
  - `Ruff` — success.

The retrieved job log provides the following exact results for this SHA:
- Full pytest suite: **8,316 passed, 9 skipped, 42 warnings**, in 940.99 seconds; no failures were reported.
- Stage 10 fixed-intent evaluator: **43 passed cases**, no failed cases, intent precision **1.0**, intent recall **1.0**. These metrics are for the current 43-case synthetic fixture at this SHA only.
- Windows retrieval tests: **14 passed, 2 warnings**, in 10.58 seconds on the GitHub-hosted Windows runner.
- Ruff: `All checks passed!`
- Black (24.10.0): job completed successfully.

These are remote GitHub Actions results for this exact SHA, not owner-machine results.

### Run 41709984847 — earlier, separate commit

- Workflow: [CI run 41709984847](https://github.com/savitrex70/micky-ai/actions/runs/41709984847)
- Exact head SHA: `99c83fcd5bcfb51b7a943262a55e65f3eefd09a0`.
- Final run status: **completed / success**.
- All four jobs completed successfully: Tests (Python 3.12, PostgreSQL), Windows retrieval (Python 3.12), Black (24.10.0), and Ruff.

This successful run belongs only to SHA `99c83fcd5bcfb51b7a943262a55e65f3eefd09a0`. Its results are not transferred to, substituted for, or claimed as evidence for any other commit. Its run metadata likewise does not expose numeric pytest totals.

Remote Windows CI is evidence that the dedicated GitHub-hosted Windows job passed. It is not evidence that the owner's local Windows environment, browser, OS-level network controls, or local worktree were inspected or validated. Similarly, the disposable PostgreSQL CI job is remote CI evidence, not an owner-managed production database validation.

## Task 057 provider-boundary audit

Remote source inspection and repository code search support these findings:

- `LLMReasoningProvider` is a generic Protocol/data boundary, not a concrete provider implementation.
- `LLMReasoningService` accepts a provider only through explicit constructor injection. Its default is `None`; the reasoning service fails closed with `MODEL_UNAVAILABLE` when a usable context exists and no provider was injected.
- `reasoning_run_stage_7_entry.py` constructs the default service as part of a Stage 7 boundary audit and checks that the provider parameter is injectable and the default provider is absent. This is an audit/check path, not provider activation.
- `reasoning_run_stage_7_dispatch.py` likewise requires explicit provider injection and fails closed when none is supplied.
- The inspected production services contain no concrete provider module or provider auto-selection configuration. Tests exercise the generic seam with test fakes. No external provider invocation or automatic fallback was found in the inspected paths.
- The separate `src/rop/inference/runtime.py` path loads the project-owned native model; it is not an external provider integration.

The generic injectable test seam and its test contracts are preserved. No external provider, Ollama runtime, hosted inference, remote model call, automatic model download, or fallback was added or enabled. This source/search audit is not a runtime network-denial test.

## Stage 8 parameter-count reconciliation

The implementation's `_estimate_parameter_count` documents and computes the per-layer count as:

`12 × hidden_dim² + 13 × hidden_dim`.

The derivation is:

- Multi-head attention: packed input projection `3h² + 3h`, plus output projection `h² + h`, total `4h² + 4h`.
- Two LayerNorms: `4h` (each has weight and bias).
- Feed-forward: `Linear(h, 4h)` contributes `4h² + 4h`; `Linear(4h, h)` contributes `4h² + h`; total `8h² + 5h`.
- Per encoder layer: `(4h² + 4h) + 4h + (8h² + 5h) = 12h² + 13h`.

The implementation formula is internally consistent. The Stage 8 model document was corrected to show the FFN bias term and complete per-layer formula without changing architecture or model code.

Stage 8 remains **NOT ACCEPTED**. Authorized real data, approved model-specific thresholds, and the required held-out model acceptance evidence remain outstanding. Synthetic-only evaluation does not satisfy those requirements.

## Stage 10 corpus and evidence reconciliation

- The current versioned fixture is documented as **43 intent cases** and a separate set of **30 regression mappings**.
- The earlier **39-case** result is historical evidence from an earlier corpus/revision. It must not be described as an execution result for the current 43-case fixture.
- The Stage 10 documentation was corrected to distinguish the historical 39-case metrics from the current 43-case fixture.
- For reviewed SHA `9118490cf10e4e0b49892ae04217e9205709b874`, the Stage 10 fixed-intent evaluation step in CI completed successfully. The retrieved GitHub run/job metadata does not expose its per-case output or metrics, so this report does not assert a numeric 43/43 result.
- The fixed corpus measures only enumerated synthetic phrase behavior. It does not establish general language understanding, independent validation, clinical validity, or product acceptance.
- Stage 10 closeout remains **NOT APPROVED** until Stage 9 product acceptance is completed.

## Preserved acceptance boundaries and blockers

- Stage 8: **NOT ACCEPTED**. Authorized real data, predeclared approved thresholds, and held-out model acceptance remain required.
- Stage 9: **NOT APPROVED**. Owner-target browser/end-to-end walkthrough, OS-level outbound-network-denial evidence, and measured startup/resource observations remain outstanding.
- Stage 10: **NOT APPROVED**. Implementation/CI evidence is distinct from product acceptance; closeout remains blocked while Stage 9 is open.
- Existing privacy, clinical/personal-data separation, authorization, confirmation, idempotency, offline-boundary, provenance, and audit guarantees are not intentionally weakened by this documentation-only correction.
- No local pytest, local Windows retrieval, local browser walkthrough, owner-machine network-denial test, local PostgreSQL validation, or local-worktree inspection was performed.

## Changes made by this review

- Correct the governance record to document active rulesets 26409138 and 26409161, including the exact owner bypass semantics.
- Record the exact SHA and final CI outcome for run 41710017623.
- Keep run 41709984847 attached only to its actual SHA `99c83fcd5bcfb51b7a943262a55e65f3eefd09a0`.
- Preserve the Stage 8 parameter derivation, 43-case/current versus 39-case/historical distinction, provider seam, and all Stage 8/9/10 non-acceptance statuses.
- Explicitly distinguish remote CI evidence from owner-machine acceptance evidence.

## Final verdict

Reviewed, CI-validated main SHA: `9118490cf10e4e0b49892ae04217e9205709b874`.
Run 41710017623: **success**, all four jobs successful; test totals are 8,316 passed, 9 skipped, 42 warnings; Stage 10 evaluator 43/43 passed; Windows retrieval 14 passed, 2 warnings.
Run 41709984847: **success**, all four jobs successful, but for its separate head SHA `99c83fcd5bcfb51b7a943262a55e65f3eefd09a0`.

**Verdict: NOT APPROVED.** Passing remote CI does not close Stage 8's real-data/threshold requirements, Stage 9's owner-machine acceptance requirements, or Stage 10's dependent product-acceptance gate. No Stage 8, Stage 9, or Stage 10 acceptance is claimed.
