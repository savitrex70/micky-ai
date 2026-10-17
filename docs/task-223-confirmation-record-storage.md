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

`consume()` requires the fingerprint the caller recomputed from the effective
policy. A mismatch invalidates the still-pending record rather than consuming
it, so a rule change cannot leave an old approval usable even though
`policy_version` still reads `"1"`.

## Retention and redaction

A terminal record keeps its `target`, `scope`, and `parameters` for **30 days
from `terminal_at`**. `redact_terminal_records(now=...)` then removes those
values from the columns and stores:

- `material_digest` — SHA-256 of
  `b"rop.assistant-confirmation-material.v1" \x00 salt \x00 canonical`,
  where canonical is the JSON form of the material values with sorted
  parameters;
- `material_digest_salt` — 32 random bytes, hex, unique per record;
- `redacted_at` — the retention pass's instant.

The pass is bounded, takes row locks, and is idempotent: already-redacted rows
are excluded, so a second run changes nothing. Pending records are never
selected, whatever their age; they must expire first. `material_redacted`
distinguishes "removed after the window" from "never supplied", and every
inspection or export reports that as `material_state`.

## Inspection, export, and deletion

`describe()`, `list_records()`, and `export_records()` project records onto
`AssistantConfirmationView`, which deliberately omits the challenge
identifier, the display-code hash and salt, and the material digest. The
export is self-describing (`format` = `rop.assistant-confirmation-records`,
`version` = `1`), ordered by creation time then id, and carries `retention_days`
plus the redaction note.

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
