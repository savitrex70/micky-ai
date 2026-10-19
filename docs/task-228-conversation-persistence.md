# Task 228 — Conversation Persistence Foundation

Implementation note for the durable conversation and message store added
in Task 228. Scope: the data layer only. The user-facing conversation
workflow (HTTP endpoints, browser UI, request-endpoint integration) is
out of scope and remains unimplemented.

## Domain

Two tables, deliberately independent of every clinical table and of the
assistant confirmation records:

- `assistant_conversations` — one row per conversation. Fields: `id`
  (UUID primary key), `title` (bounded string), `created_at`, `updated_at`
  (both timezone-aware, server-defaulted; `updated_at` is bumped on
  mutation).
- `assistant_messages` — one row per user-visible message. Fields: `id`,
  `conversation_id` (foreign key to `assistant_conversations.id` with
  `ON DELETE CASCADE`), `role` (`user` or `assistant`, constrained by a
  check constraint), `content` (text), `sequence` (non-negative integer,
  unique per conversation), `created_at`.

No foreign key exists to `reasoning_sessions`, `observations`,
`hypotheses`, `evidence`, or any other clinical or audit table. Nothing in
the conversation domain is joined to clinical data, and no clinical table
is touched by any repository method.

`role` is constrained to `user` and `assistant`. There is no `system` role
and no field for hidden internal instructions. Attempts to write a value
such as `system` are rejected by the database, not just by the schema.

`sequence` is `>= 0` and unique within a conversation. The repository
assigns `max(sequence) + 1` for each append; concurrent appends that race
for the same position fail on the unique constraint, and the caller is
expected to retry rather than the repository silently reordering.

## Migration

Migration `20261019_0018_create_assistant_conversations` (down_revision
`20261017_0017`) creates only these two tables, their constraints, their
foreign key, and their indexes. The downgrade drops exactly those
objects and touches nothing else. The migration has a dedicated upgrade/
downgrade test that asserts both tables appear on upgrade and disappear
on downgrade, while `reasoning_sessions` and `assistant_confirmations`
remain unchanged.

## Repository

`ConversationRepository` in
`src/rop/repositories/assistant_conversation.py`. Methods:

- `create(db, data)` → `AssistantConversationRead`
- `get(db, conversation_id)` → `AssistantConversationRead | None`
- `list(db, *, offset, limit)` → `list[AssistantConversationRead]`
  (ordered by `updated_at desc, id desc`; `limit` bounded by
  `MAX_CONVERSATION_LIST_LIMIT`)
- `update(db, conversation_id, data)` → `AssistantConversationRead`;
  raises `ConversationNotFoundError` if missing
- `append_message(db, conversation_id, data)` → `AssistantMessageRead`;
  raises `ConversationNotFoundError` if the conversation does not exist
- `list_messages(db, conversation_id, *, offset, limit)` →
  `list[AssistantMessageRead]` (ordered by `sequence asc`)
- `delete(db, conversation_id)` → `bool`

Transactions: the repository stages work and flushes but **never
commits**. The caller owns the transaction boundary, so a conversation
mutation can be composed atomically with other work. This is asserted by
`test_repository_does_not_commit`.

## Tests

`tests/test_conversation_records.py` covers:

- Conversation create/get/list with deterministic ordering and bounded
  pagination; empty and boundary cases.
- Message append and ordered retrieval across many messages.
- Role constraint at the schema level *and* at the database level.
- Unique `(conversation_id, sequence)` and non-negative `sequence`
  enforced by the database.
- Missing-conversation handling for both update and append.
- Delete removes the conversation's messages and leaves another
  conversation's messages untouched.
- No clinical table changes during conversation operations.
- The repository does not commit behind its caller's back.
- Migration upgrade/downgrade preserving clinical and confirmation
  tables.

Tests use `ROP_TEST_DATABASE_URL` and refuse to run unless the database
name ends in `_test`. They skip cleanly when that is not configured.
The tests do not run against a SQLite substitute: the constraints and
cascade behaviour being verified are PostgreSQL behaviour.
