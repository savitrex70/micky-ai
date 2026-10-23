# Task 232 - Stage 9.2 Interaction-Engine Design

**Stage:** Stage 9.2 (design phase only - no implementation)
**Status:** Draft design for independent review. The interaction engine
is **not implemented** by this document. Nothing in this task changes
application behaviour, schemas, migrations, tests, capabilities,
authorization policies, or executors.
**Baseline:** `5fed8e91dca70bcd5bb58b16bd6edf136b4fa60f`
**Predecessor:** Task 231 (Stage 9.1 contract reconciliation)

This document audits the actual `main` tree and proposes a concrete
design for the Stage 9.2 interaction engine. Every "verified" claim
below is based on inspection of the current source, not on prior task
documents. Recommendations are labelled as such.

---

## A. Verified current architecture

### A.1 Request lifecycle as actually implemented

The single request endpoint is `POST /api/assistant/requests`
(`src/rop/api/assistant.py::submit_request`). The verified flow is:

1. **HTTP validation.** FastAPI parses `AssistantRequest`
   (`src/rop/schemas/assistant.py`). The model forbids extra fields,
   requires `message` with length 1-2000 characters and rejects
   blank or whitespace-only content (no printable-character rule is
   enforced), and
   accepts an optional `conversation_id: UUID | None`.
2. **Persistence precheck (only when `conversation_id` is supplied).**
   `_enforce_persistence_origin(http_request)` calls
   `enforce_local_origin`; `_verify_conversation(conversation_id)` opens
   its own session, calls `ConversationRepository.get`, raises HTTP 404
   if missing, and always closes the session. No conversation ID means
   no database session is opened at this step.
3. **Capability matching.**
   `_REGISTRY.match(request.message)` (`src/rop/capabilities/registry.py`).
   `normalize_phrase` collapses whitespace, strips trailing `.`/`!`/`?`,
   and lowercases. Lookup is exact string equality against registered
   normalized aliases. No substring, no fuzzy, no model. Returns
   `Capability | None`.
4. **Unsupported path.** `None` returns
   `{status: "unsupported-capability", message: _UNSUPPORTED_MESSAGE}`.
   Not persisted, no state changes.
5. **Dispatch.**
   `_dispatch(capability, http_request)` (`assistant.py::_dispatch`).
   Two branches:
   - **Executor present branch** (`_EXECUTORS.get(capability.identifier)
     is not None` - never true in production because
     `build_default_executor_registry()` returns an empty registry).
     `evaluate_authorization` runs; on `REQUIRE_CONFIRMATION` the
     handler enforces origin, then `_issue_challenge(capability)` mints
     a durable challenge. `ISSUED` yields
     `{status: "confirmation-required", challenge: ...}`; any other
     outcome yields `{status: "confirmation-required", message:
     _CONFIRMATION_UNAVAILABLE_MESSAGE}`.
   - **Fallback branch** calls `authorize_capability_dispatch(capability,
     policy=_POLICY)` (`src/rop/authorization/dispatch.py`), which
     re-evaluates the policy and returns:
     `success` (if `ALLOW`), `clarification-required` (if `CLARIFY`),
     `confirmation-required` with `_CONFIRMATION_MESSAGE` (if
     `REQUIRE_CONFIRMATION`), `refused` (if `DENY` or evaluation
     exception).
6. **Persistence of the successful turn.**
   `if conversation_id is not None and response.status == "success"
   and response.challenge is None`: `_persist_successful_turn(...)`
   appends the user and assistant messages in a single session and
   commits atomically. `IntegrityError` classifications map to 409
   (sequence conflict) / 404 (missing parent) / 503 (other). Any other
   exception maps to 503. On any failure, the pair is rolled back and
   the HTTP error is raised *after* the response was already returned
   at the model layer - the client receives the 5xx and knows the
   exchange was answered but not saved.

### A.2 Verified facts about the current state

| Claim | Verified state | Evidence |
|---|---|---|
| Only `help` is registered | TRUE. `HELP_ALIASES` is the only set. | `registry.py::build_default_registry` |
| Aliases are exact after normalization | TRUE. No fuzzy, no substring. | `registry.py::match`, `::normalize_phrase` |
| Request path uses authorization | TRUE. `submit_request` → `_dispatch` → `authorize_capability_dispatch` → `evaluate_authorization`. | `assistant.py`, `dispatch.py`, `policy.py` |
| Production executor registry empty | TRUE. | `executors.py::build_default_executor_registry` |
| Five public statuses | TRUE. `success`, `unsupported-capability`, `clarification-required`, `confirmation-required`, `refused`. | `schemas/assistant.py::AssistantStatus` |
| Only `success` persists | TRUE. Gated explicitly. | `assistant.py::submit_request` |
| No-conversation path is database-free | TRUE. `_verify_conversation` and `_persist_successful_turn` only run when `conversation_id` is set. | `assistant.py`, `test_assistant_persistence.py::test_no_conversation_does_not_touch_db` |
| Conversation ≠ clinical reasoning | TRUE. Separate tables, no FK, no shared identifiers. | `models/assistant_conversation.py`, `models/assistant_message.py`, `test_assistant_persistence.py::test_persistence_does_not_touch_reasoning_sessions` |
| Policy contains only `help` at LOW risk | TRUE. `DEFAULT_POLICY_RULES` has one entry. | `policy.py::DEFAULT_POLICY_RULES` |
| Confirmation requires a registered executor | TRUE. `issue_challenge` returns `NO_EXECUTOR` when the operation has no executor. | `services/confirmation.py::issue_challenge` |
| Challenge bound to policy identity (SHA-256) | TRUE. `policy_identity` is stored; a policy change invalidates the challenge. | `models/assistant_confirmation.py`, `test_confirmation_flow.py::test_policy_identity_change_invalidates_and_refuses` |
| Browser confirmation card exists | TRUE. Task 226 implemented it. | `app.js`, `docs/task-222-confirmation-flow-design.md §6.4` |
| Confirmation record inspect/export/delete exists | TRUE. Task 227. | `src/rop/api/confirmation_records.py`, `docs/task-222-confirmation-flow-design.md §6.4` |

### A.3 Responsibility boundaries

- **Selection** (does a registered capability match?): `CapabilityRegistry`.
  Does not imply permission to execute.
- **Authorization** (may this operation run?): `evaluate_authorization`.
  Does not execute.
- **Confirmation** (did the user approve this exact operation?):
  `src/rop/services/confirmation.py` + `assistant_confirmations` table.
  Does not execute.
- **Execution** (run the operation): `ExecutorRegistry`. Empty in
  production. Only reachable through `confirmation.decide` after a
  consumed challenge.
- **Reporting** (what may we tell the user?): `AssistantResponse`
  envelope + HTTP status for save failures.

The boundaries are already separated. Task 232's job is to design the
*coordination* of these boundaries for a full interaction engine -
not to merge them.

### A.4 What is incomplete or absent

- **No non-`help` capability is registered.** The `submit_request`
  handler will only ever successfully dispatch `help`.
- **No parser from user `message` to `ProposedOperation`.** Today the
  only operation built is `ProposedOperation(operation_id=capability.identifier)`
  - `target`, `scope`, and `parameters` are always unset. Any future
  capability that needs a target (e.g., a note title) will require a
  new parsing step.
- **No clarification state.** When the policy returns `CLARIFY`, the
  response carries `clarification-required` but the pending question
  (what the user should clarify) is not stored anywhere. The next
  message starts a fresh selection from scratch.
- **No `execution-failed` / `execution-unknown` status.** No production
  executor exists, so these paths are unreachable today. When a
  production executor is added, the envelope must distinguish:
  operation failed (established), operation outcome unknown (interrupted
  or crashed), and confirmation unavailable (challenge could not be
  minted despite a `REQUIRE_CONFIRMATION` outcome).
- **`confirmation-required` overloads two distinct situations.** Today,
  `_dispatch` returns `confirmation-required` both when a challenge
  was actually minted (`challenge != None`) and when it could not be
  (`challenge == None`, `_CONFIRMATION_UNAVAILABLE_MESSAGE`). A client
  that switches solely on `status` cannot distinguish "show card" from
  "cannot show card". See §E for the recommended fix.

---

## B. Capability-selection contract

### B.1 Preserved invariants

- **Explicit registration is the only source of supported
  capabilities.** No implicit selection, no derived set, no fallback.
- **Deterministic normalization.** Collapse whitespace, strip trailing
  `.!?`, lowercase. Exactly as `normalize_phrase` does today.
- **Exact match.** Lookup by normalized string equality. No substring,
  no edit distance, no LLM intent classification, no hidden network
  call.
- **A match is a candidate, not a permission.** The authorization
  policy must `ALLOW` before the capability's response is returned.

### B.2 Unmatched and unsupported

An unmatched message returns `unsupported-capability` with a message
that does not echo the user's input. This behaviour is preserved.

**Recommendation:** retain the current "single unmatched status"
behaviour for Stage 9.2. Adding an "ambiguous between N registered
capabilities" status (e.g., `ambiguous-capability`) requires a
substring/fuzzy matcher to be meaningful, which is explicitly
excluded. Until such a matcher is justified, unmatched → unsupported is
correct.

### B.3 Known capability, missing information

"Known capability with missing material information" is a distinct
case from "unsupported capability." Today, this is only reachable
through the policy evaluator's `TARGET_MISSING` / `PARAMETER_MISSING`
reasons, which produce `CLARIFY` → `clarification-required`. Because
`help` requires neither target nor parameters, this path is
unreachable in production today.

**Recommendation:** the selection protocol must not conflate these.
The `Capability` contract should carry, for each registered capability,
the information its executor requires (target? which parameters?),
and the interaction engine must distinguish:

- **unsupported-capability** - no capability matches. No follow-up
  question can resolve this.
- **clarification-required** - a capability matched but the request is
  missing required information. A follow-up question can resolve this.

The policy evaluator already provides this distinction via
`AuthorizationReason.TARGET_MISSING` / `PARAMETER_MISSING`; the
selection protocol should feed it the parsed values.

### B.4 Registration of future capabilities

A capability must be registered through `CapabilityRegistry.register`
*and* have a matching rule in `AuthorizationPolicy` *and* (for
`REQUIRE_CONFIRMATION` operations) have an executor registered. All
three are independent, and none inherits the others:

- **Registering a capability does not authorize it.**
  `test_authorization_dispatch.py::test_registered_capability_absent_from_the_policy_is_blocked`
  proves this.
- **Authorizing a capability does not give it an executor.**
  `services/confirmation.py::issue_challenge` returns `NO_EXECUTOR`
  when no executor exists, and `test_confirmation_flow.py::test_no_executor_means_no_challenge`
  proves it.
- **Registering an executor does not register a capability.**
  `ExecutorRegistry.register` accepts any well-formed identifier; the
  capability registry would still need its own alias.

Task 232 must preserve this three-way independence.

### B.5 Compatibility with existing `help` behaviour

The design is additive. The current `help` flow continues to work
unchanged. No new status, no new schema field, no new matcher can
affect the `help` request path. Regression coverage for `help` must be
preserved verbatim.

---

## C. Clarification contract

### C.1 Why the previous design was wrong

The previous design (commit 7de8a89) recommended client-only pending
state and claimed no API change was needed. Two facts make that
non-viable:

1. AssistantRequest has no field for pending context. The schema in
   src/rop/schemas/assistant.py accepts only message and
   conversation_id. The browser cannot attach a pending_capability_id
   or original_message to the follow-up. Even if a field were added,
   the server would have no way to verify the client's claim was
   accurate - a malicious or buggy client could claim any capability
   it liked.

2. The follow-up does not match the original alias.
   CapabilityRegistry.match normalizes the entire message and performs
   exact string equality against registered normalized aliases (see
   src/rop/capabilities/registry.py::normalize_phrase). If the user
   first sends "remind me tomorrow" (matched to the reminder
   capability) and gets a clarification asking "what time?", the
   follow-up message will be something like "at 3pm" - which
   CapabilityRegistry.match("at 3pm") will correctly return None for,
   because it does not equal any registered alias.

Both facts point to the same conclusion: the follow-up must go through
a different code path than the initial request, one that (a) carries
the pending capability context on the wire and verifies it
server-side, and (b) does not rely on the follow-up message matching
an alias. The correct design uses server-issued pending state keyed by
an unguessable identifier, the same pattern already proven by the
confirmation-challenge system.

### C.2 Wire protocol and pending-state record

**Request:** add optional `clarification_id: UUID | None = None`. When present, the request is a continuation of that server-owned clarification, not a fresh selection. If absent, current fresh-request semantics remain unchanged.

**Response:** add optional `clarification_prompt: ClarificationPrompt | None`, present only when a real pending row is created. It contains the server-issued clarification ID, capability identifier, user-facing question, and sanitized missing-field names. It contains no authorization, executor selection, policy identity, or confirmation data.

**New server-owned table: `pending_clarifications`.** Fields: UUID primary key; unique high-entropy clarification ID; non-null UUID `conversation_id` referencing `assistant_conversations.id` with `ON DELETE CASCADE`; capability identifier; bounded `original_message`; minimized JSON partial operation values; missing-field names; created/expiry/consumed timestamps; and a constrained lifecycle status.

The table must retain the original bounded message and only the partial operation material needed to continue safely. These are temporary user values, so they must not be described as value-free. Rows expire after ten minutes and are deleted on resolution, explicit abandonment, expiry cleanup, or conversation deletion. The endpoint must not log raw user values, expose stored material through GET responses or exports, or reveal it in errors. There is no relationship to clinical reasoning tables. No pending row may be created when `conversation_id` is absent.

The migration must include expiry/status and unique-ID indexes, status constraints, and a downgrade that removes only this new table.

### C.3 Full clarification flow

1. **Initial request:** select an explicitly registered capability and run its deterministic parser. If required information is missing, create a pending row only for a verified selected conversation; store the bounded original message and minimized partial operation, then return `clarification-required` with a fresh ID and a question. Do not persist the non-success clarification in conversation messages.
2. **Follow-up:** the client sends the answer as `message`, the same `conversation_id`, and the server-issued `clarification_id`. The handler locks/claims the matching unexpired row, verifies that it belongs to that conversation, and loads its saved context. The client does not name the capability or submit an authorization.
3. **Continuation:** combine the saved partial operation with the answer and produce a validated `ProposedOperation`. Do not match the answer against the global alias registry. If more information is needed, create a replacement pending row and consume the old one atomically. If the operation is complete, consume the old row before dispatch.
4. **Fresh authorization:** every continuation re-runs the current policy over the newly reconstructed operation; no authorization or confirmation from the original turn carries forward. Material changes require a new decision and, for consequential operations, a new confirmation.
5. **Persistence:** on success, persist the original message plus the clarification answer as the user turn, and the truthful result as the assistant turn, atomically under the existing successful-turn-only rule. A non-success clarification is not stored as a successful exchange.
6. **Parser faults:** expected typed user-input errors may initiate clarification. Unexpected exceptions or invalid parser output produce a sanitized fail-closed response, not another question that misleads the user.

### C.4 No-conversation path

Requests without `conversation_id` remain database-free. When such a request needs clarification, return a sanitized message asking the user to select/create a conversation; do not create a pending row or return a continuation ID. A request containing `clarification_id` but no `conversation_id` is rejected before opening a database session. A state-changing capability must not execute on this path.

### C.5 Edge cases and lifecycle guarantees

- **Conversation switch/mismatch:** reject the follow-up without entering dispatch and without consuming the legitimate pending row.
- **Reload/recovery:** add local-origin-guarded `GET /api/assistant/clarifications?conversation_id=...`, returning only the active sanitized prompt for the selected conversation, never original input or partial operation values.
- **Abandonment:** add local-origin-guarded `DELETE /api/assistant/clarifications/{clarification_id}`, restricted to the matching selected conversation.
- **Expiry:** pending rows expire after ten minutes. Cleanup must be bounded and use indexes rather than an unbounded scan. Expired rows cannot be resumed.
- **Concurrency/replay:** use a row lock or atomic state transition from PENDING to CONSUMED. Only one continuation may claim a row. A replay or simultaneous second answer receives a sanitized stale/consumed response and cannot execute.
- **Replacement clarification:** if more information is needed, atomically consume the old row and create the new one; transaction failure rolls back both effects.
- **Deletion/privacy:** deleting a conversation removes only its clarification state, never clinical data. Raw user values are excluded from logs, generic errors, and exports. Delete/redact temporary values immediately when no longer needed.

### C.6 Options considered and rejected

- Client-only state is rejected because the backend cannot verify the client's claimed pending capability and the follow-up does not match the original exact alias.
- A continuation payload without server state is rejected because the client could alter or replay operation material without a server-verifiable binding.
- Persisting clarification questions as conversation messages is rejected for this implementation because it changes the successful-turn-only conversation persistence contract.
- Reusing `conversation_id` as the pending-interaction ID is rejected because those identifiers represent different lifecycles.
- Fuzzy matching or model-based intent inference for follow-ups is rejected. Follow-ups resolve only through the explicit pending-clarification route.

### C.7 Contract amendments for delegated Stage 9 completion

The owner has delegated the full Stage 9 implementation and associated design choices to the assistant. Within the approved privacy, deterministic-routing, offline, and authorization boundaries, the implementation will add: `clarification_id`, structured `clarification_prompt`, ten-minute server-side clarification records, restore/abandon endpoints, an idempotency key for state-changing requests, durable operation receipts, and distinct initial-request outcomes for unavailable confirmation and synchronous direct execution failure/unknown status. The confirmation-decision endpoint retains its existing outcome contract.

These changes do not authorize fuzzy matching, hosted/remote inference, hidden provider fallback, clinical-domain coupling, or enabling a production executor before its implementation and recovery tests pass.

## D. Authorization and safe-execution contract

### D.1 Three execution paths

The previous design wrongly treated confirmation consumption as the
universal prerequisite for executor dispatch. The approved risk-based
policy (`src/rop/authorization/policy.py`) allows `LOW`-risk operations
to execute on `ALLOW` without any confirmation, so the design must
distinguish three paths.

**Path A - Non-state-changing capabilities (today: `help`).**
- Capability registered; operation is read-only.
- Policy rule: `RiskLevel.LOW`, `prohibited=False`.
- `evaluate_authorization` returns `ALLOW` (`ALLOWED_LOW_RISK`).
- `capability_reply` returns the predefined reply.
- **No executor runs.** `help` has no executor and needs none.
- This is the only path exercised today.

**Path B - State-changing but LOW-risk operations (future).**
- Capability registered; operation mutates state.
- Policy rule: `RiskLevel.LOW`, `prohibited=False`.
- `evaluate_authorization` returns `ALLOW` (`ALLOWED_LOW_RISK`).
- **A server-owned executor is registered for this operation** (a
  specific, reviewed registration; not the empty default).
- The `submit_request` handler invokes the executor **directly, on
  this request**, after re-validating operation identity and material
  parameters against the freshly-parsed `ProposedOperation`. No
  confirmation step occurs because the approved policy did not require
  one.
- Executor outcome maps to `AssistantResponse`:
  - `ExecutorResult.SUCCEEDED` → `{status: "success", message: ...}`.
    If `conversation_id` supplied, persist the user/assistant pair.
  - `ExecutorError` (established failure) → `{status:
    "execution-failed", message: ...}` (new status, §E).
  - `ExecutorInterrupted` / unexpected exception → `{status:
    "execution-unknown", message: ...}` (new status, §E).
  - No conversation persistence for failed or unknown outcomes (no
    assistant reply exists to store).

**Path C - Consequential operations that require confirmation (future).**
- Capability registered; operation mutates state.
- Policy rule: `RiskLevel.CONSEQUENTIAL`, `prohibited=False`.
- `evaluate_authorization` returns `REQUIRE_CONFIRMATION`.
- The `submit_request` handler mints a challenge via
  `issue_challenge` and returns `{status: "confirmation-required",
  challenge: ...}` on `AssistantResponse`. **No executor runs here.**
- The user submits a decision via
  `POST /api/assistant/confirmations/{id}/decision`.
- `services/confirmation.decide` re-runs `evaluate_authorization`,
  verifies the display code, and on `CONFIRM` consumes the challenge
  then invokes the executor via `ExecutorRegistry.get(operation_id)`.
- Executor outcome maps to `ConfirmationDecisionResponse` (existing
  contract, unchanged): `executed`, `failed`, `unknown`, `cancelled`,
  `rejected`, `refused`, `unavailable`.

### D.2 Ordered steps common to all three paths

Regardless of which path a capability takes, the interaction engine
processes any request through these steps in order:

1. **Capability selection.** `CapabilityRegistry.match`. No side
   effects.
2. **Build a validated `ProposedOperation`.** The capability's parser
   (see §G.2) turns `message` (plus pending clarification context if
   present) into a `ProposedOperation`. For `help`, the parser is
   trivial. For future parameterized capabilities, the parser produces
   the operation from user-supplied values; missing fields do not
   crash the parser (they yield a `ProposedOperation` with those fields
   unset, and the policy returns `CLARIFY`).
3. **Required-information validation.** Policy checks
   `requires_target` and `required_parameters`. Missing → `CLARIFY`.
   This is already implemented in the policy; the interaction engine
   feeds it real values, not empty `{}`.
4. **Policy evaluation.** `evaluate_authorization(operation,
   policy=..., authorized=None)`. No caller-supplied authorization at
   this layer. Returns `ALLOW`, `CLARIFY`, `REQUIRE_CONFIRMATION`, or
   `DENY`.
5. **Clarification or refusal.** `CLARIFY` → return
   `clarification-required` with a `clarification_prompt` per §C.
   `DENY` → return `refused`. Both mean nothing was executed.
6. **Path-specific dispatch.** Path A: no executor. Path B: executor
   invoked directly on `submit_request`, outcome reported as
   `success` / `execution-failed` / `execution-unknown` on
   `AssistantResponse`. Path C: challenge minted; execution deferred
   to the decision endpoint.
7. **Persistence.** `success` turns with a `conversation_id` persist as
   today. `execution-failed`, `execution-unknown`, and every
   non-`success` outcome from Path A/B do **not** persist as
   user/assistant pairs, preserving the "only successful exchanges
   persist" invariant. Path C execution outcome is recorded in the
   `assistant_confirmations` table's terminal outcome column (existing
   behavior); it does not touch conversation messages.

### D.3 Preserved constraints

- **Per-operation, risk-based authorization.** Preserved. No
  session-scoped authorization.
- **Confirmation covers the exact operation and material
  parameters.** Preserved. Material change → new decision. Proven by
  `test_authorization_policy.py::test_authorization_for_one_target_does_not_cover_another`
  and siblings.
- **Client is never trusted for authorization.** Preserved.
  `AssistantRequest` forbids extra fields; Path B and Path C choose
  executors server-side via `ExecutorRegistry.get(operation_id)`, never
  via request field. No `AuthorizedScope`, `confirmed` flag, or
  caller-chosen executor is accepted.
- **No production executor registered in Stage 9.2.** Enforced. Path
  B and Path C are exercised only with test-only executors. The
  production `build_default_executor_registry()` remains empty
  throughout Stage 9.2.
- **Every follow-up re-validates and re-authorizes.** A clarification
  follow-up (§C) does not carry a pre-approved authorization; the
  combined input is re-parsed and the resulting operation is
  re-evaluated against the policy.

### D.4 Integration with future capabilities

A read-only operation such as listing notes uses a policy-authorized non-mutating path. A reviewed low-risk local write may use direct LOW-risk ALLOW. A destructive or consequential operation must use the trusted confirmation path. Each capability, policy rule, and executor remains independently registered and reviewed.

### D.5 Execution permits, receipts, and recovery

The current executor type is `Callable[[ProposedOperation, AuthorizedScope], ExecutorResult]`; it does not model a LOW-risk ALLOW without confirmation. Introduce a server-created, immutable execution permit with separate variants: `LowRiskPermit`, binding the exact operation fingerprint and current policy identity after an ALLOW for a LOW-risk rule, and `ConfirmedPermit`, containing the exact stored scope only after the trusted confirmation has been verified and consumed. Neither permit is accepted from HTTP input. The boundary must reject a permit whose type conflicts with the current policy risk or whose material operation differs.

Every state-changing local executor must require an idempotency key and a durable operation receipt bound to the canonical operation fingerprint. The state mutation and receipt must commit atomically in the same database transaction. Reusing a key with different material is a conflict; a completed key returns its prior result without re-running; a concurrent or unresolved receipt must not start a second execution.

This is necessary because an operation can succeed before conversation history persistence fails. The receipt stays authoritative; retrying with the same key recovers the result and saves the conversation turn without duplicating the effect. External/non-transactional side effects are not eligible for the direct local write path without a separately reviewed recovery protocol.

Tests must cover success + saved exchange, success + failed conversation persistence, established failure, unknown execution, failure to record a terminal result, duplicate replay, concurrent duplicate request, and same-key/different-operation conflict. Production state-changing executors remain disabled until these boundaries are implemented and verified.

## E. Truthful outcome contract

### E.1 Two response contracts, two owners of outcome

The interaction engine produces **two distinct response envelopes**,
each with its own status enum, for two distinct endpoints. The
previous design wrongly proposed moving post-confirmation execution
outcomes onto `AssistantStatus`; the corrected design preserves the
existing boundary.

| Contract | Endpoint | Statuses | Owner of the outcome |
|---|---|---|---|
| `AssistantResponse` | `POST /api/assistant/requests` | `success`, `unsupported-capability`, `clarification-required`, `confirmation-required`, `refused` (today) + proposed `confirmation-unavailable`, `execution-failed`, `execution-unknown` | The request handler, synchronously |
| `ConfirmationDecisionResponse` | `POST /api/assistant/confirmations/{id}/decision` | `executed`, `failed`, `unknown`, `cancelled`, `rejected`, `refused`, `unavailable` (existing, unchanged) | The decision handler, synchronously |

**`ConfirmationDecisionResponse` already owns Path C execution
outcomes.** `src/rop/schemas/confirmation.py::ConfirmationDecisionStatus`
defines exactly seven statuses, and `src/rop/api/confirmations.py`
returns `ConfirmationDecisionResponse(status=result.outcome,
message=result.message, executed=result.executed)` unchanged. The
corrected design does not touch that contract.

The three proposed `AssistantStatus` additions are for **Path B only**
and for the initial-endpoint `confirmation-unavailable`
disambiguation; they are not for post-confirmation outcomes.

### E.2 Corrected status inventory

**`ConfirmationDecisionStatus` (unchanged):** owns all Path C
execution outcomes. `executed` is the only status where an executor
ran and reported success. `failed` = ran, reported failure. `unknown`
= ran, outcome could not be established. `cancelled`, `rejected`,
`refused`, `unavailable` = nothing ran.

**`AssistantStatus` (three additions proposed):**

1. **`confirmation-unavailable`** - disambiguates from
   `confirmation-required`. Today both share the same status; only
   whether `challenge` is `None` distinguishes them. The corrected
   design returns `confirmation-required` when a challenge was issued
   (`challenge != None`) and `confirmation-unavailable` when it could
   not be (`challenge == None`). The message field remains; no other
   payload change. This is a small, honest improvement to the initial
   endpoint.

2. **`execution-failed`** - Path B only. Returned when a LOW-risk
   `ALLOW` operation's executor ran synchronously on the request
   endpoint and reported `ExecutorError`. Payload: `message` only. No
   conversation persistence (there is no assistant reply to store).
   The user is told the operation failed.

3. **`execution-unknown`** - Path B only. Returned when a LOW-risk
   `ALLOW` operation's executor ran synchronously on the request
   endpoint but its outcome could not be established
   (`ExecutorInterrupted` or unexpected exception). Payload: `message`
   only. The user is told the outcome is unknown and instructed to
   inspect logs / not retry blindly. No conversation persistence.

### E.3 Persistence per status

| Status (on `AssistantResponse`) | Path | Executor ran? | Persisted as user/assistant pair? |
|---|---|---|---|
| `success` | A | No | Yes, if `conversation_id` supplied |
| `success` | B | Yes (SUCCEEDED) | Yes, if `conversation_id` supplied |
| `unsupported-capability` | - | No | No |
| `clarification-required` | - | No | No (pending state in `pending_clarifications`) |
| `confirmation-required` | C (issued) | No | No |
| `confirmation-unavailable` | C (unavailable) | No | No |
| `refused` | - | No | No |
| `execution-failed` | B | Yes (FAILED) | No - no assistant reply exists |
| `execution-unknown` | B | Yes (unknown) | No - no assistant reply exists |

Path C execution outcome is recorded entirely by
`confirmation.decide` in the `assistant_confirmations` table's
terminal outcome column. It does not touch the conversation message
table and does not surface on `AssistantResponse`.

### E.4 Truthful-outcome invariants

- **A request is never a success merely because it was accepted,
  matched, attempted, or confirmed.** Only `success` with a
  `capability_reply` (Path A) or `ExecutorResult.SUCCEEDED` (Path B)
  is a success.
- **Execution failure is never reported as `success`.** Path B
  `ExecutorError` → `execution-failed`. Path C `ExecutorError` →
  `ConfirmationDecisionStatus.failed`.
- **Unknown outcome is never reported as `refused` or `failed`.**
  Path B `ExecutorInterrupted` → `execution-unknown`. Path C
  `ExecutorInterrupted` → `ConfirmationDecisionStatus.unknown`. These
  are distinct from `failed` and from `refused`.
- **Confirmation requirement is never inferred from a challenge
  existing.** A challenge exists only when `issue_challenge`
  succeeded; the corrected `confirmation-unavailable` status reflects
  the failed case honestly.
- **A clarification request is never confused with a refusal or with
  an internal error.** §G.2 defines the parser failure taxonomy:
  expected user-input failures map to `clarification-required`,
  unexpected parser exceptions map to `refused` with a static message.

### E.5 Compatibility and migration

Adding `confirmation-unavailable`, `execution-failed`,
`execution-unknown` to `AssistantStatus` is backward-incompatible for
any client that exhaustively matches the enum. The current browser
`describeStatus` function (`web/static/app.js`) must be updated in the
same change that adds these statuses. There is one first-party client;
no external clients are known.

`ConfirmationDecisionResponse` and its seven statuses are unchanged.
No path in this design modifies `src/rop/schemas/confirmation.py`.

### E.6 What does NOT change

For clarity, given the previous design's error:

- No new status on `ConfirmationDecisionStatus`.
- No new field on `ConfirmationDecisionResponse`.
- No change to how `services/confirmation.decide` records Path C
  outcomes.
- No change to the `assistant_confirmations` table.
- The `executed` boolean on `ConfirmationDecisionResponse` continues
  to mean exactly "an executor was invoked"; it is not redefined.



## F. Conversation, privacy, and offline boundaries

### F.1 Conversation integration

- Requests without `conversation_id` remain database-free.
- When supplied, a conversation ID is verified before dispatch.
- Only successful exchanges persist as an atomic user/assistant pair; clarification prompts are not stored as successful conversation messages.
- Pending clarifications use short-lived server-side state, not conversation ordering. A successful continuation persists the original request plus the answer as one user turn and the truthful outcome as the assistant turn.
- State-changing requests require durable idempotency receipts to recover if HTTP delivery or conversation persistence fails.
- Conversation IDs never join, map, or share identity with clinical reasoning IDs or tables. Clarification records relate only to assistant conversations.

### F.2 Privacy

- **Sensitive operation values must not leak through logs or error
  responses.** The current `_persist_successful_turn` maps
  `IntegrityError` to a sanitized 5xx. The confirmation flow stores
  hashes, not plaintexts (`display_code_hash`, `display_code_salt`).
  The interaction engine must preserve this.
- **The user's `message` is not echoed.** `test_assistant_api.py::test_unsupported_response_does_not_echo_user_message`
  and `::test_refusal_does_not_echo_the_matched_user_text` prove the
  current rule; the engine must not introduce new echo paths.
- **Confirmation secrets never appear in public responses.** The
  `AssistantConfirmationChallenge` model carries exactly
  `challenge_id`, `summary`, `display_code`, `expires_at` - nothing
  about the policy fingerprint, hashes, or the internal DB ID.

### F.3 Offline

- The entire request path is offline. No network calls, no model
  invocation, no automatic training. `test_authorization_dispatch.py::test_dispatch_module_imports_no_network_or_model_facilities`
  proves the dispatch module is offline. Task 232's design introduces
  no network dependency.

### F.4 Stage 8 native-model restrictions

The interaction engine is deterministic. It calls no model. Stage 8's
native-model restrictions remain intact: no hosted inference, no
Ollama, no third-party pretrained model, no automatic download, no
training during interaction.

### F.5 Decisions selected for delegated Stage 9 completion

- Use server-owned, ten-minute clarification state bound to a selected conversation, with restore and abandonment endpoints.
- Store only the bounded original message and minimized partial operation needed to safely reconstruct the request; delete temporary values on resolution, abandonment, expiry, or conversation deletion.
- Add an idempotency key and durable receipt before any state-changing executor is production-eligible.
- Keep execution outcomes on the endpoint that owns them: initial-request statuses for synchronous direct LOW-risk execution and challenge issuance; existing confirmation-decision statuses for consequential confirmation execution.
- Production executor registration remains separately reviewed; no production executor is registered in Stage 9.2.

## G. Implementation sequence

Proposed Stage 9.2 implementation steps. Each is small, independently
reviewable, and preserves the production executor registry being
empty. Each step ends with green tests and a design review, not an
automatic merge.

### G.1 - Test-only capability and policy fixtures

Prove non-help selection and dispatch with test-only capability/policy fixtures. Do not add a production `status` capability solely to test routing.

**Acceptance:** test the exact-alias path, a registered capability without a policy rule returning refusal, and the existing help response unchanged. Production registry stays help-only until an actual feature is independently implemented and reviewed.

### G.2 - `CapabilityParser` contract with typed failure taxonomy

**Intended behaviour:** introduce a `CapabilityParser` protocol that
turns `(message, pending_context) -> ProposedOperation`, with a defined
failure taxonomy that distinguishes **expected user-input parse
failures** from **unexpected internal parser faults**.

`help` and any future non-parameterized capability use a trivial
parser. A parameterized capability's parser produces a
`ProposedOperation` from `message` (plus pending clarification
context if present).

**Failure taxonomy (critical):**

- **Expected parse failure (`CapabilityParseError`)**: raised by the
  parser when the user's input does not contain a required field or
  contains an ambiguous value. Carries a `field_name: str` attribute
  identifying which field is missing/ambiguous. Server catches this
  and returns `clarification-required` with a `clarification_prompt`
  naming the field. This is the designed path for user input that
  legitimately needs clarification.

- **Unexpected parser exception (internal bug)**: any other exception
  from the parser. Server catches and returns `refused` with a static
  "the request could not be processed" message. **Does not echo the
  exception type, the exception message, or any input value.** Never
  maps to `clarification-required`, because disguising a bug as a
  clarification request would mislead the user into thinking they
  can fix the problem by rephrasing.

- **Invalid output from parser**: if the parser returns something
  that is not a valid `ProposedOperation`, or a
  `ProposedOperation` with a wrong `operation_id` for the matched
  capability, server returns `refused`. Same handling as unexpected
  exception - never clarified.

**Modules:** new `src/rop/capabilities/parser.py` (protocol,
`CapabilityParseError` exception with `field_name`); update
`capabilities/registry.py` (extend `Capability` with optional
`parser: CapabilityParser`); `api/assistant.py` (parser invocation
with try/except that distinguishes the two exception types).

**Dependencies:** G.1.

**Tests:**

- Unit: a well-behaved parser produces the expected
  `ProposedOperation`.
- Unit: a parser raising `CapabilityParseError("target")` produces an
  exception with `field_name == "target"`.
- Integration: a test-only capability whose parser raises
  `CapabilityParseError` returns `clarification-required` with a
  `clarification_prompt` naming the field.
- Integration: a test-only capability whose parser raises a generic
  `RuntimeError` returns `refused` with the static message.
- Integration: a test-only capability whose parser returns an
  invalid `ProposedOperation` returns `refused`.
- Regression: `help`-only path unchanged.

**Acceptance:** expected and unexpected parser failures produce
distinct statuses; neither masks the other; no exception detail is
exposed to the client.

**Compatibility:** no schema change; no browser change (the browser
must handle both `clarification-required` and `refused` per §E).

### G.3 - Server-owned clarification workflow

Implement the protocol in §C: optional clarification ID, structured prompt, ten-minute pending rows for verified selected conversations, safe continuation, GET restore, DELETE abandonment, atomic single-use consumption, and fresh authorization after every answer.

**Modules:** request/response schemas; new clarification model, repository, service, API routes and migration; `api/assistant.py`; browser UI.

**Tests:** persistence and expiry; local-origin checks; no-conversation database-free behaviour; reload restoration; malformed/expired/mismatched IDs; conversation deletion; replay and concurrent continuation; successful pair persistence; static error messages and privacy.

**Acceptance:** exactly one request can claim a pending clarification; a follow-up cannot be routed as an unrelated alias; stale/mismatched continuation never enters execution; non-success clarification is not stored as a successful turn.

### G.4 - Confirmation flow end-to-end test (no production executor)

**Intended behaviour:** demonstrate the full confirmation lifecycle in
a test-only executor scenario:
`request → REQUIRE_CONFIRMATION → challenge issued → user submits
decision with code → executor runs → terminal outcome`.
The executor is registered only in the test suite, not in
`build_default_executor_registry`.

**Modules:** existing `confirmation.py`, `api/confirmations.py`; no
production changes.

**Dependencies:** none (existing behaviour).

**Tests:** this is the existing confirmation-flow test suite,
optionally extended to cover the browser-side confirmation card
end-to-end within the harness.

**Acceptance:** the confirmation lifecycle works end to end with a
test-only executor and the production registry stays empty.

**Compatibility:** no change.

### G.5 - Truthful outcomes, idempotency, and recovery

Add `confirmation-unavailable` to distinguish failed challenge issuance from a real pending challenge. Add `execution-failed` and `execution-unknown` only for synchronous direct LOW-risk execution. Keep post-confirmation outcomes on the existing `ConfirmationDecisionResponse`.

Add state-changing request idempotency and durable operation receipts. The state mutation and receipt commit together; conversation message persistence can be recovered on retry using the same key without re-executing the operation.

**Tests:** issued/unavailable challenge; direct low-risk success, established failure and unknown execution; receipt uniqueness; concurrent duplicate; same key/different payload conflict; succeeded operation + conversation persistence failure; receipt/result record failure; browser protection from blind retry.

**Acceptance:** all outcomes are truthful, and retry cannot silently duplicate a local state-changing operation. Production executor registry remains empty.

### G.6 - Cross-flow integration and recovery tests

Exercise unsupported selection, policy refusal, expected clarification, internal parser error, stale/replayed clarification, LOW-risk ALLOW with a test-only executor, consequential confirmation with a test-only executor, operation failure, unknown outcome, receipt recovery, and conversation persistence failure.

**Acceptance:** API and UI tests verify the endpoint-specific outcome, persistence result, and retry behaviour. Existing help, successful-turn persistence, and no-conversation DB-free tests stay green.

### G.7 - Risk-appropriate executor approval gate

- **Path A:** prove policy-authorized non-mutating behaviour and exact selection.
- **Path B:** prove a test-only LOW-risk executor through request dispatch, including idempotency receipts, duplicate/replay rejection, and recovery when conversation persistence fails.
- **Path C:** prove a test-only consequential executor through the confirmation-decision endpoint, with exact scope, policy revalidation, single-use consumption, terminal-outcome recording, and replay rejection.

No blanket rule requires a LOW-risk operation to go through the confirmation endpoint. A production executor still requires a separate capability-specific review, acceptance evidence for its risk path, and its own commit. This design does not register one.

### G.8 - Out of scope for Stage 9.2

Not part of Stage 9.2, deferred to later stages:
- Registering a production executor.
- Implementing notes/tasks/reminders/retrieval.
- Integrating ROP reasoning through the conversation workflow.
- Any Stage 9.7 native-model work.

---

## H. Verification strategy and definition of done

### H.1 Test classes

**Unit-level (per component):**

- `test_authorization_policy.py` (existing, ~40 tests): policy
  decisions, identifier contract, material matching, fail-closed
  ordering. Must remain green.
- `test_authorization_dispatch.py` (existing, ~13 tests): dispatch
  boundary, non-`ALLOW` never dispatches, fail-closed, offline.
- `test_authorization_policy_identity.py` (existing): policy identity
  is deterministic and change-sensitive.
- `test_confirmation_flow.py` (existing, ~30 tests): challenge
  issuance, display-code verification, locking, races, expiry, replay.

**Integration-level (API):**

- `test_assistant_api.py` (existing, ~22 tests): endpoint paths,
  non-echo, no-conversation-does-not-touch-db, client cannot supply
  authorization.
- `test_assistant_persistence.py` (existing, ~16 tests): persistence
  atomicity, rollback, 409/503/404, no clinical coupling.
- `test_confirmation_records_api.py`, `test_confirmation_records_schema.py`
  (existing): record inspection/export/deletion.

**End-to-end behavioural (browser harness):**

- `test_conversations_ui_corrections.py` (existing, 110+ tests): UI
  behaviour across many scenarios.
- **New in Stage 9.2:** interaction-engine scenarios per G.1-G.6.

### H.2 Definition of done for Stage 9.2

Stage 9.2 is done when:

1. Every step in §G.1-G.6 is implemented, reviewed, and merged.
2. Every new status in §E.2 (if approved) has a passing test.
3. Every existing test remains green - no regressions.
4. The production executor registry remains empty.
5. No production capability beyond the design-approved set exists.
6. The browser UI handles every outcome the engine can produce.
7. A cross-flow integration test covers unsupported, refused,
   clarification, confirmation, and execution-failure paths end to
   end.
8. The documentation (this design and the implementation) has been
   reviewed together.

### H.3 Out of scope for Stage 9.2

- Registering any production executor.
- Adding notes/tasks/reminders/retrieval capabilities.
- Integrating ROP reasoning.
- Any change to the confirmation lifecycle itself.
- Any change to the conversation persistence contract beyond what
  Stage 9.2.x specifically requires.

---

## I. Stale docstrings and comments found during audit

The task prompt directed me to record stale documentation without
changing source code. The following comments are inconsistent with the
current code:

1. `src/rop/authorization/policy.py`, module docstring, line 48:
   > "This module is deliberately not wired into the assistant
   > request path."

   **False.** `assistant.py::_dispatch` and
   `authorize_capability_dispatch` both call `evaluate_authorization`.
   The policy evaluator is on every request's dispatch path.

2. `src/rop/authorization/policy.py`, module docstring, line 57:
   > "The end-to-end permission flow - obtaining, verifying, and
   > recording a user's confirmation - is not implemented here and is
   > not claimed."

   **Misleading in isolation.** The flow **is** implemented in
   `src/rop/services/confirmation.py` and `src/rop/api/confirmations.py`
   (Tasks 224/226/227). The docstring is technically about *this*
   module, but reads as if the flow does not exist anywhere.

3. `src/rop/authorization/dispatch.py`, module docstring, line 25:
   > "the browser confirmation UI remains unimplemented."

   **False.** Task 226 implemented the browser confirmation card. It
   is visible in `app.js` and covered by
   `test_conversations_ui_corrections.py`.

4. `src/rop/schemas/authorization.py`, module docstring, line 16:
   > "the browser controls that would surface it to the user remain
   > unimplemented."

   **False.** Same as #3.

**Recommendation:** these should be corrected in the implementation
step that first touches these modules (probably G.2 or G.5), in a
commit that is documented as "docstring correction, no behaviour
change." **Task 232 does not modify them** because the task prompt
explicitly scopes Task 232 to documentation-only and this design
document. The corrections are listed here so they are not lost.

Other `not claimed` hits in `src/rop/services/reasoning_run_*.py` are
legitimate reasoning-audit statements, not stale. They are **not** in
scope for correction.

---

## J. Decisions selected for delegated Stage 9 completion

The owner has delegated implementation of Stage 9 and the necessary design choices to the assistant. The selected approach is server-owned clarification state with bounded temporary input, selected-conversation binding, ten-minute expiry, and atomic single-use use; a two-path execution permit separating LOW-risk ALLOW from exact confirmed scope; and durable idempotency receipts before state-changing execution.

The initial request response may distinguish challenge-unavailable and synchronous LOW-risk failure/unknown outcomes. The existing confirmation-decision status enum remains unchanged. No production executor is registered during Stage 9.2. These decisions preserve the existing offline, privacy, deterministic selection, and clinical-domain separation boundaries.

## K. Proposed Stage 9.1 contract amendment

The corrected design requires the following amendments to the Stage 9.1
contract and to the initial assistant request/response schemas. Each
requires explicit owner approval before implementation begins. Until
approved, Stage 9.2 does not implement any of them.

### K.1 New AssistantRequest fields

- `clarification_id: UUID | None = None`: continuation for one active server-owned clarification. If absent, existing fresh-request behaviour is preserved.
- `idempotency_key: UUID | None = None`: required for state-changing execution and bound to the canonical operation fingerprint. This key grants no permission and cannot choose an executor.

### K.2 New AssistantResponse field: clarification_prompt

Present only when a real pending record has been created. Contains the server ID, capability identifier, question, and sanitized missing-field names. It never returns the original message or partial operation values. The first-party UI must use this structure to continue or restore the pending interaction.

### K.3 New AssistantStatus values

The current enum has five values. Three additions are proposed, all
scoped to Path B execution (the request endpoint) and the initial-
endpoint ambiguity between "challenge issued" and "challenge
unavailable":

- confirmation-unavailable - challenge could not be minted.
  Replaces the current confirmation-required with challenge == None
  case. Honest but is a backward-incompatible status addition.
- execution-failed - Path B executor ran and reported failure.
- execution-unknown - Path B executor ran but its outcome could not be
  established.

ConfirmationDecisionStatus (the confirmation-decision endpoint) is
unchanged. It already owns Path C execution outcomes with seven
existing statuses and this design does not touch that contract.

Backward-compatibility impact: any client that exhaustively matches
AssistantStatus must be updated. First-party clients: only web/static/
app.js. No known external clients.

### K.4 New table: pending_clarifications

Add a migration for a separate assistant-interaction state table: UUID primary key, unique clarification ID, non-null FK to `assistant_conversations.id` with `ON DELETE CASCADE`, capability identifier, bounded original message, minimized partial operation JSON, missing-field list, timestamps, and constrained status. Add indexes for unique ID lookup and bounded expiry cleanup. No foreign key or relationship to clinical reasoning tables.

### K.5 Temporary values, retention, and privacy

The original request and minimized partial-operation values are stored only to reconstruct a safe continuation. They expire after ten minutes and are deleted on resolution, abandonment, expiry, or conversation deletion. They are never logged, exported through confirmation-record controls, or returned to the client. Cleanup and deletion must be bounded and tested.

### K.6 Restore and abandonment endpoints

- `GET /api/assistant/clarifications?conversation_id=...` restores only the active sanitized prompt for that conversation.
- `DELETE /api/assistant/clarifications/{clarification_id}` explicitly abandons a pending clarification, guarded by local origin and bound to the selected conversation.
- A guessed ID cannot disclose another conversation's state.

### K.7 No-conversation path

The submit_request handler must not create a pending_clarifications
row when conversation_id is None. Instead it returns
clarification-required with a "select a conversation to continue"
message and no clarification_prompt. This preserves the existing
database-free contract; it is not itself an amendment, it is a design
decision that honours the existing contract.

### K.8 Risk-appropriate executor approval and recovery gate

A production executor is considered only after its capability and policy are reviewed. Path A needs non-mutation and policy evidence; Path B needs LOW-risk permit, idempotency receipt, direct dispatch and persistence-failure recovery tests; Path C needs exact-scope confirmation, policy revalidation, single-use consumption and terminal outcome tests through the confirmation-decision endpoint. A production executor is a separate reviewed commit.

### K.9 Design changes selected for implementation

The delegated Stage 9 work includes the clarification request/response fields, pending-clarification model/migration and restore/abandon endpoints, idempotency key and durable operation receipts, the separate low-risk/confirmed execution permit, and the three initial-request status additions `confirmation-unavailable`, `execution-failed`, and `execution-unknown`. The confirmation-decision status contract is unchanged.

Each change requires focused tests and cross-flow verification. If the implementation cannot preserve the guarantees in this design, the affected feature must remain disabled and be reported honestly.

## Closing note

This document is a **design**, not an implementation. The interaction
engine is **not implemented** by Task 232. The current endpoint will
continue to serve only the `help` capability, and the production
executor registry will remain empty, until the implementation steps
in §G are separately reviewed and merged.

The reviewer should treat every recommendation in §C, §D, §E, and §G
as subject to approval, not as decided by this document.
