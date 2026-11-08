# Stage 10 — Implementation and Acceptance Record

Repository: savitrex70/micky-ai
Baseline before Stage 10: `0091815be0733c299468ded38db147d53c4eac38`
Implementation status: Tasks 243–248 cover all defined Stage 10 implementation areas and are present on `main`.
Latest corrective code revision audited: `03b0c6f2b8a0e6964959b8c682c8c103a294d72c`.
Acceptance status: **NOT APPROVED**. Green CI and the fixed-corpus result validate the enumerated software contracts; they do not close the separately required Stage 9 product-acceptance gate or provide target-machine/manual evidence.

## Scope delivered

- **10.1 — Deterministic intent (Task 243):** an explicit allowlisted grammar maps selected user phrases to existing capabilities. Conflicts and unsafe fields fail closed; the existing parser, policy, confirmation and executor remain authoritative.
- **10.2 — Private memory (Task 244):** local structured memories/preferences can be explicitly saved, listed/searched, edited, deleted, exported, and cleared after exact confirmation. Database migrations, no-store responses, UI integration, obvious-secret/patient-identifier checks, create idempotency, and repeat-delete safety are included. No conversation or clinical-session ingestion occurs automatically.
- **10.3 — Local retrieval (Task 245):** natural-language file-search phrases route into the existing authorized, bounded, fail-closed local retrieval path.
- **10.4 — Safe workflows (Tasks 246 and 248):** the task-plus-reminder workflow requires one preview/confirmation and commits both writes in the existing receipt transaction. A second bounded workflow searches authorized local files and prepares one note/task from a matching source; its preview includes the exact source path/excerpt, execution verifies the previewed match has not changed, completed replay remains idempotent, and unavailable/incomplete/empty or changed-source cases fail closed. Other multi-step chains do not execute.
- **10.5 — Evaluation (Task 247):** a versioned fixed phrase corpus, precision/recall calculator, regression-test matrix, runnable script, and limitations are documented.
- **10.6 — Conversational workspace management (Task 249):** natural-language phrases for managing existing workspace items by exact title. Features include pending task discovery, task completion/reopening, note/task/reminder deletion, note/task updates (rename/content), reminder rescheduling with IANA timezone, safe title-to-UUID resolution with duplicate handling, and full confirmation/idempotency preservation. A dedicated read-only selector service resolves titles to canonical UUIDs with version tokens to reject stale targets.

## Latest verified automated evidence

Exact tested code revision: [`f07d7086ad6306db676e30d85125c604af01e995`](https://github.com/savitrex70/micky-ai/commit/f07d7086ad6306db676e30d85125c604af01e995).

GitHub Actions run [40871167595](https://github.com/savitrex70/micky-ai/actions/runs/40871167595) completed successfully on that revision:

| Check | Result |
| --- | --- |
| Ruff | Passed |
| Tests (Python 3.12, PostgreSQL) | Passed — 8,281 passed, 9 skipped, 42 warnings |
| Black (24.10.0) | Passed |
| Windows retrieval job | Passed |

The 39-case result recorded for the earlier tested revision is historical evidence only; it must not be presented as the current fixture size. The current versioned fixture, `tests/fixtures/stage10_evaluation_v1.json`, contains **43 intent cases** and a separate matrix of **30 regression-test mappings**. The later Task 247 record documents that expanded corpus. The 39-case metrics (all 39 passed; exact-outcome accuracy, precision, and recall 1.0) apply only to the earlier corpus/revision and are not a 43-case execution result. A current 43-case metric claim requires an evaluator run against the current fixture and exact code SHA. In all cases, this project-owned finite corpus is not evidence of general language understanding or real-world/clinical quality.

The nine skips include host/backend-specific tests; the separate Windows CI job does not prove the feature works on the owner's target Windows machine or replace live OS-level and browser acceptance. Results above apply only to the cited exact code revision.

## Validation commands

The focused commands remain useful for diagnosis after future changes:

```powershell
uv run python scripts/evaluate_stage10.py
uv run pytest tests/test_intent_interpreter.py tests/test_stage10_evaluation.py -q
uv run pytest tests/test_assistant_memory.py tests/test_personal_data_export.py -q
uv run pytest tests/test_workspace_api.py::test_confirmed_root_identity_is_persisted_and_used_by_retrieval -q
uv run pytest tests/test_workspace_api.py -k "search_and_create or task_reminder_workflow" -q
uv run ruff check .
uv run black --diff --check .
```

## Boundaries and remaining acceptance

The interpreter is deterministic and intentionally narrow; no model, hosted provider, Ollama, automatic download, external retrieval service, or arbitrary command execution is enabled. Memory remains explicit and separately stored, and the current application has a single local-user security model rather than account-level multi-user ownership.

**Stage 10 is implementation-complete for the currently defined Tasks 243–248, but this does not mean the product is accepted.** Stage 9 remains NOT APPROVED, so the repository's acceptance gate still blocks Stage 10 closeout. The older [Task 242 closeout](task-242-stage-9-acceptance-walkthrough.md) has been reassessed: native Windows handle-based retrieval is now implemented and the dedicated Windows CI job passed on code revision `f07d7086ad6306db676e30d85125c604af01e995` in [run 40871167595](https://github.com/savitrex70/micky-ai/actions/runs/40871167595). The remaining owner-target evidence is the real browser/end-to-end walkthrough, OS-level use with outbound networking denied, measured startup/resource observations, and disposition of any target-specific filesystem/network scenarios. Passing CI is not a substitute for that evidence. Stage 8 model acceptance and Stage 9 product acceptance remain separate gates; neither is accepted by this record.

This is an implementation/automated-validation handoff, not owner sign-off or a declaration of Stage 10 product acceptance.


## Corrective review closeout — 2026-10-29

The two findings in the consolidated corrective assignment were addressed on `main` without changing the Stage 10 scope:

- **Untrusted Host / private read exposure:** `TrustedLocalHostMiddleware` is registered at the ASGI application boundary and checks the single Host authority against the configured local origin before dispatch. This covers private GET endpoints as well as the root page and static assets, rejects missing/duplicate/untrusted Host values, and returns a value-free 403 with `Cache-Control: no-store`. State-changing requests retain the separate Origin, Host, and JSON content-type checks. The documentation retains the limitation that this is not authentication against malicious code running as the same local user.
- **Relative reminder clarification:** the deterministic interpreter now carries a validated relative-date hint and optional clock time separately from the title. The pending server-owned operation persists the original request-time UTC anchor, and resolution uses the selected IANA timezone, checks that the resulting time has not passed, and fails closed for missing/invalid timezone, ambiguous daylight-saving wall times, and stale requests. Clarification remains on the existing confirmation/idempotency path; no reminder is written before confirmation. The fixed corpus and regression coverage include relative-date clarification, including a clarification that crosses local midnight.

Corrective commit sequence on `main` (oldest to newest):

- `f1c21b072ad3f68590879136d5a2b45df49c9fb3` — document the relative-date anchor regression in the evaluation record.
- `b54dbcbb63e3b6a52c9bbb6530f9328bc7cab55a` — refuse stale relative dates safely.
- `b65bc97cfbedf83bd97f3c8932e674e18b665d69` — clarify stale relative-date clarification safely.
- `035e0b47a221ad073045bf295e78d65525820620` — format the anchor regression test.
- `03b0c6f2b8a0e6964959b8c682c8c103a294d72c` — align the end-to-end reminder expectation with the exact title supplied by the user (lowercase in that test input).

### Verification for the corrective revision

GitHub Actions [run 40926106993](https://github.com/savitrex70/micky-ai/actions/runs/40926106993) completed successfully for exact commit `03b0c6f2b8a0e6964959b8c682c8c103a294d72c` on `main`:

| Check | Exact result |
| --- | --- |
| Stage 10 fixed intent evaluation | Passed; evaluator reported `outcome_accuracy: 1.0` |
| Full test suite (Python 3.12, PostgreSQL) | **8,316 passed, 9 skipped, 42 warnings** in 946.76 seconds |
| Ruff | Passed |
| Black 24.10.0 | Passed; 712 files unchanged |
| Native Windows retrieval tests | **14 passed**, 2 deprecation warnings |

The nine full-suite skips are reported by pytest and include backend/host-specific scenarios; the dedicated Windows job passed its 14 selected retrieval tests. The PostgreSQL log contains expected constraint-violation messages from negative tests; the overall test job concluded successfully. CI job results are independently visible in the linked run.

The correction commits above are on `main`. CI was first green on the code revision `03b0c6f2b8a0e6964959b8c682c8c103a294d72c`; the later record commit `ac6c6f744a21bad0fbb10983e4e611bf744a9a05` was then verified separately, and the documentation-only commit `8dbab2aa74f40ddeaed59192b0ee2f0b88c94a1c` (current `main` HEAD at first push of this paragraph) was verified in [run 41113172186](https://github.com/savitrex70/micky-ai/actions/runs/41113172186), so the evidence now covers the actual `main` HEAD rather than an earlier revision. Stage 10 remains **NOT APPROVED for product closeout** until the owner completes the outstanding Stage 9 target-machine/browser/network-denial and resource-observation acceptance evidence. Stage 8 model acceptance is also separate and is not claimed.

### Verification of the current `main` HEAD

GitHub Actions [run 40930143724](https://github.com/savitrex70/micky-ai/actions/runs/40930143724) completed successfully for exact commit `ac6c6f744a21bad0fbb10983e4e611bf744a9a05`. A follow-up documentation commit `8dbab2aa74f40ddeaed59192b0ee2f0b88c94a1c` was then verified in [run 41113172186](https://github.com/savitrex70/micky-ai/actions/runs/41113172186): all four jobs (Tests (Python 3.12, PostgreSQL), Ruff, Black (24.10.0), Windows retrieval (Python 3.12)) succeeded, with the full suite reporting **8,316 passed, 9 skipped, 42 warnings** in 949.58s, Ruff "All checks passed!", and the Windows retrieval job **14 passed** in 10.59s:

| Job | Result |
| --- | --- |
| Tests (Python 3.12, PostgreSQL) | Passed (14/14 steps) |
| Ruff | Passed (9/9 steps) |
| Black (24.10.0) | Passed (9/9 steps) |
| Windows retrieval (Python 3.12) | Passed (10/10 steps) |

### Independent re-verification on the owner's Windows host — 2026-10-30

A separate check was run on the owner's machine against this same revision, using the project's own PostgreSQL 16 database with all migrations applied (`0021 → 0022 → 0023`, head `20261028_0023`):

| Check | Result |
| --- | --- |
| Focused suites (`test_trusted_host`, `test_intent_interpreter`, `test_workspace_parser`, `test_stage10_evaluation`) | **87 passed** in 9.69s |
| Full test suite (Windows, PostgreSQL) | **8,085 passed, 238 skipped, 2 failed** in 3,248.72s |
| Ruff | All checks passed |
| Black | 712 files unchanged |
| Stage 10 evaluator corpus | 43 intent cases, 30 regression mappings; relative-date and host-boundary domains present |

The two local failures (`tests/test_cli.py::test_missing_configuration_is_a_concise_error` and `tests/test_config.py::test_get_settings_raises_settings_error_for_invalid_config`) are environment-caused, not corrective-code defects: both assume no `.env` file exists in the working directory, as on CI. They were reproduced identically at the pre-Stage-10 baseline `0091815be0733c299468ded38db147d53c4eac38` with the same `.env` present, and the config test passes when run from a directory without one. They are recorded here as a local-environment caveat rather than resolved by weakening the tests.

These checks confirm the two corrective findings behave as described at the request boundary. They do not close the owner-side Stage 9 acceptance evidence, and Stage 10 closeout therefore remains NOT APPROVED.


Live end-to-end checks were also run against the served application (loopback origin, real database):

- **Host boundary:** `/api/assistant/memories`, `/api/assistant/personal-data/export`, `/api/assistant/workspace/items`, `/`, `/docs`, and `/openapi.json` each returned `403` with `{"detail": "This request was refused."}` for `Host: rebinding.attacker.invalid`, and no response echoed the hostile host.
- **Relative reminder:** `Remind me to review my notes tomorrow.` returned `clarification-required` with missing fields `due_at` and `timezone`; the pending clarification was restored by conversation id; `09:00 | Europe/Amsterdam` produced `confirmation-required`; no reminder existed before confirmation; confirming created one reminder due `2026-10-31T08:00:00Z` with timezone `Europe/Amsterdam`; replaying the clarification returned `refused` and left exactly one reminder. The test reminder was then removed, leaving the owner's workspace unchanged.

These checks confirm the two corrective findings behave as described at the request boundary. They do not close the owner-side Stage 9 acceptance evidence, and Stage 10 closeout therefore remains NOT APPROVED.


## Task 249 — Conversational workspace management — 2026-11-08

Scope item **10.6**: natural-language management of existing notes, tasks, and reminders by exact normalized title, implemented in [task-249-conversational-workspace-management.md](task-249-conversational-workspace-management.md). Pending listings are read-only; every mutation reuses the existing authorization, clarification, confirmation, idempotency, and receipt machinery. A new read-only selector service (`rop.services.workspace_selector`) resolves exact titles to canonical UUIDs with a freshness witness that is enforced at execution time and excluded from the operation fingerprint. The deterministic interpreter remains pure; no model or network dependency was added.

### Fixed intent evaluation corpus v2

`tests/fixtures/stage10_evaluation_v2.json` (`corpus_id: micky-ai-stage10-intent-evaluation-v2`) is a superset of the historical v1 corpus (all 43 cases retained verbatim): 76 intent cases and 45 regression-matrix entries, including 15 Task 249 domains. `scripts/evaluate_stage10.py` now evaluates v2; the v1 file is unchanged on disk.

Executed result (`uv run python scripts/evaluate_stage10.py`): `case_count` 76, `failed_cases` [], `intent_precision` 1.0, `intent_recall` 1.0, `outcome_accuracy` 1.0, `false_match_count` 0, `missed_supported_count` 0. The same corpus passed inside CI run [42481639850](https://github.com/savitrex70/micky-ai/actions/runs/42481639850).

### Local verification of the candidate revision

| Check | Result |
| --- | --- |
| Focused suites (interpreter 98, parser 43, conversational 39, evaluation 5) | **185 passed** |
| Full local suite (`uv run pytest tests -q -ra`) | **8,204 passed, 238 skipped, 6 failed** in 5,532.60s |
| Ruff (Task 249 and all tracked source) | All checks passed |
| Black (Task 249 files in scope) | All reformatted files clean; check passes on the tracked tree |
| Stage 10 evaluator (corpus v2) | Executed, 76/76 cases, metrics above |

The 238 skips include the PostgreSQL-backed tests (`ROP_TEST_DATABASE_URL` is not set on this machine; the local postmaster is not running), so PostgreSQL-backed execution remains available only on CI or the owner's database environment.

The 6 full-suite failures decompose honestly as follows:

- `tests/test_cli.py::test_missing_configuration_is_a_concise_error` and `tests/test_config.py::test_get_settings_raises_settings_error_for_invalid_config` — the already-documented `.env`-present local-environment caveat (identical behaviour reproduced at the pre-Stage-10 baseline; not a Task 249 defect).
- `tests/test_task057_provider_boundary_audit.py` (3 tests) — this untracked, owner-owned audit file must not be edited; its construction heuristic also matches committed `class LLMReasoningProvider(Protocol):` definitions introduced at Task 123 (`930bc0c`), long before Task 249, so it fails identically on a pristine `origin/main` checkout with that file present. Pre-existing local-only condition.
- `tests/test_rop_model_agnostic.py::test_no_network_clients_in_production_services` — a genuine Task 249 candidate defect against the offline-boundary audit: the new `workspace_selector.py` module docstring contained the substring "requests", tripping the audit's client-name scan. Fixed by rewording the docstring; the test now passes in a focused re-run. No network-client import was ever present.

### CI verification of the pushed revision

GitHub Actions run [42481639850](https://github.com/savitrex70/micky-ai/actions/runs/42481639850) (run #415, workflow `CI`, push event) completed successfully for the exact Task 249 implementation commit `362e8df59646a7aae78098d43fdd054034f34f87` on `main`:

| Check | Exact result |
| --- | --- |
| Tests (Python 3.12, PostgreSQL) | **8,430 passed, 9 skipped, 42 warnings** in 833.74s |
| Stage 10 fixed intent evaluation (corpus v2) | `passed_cases: 76`, `failed_cases: []`, `outcome_accuracy: 1.0` |
| Ruff | Passed |
| Black (24.10.0) | Passed |
| Native Windows retrieval (Python 3.12) | Passed |

The PostgreSQL job's container-stop log contains the expected constraint-violation messages from negative tests (`ck_assistant_confirmations_failed_code_attempts`); the job concluded successfully. This CI result includes the Task 249 conversational, interpreter, parser, and corpus-v2 suites and the offline/network-free audits against the new `workspace_selector` service. Stage 9 and Stage 10 acceptance remain **NOT APPROVED** and Stage 8 remains gated: passing CI does not provide the outstanding owner-target Stage 9 acceptance evidence.

### Acceptance status

Task 249 is an implementation task. Stage 9 and Stage 10 acceptance remain **NOT APPROVED** and Stage 8 remains gated; this work provides no independent acceptance evidence for either stage. CI verification of the pushed revision is recorded in the accompanying task-249 document and the final delivery report.
