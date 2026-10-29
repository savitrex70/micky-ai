# Task 242 — Stage 9.8 Acceptance Closeout and Owner Validation Record

**Repository:** `savitrex70/micky-ai`  
**Branch policy:** `main` only  
**Code candidate verified by CI:** `789d771fa4609b5c05091d6773f26fe040c9246d`  
**CI run:** [40360442463](https://github.com/savitrex70/micky-ai/actions/runs/40360442463)  
**Verdict:** **Stage 9 is NOT YET ACCEPTED.**

This closeout first records the evidence for its historical code candidate. The Windows-backend gap described in the original assessment was superseded by later implementation and a dedicated Windows CI run; see §7 for the current reassessment. Machine-specific browser, OS-level offline, and resource evidence remains open, so the Stage 9 acceptance verdict is still NOT APPROVED.

## 1. Work completed on main

| Task | Implementation / evidence | Status |
|---|---|---|
| 236 — Clarification expiry cleanup | Bounded transactional startup cleanup removes expired/consumed clarification rows, including temporary source and partial-operation values. Cleanup failures roll back and are reported without leaking database details. Tests cover active-vs-expired rows, bounded batches, recovery/redaction and cleanup failures. | Implemented; CI-backed |
| 237 — Workspace lifecycle matrix | `tests/test_workspace_lifecycle_matrix.py` covers note/task/reminder mutations through real routes, confirmation/receipt behavior, cancellation, wrong code, expiry, invalid/deleted targets, key conflicts, replay, uncertain commits, restart persistence, and overdue UI visibility. | Implemented; CI-backed |
| 238 — Retrieval security/offline | Authorized-root identity binding, Linux descriptor-relative/no-follow traversal, network/mount checks, file/byte/directory/entry/root ceilings, truthful root/file/entry counters, runtime Python-level network guards, and honest secure-backend availability status. | Original candidate: Linux path tested; Windows backend gap was superseded by the native implementation and later Windows CI (see §7). |
| 239 — General personal-data export | Versioned bounded JSON export for conversation metadata, messages, notes, tasks and reminders. Browser validates format/version, counts, page progression and completeness before downloading. Responses are no-store/no-cache/nosniff. Clinical data, retrieval-root paths, and confirmation/clarification internals are excluded; import is unsupported. | Implemented; API and browser-harness tests included in green CI |
| 240 — Clinical workflow boundary | Automated test creates a personal conversation and separate clinical session, adds an observation, runs the existing fully audited endpoint, rejects cross-domain identifiers, and verifies clinical-only content is excluded from general export. Corrected six browser session URLs to use the mounted `/sessions` routes and updated the UI harness. | Automated tests passed; manual browser walkthrough outstanding |
| 241 — PostgreSQL/migration CI | CI provisions isolated PostgreSQL 16, upgrades Alembic to head, sets explicit application/test settings, fails on an unreachable configured database, reports skip reasons, and fixes migration-test cleanup to restore head. | Implemented; green PostgreSQL-backed CI |
| 242 — Stage 9.8 closeout | Records evidence and remaining gaps without inventing machine-specific results. | Report complete; Stage 9 acceptance pending |

## 2. Verified automated evidence for the original candidate

The verified run for the original code candidate `789d771fa4609b5c05091d6773f26fe040c9246d` is [GitHub Actions run 40360442463](https://github.com/savitrex70/micky-ai/actions/runs/40360442463):

- **Ruff:** PASS
- **Black 24.10.0:** PASS
- **Full pytest with PostgreSQL 16 service:** **8,222 passed, 3 skipped, 36 warnings**

The three reported skips were:

1. `tests/test_assistant_retrieval.py`: real-junction integration requires an appropriate supported host/backend; Linux CI cannot provide the Windows junction scenario.
2. `tests/test_assistant_retrieval.py`: native Windows retrieval-policy test is Windows-only and does not execute on Linux.
3. `tests/test_reasoning_run_stage_7_evidence_package_audit.py`: `None` is an intentionally valid Task 166 snapshot value.

The passing run includes the export-all-workspace-kind tests, Node-based browser export success/incomplete-pagination harness, export cache headers and beyond-total offset check, clinical route/harness correction, local-startup offline guard, retrieval-backend status, and PostgreSQL migration tests. That historical run did not establish Windows retrieval; the later native Windows backend and dedicated Windows CI result are documented in §7.

A documentation-only follow-up to this report triggers its own CI run. The run above is the verified functional-code candidate; any later source changes must be checked separately.

## 3. Boundaries preserved

- No hosted provider, Ollama, hidden remote fallback, automatic model download or general model-backed chat path was added.
- Stage 9.7 remains gated by formal Stage 8 acceptance; it was not activated.
- Clinical reasoning reuses the existing deterministic, fully audited ROP workflow. Package consistency is not clinical validity.
- General export excludes clinical records and retrieval-root authorization information; confirmation records retain their separate export surface.
- Unsupported secure traversal fails closed. No unsafe path-based fallback was added to make Windows appear to work.

## 4. Original blockers identified for the historical candidate (reassessed in §7)

### 4.1 Historical Windows-backend gap — superseded

At the original code candidate, the product contract targeted Windows 10/11, approximately 8 GB RAM and CPU-only, but the secure traversal implementation used Linux `openat2`, descriptor-relative traversal and Linux mount-identity information. On that candidate, Windows authorization/search failed closed. This was a real gap at the time, not a security bypass. The native Windows handle/file-identity/reparse-point-aware backend was added later; the previous claim that the current Windows backend is unavailable is superseded by §7 and CI run 40871167595.

The required implementation shape was pinned Windows handles/file IDs and reparse-point-aware directory enumeration and child opens. The later native implementation follows that approach; it has dedicated Windows CI regression tests. Owner-target use and OS-level offline/resource evidence are still required before the entire product can be accepted.

### 4.2 Target-machine and browser acceptance was not performed here

Not claimed as passed:
- Actual Windows 10/11 startup and use with outbound network access denied.
- A real browser walkthrough of conversation create/list/rename/delete/reopen, clarification restore/expiry, confirm/cancel/recovery, workspace mutations, and the saved personal-export file.
- Real Windows junction/mapped-drive behavior or a live network-mounted filesystem.
- Measured startup time and memory/resource use on the target machine.

These cannot be inferred from Linux CI or source inspection. The contract requires measured results rather than invented performance figures.

## 5. Local validation command

After making any needed backup of local changes, run this in PowerShell. It checks whether local `main` already matches `origin/main` before running tests and refuses to test a different revision.

```powershell
Set-Location "C:\Users\micha\Desktop\rop\micky-ai"
git fetch origin
$localCommit = (git rev-parse HEAD).Trim()
$remoteCommit = (git rev-parse origin/main).Trim()
if ($localCommit -ne $remoteCommit) {
    Write-Host "Local main is not at origin/main. Review local changes, then fast-forward safely." -ForegroundColor Yellow
    throw "Stop: local and remote SHAs differ."
}
uv run pytest tests -q -ra
if ($LASTEXITCODE -ne 0) { throw "Full pytest failed; preserve the report and stop." }
uv run ruff check .
if ($LASTEXITCODE -ne 0) { throw "Ruff failed; preserve the report and stop." }
uv run black --diff --check .
if ($LASTEXITCODE -ne 0) { throw "Black failed; preserve the report and stop." }
Write-Host "Local full pytest, Ruff, and Black passed." -ForegroundColor Green
git rev-parse HEAD
```

Local PostgreSQL-specific tests may intentionally skip unless a **dedicated disposable** `ROP_TEST_DATABASE_URL` is configured. Do not point destructive tests at the application's real database.

## 6. Original Stage 9 decision for the historical candidate

The decision for the code candidate at the time of the original report was **NOT APPROVED**: Windows retrieval was then unavailable and target-machine/browser/offline/resource evidence had not been performed or formally dispositioned. The native Windows backend has since been implemented and independently exercised in Windows CI, so the first reason is no longer current. See §7 for the current decision.

**Formal Stage 9 acceptance remains NOT APPROVED**, and Stage 10 closeout remains gated until the remaining target-machine evidence is recorded and reviewed.

## 7. Post-closeout reassessment — 2026-10-29

This report captured the earlier state of `main`. Its statement that Windows
secure retrieval was unavailable has since been superseded by the native
Windows handle-based backend and its adversarial regression coverage. The
implementation was added and hardened in commits including
[`7767ad8`](https://github.com/savitrex70/micky-ai/commit/7767ad82e98d5f39e098080b2b9cc9f5f640f6ef),
[`2c6683a`](https://github.com/savitrex70/micky-ai/commit/2c6683a8ef4a67237c09bc82b2ec7da3e1caa459),
and
[`3c81dca`](https://github.com/savitrex70/micky-ai/commit/3c81dca8408124a25ba40efa9a3fa5cdab8710aa).
The later code revision
[`f07d7086ad6306db676e30d85125c604af01e995`](https://github.com/savitrex70/micky-ai/commit/f07d7086ad6306db676e30d85125c604af01e995)
passed [CI run 40871167595](https://github.com/savitrex70/micky-ai/actions/runs/40871167595),
including its dedicated **Windows retrieval** job. That job exercises native
Windows handle/reparse-point behavior; it is stronger evidence than Linux
policy mocks, but it is not proof of the owner's own machine configuration or
OS-wide network isolation.

Accordingly, the current Stage 9 blocker is no longer “no Windows retrieval
backend.” Formal Stage 9 acceptance remains **NOT APPROVED** because the
owner-target browser and end-to-end walkthrough, OS-level outbound-network-
denied run, measured startup/resource observations, and any remaining
target-specific filesystem/network scenarios have not been recorded or
formally dispositioned. No such machine-specific evidence is inferred from CI.

**Stage 10 remains gated on the full Stage 9 acceptance decision.**

## 8. Remaining owner-target acceptance evidence — checklist

This is the remaining acceptance work that repository code and CI cannot
honestly perform on behalf of the owner. Use one exact candidate SHA for the
walkthrough, and write observations and artifacts rather than recording a
bare “pass.” Do not mark a row PASS when it was only source-reviewed or
covered by a mock.

| Gate | Required execution on the owner target | Evidence to record | Current status |
| --- | --- | --- | --- |
| Candidate and environment | Update/inspect local `main`; record `git rev-parse HEAD`, Windows edition/build, Python version, RAM, and database/runtime mode. Confirm the candidate is the reviewed repository head. | Exact SHA and environment details | NOT RUN HERE |
| Offline startup and use | With dependencies already installed and migrations applied, enforce outbound-network denial at the OS/network-policy layer. Start the API, check `/health`, `/health/ready`, open `/`, and exercise local help, workspace and memory operations while the denial remains active. Do not treat Python socket mocks or simply reading source as OS-level proof. | Firewall/network policy used, startup result, endpoint results, any attempted/blocked egress, app log excerpt | NOT RUN HERE |
| Startup/resource measurements | On the target machine, measure time from application process launch to readiness and sample/record peak working set during startup and representative local use. Record whether the database is warm/cold and whether Docker is involved. Do not invent target numbers. | Start-to-ready duration, peak working set, conditions, repeated observations if any | NOT RUN HERE |
| Conversations and clarifications | In the actual browser, create/list/open/rename/delete/reopen conversations. Exercise a clarification, resume it, test expiry, and verify state remains bound to the correct conversation. | Actions, visible outcomes, API/server evidence for failures | NOT RUN HERE |
| Workspace lifecycle and recovery | Create/list/edit/delete notes, tasks, and reminders. Test exact timezone handling and ambiguous/nonexistent daylight-saving times. Confirm, cancel, use a wrong/expired challenge, retry/replay, and restart/recovery paths. Ensure cancellations create no writes and replay does not duplicate writes. | Before/after item counts, operation keys/receipt outcomes, restart behavior | NOT RUN HERE |
| Private memory and export | Create/list/search/update/delete memory, test idempotency replay/conflict, prove clear-all requires the exact confirmation phrase, and verify obvious credential/patient identifiers are rejected. Export all supported personal-data sections from the browser and inspect the downloaded JSON for completeness and exclusion of clinical data, confirmation internals, and retrieval-root paths. | Sanitized result summary, export version/count/completeness fields, privacy observations; do not attach real private data | NOT RUN HERE |
| Windows retrieval | In the actual Windows environment, authorize a test directory and verify supported formats are found only within that root. Exercise a junction/reparse point, root replacement, mapped/network-drive policy, unsupported formats, and read/resource bounds where the host supports them. Never replace fail-closed behavior with a path-based fallback. | Root identities/results, relevant OS behavior, blocked or skipped entries and counters | CI PASS; OWNER TARGET NOT RUN |
| Stage 10 workflow 1 | Use a task-plus-reminder request. Inspect the preview, cancel one attempt and confirm neither record is written; then confirm another and verify both writes commit together. Replay the same request and verify no duplicates. | Preview fields, post-cancel/post-confirm item counts, replay receipt/result | Automated CI PASS; BROWSER NOT RUN |
| Stage 10 workflow 2 | Search authorized test files and prepare a note/task. Verify the preview contains the exact source path and bounded excerpt. Test cancel, no match, source changed after preview, successful confirmation, and completed-request replay. Confirm no write occurs for cancelled/failed/stale previews. | Preview evidence, item counts, changed-source rejection, replay result | Automated CI PASS; BROWSER NOT RUN |
| Clinical/personal separation | In the browser, use a personal conversation and separate clinical session. Run the fully audited ROP reasoning action, observe visible package/failure handling, and verify clinical identifiers/content do not leak into personal conversations or personal-data export. Do not interpret package consistency as clinical validity. | Distinct identifiers and sanitized output/export checks | Automated CI PASS; BROWSER NOT RUN |
| Final review decision | Review the captured evidence for the same exact candidate SHA; disposition every failed/unsupported/skipped scenario and retain the Stage 8 model gate as blocked unless its separate owner prerequisites are satisfied. | Signed acceptance decision with SHA, reviewers, exceptions and unresolved risks | NOT APPROVED |

The CI evidence currently verified for code revision
`f07d7086ad6306db676e30d85125c604af01e995` is documented above and in
[run 40871167595](https://github.com/savitrex70/micky-ai/actions/runs/40871167595).
All subsequent commits to current `main` have been verified as
documentation-only changes; no production or test code changed after that
tested code revision. The CI result for those later document-only pushes
could not be independently retrieved through the available run-status
interface, so no new passing test result is claimed for them.

**Closeout rule:** Stage 9 and therefore formal Stage 10 acceptance remain
NOT APPROVED until the NOT RUN HERE items above are completed, the results are
reviewed on one candidate SHA, and the owner records the final decision.
