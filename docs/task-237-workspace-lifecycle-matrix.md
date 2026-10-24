# Task 237 — Workspace Lifecycle Matrix

**Authority:** `docs/stage-9-product-contract.md`  
**Related audit:** `docs/task-235-stage-9-acceptance-audit.md`  
**Scope:** local notes, tasks, reminders, and their existing confirmation/receipt path  
**Status:** test matrix added; final CI must be checked against the commit that contains this document.

## Supported operations established from the implementation

| Item | Permitted operations | Existing API semantics | Explicitly unsupported |
|---|---|---|---|
| Notes | Create, list/read through filtered workspace item listing, update title/content, clear content on update, delete | Every mutation goes through `POST /api/assistant/workspace/changes`, then the exact confirmation decision endpoint. Listing uses `GET /api/assistant/workspace/items?kind=note`. | No single-item GET route; no completion/reopen operation. |
| Tasks | Create, list/read through filtered workspace item listing, update title/content, complete, reopen, delete | Completion and reopening use `action="complete"` with explicit `completed=true/false`. Listing uses `kind=task` and may filter completed items. | No single-item GET route; no distinct `action="reopen"` value. Reopening is `completed=false`. |
| Reminders | Create, list/read through filtered workspace item listing, update title/content/due time/timezone, delete/dismiss | Create/update require local wall time and an IANA timezone; the API normalizes due time to UTC while retaining the timezone name. Due/overdue display is in-app. | No single-item GET route; no completion action. The schema expressly rejects reminder completion; dismissal is update or delete. No OS notification or background scheduler. |

The current `AssistantItem` model contains no conversation ID or user ID. This build therefore represents one local personal workspace, not multi-user or per-conversation item isolation. The tests do not claim an ownership boundary that the schema does not implement.

## Integration matrix

The new `tests/test_workspace_lifecycle_matrix.py` uses the real FastAPI routes, confirmation service, workspace executor and operation receipts, with a file-backed SQLite test database. The same database file is reused across separate TestClient lifespan contexts for restart checks. This is SQLite integration coverage; it is not a PostgreSQL test.

| Matrix row | Coverage added |
|---|---|
| LIFECYCLE-01 | Parameterized create/update/delete for notes, tasks, reminders; task complete and reopen. Mutation stays unchanged before confirmation; persisted result and succeeded receipt are checked after confirmation. |
| READ-01 | List all items, filter by each supported item kind, exclude completed tasks when requested, and explicitly assert that a single-item GET route is unsupported. |
| IDEMPOTENCY-01 | Same-key/same-material request while a challenge is pending, same-key replay after success, conflicting material under the same key, changed target/action/parameters on existing-item mutations, explicit `clear_content=true` versus content replacement, and exactly-once executor-call assertions. |
| CONFIRM-01 | Creation confirmation failures plus a parameterized existing-item matrix for note/task/reminder updates, deletes, task completion and reopening. Cancellation, wrong code, expiry and consumed-challenge replay are checked without applying a pending mutation a second time. |
| TARGET-01 | Valid but nonexistent targets for note update, task completion, and reminder delete fail without creating an item; targets deleted earlier cannot be updated/completed/deleted again. Invalid IDs and missing target/title fields are rejected at request validation. |
| POLICY-01 | Missing local Origin and a policy-prohibited mutation are refused without a challenge, receipt reservation, or item mutation. |
| UPDATE-01 | Content clearing is tested end-to-end. The API operation builder now carries the existing schema's `clear_content` flag to the executor so it is applied only after confirmation. |
| STATE-01 | Re-completing an already-completed task, editing a completed task, and deleting it are exercised under the existing semantics. |
| REMINDER-01 | Nonexistent and ambiguous DST wall times are rejected; future/overdue UTC due times, timezone retention, update/delete, no duplicate records, and persistence across API lifespan restarts are checked. The real workspace JavaScript is run in a minimal DOM/fetch harness against the persisted API response with a deterministic clock; overdue visibility is checked on initial load, refresh, and a fresh page context. |
| RECEIPT-01 | Covers creation's unknown result plus an existing note update failing before mutation, uncertain task completion, and uncertain reminder update. Commit acknowledgement loss is reconciled from the original succeeded receipt/key; replay does not reapply the mutation. |

## Boundaries retained

- Mutations remain confirmation-gated, policy-revalidated and idempotency-key-bound.
- Unknown outcomes are reconciled through the original durable receipt/key; tests do not retry with a new key.
- Reminder time parsing uses the current UTC persistence model and rejects ambiguous/nonexistent local times.
- No per-user/per-conversation ownership was added because that is not present in the current item model.
- PostgreSQL behavior, true browser automation/manual walkthrough, and Stage 9 overall acceptance are not asserted by this task.
