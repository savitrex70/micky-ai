# Task 230 - Persistent Conversations in the Existing Micky AI Interface

Integrates the Task 228 store and Task 229 HTTP API into the existing
vanilla-JS browser interface. Adds a saved-conversations panel, an explicit
create action, per-conversation message history, persistence of successful
exchanges, rename, delete, and honest handling of non-success outcomes.

The task is additive. No new dependencies, migrations, model providers, or
production executors are introduced. The application remains local-first and
offline-capable.

## Browser workflow

- **List.** On page load, the interface calls
  `GET /api/assistant/conversations` with a bounded `limit`. An honest
  empty state is shown when the server confirms zero conversations; a
  distinct error state is shown if the request fails. No conversation is
  ever auto-created.
- **Create.** The New conversation button issues
  `POST /api/assistant/conversations` with a fixed default title
  (`New conversation`). The new conversation is selected only after the
  server returns `201`; a failure does not fabricate a row.
- **Select.** Selecting a conversation loads
  `GET /api/assistant/conversations/{id}/messages` and renders messages in
  ascending `sequence` order. User and assistant messages are visually
  distinct. A monotonic load token rejects stale responses from a
  previously-selected conversation.
- **Compose.** The existing request form submits to
  `POST /api/assistant/requests` with `conversation_id` included when a
  conversation is selected. The server (not the browser) persists the
  user/assistant pair atomically.
- **Rename.** `PATCH /api/assistant/conversations/{id}` with the new
  title. Local state is updated only after the server confirms.
- **Delete.** `DELETE /api/assistant/conversations/{id}` after an
  explicit `window.confirm`. The row is removed from the list only after
  a `204 No Content` response. Cancelling the dialog performs no API call.

## Persistence semantics

**When no conversation is selected**

- The request is sent without `conversation_id`.
- The endpoint preserves its historical behaviour exactly: no database
  session is opened, no conversation or message table is touched, and the
  response is the same envelope an unpersisted caller has always received.
- The composer shows a transient label explaining the turn will not be
  saved.

**When a conversation is selected**

- The endpoint enforces the configured local origin, verifies the
  conversation exists (404 for a missing/deleted one), dispatches the
  request through the same deterministic capability registry, and then -
  only when the final response status is `success` - appends the user's
  exact message and the assistant's actual reply in one transaction,
  committed once.
- After a successful persisted turn the interface refreshes the message
  list from the API. It never POSTs the user message separately and never
  fabricates an assistant message.
- A failure during the second append or the commit rolls back the entire
  pair: no half-saved successful exchange is possible. Sequence conflicts
  are reported as `409`; a disappeared parent is `404`; any other
  persistence error is a sanitized `503`. The UI never claims the
  exchange was saved when the server did not confirm it.

**Non-success outcomes**

- `unsupported-capability`, `clarification-required`,
  `confirmation-required`, and `refused` are shown through the existing
  transient status/history UI and are not written to conversation history.
- A pending confirmation challenge retains its existing independent
  lifecycle; nothing about it is stored as conversation content.
- Origin enforcement runs before dispatch on the persistence path, so a
  mismatched `Origin` / `Host` / content type returns 403 without
  touching the conversation store.

## Error, retry, and ambiguity

- A failed conversation list load shows an error state, not an empty state.
- A failed request in a selected conversation leaves the existing messages
  visible; the interface does not clear the typed message until a response
  is established.
- No automatic retry is performed on either the client or the server.
  Retrying is a deliberate user action.

## Privacy and separation

- The browser continues to load only local static assets; no remote
  scripts, analytics, or telemetry.
- No conversation content is stored in `localStorage`,
  `sessionStorage`, `indexedDB`, cookies, URL parameters, or logs.
- The database is the sole authority for persisted messages.
- Conversation data remains separate from clinical reasoning records;
  there is no foreign key, join, or ID mapping between conversation IDs
  and clinical session IDs.
- The existing confirmation-record inspection/export/delete UI is
  preserved unchanged.

## Remaining work

- Conversation export/import.
- Per-message editing or deletion.
- Notes, tasks, reminders, retrieval.
- Any production state-changing capability or executor.
- Stage 9 owner decisions H.1, H.3, H.4 remain unresolved.

The Stage 9 product contract remains a draft. This task does not resolve
any owner decision and does not mark Stage 9 complete.
