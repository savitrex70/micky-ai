# Task 222 — Per-Operation Confirmation Flow (design proposal)

**Status: implemented server-side (Task 224). Browser confirmation UI is not
implemented.**
This document was written as a design proposal and its mechanism has since
been built in two follow-on tasks. Task 223 added the durable confirmation
record (`assistant_confirmations`, migration `20261017_0017`,
`src/rop/repositories/assistant_confirmation.py`). Task 224 added the
server-side lifecycle (`src/rop/services/confirmation.py`,
`src/rop/api/confirmations.py`, `src/rop/authorization/executors.py`) and
wired challenge creation into the assistant request endpoint. The browser
confirmation card and its Confirm/Cancel controls, described in section 7.1,
remain unimplemented. No production state-changing capability and no
production executor are registered, so a consequential operation cannot run
in this build.

## 1. What exists today

| Piece | Path | State |
| --- | --- | --- |
| Deterministic risk-based policy | `src/rop/authorization/policy.py` | Implemented. `evaluate_authorization(operation, *, policy, authorized=None)` returns `ALLOW`, `CLARIFY`, `REQUIRE_CONFIRMATION`, or `DENY` with one stable reason. |
| Contracts | `src/rop/schemas/authorization.py` | Implemented. `ProposedOperation`, `AuthorizedScope`, `OperationRule`, `AuthorizationPolicy`, `AuthorizationDecision`. Identifiers are matched exactly and never normalized. |
| Dispatch boundary | `src/rop/authorization/dispatch.py` | Implemented. Returns a matched capability's predefined response only on `ALLOW`; every other outcome and every evaluation failure returns a static non-success envelope. |
| Request endpoint | `src/rop/api/assistant.py` | Implemented. `POST /api/assistant/requests`, message-only schema, `_REGISTRY` plus explicitly configured `_POLICY`. |
| Response envelope | `src/rop/schemas/assistant.py` | Implemented. `success`, `unsupported-capability`, `clarification-required`, `confirmation-required`, `refused`. |
| Interface | `src/rop/web/static/` | Implemented. Vanilla HTML/CSS/JS; each status has its own wording; replies are written with `textContent`. |
| Confirmation record | `src/rop/models/assistant_confirmation.py` | Implemented (Task 223). Durable `assistant_confirmations` table (migration `20261017_0017`), guarded transitions in `src/rop/repositories/assistant_confirmation.py`, thirty-day retention and redaction. |
| Confirmation service | `src/rop/services/confirmation.py` | Implemented (Task 224). Challenge issuance, decision handling, constant-time code verification, policy revalidation against the effective policy identity, atomic once-only consumption, and the executor boundary. |
| Confirmation API | `src/rop/api/confirmations.py` | Implemented (Task 224). `POST /api/assistant/confirmations/{id}/decision` with a strict body schema, loopback origin enforcement, and value-free refusals. |
| Executor registry | `src/rop/authorization/executors.py` | Implemented (Task 224). Server-side only. **Empty by default**: no production executor is registered, so a `REQUIRE_CONFIRMATION` operation cannot execute in this build. |

The server-side confirmation workflow is implemented and exposed through
`POST /api/assistant/confirmations/{id}/decision`. What does **not**
exist in this build: the browser confirmation card and its Confirm/Cancel
controls; any HTTP surface for inspecting, exporting, or deleting
confirmation records; a production state-changing capability; and any
production executor. Because the default executor registry is empty, a
`REQUIRE_CONFIRMATION` operation cannot execute, and the only capability
registered is `help`.

Two properties of the current code are load-bearing for this design:

- `AuthorizedScope` is documented and implemented as a **comparison input,
  not a credential**. Creating one is an assertion by the caller, and the
  policy cannot tell whether the assertion is true.
- The dispatch boundary takes **no authorization input at all**: it accepts a
  registry-resolved capability and a policy, and nothing else.
- `policy_version` on `AuthorizationPolicy` is the **fixed literal `"1"`**
  (`AUTHORIZATION_CONTRACT_VERSION`). It is not a change detector: a rule's
  risk level, prohibited flag, required-target rule, or required-parameter set
  can change while the version still reads `"1"`. Comparing only that label
  would let a stale approval look valid after the rules changed, which is the
  first gap this revision closes (section 5.9).

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

Lockout after repeated wrong display codes (section 5.10) is a terminal state of
category 9, recorded as `LOCKED` rather than folded into `INVALIDATED`, so an
audit distinguishes "the policy or binding changed" from "the attempt budget was
exhausted". The nine states themselves are unchanged.

### Walkthrough

1. The user's message resolves to exactly one registered capability, and the
   request schema has already rejected anything other than a message.
2. The dispatch boundary evaluates `ProposedOperation(operation_id=...)`
   against `_POLICY`. For a consequential rule with no supplied
   authorization, the decision is `REQUIRE_CONFIRMATION` (reason
   `AUTHORIZATION_REQUIRED`).
3. The boundary mints a pending confirmation: a high-entropy challenge
   identifier, the canonical operation it is bound to (identifier, target,
   scope, material parameters), the **effective policy identity** that
   produced the requirement (section 5.9), a creation and expiry time, and a
   short human-checkable code. The response is `confirmation-required` with a
   display summary and no capability response.
4. The human sees exactly what would run and chooses Confirm, Cancel, or
   nothing. Rejection and cancellation are first-class outcomes, not errors.
5. On Confirm, the server re-reads the stored pending record — not the
   request body — and checks identity, status, expiry, code, the remaining
   attempt budget (section 5.10), and the current effective policy identity
   (section 5.9).
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
| Guessing the short display code after obtaining a challenge identifier | The code is compared against a stored hash inside an atomically counted attempt budget; the challenge locks at the limit, and every failure looks identical (section 5.10). |
| Replay of a previously valid approval | One-time consumption with an atomic compare-and-set; a second attempt is refused. |
| Approval of action A used for action B (target, scope, or parameter change) | Binding to the canonical operation; the executed values come from the stored record, never from the confirming request. |
| A stale approval used after the rules changed | A deterministic fingerprint of the effective policy contents, plus expiry, are part of the record and re-checked at consumption; any material content change invalidates, even when the `policy_version` label is unchanged (section 5.9). |
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
- the **effective policy identity** — a deterministic fingerprint of the
  policy contents that can change an authorization decision — of the policy
  that produced the requirement (section 5.9), and
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
  Cancelling an already-decided challenge is a no-op: it reports that nothing
  ran and does not revive, extend, or unlock the record.
- **Rejection.** A reject action moves the record to `REJECTED` and is treated
  as a legitimate user outcome: the operation is not executed and no retry is
  attempted.
- **Invalidation triggers.** Any change to the effective policy identity
  (section 5.9), even when the human-readable `policy_version` label is
  unchanged; reaching the failed-code-attempt limit (section 5.10); a
  superseding request that produces a different operation requiring
  confirmation (the new request gets its own challenge); a malformed stored
  record (fail closed: refuse and mark invalid); server restart when pendings
  are not durable; and any validation failure at consumption time.
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
  The startup sweep expires overdue records in bounded batches, and any
  transition that meets an expired challenge settles it to `EXPIRED`.
- With ephemeral pendings: a restart silently discards them, and the user
  must ask again. That is fail-closed and honest, but it also means the
  interface must not show a stale "pending" card after a restart.
- In both cases, an authorization that was consumed but whose execution was
  interrupted by a crash is **burned, not replayed**: the record shows
  consumed-without-established-result, no executor runs automatically, and
  the user is told the outcome is unknown.

### 5.8 Fail closed

Every path that cannot establish all of "valid challenge, matching binding,
within the attempt budget, not expired, not consumed, current effective policy
identity, current policy still permits, executor available" results in **no
execution** and an honest non-success status. Nothing defaults to permission,
and no exception during validation is allowed to fall through to an executor.

### 5.9 Effective policy identity (content fingerprint)

The stored `policy_version` is **not** a change detector: Task 220 defines it
as the fixed literal `"1"` (`AUTHORIZATION_CONTRACT_VERSION`). A rule's risk
level, prohibited flag, required-target rule, or required-parameter set can
change while the version still reads `"1"`, so a pending confirmation checked
against the label alone would look valid after the rules changed. The design
therefore binds challenges to a deterministic **identity of the effective
policy contents**, and keeps the label only as human-readable metadata.

**What affects validity.** Exactly the fields that can change an authorization
decision:

- the set of operation identifiers that have rules;
- each rule's `risk` (including "no risk level recorded", which denies);
- each rule's `prohibited` flag (which outranks every other field);
- each rule's `requires_target` flag;
- each rule's `required_parameters` set;
- the `policy_version` label itself.

**What does not.** A rule's `description` is documentation and cannot change
any decision, so editing it does not invalidate a pending confirmation.
Saying so explicitly matters: a fingerprint that changed on a comment edit
would train people to ignore invalidations.

**Canonicalization.** Rules are ordered by `operation_id` and serialized in a
fixed shape: sorted keys, no insignificant whitespace, `required_parameters`
sorted (order is irrelevant to the policy, which compares them as a set),
`risk` as its enum value or null, booleans as booleans. Two policies that
authorize identically therefore produce the same identity regardless of rule
order or parameter order in the source.

**Digest.** SHA-256 over the canonical bytes, hex-encoded — `hashlib` is in
the standard library, so no dependency is added. The plan is a side-effect-free
helper on Task 220's policy module (for example
`authorization_policy_identity(policy) -> str`) that changes no decision,
returns the same value for two equal policies, and is testable on its own.

**Binding and re-check.** The identity is stored with the pending record
(`policy_identity`) and recomputed from the currently loaded policy at
consumption time. A mismatch invalidates the challenge before any
authorization is consumed and before any executor is called. The comparison
uses the recomputed identity of the *effective* policy — the object the
boundary is actually about to evaluate against — not a cached copy taken at
mint time.

**Failure is refusal.** If loading, canonicalization, digest calculation, or
the comparison itself fails, the challenge is invalidated when the store is
reachable, the response is the generic non-success message of section 5.10,
and **no executor runs**.

**Limits, stated honestly.** The identity is a change *detector*, not proof of
authenticity: it is computed from whatever policy the process holds, so it
cannot detect that the policy itself was replaced deliberately by someone able
to modify the deployment, and it is not a signature or a trust anchor. What it
buys is precise: a consequential approval cannot survive a change to the rules
that governed it.

### 5.10 Bounded confirmation-code attempts

The display code is a second check on top of the 128-bit challenge identifier,
and it is only worth having if guessing it is bounded. **Proposed default:
five failed code attempts per challenge**, after which the challenge locks.

- **Atomic counting.** A confirm request locks the record and performs the
  comparison and the counter in the same atomic unit (for example
  `SELECT ... FOR UPDATE` followed by the update, or a conditional update that
  increments `failed_code_attempts` and returns the row). Concurrent wrong
  guesses therefore cannot exceed the budget by racing, and a correct code
  cannot slip past a failure that was recorded before it.
- **Terminal behaviour at the limit.** The budget counts *failures*, not
  attempts: the challenge stays `PENDING` after failures one to four, a
  correct code on the fifth attempt still succeeds, and the fifth **failure**
  sets `LOCKED`. Every later attempt is refused, nothing is consumed, and no
  executor runs. The user must re-propose the request, which produces a new
  challenge; a locked challenge is never unlocked or extended.
- **No consumption on failure.** Failed attempts are evaluated strictly before
  the consume transition, so a wrong code cannot burn, trigger, or dispatch
  anything.
- **Generic responses.** Unknown, malformed, expired, locked, already-used,
  and wrong-code all return the same non-success wording, with no attempt
  count, no remaining-budget disclosure, and no hint about how close a guess
  was. The caller learns only that nothing ran. The pending card keeps its own
  client-side context from the mint response, so a legitimate user can still
  retry; the server never confirms whether a given challenge exists.
- **No leakage.** Challenge identifiers and display codes never appear in
  application logs or error bodies; an attempt count may be recorded as a
  number without any identifier.
- **Budget arithmetic, for honesty about what this defends.** With the
  proposed six-character code over a 32-symbol unambiguous alphabet there are
  roughly 1.07e9 possibilities; five failures leave a per-challenge success
  probability near 1e-8 for someone who already holds a challenge identifier.
  That is why the identifier must stay secret, and why this is a guard against
  guessing rather than against an attacker who can read the store.
- **Out of scope, again.** This does not defend against malicious code running
  with the same local user's privileges: such code can read the database, call
  the confirm endpoint itself, and click Confirm. Bounded attempts raise the
  cost of guessing; they do not create a boundary the threat model in
  section 4 does not claim.

## 6. Recording and privacy

**Approved by the project owner (Task 223):** option B - durable local
records in the dedicated `assistant_confirmations` table, with a terminal
record keeping its material values for thirty days and then retaining only a
salted digest. The comparison below is kept as the record of how that was
decided. Durable storage being approved does not mean the confirmation
workflow exists: see section 14.

### 6.1 Options

| Option | Behaviour | Trade-offs |
| --- | --- | --- |
| A. In-memory only | Challenges and outcomes live in the server process and vanish on restart. | Simplest; no migration; nothing private is written. But approvals cannot survive a restart, there is no record of what was approved, and E.1's "understand, inspect, edit, export, delete" has nothing to inspect. Refusal records required by the contract's acceptance criterion (a) remain impossible. |
| B. Durable local records | Challenges and decisions are rows in the existing local PostgreSQL database, in a dedicated personal-assistant table. | Survives restart; provides a real record of what was approved and consumed; fits the existing stack (SQLAlchemy, Alembic, `/health/ready`). Costs one migration, one table, and a retention policy; stores operation values that are personal data and therefore need protection and deletion paths. |
| C. Hybrid | Pending state in memory; a durable record only for decided outcomes. | Keeps pending material out of the database, but pending approvals then vanish on restart, and the record is written after the fact — so a crash between execution and write can lose the record, which weakens exactly the audit property the record is for. |

### 6.2 Approved decision (Task 223)

**Option B is approved: durable local records in the existing database, in a
dedicated table, with a thirty-day retention window on material values after a
record becomes terminal.** The reasons below are the ones put to the owner and
are kept as the record of the decision, not as an argument still under review.

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

### 6.3 Stored fields (implemented in Task 223)

`assistant_confirmations`, created by migration `20261017_0017`. The
implementation keeps these names; the two salt columns and `redacted_at`
were added because a bare hash of a six-character code, and a digest with no
record of which salt produced it, would not support the privacy rules below.

| Field | Purpose | Notes |
| --- | --- | --- |
| `id` | Primary key | Internal, not the challenge identifier. |
| `challenge_id` | Opaque 128-bit identifier, unique index | Lookup key for the confirmation endpoint. |
| `display_code_hash` | Short code shown to the human | Salted hash; the code itself is never stored or logged, and no verification path exists yet. Cleared when the record becomes terminal, since a decided record can never be confirmed again. |
| `display_code_salt` | Per-record salt for that hash | Prevents a six-character code from being recovered from an unsalted digest. |
| `operation_id` | Exact machine identifier | Never normalized. |
| `target`, `scope` | Canonical target/scope, or null | Personal data; redact after the window. |
| `parameters` | Canonical parameter map, or empty | Personal data; redact after the window. |
| `policy_identity` | Deterministic fingerprint of the effective policy contents (section 5.9) | The real change detector. |
| `policy_version` | Human-readable version label that required confirmation | Metadata only; the current value is always `"1"`, so it cannot detect a rule change. |
| `failed_code_attempts` | Wrong display codes seen so far | Integer only; never stores a submitted code. |
| `required_risk`, `required_reason` | Why confirmation was required | Makes the record self-explaining. |
| `status` | `PENDING`, `CONSUMED`, `REJECTED`, `CANCELLED`, `EXPIRED`, `INVALIDATED`, `LOCKED` | Terminal states are explicit; `LOCKED` means the attempt budget was exhausted. There is no separate `CONFIRMED` state: the single success transition is `PENDING` to `CONSUMED`. |
| `created_at`, `expires_at`, `decided_at`, `terminal_at`, `consumed_at` | Timing | Server clock only; `terminal_at` is what the retention window counts from. |
| `outcome` | Result of the execution attempt, if any | `NOT_RUN`, `FAILED`, `SUCCEEDED`, `UNKNOWN_AFTER_CONSUME`. |
| `material_redacted` | Whether the values above were removed | Distinguishes "redacted after the window" from "never supplied". |
| `material_digest`, `material_digest_salt` | Salted digest of the removed values | One salt per record; present only once redacted. |
| `redacted_at` | When the values were removed | Server clock only. |

Deliberately **not** stored: the user's raw message, the assistant reply, any
model output, and any value that is not material to binding or reporting the
operation. The record must not become a conversation store.

Constraints enforced by the database, not only by application code: the
status enum, the outcome enum, the attempt counter bounded to zero through
five, the challenge identifier unique, `terminal_at` present exactly when the
record is not `PENDING`, a code verifier present exactly while the record is
`PENDING`, that verifier's hash and salt present together, the digest and its
salt present together, a redacted record carrying a digest, and a redacted
record carrying `redacted_at`. The table has no foreign keys at all.

### 6.4 Privacy rules

- Material parameter values are stored only because binding and execution
  require them, and are **redacted to a salted digest** once the record is
  terminal and past the retention window; the identifier, decision, timing,
  policy identity, and reason survive so the audit trail still shows *that*
  an exactly-specified action was approved, and under which rules it was
  approved. The window is thirty days from `terminal_at`, approved with the
  storage decision; the digest is SHA-256 over a domain-separated canonical
  form of the removed values and a random per-record salt. The original
  values are removed from every column, not hidden from output, and pending
  records are never redacted.
- Confirmation records, material values, and display codes are never written
  to application logs. Log lines may reference the internal id and status
  only.
- Display codes and challenge identifiers must not appear in error messages
  returned to the client (the existing 422 handler already strips `input`
  values for `/api/assistant/`; the confirm endpoint must be covered by the
  same treatment). Failed-attempt counts are never disclosed to the client,
  and a submitted code is never stored in plaintext or logged.
- User control: the storage layer now provides inspection, export, and
  deletion of confirmation records, but **no HTTP route or UI exposes them
  yet**. Until a later task integrates that surface with the confirmation
  lifecycle, E.1's inspect/export/delete promise is met at the service layer
  only, and the design does not claim otherwise.

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
3. the display code matches its stored hash, inside the remaining attempt
   budget of section 5.10, with the comparison and the counter in the same
   atomic update;
4. the request's `Origin`/`Host` match the configured local origin;
5. the bound operation, effective policy identity, and reason are intact, and
   the record is neither invalidated nor locked;
6. the *current* policy still yields `REQUIRE_CONFIRMATION` for the bound
   operation, and re-evaluating with an `AuthorizedScope` built from the
   stored record yields `ALLOW`;
7. an executor exists for the operation;
8. only then is the record consumed and the executor invoked.

Failure at any step returns a non-success status, executes nothing, and
records the failure (when durable records are approved) without personal
content. Every challenge-related refusal — unknown, malformed, expired,
locked, already used, or wrong code — returns the same generic wording, so a
caller cannot learn whether a challenge exists or how close a guess was.

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

- the **effective policy identity** is recomputed from the currently loaded
  policy and compared with the stored identity; any difference — a changed
  risk classification, a prohibited-flag flip, a changed required-target or
  required-parameter rule, an added or removed rule — invalidates the
  challenge even when `policy_version` still reads `"1"`, and the user must
  ask again (section 5.9); if loading or comparing the policy fails, the
  challenge is invalidated and nothing executes;
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
| Policy contents changed between mint and confirm | The recomputed policy identity is compared at consumption; any mismatch invalidates and refuses, even when the `policy_version` label is unchanged. |
| Two wrong codes submitted concurrently | The comparison and the counter increment happen in the same locked update, so the budget is spent, not raced past. |
| A correct code arriving after lockout | Refused; the challenge is terminal, nothing is consumed, and a new request is required. |
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
  scope, parameter set, effective policy identity, and reason;
- the policy identity is deterministic: equivalent policies (reordered rules,
  reordered `required_parameters`) produce the same identity, and a rule's
  `description` edit alone does not change it;
- confirming with an unknown, blank, or malformed challenge id executes
  nothing and reveals nothing;
- confirming with a wrong display code executes nothing;
- repeated wrong codes are bounded: the budget counts failures, so a correct
  code on the fifth permitted attempt succeeds, while the fifth failure locks
  the challenge and every later attempt — including one with the correct code
  — is refused and executes nothing;
- concurrent wrong-code submissions cannot exceed the budget, because the
  comparison and the increment share one atomic update;
- attempts against an already invalidated, expired, locked, or consumed
  challenge are refused and execute nothing;
- unknown, malformed, expired, locked, already-used, and wrong-code responses
  are indistinguishable in wording, disclose no attempt count, and contain
  neither the challenge identifier nor the display code;
- confirming an expired challenge executes nothing, including when it expires
  during the request;
- replaying a consumed challenge executes nothing the second time;
- two concurrent confirms produce exactly one execution;
- confirm and cancel racing produce at most one execution and never revive a
  consumed record;
- a change to the effective policy contents between mint and confirm
  invalidates the pending challenge in every case below, while the
  human-readable `policy_version` still reads `"1"`:
  - a rule's `risk` changes, including becoming unclassified;
  - a rule becomes `prohibited`, or stops being;
  - a rule's `requires_target` changes;
  - a rule's `required_parameters` set changes;
  - a rule is added, removed, or renamed;
  - the `policy_version` label itself changes;
- the identity is stable when nothing material changed: reordering rules,
  reordering `required_parameters`, or editing only a rule's `description`
  leaves the identity unchanged and does **not** invalidate a pending
  challenge;
- a failure while loading, canonicalizing, digesting, or comparing the policy
  identity refuses the confirmation and executes nothing;
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

These were proposals. Items 5 and 6 were approved by the owner and
implemented in Task 223 (noted inline); the rest remain proposals, because
nothing mints, displays, or verifies a challenge yet.

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
   retention window. **Approved and implemented (Task 223).**
6. **Retention: keep pending records only until expiry; keep terminal records
   for a bounded window (30 days) and then redact material values** while
   keeping the decision metadata. **Approved and implemented (Task 223).**
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
11. **Five failed display-code attempts lock the challenge** (section 5.10),
    counted atomically with the comparison, with one generic response for
    every failure and no disclosure of the remaining budget.
12. **Pending confirmations are bound to a SHA-256 fingerprint of the
    canonical policy contents** (section 5.9), not to the fixed `"1"` version
    label, and the fingerprint is recomputed and compared at consumption.

Items 11 and 12 add one side-effect-free helper to Task 220's policy module
(`authorization_policy_identity`) and two columns (the stored identity and the
attempt counter). Task 223 implemented both at the storage layer. Neither
changes an authorization decision, and neither makes a confirmation
obtainable: no challenge can be minted, consumed, or validated through any
HTTP route yet.

## 12. Decisions requiring owner approval

1. **Confirmation recording and retention (H.2 pending item).** **RESOLVED
   (owner, Task 223):** durable records in the existing local database, with
   the thirty-day terminal retention and redaction described above. The
   recording choice is decided; the interaction that obtains a confirmation is
   not, and no confirmation can be obtained through the application today.
2. **Identity and session binding assumption.** The design assumes a single
   local user on loopback with no authentication, and therefore binds an
   approval to the challenge alone. Any move to multiple users, remote
   access, or a shared machine invalidates that assumption and requires a
   session identity decision first.
3. **Whether confirmation records appear in the user's inspect, export, and
   delete surface** (E.1 user control), and under which Stage 9 item that
   surface is delivered. If durable records are approved without a deletion
   path, E.1 is not satisfied.
4. **Expiry duration and retention window.** **RESOLVED for retention (owner,
   Task 223):** thirty days from `terminal_at`. The five-minute challenge
   lifetime is implemented (Task 224: `CHALLENGE_LIFETIME` in
   `src/rop/services/confirmation.py`).
5. **How "no executor exists yet" is reported.** Reusing `refused` conflates
   a policy decision with a build limitation; a new additive status (for
   example `not-implemented`) is more honest but extends the response
   contract, so it needs review.
6. **Whether a pending approval survives a restart** (durable) or is
   discarded (ephemeral), and whether the user is told about the loss.
   **RESOLVED for storage (owner, Task 223):** pending records are durable, so
   a restart does not discard an outstanding challenge; the user-facing
   behaviour when one lapses still belongs to the confirmation workflow.

Unchanged by this document: the contract as a whole remains a **draft**; H.1,
H.3, and H.4 remain unresolved; E.2's owner decision stands as recorded; and
nothing here marks the authorization work as complete. The recording and
retention decision above resolves the storage half of the H.2 section. The
server-side confirmation workflow that obtains and consumes a user approval
was implemented in Task 224 (`src/rop/services/confirmation.py`,
`src/rop/api/confirmations.py`, `src/rop/authorization/executors.py`); the
browser surface that lets a user actually decide a pending challenge is not,
so no confirmation can be obtained through the application UI today. No
production executor is registered, so a `REQUIRE_CONFIRMATION` operation
cannot execute in this build.

## 13. Review checklist

The design is complete when a reviewer can confirm:

- [ ] the nine lifecycle states and their allowed transitions are explicit;
- [ ] clarification can never be turned into authorization, and the code path
      that mints challenges is restricted to `REQUIRE_CONFIRMATION`;
- [ ] forged, mismatched, expired, replayed, locked, and racing confirmations
      all fail closed, each with a stated mechanism;
- [ ] the identity gating a pending confirmation is a content fingerprint, not
      the fixed `"1"` label, and every material rule change invalidates the
      challenge;
- [ ] failed display-code attempts are bounded, counted atomically, land in
      the terminal `LOCKED` state at the limit, and produce indistinguishable
      failure responses;
- [ ] the threat model states what is *not* defended against, without
      over-claiming origin checks or opaque identifiers;
- [ ] recording, privacy, retention, and clinical separation are specified,
      and the recording choice is marked as an owner decision;
- [ ] the UI contract shows what is approved and says nothing has run;
- [ ] the execution boundary, re-checks, and race handling are specified;
- [ ] a testing plan exists for each failure scenario;
- [ ] Stage 9's contract remains a draft and no other pending decision is
      resolved here.

## 14. Implementation status at end of Task 223 (superseded by Task 224)

Task 223 implemented the storage and data-lifecycle foundation only. What
exists today:

- table `assistant_confirmations`, created by migration `20261017_0017`,
  with the constraints listed in section 6.3 and no foreign keys;
- `src/rop/models/assistant_confirmation.py`, registered in the models
  package and imported by Alembic's `env.py`;
- `src/rop/repositories/assistant_confirmation.py`: draft creation,
  challenge lookup, inspection, export, deletion, guarded transitions
  (consume, reject, cancel, invalidate, expire), the atomic failed-attempt
  counter with the `LOCKED` terminal state, and the thirty-day retention and
  redaction pass;
- `authorization_policy_identity(policy)` in the Task 220 policy module;
- tests that run against PostgreSQL: `tests/test_assistant_confirmation_records.py`
  and `tests/test_authorization_policy_identity.py`.

What does not exist, and is not claimed:

- no endpoint issues, confirms, cancels, or rejects a challenge, and no UI
  control does either;
- no code mints a challenge, so `REQUIRE_CONFIRMATION` is still unreachable
  and the Task 221 dispatch boundary cannot reach a state-changing operation;
- no executor, no state-changing capability, and no simulated action;
- no HTTP route exposes the inspection, export, or deletion service, so E.1's
  user-control promise is satisfied at the service layer only;
- `authorization_policy_identity` is not yet consulted by the live dispatch
  path; only the later confirmation workflow can enforce it.

Status: the durable-record foundation and its privacy lifecycle are
implemented and tested; the confirmation interaction and the execution path
remain unimplemented pending separate review and approval.

**Superseded by Task 224.** The server-side confirmation workflow that
sections 1 and 7 of this document specify was implemented in Task 224:
challenge issuance, decision handling, policy revalidation, atomic
consumption, and the executor boundary. The browser confirmation card
and Confirm/Cancel controls remain unimplemented, and no production
executor is registered. The bullets above describe the state at the end
of Task 223 and are preserved as a historical snapshot.
