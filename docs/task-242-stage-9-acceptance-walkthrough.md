# Task 242 — Stage 9.8 Acceptance Closeout and Owner Validation Record

**Repository:** `savitrex70/micky-ai`  
**Branch policy:** `main` only  
**Code candidate verified by CI:** `789d771fa4609b5c05091d6773f26fe040c9246d`  
**CI run:** [40360442463](https://github.com/savitrex70/micky-ai/actions/runs/40360442463)  
**Verdict:** **Stage 9 is NOT YET ACCEPTED.**

This closeout distinguishes implementation and automated evidence from machine-specific validation that has not actually been performed. It also records a target-platform functional gap that prevents Stage 9.5 from being considered complete.

## 1. Work completed on main

| Task | Implementation / evidence | Status |
|---|---|---|
| 236 — Clarification expiry cleanup | Bounded transactional startup cleanup removes expired/consumed clarification rows, including temporary source and partial-operation values. Cleanup failures roll back and are reported without leaking database details. Tests cover active-vs-expired rows, bounded batches, recovery/redaction and cleanup failures. | Implemented; CI-backed |
| 237 — Workspace lifecycle matrix | `tests/test_workspace_lifecycle_matrix.py` covers note/task/reminder mutations through real routes, confirmation/receipt behavior, cancellation, wrong code, expiry, invalid/deleted targets, key conflicts, replay, uncertain commits, restart persistence, and overdue UI visibility. | Implemented; CI-backed |
| 238 — Retrieval security/offline | Authorized-root identity binding, Linux descriptor-relative/no-follow traversal, network/mount checks, file/byte/directory/entry/root ceilings, truthful root/file/entry counters, runtime Python-level network guards, and honest secure-backend availability status. | Linux security path tested; **target Windows retrieval remains unavailable** |
| 239 — General personal-data export | Versioned bounded JSON export for conversation metadata, messages, notes, tasks and reminders. Browser validates format/version, counts, page progression and completeness before downloading. Responses are no-store/no-cache/nosniff. Clinical data, retrieval-root paths, and confirmation/clarification internals are excluded; import is unsupported. | Implemented; API and browser-harness tests included in green CI |
| 240 — Clinical workflow boundary | Automated test creates a personal conversation and separate clinical session, adds an observation, runs the existing fully audited endpoint, rejects cross-domain identifiers, and verifies clinical-only content is excluded from general export. Corrected six browser session URLs to use the mounted `/sessions` routes and updated the UI harness. | Automated tests passed; manual browser walkthrough outstanding |
| 241 — PostgreSQL/migration CI | CI provisions isolated PostgreSQL 16, upgrades Alembic to head, sets explicit application/test settings, fails on an unreachable configured database, reports skip reasons, and fixes migration-test cleanup to restore head. | Implemented; green PostgreSQL-backed CI |
| 242 — Stage 9.8 closeout | Records evidence and remaining gaps without inventing machine-specific results. | Report complete; Stage 9 acceptance pending |

## 2. Verified automated evidence

The latest verified run for code candidate `789d771fa4609b5c05091d6773f26fe040c9246d` is [GitHub Actions run 40360442463](https://github.com/savitrex70/micky-ai/actions/runs/40360442463):

- **Ruff:** PASS
- **Black 24.10.0:** PASS
- **Full pytest with PostgreSQL 16 service:** **8,222 passed, 3 skipped, 36 warnings**

The three reported skips were:

1. `tests/test_assistant_retrieval.py`: real-junction integration requires an appropriate supported host/backend; Linux CI cannot provide the Windows junction scenario.
2. `tests/test_assistant_retrieval.py`: native Windows retrieval-policy test is Windows-only and does not execute on Linux.
3. `tests/test_reasoning_run_stage_7_evidence_package_audit.py`: `None` is an intentionally valid Task 166 snapshot value.

The passing run includes the export-all-workspace-kind tests, Node-based browser export success/incomplete-pagination harness, export cache headers and beyond-total offset check, clinical route/harness correction, local-startup offline guard, retrieval-backend status, and PostgreSQL migration tests. It still does not prove that local retrieval functions on Windows.

A documentation-only follow-up to this report triggers its own CI run. The run above is the verified functional-code candidate; any later source changes must be checked separately.

## 3. Boundaries preserved

- No hosted provider, Ollama, hidden remote fallback, automatic model download or general model-backed chat path was added.
- Stage 9.7 remains gated by formal Stage 8 acceptance; it was not activated.
- Clinical reasoning reuses the existing deterministic, fully audited ROP workflow. Package consistency is not clinical validity.
- General export excludes clinical records and retrieval-root authorization information; confirmation records retain their separate export surface.
- Unsupported secure traversal fails closed. No unsafe path-based fallback was added to make Windows appear to work.

## 4. Remaining blockers

### 4.1 Target Windows retrieval is safe but unavailable

The product contract targets Windows 10/11, approximately 8 GB RAM and CPU-only. The current secure retrieval backend requires Linux `openat2`, descriptor-relative traversal and Linux mount-identity information. On Windows, the capability check is false; new root authorization/search refuses to proceed and the UI says secure local retrieval is unavailable.

This is **not a security bypass**, but it is a real Stage 9.5 functional gap on the intended platform. A safe Windows implementation needs pinned Windows handles/file IDs and a reparse-point policy, with directory enumeration and file opens bound to the approved directory objects. Do not replace it with ordinary path-based `open()`, `resolve()` or `os.walk()` fallbacks. It needs Windows-hosted adversarial tests before acceptance.

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

## 6. Final Stage 9 decision

The implementation and automated corrections for Tasks 236–242 are on `main`, and the latest observed functional-code CI run is green. **Formal Stage 9 acceptance remains NOT APPROVED** because secure local retrieval is unavailable on the target Windows platform and the required target-machine/browser/offline/resource evidence has not been performed or formally dispositioned.

**Stage 10 remains blocked.**

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
