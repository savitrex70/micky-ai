# Task 229 - Conversation HTTP API

HTTP API for the durable assistant conversation and message store added in
Task 228. This is the API layer only. The conversation-management UI, wiring
persistence into `/api/assistant/requests`, conversation export, notes,
tasks, reminders, and retrieval remain unfinished and are tracked separately.

## Endpoints

All paths are under `/api/assistant/conversations`.

| Method | Path | Purpose | Status codes |
| --- | --- | --- | --- |
| `GET` | `/api/assistant/conversations` | List conversations | 200, 422 |
| `POST` | `/api/assistant/conversations` | Create a conversation | 201, 403, 422, 503 |
| `GET` | `/api/assistant/conversations/{conversation_id}` | Read one conversation | 200, 404, 422 |
| `PATCH` | `/api/assistant/conversations/{conversation_id}` | Rename a conversation | 200, 403, 404, 422, 503 |
| `DELETE` | `/api/assistant/conversations/{conversation_id}` | Delete a conversation | 204, 403, 404, 422, 503 |
| `GET` | `/api/assistant/conversations/{conversation_id}/messages` | List messages | 200, 404, 422 |
| `POST` | `/api/assistant/conversations/{conversation_id}/messages` | Append a user message | 201, 403, 404, 409, 422, 503 |

All endpoints are registered in the FastAPI application and appear in
`/openapi.json`.

## Request and response schemas

**List / read conversations** -> `list[AssistantConversationRead]` or
`AssistantConversationRead`:

- `id` (uuid)
- `title` (string)
- `created_at` (iso-8601 timestamp with offset)
- `updated_at` (iso-8601 timestamp with offset)

**Create conversation** - body: `AssistantConversationCreate` with only
`title`. `extra=forbid`; a body with `id`, `created_at`, or
`updated_at` is rejected with 422. `title` must be non-blank and no
longer than `MAX_CONVERSATION_TITLE_LENGTH` (200).

**Rename conversation** - body: `AssistantConversationUpdate`, same shape
as create. Only the title is editable.

**List / append messages** -> `list[AssistantMessageRead]` or
`AssistantMessageRead`:

- `id` (uuid)
- `conversation_id` (uuid)
- `role`: `user` or `assistant`
- `content` (string)
- `sequence` (integer, non-negative, unique per conversation)
- `created_at` (iso-8601 timestamp with offset)

**Append message** - body: `AssistantUserMessageCreate` with only
`content`. The public endpoint does **not** accept a caller-supplied
`role`. Any body containing `role` is rejected with 422 and writes
nothing. The stored role is always `user`, so a caller cannot forge an
`assistant` message and make invented output appear as though Micky AI
produced it. Internal code that persists genuine assistant replies
continues to use the internal `AssistantMessageCreate` schema (which
retains the role field).

## Pagination

Conversations and messages each support bounded `limit` and
non-negative `offset` query parameters:

- Conversations: `limit` in `[1, MAX_CONVERSATION_LIST_LIMIT]`, default
  `DEFAULT_CONVERSATION_LIST_LIMIT`.
- Messages: `limit` in `[1, MAX_MESSAGE_LIST_LIMIT]`, default
  `DEFAULT_MESSAGE_LIST_LIMIT`.

Invalid pagination values return 422. Conversation and message list
responses include an `X-Total-Count` header carrying the total number
of matching records. Callers page until `offset + len(page) == total`,
or until the list is exhausted (empty page at offset zero).

## Ordering

- Conversations: `updated_at` descending, then `id` descending.
  Appending a message advances the parent's `updated_at`, so a
  conversation with a new message moves to the top of the list (Task 228
  correction).
- Messages within a conversation: `sequence` ascending. `sequence` is
  non-negative and unique per conversation.


## Local-origin requirement for writes

Every state-changing conversation endpoint (POST /, PATCH /{id},
DELETE /{id}, POST /{id}/messages) is guarded by require_local_origin.
The request must carry:

- an Origin header matching the configured assistant_local_origin
  (default http://127.0.0.1:8000),
- a Host header matching that origin's netloc,
- Content-Type: application/json.

Missing or mismatched values return 403 with a fixed, value-free body. No
CORS allowance is enabled. This is not authentication and does not defend
against malicious code running as the same local user; it defends the
documented loopback application against cross-site writes, matching the
existing confirmation-decision and confirmation-record endpoints.

Read-only endpoints (GET) do not require origin enforcement; that matches
the existing local API surface.

## Transaction ownership and error handling

Transaction ownership is at the API boundary:

- The repository stages work and flushes but does not commit.
- A successful mutation commits its session at the handler.
- A failed mutation rolls back and returns a sanitized error string
  ("The operation could not be completed." for 503, a fixed specific
  message for 409 concurrent-append conflict).

Error responses never include submitted message content, SQL statements or
fragments, connection strings or database exception text, challenge
identifiers, material values, or other secret-adjacent data.

## Concurrent appends

`append_message` computes `max(sequence) + 1` and lets the database's
`uq_assistant_messages_conversation_sequence` constraint arbitrate
races. If two appends race for the same position, one succeeds and the
other raises `IntegrityError` on that named constraint, which the
handler maps to 409 Conflict with a fixed message. The append is not
retried automatically - a silent retry could duplicate a visible
message. The caller must reload and re-submit deliberately.

Other integrity errors are classified by their constraint name:

- A foreign-key violation on `conversation_id` means the parent
  conversation was deleted while the append was racing; the handler
  returns 404.
- Any other constraint violation is treated as an unclassified
  persistence failure and returns 503 with a sanitized message. It is
  never reported as a sequence conflict.

## What is not exposed

- No endpoint accepts or returns hidden internal instructions.
- No endpoint lets the caller choose the message role.
- No conversation-export or bulk-delete endpoint.
- No interface for creating conversations implicitly from
  `/api/assistant/requests` or any other endpoint.
- No foreign key to `reasoning_sessions` or any clinical table.

## Remaining work (excluded from Task 229)

- Browser conversation-management controls.
- Persistence of request/response pairs in `/api/assistant/requests`.
- Conversation export / import.
- Notes, tasks, reminders, retrieval.
- Production executor or production state-changing capability.
- Stage 9 decisions H.1, H.3, H.4 remain unresolved.

The Stage 9 product contract remains a draft; this task does not resolve
any owner decision and does not mark Stage 9 complete.
