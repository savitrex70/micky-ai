# Repository Governance and Corrective Review — 2026-11-03

Repository: `savitrex70/micky-ai`
Authorized write target: `main` only
Reviewed main SHA (the exact revision validated by workflow run 41710017623): `9118490cf10e4e0b49892ae04217e9205709b874`
Report correction is committed directly to `main`; its resulting commit SHA is reported in the handoff accompanying this record.
Review status: **NOT APPROVED — repository CI passed, but Stage 8/9/10 acceptance evidence remains outstanding.**

## Scope and execution boundary

This review used GitHub's remote repository interface only. No local checkout, worktree, local files, local commands, local pytest invocation, owner-machine browser walkthrough, owner-machine network-denial test, or local Git bundle was accessed. The owner retains all local work and local pytest execution. Remote GitHub Actions evidence is identified separately below and must not be interpreted as owner-machine acceptance evidence.

## Remote governance inventory and active rulesets

The remote branch inventory returned exactly one branch: `main`, at reviewed SHA `9118490cf10e4e0b49892ae04217e9205709b874`. No non-main remote branch was returned. The open pull-request search returned zero open pull requests. No branch or release ref was deleted.

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
