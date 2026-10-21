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
  After a confirmed deletion the selection is cleared; the interface does
  not auto-select another conversation, so a subsequent exchange is never
  silently saved to a conversation the user did not choose.
- **Pagination.** The conversation list and the message list each expose
  Previous / Next controls with a visible range. The API's
  `X-Total-Count` header (added by this task, backward-compatible) is the
  source of truth for the total.
- **Selection across pages.** Navigating the conversation-list pagination
  does not deselect the active conversation. A row missing from the
  currently visible page is not evidence of deletion; the selection and
  composer mode are preserved. Only an explicit delete (204) or a
  confirmed 404 clears the selection.

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
- After a successful persisted turn the interface calls a single
  authoritative helper (`reloadLatest`) that reads the server's
  `X-Total-Count` for the conversation, then fetches the page containing
  the newest messages. This is correct even at page boundaries (totals
  199, 200, 201, 399, 400, 401) and under concurrent appends by other
  writers. It never POSTs the user message separately and never
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

**Definite vs ambiguous failures.** A non-2xx HTTP response is treated
as a definite rejection only when it does not represent a
commit-outcome-uncertain persistence failure. Two cases are deliberately
treated as ambiguous on the selected-conversation path:

- `503` from the persist path: a commit failure may or may not have
  saved the pair. The interface states that the exchange may or may not
  have been stored.
- `409` for a concurrent sequence conflict: the pair was rolled back, but
  the user is still directed to reload before retrying so they verify
  the visible history.

Both mark the conversation ambiguous.

**Explicit recovery.** Clicking the selected conversation's title (or
the reload control) triggers `reloadLatest`, which reads a fresh
`X-Total-Count` and then fetches the page containing the newest
messages. The ambiguity marker clears only after that fetch succeeds and
renders for the same conversation under the same generation token. A
failed total fetch, a failed page fetch, or a stale response leaves the
marker set and the composer blocked, so the user cannot blind-resubmit
until the reload succeeds and they have inspected the actual persisted
history. The interface never claims the reload proves a particular
request was or was not saved.

**Switch clears stale messages.** When the user selects a different
conversation, the previous conversation's rendered messages are cleared
before the new fetch begins. A failed fetch shows an error and no stale
content; the previous conversation's messages never appear under the new
title.

**Create is decoupled from list refresh.** The POST response is the
authority for the new conversation's id and title. That id and title are
applied immediately; a subsequent list-refresh failure cannot leave the
previous title displayed under the new selection. A list-refresh failure
is reported as a list error with a reload path. A network failure during
the POST is treated as ambiguous: the server may have created the
conversation, the interface does not repeat the request, and the user is
directed to reload the list.

**Refresh conversations.** The Saved conversations toolbar has an
explicit "Refresh conversations" button. Clicking it always requests
offset zero, is disabled while an in-flight list fetch is running, and
preserves the selected conversation, the displayed title, the composer
mode, and any ambiguity marker. A successful refresh updates the list; a
failed refresh shows a distinct error state (not an empty list) that can
be retried by clicking the same button.

List requests are serialized: if another list request is in flight, a
new caller awaits its completion (rechecking the state after each wait)
before starting its own request. Pagination buttons check the in-flight
state and are disabled while a request is pending, so multiple clicks
cannot start overlapping requests. A successful response commits the
list, total, and offset together as one atomic step; any failure — HTTP
error, unreadable body, structurally invalid body, or network error —
leaves the previous rows, offset, and pagination range intact.

**Confirmed-404 clears the selected conversation.** If the server
returns 404 for the selected conversation's message fetch, the interface
treats that as proof the conversation no longer exists. It clears
`selectedId`, `selectedTitle`, the displayed title, rendered messages,
pagination state, and any ambiguity marker for that conversation, and
invalidates any in-flight message load so a stale response cannot
resurrect it. The composer becomes transient ("No conversation is
selected"). A network error, 500, 503, or another inconclusive outcome
does NOT clear the selection; the conversation stays selected with its
title intact and an error message is shown. A 404 that arrives for a
conversation other than the currently selected one does not clear the
current selection. A submission after a confirmed-404 clears the
selection is sent as a transient request — its POST body contains no
`conversation_id` — proving no other conversation was silently chosen
as the destination.

**Strict message validation on recovery.** `reloadLatest` accepts a
message fetch as establishing the conversation's history only when:

- every record validates against the message read contract (`id`,
  `conversation_id`, `role` in `{user, assistant}`, `content` string,
  non-negative integer `sequence`, `created_at` string);
- the `X-Total-Count` header is present and parses as a finite
  non-negative integer;
- the rendered page does not exceed the reported total, and is not
  shorter than `MESSAGES_LIMIT` while ending before the total; and
- the page ends exactly at the current total (which is what makes the
  loaded page the actual last page containing the newest messages).

A malformed record, a missing or invalid total, an empty page
inconsistent with a non-zero total, or a page whose end does not match
the fresh total all leave the ambiguity marker set so the composer
remains blocked for that conversation. A genuinely empty conversation
(total 0, empty page, header 0) recovers normally.

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
