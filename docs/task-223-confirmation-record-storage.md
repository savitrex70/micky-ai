# Task 223 — durable confirmation-record storage

Implementation note for the storage and data-lifecycle half of the approved
per-operation confirmation design ([task-222](task-222-confirmation-flow-design.md)).
The confirmation interaction itself is **not** implemented.

## What exists

| Piece | Location |
| --- | --- |
| ORM model | `src/rop/models/assistant_confirmation.py` |
| Table + constraints | migration `20261017_0017` (`down_revision = 20261002_0016`) |
| Persistence and lifecycle | `src/rop/repositories/assistant_confirmation.py` |
| Inspection / export / deletion contracts | `src/rop/schemas/assistant_confirmation.py` |
| Effective policy identity | `authorization_policy_identity` in `src/rop/authorization/policy.py` |
| Tests | `tests/test_assistant_confirmation_records.py`, `tests/test_authorization_policy_identity.py` |

No runtime schema creation is involved: the table exists only through the
Alembic migration, which creates nothing but `assistant_confirmations`, its
constraints, and its two indexes.

## Lifecycle

`PENDING` is the only live state. `CONSUMED` is the single success transition
and is reached only by the atomic compare-and-set in `consume()`; there is no
second "confirmed" state to disagree with it. `REJECTED`, `CANCELLED`,
`EXPIRED`, `INVALIDATED`, and `LOCKED` are terminal, and every terminal state
records `terminal_at`.

Every transition is one conditional `UPDATE` whose predicate carries the state
it expects (`status = 'PENDING'`, not expired, and for consumption the stored
`policy_identity`). A caller that lost the race affects zero rows and is told
nothing happened. Transactions belong to the caller; methods flush so
constraints are checked but never commit.

`record_failed_code_attempt()` increments the counter and applies the lockout
in the same statement, so concurrent wrong guesses serialize instead of
racing. The budget counts failures: the fifth wrong code sets `LOCKED`, while a
correct code entered on the fifth attempt still succeeds.

Every terminal transition drops the display-code verifier, and the database
enforces that a verifier exists exactly while the record is `PENDING`: a
decided record can never be confirmed again, so it keeps no code material at
all.

A transition attempted after `expires_at` does nothing, but it is not allowed
to leave the challenge looking live: `_expire_if_overdue()` settles such a
record to `EXPIRED` in the same guarded statement (still `PENDING`, still
overdue), setting `decided_at` and `terminal_at` and clearing the verifier.
It never consumes, renews, revives, extends, or executes the challenge, and a
concurrent cancel/reject/invalidate/consume resolves through the same guarded
`UPDATE`, so no terminal state overwrites another. Expiry starts the retention
window below.

`expire_overdue(limit=...)` is the bounded maintenance sweep for startup: one
invocation expires at most `limit` (default `DEFAULT_EXPIRY_SWEEP_LIMIT`,
capped at `MAX_EXPIRY_SWEEP_LIMIT`) records, ordered by deadline then id, and
selected with `FOR UPDATE SKIP LOCKED` so it races safely with concurrent
decisions.

`consume()` requires the fingerprint the caller recomputed from the effective
policy. A mismatch invalidates the still-pending record rather than consuming
it, so a rule change cannot leave an old approval usable even though
`policy_version` still reads `"1"`.

## Retention and redaction

A terminal record keeps its `target`, `scope`, and `parameters` for **30 days
from `terminal_at`**. This is the owner-approved policy, fixed at
`CONFIRMATION_RETENTION_DAYS = 30`; `redact_terminal_records(now=...)` takes no
retention argument, so an ordinary caller cannot shorten the window or redact
early. It then removes those values from the columns and stores:

- `material_digest` — SHA-256 of
  `b"rop.assistant-confirmation-material.v1" \x00 salt \x00 canonical`,
  where canonical is the JSON form of the material values with sorted
  parameters;
- `material_digest_salt` — 32 random bytes, hex, unique per record;
- `redacted_at` — the retention pass's instant.

The pass is bounded, takes row locks, and is idempotent: already-redacted rows
are excluded, so a second run changes nothing and never rewrites a digest or a
timestamp. Pending records are never selected, whatever their age; they must
expire first.

Only records that actually carried a target, scope, or parameter are selected.
A terminal record that never carried a material value stays `ABSENT`: it is
never given a digest of an empty object, is never reported as `REDACTED`, and
cannot occupy a slot in the bounded batch ahead of an older record that still
holds values. `material_redacted` distinguishes "removed after the window"
from "never supplied", and every inspection or export reports that as
`material_state`.

## Inspection, export, and deletion

`describe()`, `list_records()`, and `export_records()` project records onto
`AssistantConfirmationView`, which deliberately omits the challenge
identifier, the display-code hash and salt, and the material digest.

`export_records()` returns **one page** of a self-describing
(`format` = `rop.assistant-confirmation-records`, `version` = `1`) export
ordered by creation time then id. A page is not a whole export and cannot be
mistaken for one:

- `record_count` — records in **this page**;
- `total_record_count` — records in the **whole store**;
- `offset` — the page's zero-based start; `limit` — the page size used;
- `has_more` and `next_offset` — whether more remain and the exact offset to
  request next; and
- `is_complete` — true only when the page is the whole store.

A caller exports everything by starting at `offset = 0` and following
`next_offset` while `has_more` is true; it never guesses offsets and never
assumes `record_count` is the database total. `list_records()` keeps its
`MAX_INSPECTION_LIMIT` bound, and the export never fetches the table
unboundedly — it counts with an aggregate and reads one bounded page.

Deletion is available by primary key, by challenge identifier, and for the
whole store. It removes material values with the record and executes nothing;
the returned count is what the database actually removed. **No HTTP route or
UI exposes inspection, export, or deletion yet** — that integration belongs to
a later privacy-surface task.

## Running the tests

The confirmation tests use the project's PostgreSQL database and truncate the
table between tests, so they only run against a database whose name ends in
`_test`, supplied explicitly:

```bash
export ROP_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/rop_task223_test
export ROP_DATABASE_URL=$ROP_TEST_DATABASE_URL   # used only by the migration test
python -m alembic upgrade head
python -m pytest tests/test_assistant_confirmation_records.py \
                 tests/test_authorization_policy_identity.py
```

Without `ROP_TEST_DATABASE_URL` the module skips with that reason rather than
touching the application database. SQLite is not used as a stand-in: the
constraints, conditional updates, row locking, and `RETURNING` behaviour under
test are PostgreSQL behaviour.

## Scope limits

Not implemented, and not claimed: challenge issuance, confirm/cancel/reject
endpoints, browser controls, a state-changing capability, an executor or any
simulated action, an alternate risk table, session-wide permissions, or model
inference. `REQUIRE_CONFIRMATION` remains unreachable because nothing mints a
challenge, and the Task 221 dispatch boundary is unchanged.
