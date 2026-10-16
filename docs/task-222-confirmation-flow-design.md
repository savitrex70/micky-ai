# Task 222 — Per-Operation Confirmation Flow (design proposal)

**Status: design proposal for review. Nothing described here is implemented.**
No endpoint, request field, database table, migration, UI control, token,
executor, or state-changing capability was added by this task. The document
exists so the mechanism can be reviewed and approved before any of it is
built.

## 1. What exists today

| Piece | Path | State |
| --- | --- | --- |
| Deterministic risk-based policy | `src/rop/authorization/policy.py` | Implemented. `evaluate_authorization(operation, *, policy, authorized=None)` returns `ALLOW`, `CLARIFY`, `REQUIRE_CONFIRMATION`, or `DENY` with one stable reason. |
| Contracts | `src/rop/schemas/authorization.py` | Implemented. `ProposedOperation`, `AuthorizedScope`, `OperationRule`, `AuthorizationPolicy`, `AuthorizationDecision`. Identifiers are matched exactly and never normalized. |
| Dispatch boundary | `src/rop/authorization/dispatch.py` | Implemented. Returns a matched capability's predefined response only on `ALLOW`; every other outcome and every evaluation failure returns a static non-success envelope. |
| Request endpoint | `src/rop/api/assistant.py` | Implemented. `POST /api/assistant/requests`, message-only schema, `_REGISTRY` plus explicitly configured `_POLICY`. |
| Response envelope | `src/rop/schemas/assistant.py` | Implemented. `success`, `unsupported-capability`, `clarification-required`, `confirmation-required`, `refused`. |
| Interface | `src/rop/web/static/` | Implemented. Vanilla HTML/CSS/JS; each status has its own wording; replies are written with `textContent`. |

What does **not** exist: any confirmation interaction, any confirmation
record, any trusted way to turn a user's approval into the `AuthorizedScope`
that `evaluate_authorization` accepts, and any state-changing capability or
executor. `REQUIRE_CONFIRMATION` is therefore terminal today, and reachable
only through test policies.

Two properties of the current code are load-bearing for this design:

- `AuthorizedScope` is documented and implemented as a **comparison input,
  not a credential**. Creating one is an assertion by the caller, and the
  policy cannot tell whether the assertion is true.
- The dispatch boundary takes **no authorization input at all**: it accepts a
  registry-resolved capability and a policy, and nothing else.

The confirmation flow's whole job is to make that assertion true for exactly
one operation, once, and then get out of the way.

## 2. Objective and non-goals

**Objective.** Specify a mechanism where a consequential, sufficiently
specified operation is presented to the human, approved or rejected by that
human, and only then executed once — with forgery, mismatch, expiry, replay,
races, and restart all failing closed.

**Non-goals.** This design does not add capabilities, does not define notes or
reminders, does not add hosted or local model inference, does not introduce a
second permission evaluator or risk table, and does not resolve any other
Stage 9 owner decision (H.1, H.3, H.4). It also does not claim that the
interface can already obtain, record, or verify a confirmation.

**Reuse rule.** The policy evaluator (Task 220) and the dispatch boundary
(Task 221) stay the only decision path. This design adds a *challenge store*
and a *verification step that produces a genuine `AuthorizedScope`*, and
nothing that re-decides risk, re-implements scope matching, or keeps its own
allow-list.

## 3. Lifecycle

The states below are the same nine the task asks for, in order. State numbers
are referenced by the later sections.

| # | State | Owner of the state | Allowed next states |
| --- | --- | --- | --- |
| 1 | Operation selected and sufficiently specified | Deterministic registry + strict request schema | 2, 7-safe-stop |
| 2 | Policy requires confirmation | `evaluate_authorization` | 3, 7-safe-stop |
| 3 | Pending confirmation created, bound to the exact action | Server (challenge store) | 4, 9 |
| 4 | User reviews and confirms or rejects | Human, through the interface | 5, 9 |
| 5 | Server validates genuineness, applicability, currency, unused-ness | Server, inside the trusted boundary | 6, 7-safe-stop, 9 |
| 6 | Authorization consumed for that one action | Server, atomically | 7, 9 |
| 7 | Executes through the trusted dispatch path, or stays blocked | Trusted executor boundary | 8, 9 |
| 8 | Truthful result reported | Response envelope + UI | 9 |
| 9 | Expired, cancelled, rejected, or invalidated | Server sweep / explicit action | terminal |

### Walkthrough

1. The user's message resolves to exactly one registered capability, and the
   request schema has already rejected anything other than a message.
2. The dispatch boundary evaluates `ProposedOperation(operation_id=...)`
   against `_POLICY`. For a consequential rule with no supplied
   authorization, the decision is `REQUIRE_CONFIRMATION` (reason
   `AUTHORIZATION_REQUIRED`).
3. The boundary mints a pending confirmation: a high-entropy challenge
   identifier, the canonical operation it is bound to (identifier, target,
   scope, material parameters), the policy version, a creation and expiry
   time, and a short human-checkable code. The response is
   `confirmation-required` with a display summary and no capability response.
4. The human sees exactly what would run and chooses Confirm, Cancel, or
   nothing. Rejection and cancellation are first-class outcomes, not errors.
5. On Confirm, the server re-reads the stored pending record — not the
   request body — and checks identity, status, expiry, code, and the current
   policy.
6. Consumption is a single atomic `PENDING -> CONSUMED` transition. One
   approval yields at most one execution.
7. Execution happens immediately after consumption, in the same request, and
   only through an executor that requires a verified `AuthorizedScope`. If no
   executor is registered for the operation, nothing runs and the response
   says so.
8. The response reports what actually happened, including "not executed" for
   every path that did not run.
9. Expiry, cancellation, rejection, and invalidation are terminal. A pending
   confirmation that is no longer valid can never be consumed; the user must
   ask again, which mints a fresh challenge.

### Why clarification cannot be converted into authorization

`CLARIFY` means **no operation has been selected** — the target or a required
parameter is absent. There is nothing to bind a challenge to, so a
"confirmation" at that point would be the user approving an action whose
content is still being decided by the server. That is precisely the failure
mode the owner's rule forbids ("must stop to clarify whenever it is unsure
about the user's intent, the target, the scope, or the likely consequences").

The policy already enforces the ordering: `TARGET_MISSING` and
`PARAMETER_MISSING` are evaluated **before** any confirmation decision, so an
under-specified operation can never reach `REQUIRE_CONFIRMATION`. The design
keeps that property and adds the matching rule for the new code: **a pending
confirmation may only be created from a `REQUIRE_CONFIRMATION` decision**, and
that must be asserted in code and in tests rather than assumed.

The flow for an unclear request stays what it is today: answer
`clarification-required`, state that nothing ran, and ask the user for the
missing detail. Once the request is specific enough, it is selected, and then
and only then can it require confirmation.

## 4. Threat model

Stated plainly, because the mechanism's limits matter more than its features.

**The application is a single-user, loopback-served local app with no
authentication.** Anything that can reach `127.0.0.1` on the bound port can
call the API, and any process running as the same local user can read the
database and the server's files. A confirmation flow does not change that,
and this design does not pretend it does.

**In scope — what the mechanism must defend against:**

| Threat | Defence |
| --- | --- |
| A browser request asserting its own permission (`confirmed: true`, a supplied operation identifier, a hand-built scope) | The strict request schema rejects unknown fields, the confirm endpoint accepts only a challenge id plus a decision, and the dispatch path never reads client-supplied authorization. |
| A cross-site page silently submitting a confirm POST to the loopback server | Same-origin enforcement: `Origin`/`Host` must match the configured local origin; state-changing requests require `Content-Type: application/json` (no simple-form submission) and a server-issued challenge id. |
| A blind confirm: an automated or scripted click that never showed a human the action | The challenge is created by the server for a specific stored operation, and confirmation requires the short code displayed with that summary, so a request that only knows the id cannot complete the approval. |
| Replay of a previously valid approval | One-time consumption with an atomic compare-and-set; a second attempt is refused. |
| Approval of action A used for action B (target, scope, or parameter change) | Binding to the canonical operation; the executed values come from the stored record, never from the confirming request. |
| A stale approval used after the rules changed | Policy version and expiry are part of the record and are re-checked at consumption; mismatch invalidates. |
| Approval of an operation that was never specified | `CLARIFY` never mints a challenge, and challenges are minted only from `REQUIRE_CONFIRMATION`. |
| Use of a pending challenge as if it were authorization | A pending challenge is not an `AuthorizedScope`; only a verified, unexpired, exactly-matching, unconsumed record can produce one, and only inside the trusted boundary. |
| Silent execution | No executor runs on `CLARIFY`, `DENY`, rejection, cancellation, expiry, validation failure, or missing executor; every such path reports "not executed". |

**Out of scope — explicitly not defended against, and must not be implied in
the UI or the docs:**

- Code already running as the same local user (it can read the store, call the
  API, and act as the user).
- A user who confirms something harmful on purpose. Confirmation records the
  human decision; it does not judge it.
- Malicious modification of the client's own rendered page by an extension or
  local script. The server's stored operation is what executes, so the damage
  is bounded to what the server stored — but the attacker can still read and
  click.
- Anything reachable if the server is ever bound to a non-loopback interface
  or exposed to a network. That would be a new security requirement, not an
  extension of this design.

Consequences for honesty: the interface must not describe confirmation as
"secure", "authenticated", or "approved by you because only you could have
clicked it". It should describe what did happen: a specific action was shown
and approved at this machine, once.

## 5. Preventing forged, mismatched, expired, and replayed confirmations

### 5.1 Server-owned challenge

- **Generation.** The server generates a challenge identifier from a
  cryptographically secure source (128 bits, URL-safe encoding) plus a short
  display code (6 characters from an unambiguous alphabet, compared
  case-insensitively). The identifier is opaque: it encodes no operation
  data, so it cannot be edited into an approval for something else.
- **Ownership.** The action being approved is defined by the server's stored
  record. The confirming request carries the challenge id, the decision, and
  the display code — **no operation identifier, target, scope, or
  parameters**. Any such field is rejected by the strict schema (`extra`
  forbidden, as `AssistantRequest` already does).
- **Presentation.** The response that creates the challenge carries a
  human-readable summary derived from the stored record plus the display
  code. The client displays it; the client does not define it.

### 5.2 Binding

A challenge is bound to the canonical tuple that Task 220 already compares
exactly:

- `operation_id` (exact machine identifier, never normalized),
- `target` (normalized per the existing contract),
- `scope` (normalized per the existing contract),
- material `parameters` (names validated by the existing identifier contract,
  values normalized, order-insensitive),
- `policy_version` of the policy that produced the requirement, and
- the risk classification and reason code that required confirmation.

Binding is verified by constructing `AuthorizedScope` **from the stored
record** and calling the existing `covers()`, which already fails closed for
anything that is not an exactly matching `ProposedOperation`. A different
identifier, target, scope, or parameter set is a different operation, so the
approval does not apply.

### 5.3 Expiry, cancellation, invalidation

- **Expiry.** Every challenge has `created_at` and `expires_at`. Expiry is
  enforced inside the same atomic transition that consumes it, so a challenge
  that expires during the click cannot be consumed.
- **Explicit cancellation.** A cancel action moves the record to `CANCELLED`.
  Cancelling an already-decided challenge is a no-op that reports the current
  state rather than an error.
- **Rejection.** A reject action moves the record to `REJECTED` and is treated
  as a legitimate user outcome: the operation is not executed and no retry is
  attempted.
- **Invalidation triggers.** Policy version change; a superseding request that
  produces a different operation requiring confirmation (the new request gets
  its own challenge); a malformed stored record (fail closed: refuse and mark
  invalid); server restart when pendings are not durable; and any validation
  failure at consumption time.
- **Sweeping.** Expired pendings are swept lazily on access and by a bounded
  startup sweep. A sweep never resurrects or extends anything.

### 5.4 One-time consumption and races

- Consumption is a single UPDATE with the guard in the predicate:
  `status = PENDING AND expires_at > now()` → `CONSUMED`, and it must affect
  exactly one row. Zero rows affected means "already consumed, expired, or
  gone" and the request is refused without executing.
- **Concurrent confirm of the same challenge:** exactly one request wins the
  compare-and-set; the loser executes nothing and is told the approval was
  already used.
- **Concurrent confirm and cancel:** the same transition decides the winner;
  the loser is refused. Cancellation never resurrects a consumed record.
- **Re-proposing the same action while one approval is pending:** the second
  proposal gets its own challenge; the first stays bound to the operation it
  was created for. Approving either executes only the values in that record.
- **Validity check and execution are adjacent.** Validation, consumption, and
  the executor call happen in one request with no queue, no background
  worker, and no window in which a component could hold a validated approval
  and later act on it.

### 5.5 Unknown or malformed challenge identifiers

An unknown, malformed, or structurally invalid identifier is refused with a
static message that reveals nothing about which identifiers exist. No
timing-oracle promises are made; the store lookup is a direct indexed read.

### 5.6 Browser-origin and cross-site protections

Appropriate for this application, and no more:

- The application is documented and started on loopback
  (`http://127.0.0.1:8000`); it should also reject state-changing requests
  whose `Host` is not the configured local origin.
- Confirm/cancel requests must carry an `Origin` matching the configured
  local origin; a missing or mismatched `Origin` on a state-changing request
  is refused.
- `Content-Type: application/json` is required, which prevents a plain HTML
  form on another page from submitting the request as a simple request.
- No CORS allowance is added. No cross-origin embedding is permitted.

None of this is a security boundary against code running as the same local
user; that is stated in section 4 and must not be softened in the UI.

### 5.7 Restart and loss of outstanding approvals

- With durable pendings (section 6): outstanding challenges survive a restart
  but are still bounded by `expires_at`; a restart never extends a deadline.
  The startup sweep expires overdue records.
- With ephemeral pendings: a restart silently discards them, and the user
  must ask again. That is fail-closed and honest, but it also means the
  interface must not show a stale "pending" card after a restart.
- In both cases, an authorization that was consumed but whose execution was
  interrupted by a crash is **burned, not replayed**: the record shows
  consumed-without-established-result, no executor runs automatically, and
  the user is told the outcome is unknown.

### 5.8 Fail closed

Every path that cannot establish all of "valid challenge, matching binding,
not expired, not consumed, current policy version, current policy still
permits, executor available" results in **no execution** and an honest
non-success status. Nothing defaults to permission, and no exception during
validation is allowed to fall through to an executor.

## 6. Recording and privacy

Section H.2 of the Stage 9 contract leaves the form and persistence of
confirmation records undecided. This section compares the options and makes a
**recommendation**, which remains an owner decision.

### 6.1 Options

| Option | Behaviour | Trade-offs |
| --- | --- | --- |
| A. In-memory only | Challenges and outcomes live in the server process and vanish on restart. | Simplest; no migration; nothing private is written. But approvals cannot survive a restart, there is no record of what was approved, and E.1's "understand, inspect, edit, export, delete" has nothing to inspect. Refusal records required by the contract's acceptance criterion (a) remain impossible. |
| B. Durable local records | Challenges and decisions are rows in the existing local PostgreSQL database, in a dedicated personal-assistant table. | Survives restart; provides a real record of what was approved and consumed; fits the existing stack (SQLAlchemy, Alembic, `/health/ready`). Costs one migration, one table, and a retention policy; stores operation values that are personal data and therefore need protection and deletion paths. |
| C. Hybrid | Pending state in memory; a durable record only for decided outcomes. | Keeps pending material out of the database, but pending approvals then vanish on restart, and the record is written after the fact — so a crash between execution and write can lose the record, which weakens exactly the audit property the record is for. |

### 6.2 Recommendation (not yet approved)

**Recommend option B: durable local records in the existing database, in a
dedicated table, with redaction of material values after the decision window.**

Reasons:

- E.1 already commits to local storage of personal information plus user
  inspection, export, and deletion. Confirmation records are personal
  information; a local database is where the project already keeps that.
- The contract's acceptance criterion (a) asks for a *recorded* refusal. Only
  durable records can satisfy it honestly.
- Durable pendings make restart behaviour simple to state and test: expiry
  governs, not process lifetime.
- The project already has the machinery (SQLAlchemy models, Alembic
  migrations) and the local-first stance forbids sending this anywhere.

### 6.3 Proposed minimum fields

`assistant_confirmations` (name illustrative; final naming follows existing
model conventions):

| Field | Purpose | Notes |
| --- | --- | --- |
| `id` | Primary key | Internal, not the challenge identifier. |
| `challenge_id` | Opaque 128-bit identifier, unique index | Lookup key for the confirmation endpoint. |
| `display_code_hash` | Short code shown to the human | Stored hashed, compared in constant time; never logged. |
| `operation_id` | Exact machine identifier | Never normalized. |
| `target`, `scope` | Canonical target/scope, or null | Personal data; redact after the window. |
| `parameters` | Canonical parameter map, or empty | Personal data; redact after the window. |
| `policy_version` | Policy version that required confirmation | Detects a changed rule set. |
| `required_risk`, `required_reason` | Why confirmation was required | Makes the record self-explaining. |
| `status` | `PENDING`, `CONFIRMED`, `REJECTED`, `CANCELLED`, `EXPIRED`, `CONSUMED`, `INVALIDATED` | Terminal states are explicit. |
| `created_at`, `expires_at`, `decided_at`, `consumed_at` | Timing | Server clock only. |
| `outcome` | Result of the execution attempt, if any | `NOT_RUN`, `FAILED`, `SUCCEEDED`, `UNKNOWN_AFTER_CONSUME`. |

Deliberately **not** stored: the user's raw message, the assistant reply, any
model output, and any value that is not material to binding or reporting the
operation. The record must not become a conversation store.

### 6.4 Privacy rules

- Material parameter values are stored only because binding and execution
  require them, and are **redacted to a salted digest** once the record is
  terminal and past the retention window; the identifier, decision, timing,
  policy version, and reason survive so the audit trail still shows *that*
  an exactly-specified action was approved.
- Confirmation records, material values, and display codes are never written
  to application logs. Log lines may reference the internal id and status
  only.
- Display codes and challenge identifiers must not appear in error messages
  returned to the client (the existing 422 handler already strips `input`
  values for `/api/assistant/`; the confirm endpoint must be covered by the
  same treatment).
- User control: the eventual inspect/export/delete surface for assistant data
  (H.3 territory) must include confirmation records, otherwise option B
  conflicts with E.1. This is flagged as an owner decision in section 11.

### 6.5 Separation from clinical records

- Confirmation records live in their own table in the personal-assistant
  domain. They must not reference, extend, or be joined to
  `reasoning_sessions`, hypotheses, evidence, templates, or any clinical
  audit, provenance, certification, or consistency record.
- No clinical service may read or write `assistant_confirmations`; no
  assistant code may read or write clinical tables. This mirrors the existing
  rule that assistant conversation history is not clinical
  `reasoning_sessions`.
- The Task 220 evaluator and Task 221 boundary already touch no database at
  all; this design introduces the first assistant-side write, which is why the
  separation must be explicit and testable.

## 7. Trust boundary and user interaction

### 7.1 The UI contract (to be built later; not built here)

When the response status is `confirmation-required`, the page shows a pending
confirmation card containing:

- a human-readable summary written from the server's stored record: what
  would happen, to which target, in which scope, with which material
  parameters, and that it is consequential;
- the short display code, so the human can see that the code they enter or
  click belongs to this summary;
- **Confirm** and **Cancel** actions, both explicit;
- a plain statement that the operation has **not run yet** and will not run
  until it is confirmed;
- the expiry time in local terms (for example "expires in 5 minutes"), not a
  server timestamp to interpret.

After a decision, the card is replaced by an outcome line that distinguishes:
confirmed and executed successfully; confirmed but failed; confirmed but the
result is unknown; cancelled; rejected; expired; and unavailable because no
executor exists. Every one of those except the first says clearly that the
operation did not run or that its outcome is unknown.

Accessibility and interface consistency follow what already exists: the
pending card is announced through the existing `role="status"` region and the
history list stays a `role="log"` live region; text is written with
`textContent`; keyboard focus moves to the confirmation actions when the card
appears and back to the message box when it is resolved; no confirmation is
auto-submitted, and no button is pre-focused in a way that lets a stray Enter
approve an action. Existing page conventions (labels, `aria-describedby`,
visually hidden headings) are reused rather than replaced.

The UI must not display a fake approval affordance: no "approve all", no
session-wide "always allow", and no control that claims to have authorized
anything on the user's behalf.

### 7.2 Server-side verification is the boundary

Hiding, disabling, or removing a button is presentation, not security. The
server verifies every confirmation on its own before anything executes:

1. the challenge exists and is `PENDING`;
2. it is not expired, compared with the server clock inside the atomic
   transition;
3. the display code matches its stored hash;
4. the request's `Origin`/`Host` match the configured local origin;
5. the bound operation, policy version, and reason are intact and the record
   has not been invalidated;
6. the *current* policy still yields `REQUIRE_CONFIRMATION` for the bound
   operation, and re-evaluating with an `AuthorizedScope` built from the
   stored record yields `ALLOW`;
7. an executor exists for the operation;
8. only then is the record consumed and the executor invoked.

Failure at any step returns a non-success status, executes nothing, and
records the failure (when durable records are approved) without personal
content.

## 8. Execution boundary

### 8.1 Where validation sits

Confirmation validation belongs **inside the trusted boundary that already
owns policy evaluation and dispatch**, immediately before the executor call,
in the same request. Concretely, the future shape extends the existing
boundary rather than adding a parallel path:

- `authorize_capability_dispatch()` keeps its current contract for
  non-state-changing capabilities.
- A state-changing capability's dispatch becomes: evaluate policy → if
  `REQUIRE_CONFIRMATION`, create and return a challenge → on confirm, verify
  the challenge, build `AuthorizedScope` from the stored record, re-evaluate,
  and only then call the executor registered for that operation.
- An executor is only callable with a verified `AuthorizedScope` and the
  canonical operation it covers. Executors are not reachable from the
  endpoint, from a request field, or from any other route.

### 8.2 Invariants

- A policy result alone is not proof of confirmation. `ALLOW` without a
  matching consumed confirmation means *no execution* for a consequential
  operation.
- A pending challenge is not authorization and must never be converted into
  one outside the consume step.
- Confirmation for one action cannot authorize another action or modified
  parameters: the executed values come from the stored record.
- A validated confirmation is used at most once; consumption precedes
  execution and is atomic.
- No executor runs on clarification, refusal, cancellation, expiry,
  validation failure, or unverified confirmation.
- If no supported executor exists, the assistant stays honest: nothing is
  simulated, and the response says the operation cannot be performed by this
  build yet. A future status such as `not-implemented` would make that
  distinct from a policy `refused`; that contract change needs review before
  it is added.
- Every state-changing operation goes through this boundary. No capability,
  route, or service may call a lower-level mutation handler directly.

### 8.3 Re-checking at execution time

Because conditions can change between minting a challenge and consuming it:

- the **policy version** is re-read; if the effective policy that governs the
  operation changed, the challenge is invalidated and the user must ask
  again;
- the **operation** is re-evaluated with the stored canonical values; if the
  decision is no longer `REQUIRE_CONFIRMATION` (now `DENY` or `CLARIFY`),
  nothing executes;
- the decision is re-evaluated with a freshly constructed `AuthorizedScope`
  from the stored record, so the existing exact-match rules decide — not the
  new code;
- if an executor's preconditions fail (for example a target no longer
  exists), the executor reports failure; the authorization is already
  consumed and is not re-offered. Retrying means asking again, which produces
  a new confirmation.

### 8.4 Race conditions

| Race | Outcome |
| --- | --- |
| Two confirms for the same challenge | Atomic compare-and-set; exactly one execution; the other is refused as already used. |
| Confirm and cancel together | Same transition decides; the loser is refused; a consumed record is never revived. |
| Confirm as the deadline passes | Expiry is part of the transition predicate; an expired challenge executes nothing. |
| Same operation re-proposed during a pending approval | A separate challenge is created; approving the older one executes only the older, approved values. |
| Policy changed between mint and confirm | Re-evaluated at consumption; mismatch invalidates and refuses. |
| Crash after consume, before execution | No automatic execution on restart; the record shows unknown outcome; the user is told the result was not established. |
| Duplicate HTTP submit (double-click, retry) | Same as two confirms: the second is refused; the UI reflects the first decision. |

## 9. Testing plan (to be implemented with the mechanism)

Following the repository's existing conventions (focused pytest files, one
behaviour per test, no assertion that merely checks a symbol exists):

`tests/test_confirmation_flow.py` — lifecycle and validation:

- no challenge is created for `ALLOW`, `CLARIFY`, or `DENY` decisions;
- a challenge is created only for `REQUIRE_CONFIRMATION`, and it exposes only
  the challenge id, a display summary, the display code, and expiry;
- the stored record is bound to the exact operation identifier, target,
  scope, parameter set, policy version, and reason;
- confirming with an unknown, blank, or malformed challenge id executes
  nothing and reveals nothing;
- confirming with a wrong display code executes nothing;
- confirming an expired challenge executes nothing, including when it expires
  during the request;
- replaying a consumed challenge executes nothing the second time;
- two concurrent confirms produce exactly one execution;
- confirm and cancel racing produce at most one execution and never revive a
  consumed record;
- a policy-version change between mint and confirm invalidates the challenge;
- a decision that becomes `DENY` or `CLARIFY` before consumption executes
  nothing;
- approving action A cannot execute action B with a changed target, scope, or
  parameter (the executed values are the stored ones);
- a rejected or cancelled challenge never executes and is reported as such;
- a missing executor produces an honest non-execution result, not a
  simulated success;
- an executor failure is reported as failure, the authorization stays
  consumed, and nothing retries;
- simulated crash between consume and execute produces no execution and an
  "unknown outcome" report on restart;
- an unavailable confirmation store fails closed with a sanitized error;
- no personal value (target, parameter, display code, user message) appears in
  any error response or log line;
- no clinical table is written or read (assert no `reasoning_sessions` or
  related access from the confirmation path).

`tests/test_assistant_api.py` (extended when the endpoint exists):

- the confirm endpoint rejects unknown fields, including any operation
  identifier, target, parameters, `scope`, `authorized`, or `confirmed`;
- `{"confirmed": true}` alone never executes and never changes a decision;
- a cross-origin or mismatched-`Origin` confirm request is refused;
- the request endpoint returns `confirmation-required` without any capability
  response for a consequential test capability.

`tests/test_web.py` (extended):

- the served page renders the pending summary with `textContent`, shows
  Confirm and Cancel, states that nothing has run yet, and contains no
  session-wide or "approve all" control;
- each terminal outcome has its own wording and none of them claims success
  for an operation that did not run.

Policy and dispatch guarantees (already covered) must keep passing unchanged:
exact identifier matching, one-action scope matching, no outcome other than
`ALLOW` dispatching, and fail-closed behaviour for broken policy input.

## 10. Integration and compatibility

- **Deterministic and local-first.** No model call, no network, no external
  service anywhere in the flow. The only new state is local.
- **Existing UI.** Vanilla HTML/CSS/JS served by FastAPI, same page, same
  accessibility conventions, same `textContent` discipline.
- **Strict request schema.** Still message-only for the request endpoint; the
  confirm endpoint accepts a challenge id, a decision, and a code, and
  nothing else.
- **Task 220 contracts.** `AuthorizedScope` stays a comparison input. Exact
  one-operation matching is reused, not re-implemented.
- **Task 221 boundary.** The dispatch boundary remains the only path to a
  capability response; confirmation verification is added inside it.
- **Clinical separation.** No interaction with `reasoning_sessions` or any
  Stage 7 audit, certification, evidence, provenance, fingerprint, or
  identity contract.
- **Cost.** One write per pending confirmation and one compare-and-set update
  per decision; no background workers; no new dependency.

## 11. Recommended defaults

These are proposals, not approved decisions.

1. **Challenge lifetime: 5 minutes**, configurable, evaluated inside the
   atomic transition. Long enough to read a summary, short enough that a
   forgotten tab does not hold a live approval.
2. **Display code required in addition to the challenge id**, so an id alone
   cannot complete a blind approval.
3. **Server-owned operation, client-supplied nothing.** Confirming requests
   carry no operation data; the stored record defines the action.
4. **Atomic single-use consumption before execution**, with the executor call
   in the same request.
5. **Durable local records (option B)** in a dedicated assistant table, with
   material values redacted to a salted digest once terminal and past the
   retention window.
6. **Retention: keep pending records only until expiry; keep terminal records
   for a bounded window (proposal: 30 days) and then redact material values**
   while keeping the decision metadata.
7. **Loopback-only, same-origin state-changing requests** with
   `Content-Type: application/json`, no CORS allowance.
8. **Cancellation and rejection are first-class states**, reported plainly and
   never retried automatically.
9. **No new capability is added with this mechanism.** The flow is built and
   tested against test-only capabilities first, so the first real
   consequence-requiring capability arrives onto an already-tested boundary.
10. **The pending card states "not run yet"; every terminal state except
    confirmed-and-succeeded states that nothing ran or that the outcome is
    unknown.**

## 12. Decisions requiring owner approval

1. **Confirmation recording and retention (H.2 pending item).** Durable
   records in the existing local database, with the retention window and
   redaction timing above — or ephemeral in-memory records with no audit of
   what was approved. This changes the privacy surface and the answer to
   acceptance criterion (a), so it cannot be derived from the existing
   per-operation rule.
2. **Identity and session binding assumption.** The design assumes a single
   local user on loopback with no authentication, and therefore binds an
   approval to the challenge alone. Any move to multiple users, remote
   access, or a shared machine invalidates that assumption and requires a
   session identity decision first.
3. **Whether confirmation records appear in the user's inspect, export, and
   delete surface** (E.1 user control), and under which Stage 9 item that
   surface is delivered. If durable records are approved without a deletion
   path, E.1 is not satisfied.
4. **Expiry duration and retention window** (proposed 5 minutes and 30 days).
5. **How "no executor exists yet" is reported.** Reusing `refused` conflates
   a policy decision with a build limitation; a new additive status (for
   example `not-implemented`) is more honest but extends the response
   contract, so it needs review.
6. **Whether a pending approval survives a restart** (durable) or is
   discarded (ephemeral), and whether the user is told about the loss.

Unchanged by this document: the contract as a whole remains a **draft**; H.1,
H.3, and H.4 remain unresolved; E.2's owner decision stands as recorded; and
nothing here marks the authorization work as complete. The confirmation
recording decision above is exactly the item §H.2 still lists as pending, and
it stays pending until the owner chooses.

## 13. Review checklist

The design is complete when a reviewer can confirm:

- [ ] the nine lifecycle states and their allowed transitions are explicit;
- [ ] clarification can never be turned into authorization, and the code path
      that mints challenges is restricted to `REQUIRE_CONFIRMATION`;
- [ ] forged, mismatched, expired, replayed, and racing confirmations all fail
      closed, each with a stated mechanism;
- [ ] the threat model states what is *not* defended against, without
      over-claiming origin checks or opaque identifiers;
- [ ] recording, privacy, retention, and clinical separation are specified,
      and the recording choice is marked as an owner decision;
- [ ] the UI contract shows what is approved and says nothing has run;
- [ ] the execution boundary, re-checks, and race handling are specified;
- [ ] a testing plan exists for each failure scenario;
- [ ] Stage 9's contract remains a draft and no other pending decision is
      resolved here.
