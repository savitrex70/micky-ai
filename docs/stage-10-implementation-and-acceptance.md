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

## Latest verified automated evidence

Exact tested code revision: [`f07d7086ad6306db676e30d85125c604af01e995`](https://github.com/savitrex70/micky-ai/commit/f07d7086ad6306db676e30d85125c604af01e995).

GitHub Actions run [40871167595](https://github.com/savitrex70/micky-ai/actions/runs/40871167595) completed successfully on that revision:

| Check | Result |
| --- | --- |
| Ruff | Passed |
| Tests (Python 3.12, PostgreSQL) | Passed — 8,281 passed, 9 skipped, 42 warnings |
| Black (24.10.0) | Passed |
| Windows retrieval job | Passed |

The Stage 10 fixed-corpus evaluator executed in the CI test workflow: 39 cases, 39 passed, zero failed; exact-outcome accuracy, intent precision, and intent recall were each 1.0 on this corpus. The corpus is project-owned and finite; these results are not evidence of general language understanding or real-world/clinical quality.

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

The correction commits above are on `main`. CI was first green on the code revision `03b0c6f2b8a0e6964959b8c682c8c103a294d72c`; the later record commit `ac6c6f744a21bad0fbb10983e4e611bf744a9a05` was then verified separately, so the evidence now covers the actual `main` HEAD rather than an earlier revision. Stage 10 remains **NOT APPROVED for product closeout** until the owner completes the outstanding Stage 9 target-machine/browser/network-denial and resource-observation acceptance evidence. Stage 8 model acceptance is also separate and is not claimed.

### Verification of the current `main` HEAD

GitHub Actions [run 40930143724](https://github.com/savitrex70/micky-ai/actions/runs/40930143724) completed successfully for exact commit `ac6c6f744a21bad0fbb10983e4e611bf744a9a05`, which is the current `main` HEAD and includes this closeout record:

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

Live end-to-end checks were also run against the served application (loopback origin, real database):

- **Host boundary:** `/api/assistant/memories`, `/api/assistant/personal-data/export`, `/api/assistant/workspace/items`, `/`, `/docs`, and `/openapi.json` each returned `403` with `{"detail": "This request was refused."}` for `Host: rebinding.attacker.invalid`, and no response echoed the hostile host.
- **Relative reminder:** `Remind me to review my notes tomorrow.` returned `clarification-required` with missing fields `due_at` and `timezone`; the pending clarification was restored by conversation id; `09:00 | Europe/Amsterdam` produced `confirmation-required`; no reminder existed before confirmation; confirming created one reminder due `2026-10-31T08:00:00Z` with timezone `Europe/Amsterdam`; replaying the clarification returned `refused` and left exactly one reminder. The test reminder was then removed, leaving the owner's workspace unchanged.

These checks confirm the two corrective findings behave as described at the request boundary. They do not close the owner-side Stage 9 acceptance evidence, and Stage 10 closeout therefore remains NOT APPROVED.
