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

The latest verified run for code candidate `789d771fa4609b5c05091d6773f26fe040c9246d` is [GitHub Actions run 40360442463](https://github.com/savitrex70/micky-ai/actions/runs/40360442463):

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
