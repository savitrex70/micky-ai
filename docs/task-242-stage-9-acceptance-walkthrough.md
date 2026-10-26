# Task 242 — Stage 9.8 Acceptance Closeout and Owner Validation Record

**Repository:** `savitrex70/micky-ai`  
**Branch policy:** `main` only  
**Candidate SHA before this report:** `c43ed514015cdcefde76b17eb421140cf26eebd4`  
**Verdict:** **Stage 9 implementation work is substantially complete; Stage 9 is NOT YET ACCEPTED.**

This closeout follows the authoritative scope in `docs/stage-9-product-contract.md` and the baseline audit in `docs/task-235-stage-9-acceptance-audit.md`. It distinguishes implementation and automated evidence from machine-specific validation that has not actually been performed.

## 1. Work completed on main

| Task | Implementation / evidence | Status |
|---|---|---|
| 236 — Clarification expiry cleanup | Bounded, transactional cleanup removes expired and consumed pending clarification rows, including temporary source/partial-operation material. Cleanup is wired into enabled startup recovery; failures are rolled back and reported without leaking database details. Tests cover active-vs-expired rows, bounded batches, restart-recovery service behavior, session/commit failure, and redaction. | Implemented; CI-backed tests on earlier candidate |
| 237 — Workspace lifecycle matrix | `tests/test_workspace_lifecycle_matrix.py` covers note/task/reminder mutations through real routes and confirmation/receipt behavior, including cancel, wrong code, expiry, invalid/deleted targets, conflicting keys, idempotent replay, uncertain commits, restart persistence, due reminders and UI overdue surfacing. | Implemented; CI-backed tests on earlier candidate |
| 238 — Retrieval security/offline boundary | Explicitly authorized-root identity binding, descriptor-relative traversal and no-follow opens, network/mount rejection, bounded file/byte/directory/entry/root work, root/file/entry counters, secure-backend availability status, runtime Python-level network guards, and an explicit Windows fail-closed regression test. The UI no longer disguises an unavailable secure backend as an ordinary search-limit outcome. | Implemented; Linux CI does not substitute for real Windows/network-mount validation |
| 239 — General personal-data export | Versioned, bounded `GET /api/assistant/personal-data/export` and local browser JSON download for conversations, messages, notes, tasks and reminders. Browser pagination checks format/version, totals, page progression and completeness before it creates a download. Import remains explicitly unsupported; clinical data, retrieval-root authorization material and confirmation/clarification internals are excluded. Export responses carry `no-store`, `no-cache`, `Pragma: no-cache`, and `nosniff` headers. | Implemented; latest UI harness run is still required |
| 240 — Clinical workflow boundary | Automated API integration creates a personal conversation and separate clinical session, adds an observation, executes the existing fully audited reasoning endpoint, rejects using the conversation UUID as a clinical session ID, and proves clinical marker text is excluded from the personal export. Fixed the browser's six clinical-session URLs to match the mounted `/sessions` router; updated its harness and contract path. | Implemented; manual clinical browser walkthrough remains unperformed |
| 241 — PostgreSQL/migration CI | CI provisions isolated PostgreSQL 16, applies Alembic migrations to head, sets explicit test/application settings and `ROP_TEST_DATABASE_URL`, fails on an unreachable configured database, shows skip reasons with `pytest -ra`, and restores the conversation migration test to head rather than leaving revision 0018 active. | Implemented; the exact current candidate still needs a final green run |
| 242 — Stage 9.8 closeout | This report records remaining machine-specific gates rather than fabricating manual/resource evidence. | Closeout report prepared; formal Stage 9 acceptance still pending |

## 2. CI evidence actually observed

The last verified green full-suite candidate in the current sequence is commit `0c5ba331ed18df41d4c47c27dc56ed499242e9ee`, run [40357372715](https://github.com/savitrex70/micky-ai/actions/runs/40357372715):

- Ruff: PASS
- Black 24.10.0: PASS
- Full pytest with PostgreSQL 16 service: **8,221 passed, 2 skipped, 36 warnings**.

The two reported skips were:
- `tests/test_assistant_retrieval.py`: the real junction integration test requires a supported junction/retrieval backend; the Linux runner does not provide that Windows-host scenario.
- `tests/test_reasoning_run_stage_7_evidence_package_audit.py`: `None` is intentionally a legitimate Task 166 snapshot value.

This green result predates subsequent commits adding the real browser-download harness, export-all-workspace-kind assertions, clinical harness path alignment, a Windows fail-closed test, and export no-cache headers. **Do not treat run 40357372715 as proof that those later changes passed.** CI for the exact final commit containing this report must be checked separately. No local Windows test execution is claimed.

## 3. Acceptance boundaries that must remain true

- Stage 9 remains deterministic and local-first. No hosted provider, Ollama, hidden remote fallback, automatic model download, or general model-backed chat path was added.
- Stage 9.7 remains gated by formal Stage 8 acceptance. It was not activated by this work.
- Clinical reasoning continues to use the existing fully audited ROP workflow. Package consistency is not clinical validity.
- General export does not export clinical reasoning records or retrieval-root paths. Confirmation-record export remains a separate privacy surface. JSON import is not implemented.
- Retrieval does not fall back to unsafe path-based traversal on unsupported systems. On Windows, the current strict secure traversal backend is unavailable and retrieval is deliberately fail-closed; this behavior must be visible to the user rather than reported as a successful empty search.
- A passing CI result, including PostgreSQL, does not prove OS-wide offline isolation or replace a real browser walkthrough on the target Windows machine.

## 4. Owner-side validation still required

Run the following after updating the local `main` to the SHA shown in GitHub. The project has a large full test suite; preserve its full output and skip summary.

```powershell
Set-Location "C:\Users\micha\Desktop\rop\micky-ai"
git status --short
git pull --ff-only origin main
if ((git rev-parse HEAD).Trim() -ne (git rev-parse origin/main).Trim()) {
    throw "Local main does not match origin/main. Stop before testing."
}
uv run pytest tests -q -ra
if ($LASTEXITCODE -ne 0) { throw "Full pytest failed; preserve the report and stop." }
uv run ruff check .
if ($LASTEXITCODE -ne 0) { throw "Ruff failed; preserve the report and stop." }
uv run black --diff --check .
if ($LASTEXITCODE -ne 0) { throw "Black failed; preserve the report and stop." }
Write-Host "Local full pytest, Ruff, and Black passed for the checked-out SHA." -ForegroundColor Green
git rev-parse HEAD
```

For the most meaningful local comparison, inspect pytest's `-ra` skip summary and compare it with the PostgreSQL-enabled CI result. Database-backed tests that require `ROP_TEST_DATABASE_URL` can legitimately skip on a local machine without a dedicated disposable PostgreSQL test database; do not mistake that local skip for PostgreSQL verification.

## 5. Manual and platform evidence not claimed

These remain genuinely unverified here and cannot be inferred from the repository or Linux CI output:

1. A real Windows 10/11 run on the intended CPU-only/approximately 8 GB target, starting from the documented local workflow without AI credentials and with outbound network access denied.
2. A real browser session verifying create/list/rename/delete/reopen conversation behavior; clarification restart/expiry; confirm/cancel/recovery; workspace create/update/delete/complete; and the saved personal-export file.
3. Windows junction and mapped-network-drive behavior against a real Windows filesystem, plus an actual network-mounted filesystem test where available.
4. Measured startup time and memory/resource use on the target machine. The project contract explicitly requires measurements instead of invented figures.
5. The exact current candidate commit's GitHub Actions result, including any regression from the recent export UI harness and response-cache changes.

No result above is called PASS until the relevant action actually occurs and its SHA/output is recorded.

## 6. Final Stage 9 decision

The implementation work for Tasks 236–242 has been made on `main`; no feature branch or worktree was created. The project is ready for owner-side full tests and reconciliation of any real failures. **Formal Stage 9 acceptance remains NOT APPROVED** until (a) the exact current candidate's CI is green, (b) the owner-side pytest/Ruff/Black run is green or any differences are reconciled, and (c) the target-machine/browser/offline/resource evidence above is either completed or explicitly dispositioned by the project owner.

**Stage 10 remains blocked.**
