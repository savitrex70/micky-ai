# Task 249 — Conversational Workspace Management

## Objective

Enable natural-language management of existing workspace items (notes, tasks, reminders) without requiring users to remember or look up UUID identifiers. Users can refer to items by their exact titles, and the system safely resolves these titles to canonical UUIDs, handles duplicates, and preserves all existing confirmation and idempotency guarantees.

## Scope

### 1. Pending Task Discovery

Read-only listing of incomplete (pending) items by kind. These requests never require confirmation.

**Supported phrases:**
- "Show my pending tasks"
- "List incomplete tasks"
- "What tasks do I still have to finish?"
- "Show my pending notes"
- "Show my pending reminders"

**Implementation:**
- Intent interpreter pending-phrase group (Task 249 block in `intent_interpreter.py`, lines 160-333)
- Maps to `workspace list pending <kind>` command
- Workspace parser handles the `status: pending` parameter; `workspace_read.py` applies the pending filter
- Read-only operation: no confirmation required

### 2. Task Completion and Reopening by Title

Change a task's completion state using its exact title.

**Supported phrases:**
- "Mark the Ward revision task as complete"
- "Complete the Ward revision task"
- "Mark my Ward revision task as done"
- "Reopen the Ward revision task"
- "Reopen my Ward revision task"

**Implementation:**
- Intent interpreter task-state phrase group (`intent_interpreter.py`, Task 249 block)
- Maps to `workspace complete task titled: <title>` or `workspace reopen task titled: <title>`
- Selector resolution in `workspace_selector.py` resolves title to UUID
- Version token recorded at resolution time to detect staleness
- Confirmation required before execution
- Idempotency via operation key

### 3. Note/Task/Reminder Deletion by Title

Delete an item using its exact title.

**Supported phrases:**
- "Delete my note titled Ward revision"
- "Delete the task titled Lab follow-up"
- "Delete the reminder titled Check mail"
- "Delete my Ward revision note"

**Implementation:**
- Intent interpreter delete phrase group (`intent_interpreter.py`, Task 249 block)
- Maps to `workspace delete <kind> titled: <title>`
- Same selector resolution and confirmation flow as task completion
- Disambiguation prompt when multiple items share the same title

### 4. Note/Task Updates (Rename, Content)

Update an item's title or content using its exact title.

**Supported phrases:**
- "Rename my note titled Ward revision to Ward revision two"
- "Update the content of the note titled Ward revision with New recovery notes"
- "Update the content of my task titled Lab follow-up to Complete the report"

**Implementation:**
- Intent interpreter update phrase group (`intent_interpreter.py`, Task 249 block)
- Maps to `workspace update <kind> titled: <title> | title: <new_title>` or `content: <new_content>`
- Content-only updates preserve the existing title
- Bare "update my note titled X" asks for the specific field to change
- Confirmation required

### 5. Reminder Rescheduling with IANA Timezone

Change a reminder's due date/time using explicit local time or relative dates with IANA timezone.

**Supported phrases:**
- "Reschedule my reminder titled Check mail to 2026-11-12T14:00 in Europe/Amsterdam"
- "Move the Check mail reminder to tomorrow at 09:00 in Europe/Amsterdam"
- "Reschedule my Check mail reminder to tomorrow in Europe/Amsterdam"

**Implementation:**
- Intent interpreter reschedule phrase group (`intent_interpreter.py`, Task 249 block)
- Explicit time: `workspace update reminder titled: <title> | due: <YYYY-MM-DDTHH:MM> | tz: <IANA>`
- Relative time: carries `relative_date_hint` and `relative_clock_time` through to parser
- Without a timezone separator, a relative reschedule falls to the named-skeleton clarification prompt instead of guessing a timezone (see Limitations)
- Parser resolves relative dates using request-time UTC anchor and selected timezone
- DST edge cases (nonexistent times, ambiguous times) fail closed with clear messages
- Confirmation required

### 6. Safe Target Resolution (Title to UUID, Handle Duplicates)

The `workspace_selector.py` module provides read-only title-to-UUID resolution.

**Resolution rules:**
- Exact normalized title matching (case-insensitive, whitespace-collapsed)
- Kind-scoped (notes, tasks, reminders are separate namespaces)
- Zero matches: refuse with clear message
- Exactly one match: bind to that UUID, record version token
- Multiple matches: ask user to disambiguate by item ID
- Disambiguation answer validated against original title and kind
- Version token enforced at execution time to reject stale targets

**Implementation:**
- `resolve_selector_title()`: look up records by exact normalized title
- `bind_resolved_target()`: convert selector operation to UUID-targeted operation with version
- `verify_disambiguated_target()`: validate user's disambiguation answer
- `item_version_token()`: staleness witness (ISO UTC timestamp of `updated_at`)

### 7. Confirmation Mechanism for All Mutations

All selector-driven mutations use the existing confirmation flow:

1. Intent interpreter maps phrase to workspace command with `titled:` selector
2. Workspace parser creates `ProposedOperation` with `selector_title` parameter
3. API layer calls `_resolve_workspace_selector()` to resolve title to UUID
4. On unique match: operation bound to UUID with version token, confirmation issued
5. On ambiguous match: clarification persisted with disambiguation question
6. User answers clarification with item ID, verification runs, confirmation issued
7. User confirms challenge, executor checks version token, applies mutation
8. Receipt committed with operation fingerprint for idempotency

**Safety guarantees:**
- Nothing mutates before confirmation
- Stale targets (changed/deleted after resolution) rejected at execution
- Wrong display code refuses
- Expired challenges refuse
- Cancelled challenges refuse
- Conflicting idempotency keys refuse

## Files Modified/Created

### Core Implementation
- `src/rop/capabilities/intent_interpreter.py` - Added Task 249 phrase groups for conversational management
- `src/rop/capabilities/workspace_parser.py` - Extended with `titled:` selector grammar, pending listings, clarification continuations, and selector-field guards
- `src/rop/services/workspace_selector.py` - **NEW** - Read-only title-to-UUID resolution
- `src/rop/services/workspace_executor.py` - Extended to enforce version tokens on selector operations; fingerprint excludes the version witness
- `src/rop/services/workspace_read.py` - Extended with the pending status filter
- `src/rop/api/assistant.py` - Extended with `_resolve_workspace_selector()` and disambiguation flow

### Tests
- `tests/test_workspace_conversational.py` - **NEW** - End-to-end API/E2E suite (39 tests, including UI-contract checks)
- `tests/test_intent_interpreter.py` - Extended with Task 249 phrase groups (98 tests total)
- `tests/test_workspace_parser.py` - Extended with selector/pending/listing cases (43 tests total)
- `tests/test_stage10_evaluation.py` - Kept v1 pinned and added corpus v2 checks (5 tests)

### Evaluation
- `tests/fixtures/stage10_evaluation_v2.json` - **NEW** - 76-case fixed corpus: a superset of v1 plus 33 Task 249 cases and 15 new regression-matrix domains
- `scripts/evaluate_stage10.py` - Points at corpus v2 (v1 file unchanged on disk)

### Documentation
- `docs/task-249-conversational-workspace-management.md` - **NEW** - This file
- `docs/stage-10-implementation-and-acceptance.md` - Added the 10.6 scope bullet and the Task 249 record section (acceptance statuses unchanged)

## Parser hardening during Task 249

Testing each phrase against the parser surfaced three defects that were found
and fixed before ship:

1. **Update selector dropped its title** - the `workspace update <kind>
   titled: <title>` grammar parsed but never set `params["selector_title"]`,
   so the resolution boundary had nothing to resolve. The update-selector path
   now binds the selector like the other verbatim commands.
2. **No selector printability/length guard on one path** - separators and
   control characters were refused in most selectors, but one update path let
   a 201+ character or non-printable title reach the operation. All selector
   and field values now fail closed with a `selector_title` field error and no
   partial operation.
3. **Continuation could not complete update selectors** - a clarification
   started by an empty `workspace update note titled:` could never collect the
   change fields. `_continue_clarification` now tracks the filled fields and
   parses `title: X` / `content: Y` segments, defaulting the update `title`
   from `selector_title` for content-only completions.

## UI contract

The existing conversations UI (served `app.js`) required no changes: its
response envelope validators are generic. New automated checks prove this:

- Served `/` and `/static/app.js` source assertions: every Task 249 response
  status is handled by the existing status dispatcher, the clarification
  validator accepts any non-empty string-array `missing_fields` (including the
  disambiguation `["target"]`), and none of the new field names are
  special-cased in the UI.
- Live round-trips: Task 249 success, unsupported-capability, disambiguation,
  challenge, and cancellation payloads satisfy the exact served envelope with
  no invented fields.

Behavioural coverage for the reused statuses (success, clarification,
confirmation, refusal) already exists in `tests/conversations_ui_harness.cjs`.

## Evaluation (fixed corpus v2)

Corpus v2 (`corpus_id: micky-ai-stage10-intent-evaluation-v2`) is a superset of
the historical v1 corpus (all 43 v1 cases retained verbatim) plus 33 Task 249
conversation cases (pending listings, task state, deletion, updates,
rescheduling, refusals, unsafe selectors) and 15 new regression-matrix domains
pointing at the automated tests.

Executed result (`uv run python scripts/evaluate_stage10.py`):

| Metric | Value |
|---|---|
| case_count | 76 |
| passed_cases | 76 |
| failed_cases | [] |
| intent_precision | 1.0 |
| intent_recall | 1.0 |
| outcome_accuracy | 1.0 |
| false_match_count | 0 |
| missed_supported_count | 0 |

Limitations are unchanged: this is a fixed project-owned phrase corpus, not
independent or statistically representative evidence of general language
understanding. v1 stays untouched; `tests/test_stage10_evaluation.py` keeps its
v1-pinned tests and adds superset + regression-matrix checks for v2.

## Test Coverage

The test suite covers:

### Read-only pending listings (2 tests)
- Multiple phrase variations
- Empty results
- Legacy "list all" compatibility

### Task completion/reopening (3 tests)
- Unique title resolution with confirmation
- Reopening completed tasks
- Unknown title refusal

### Disambiguation (6 tests)
- Duplicate titles prompt for item ID
- Wrong kind disambiguation refusal
- Target renamed after offer refusal
- Expired clarification refusal
- Deleted duplicate after offer refusal
- Disambiguated delete executes for chosen item

### Updates (4 tests)
- Rename by title flow
- Content update by title flow
- Bare update phrase asks for field
- Update selector without field clarifies then binds

### Staleness (2 tests)
- Changed target rejected at execution, retry succeeds
- Deleted target rejected at execution

### Confirmation contract (4 tests)
- Wrong display code refuses
- Cancelled command does not mutate
- Expired challenge refuses
- Conflicting idempotency key refuses

### Uncertain commit recovery (1 test)
- Simulated lost commit reports unknown, receipt recovers

### Reminder rescheduling (9 tests)
- Explicit time and zone
- Missing timezone clarification
- Invalid timezone repeats question
- Relative reschedule with clock needs timezone
- Relative reschedule without clock asks both
- Relative date anchor survives midnight
- DST nonexistent time fails closed
- DST ambiguous time asks offset
- Failed reschedule then new request recovers

### Selector unit tests (6 tests)
- Normalization stability
- Resolution outcomes (unique, not_found, ambiguous)
- Partial/similar match rejection
- Invalid input rejection
- Bind resolved target drops selector and versions row
- Verify disambiguated target validates kind

### UI contract (2 tests)
- Served assets accept every Task 249 status and prompt shape, with no
  special-casing of the new field names
- Live success / unsupported / disambiguation / challenge / cancel payloads
  satisfy the served envelope exactly

**Total: 39 conversational tests, plus 98 interpreter tests, 43 parser tests,
and 5 evaluation tests, all passing**

## Verification Commands

```powershell
# Run conversational workspace tests
uv run pytest tests/test_workspace_conversational.py -v

# Run all workspace-related tests
uv run pytest tests/test_workspace_conversational.py tests/test_workspace_parser.py tests/test_workspace_executor.py tests/test_workspace_api.py -v

# Run full test suite
uv run pytest tests -q -ra

# Code quality checks
uv run ruff check .
uv run black --diff --check .

# Fixed-corpus Stage 10 evaluation (corpus v2)
uv run python scripts/evaluate_stage10.py
```

## Integration with Existing Systems

### Intent Interpreter
- Adds new patterns alongside existing help, list, create, search patterns
- No changes to existing pattern matching logic
- Maintains conservative, fail-closed behavior

### Workspace Parser
- Extends existing `titled:` selector syntax (already used for UUID-based operations)
- Adds `status: pending` parameter support for listings
- Relative date hints flow through existing reminder resolution path

### Workspace Executor
- Adds `target_updated_at` parameter to selector operations
- Version checking integrated into existing `_apply_item()` function
- Receipt fingerprint excludes version token (natural-language idempotency)

### Confirmation Flow
- Uses existing challenge issuance and decision endpoints
- Clarification flow for disambiguation reuses existing pending clarification table
- No changes to confirmation UI or display code mechanism

### Authorization Policy
- Selector operations use existing operation IDs (`workspace_note_delete`, etc.)
- Existing `REQUIRE_CONFIRMATION` rules apply
- No new policy rules needed

## Limitations and Boundaries

1. **Exact title matching only**: No fuzzy or partial matching. User must provide the exact title.
2. **Kind-scoped**: A note and a task can share the same title without conflict.
3. **No silent disambiguation**: Multiple matches always require user selection by item ID.
4. **Staleness detection**: If an item is changed or deleted between resolution and confirmation, the operation fails and must be retried.
5. **Read-only resolution**: The selector service never mutates records.
6. **Confirmation required**: All mutations require explicit confirmation via display code.
7. **Idempotency preserved**: Repeating the exact same natural-language request replays the established result.
8. **Relative reschedule needs a timezone separator**: A natural-language reschedule with a relative date must carry the timezone via ` in <IANA>` or a `|` separator. A relative value without one (e.g. "Move my reminder to tomorrow") falls to the clarification prompt asking for the missing timezone rather than silently assuming the machine timezone; the named-skeleton variant asks for title and time together.
9. **Bounded selector scan**: Title resolution inspects only the newest 500 records per kind; older records may not resolve and fail closed with "no matching item".

## Security Considerations

1. **Title injection prevention**: Titles are validated for length and printable characters before resolution.
2. **Generic word rejection**: Words like "my", "the", "this" are rejected as selectors to prevent accidental bulk operations.
3. **Control-character injection**: Selectors containing line/paragraph separators or other non-printable characters are refused by both interpreter (ambiguous) and parser (fail closed).
4. **Disambiguation validation**: User's disambiguation answer is validated against the original title and kind.
5. **Version enforcement**: Stale targets are rejected at execution time.
6. **Origin enforcement**: All state-changing operations enforce the configured local origin.
7. **No command echo**: User's natural-language phrase is never echoed in responses.

## Performance Considerations

1. **Bounded lookup**: Selector resolution inspects only the newest 500 records of each kind.
2. **Indexed lookup**: Title resolution uses database ordering by `updated_at DESC` for efficiency.
3. **Single transaction**: Resolution, confirmation, and execution each use a single database transaction.
4. **No N+1 queries**: Disambiguation presents all matches from one query.

## Future Enhancements (Out of Scope)

- Fuzzy title matching (e.g., typo tolerance)
- Bulk operations (e.g., "complete all tasks containing 'review'")
- Automatic title suggestions
- Historical item reference (e.g., "the task I completed yesterday")
- Cross-kind title collision detection and warnings

## Stage 10 record

Task 249 is filed as Stage 10 scope item **10.6** in
[stage-10-implementation-and-acceptance.md](stage-10-implementation-and-acceptance.md).
That record continues to hold Stage 9 and Stage 10 acceptance at **NOT
APPROVED** and Stage 8 gated: Task 249 is an implementation task and does not
constitute independent acceptance evidence for either stage.
