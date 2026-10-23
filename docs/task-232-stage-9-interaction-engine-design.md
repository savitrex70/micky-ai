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

### C.2 Wire protocol

The corrected design requires three coordinated changes.

**New optional field on AssistantRequest:**

    clarification_id: UUID | None = None

When present, message is the answer to the identified pending question,
not a fresh request. When absent, behaviour is unchanged.

**New optional field on AssistantResponse:**

    clarification_prompt: ClarificationPrompt | None = None

    class ClarificationPrompt(BaseModel):
        model_config = ConfigDict(extra="forbid")
        clarification_id: UUID
        capability_identifier: str
        question: str
        missing_fields: list[str]  # sanitized field names, not user values

Present only when status == "clarification-required". Carries the
server-issued clarification_id (unguessable, high-entropy UUID), the
matched capability identifier, a user-facing question, and the missing
field names - but never the user's original input, never a
pre-approved authorization, never an executor name.

**New server-side state: pending_clarifications table** (or equivalent
server-owned store, modeled on assistant_confirmations). Fields:

- id (primary key, UUID)
- clarification_id (unique, indexed, unguessable - the wire value)
- conversation_id (nullable; see C.4)
- capability_identifier
- missing_fields (JSON array of field names)
- created_at
- expires_at (a bounded window, e.g. 10 minutes)
- resolved_at (nullable, set on consumption)
- resolved_by_operation_id (nullable; the operation identifier the
  follow-up produced, for audit)

Rows are created when _dispatch decides CLARIFY, consumed when the
follow-up resolves or is abandoned, and cleared on:

- successful resolution
- explicit abandonment (see C.5)
- expiry
- conversation deletion (via app-level cleanup, not a DB-level FK
  cascade, to preserve the conversation/clinical separation invariant)

### C.3 Full clarification flow

1. **Initial request.** Client sends {message, conversation_id?}.
   submit_request runs as today until the policy returns CLARIFY. At
   that point, instead of returning {status:
   "clarification-required", message: ...} with no context, the
   endpoint now:

   - creates a pending_clarifications row with a fresh
     clarification_id,
   - returns {status: "clarification-required", message: ...,
     clarification_prompt: {clarification_id, capability_identifier,
     question, missing_fields}}.

2. **User answers.** Client sends {message: "<the answer>",
   conversation_id?, clarification_id}. submit_request detects
   clarification_id is not None and routes to a clarification-
   resolution path that:

   - loads the pending row by clarification_id; 404 if absent or
     expired,
   - verifies conversation_id matches the pending row's
     conversation_id (both must be set, or both must be None),
   - re-runs the capability's parser with the combined input (original
     message + answer); NOT through CapabilityRegistry.match, which
     would fail,
   - produces a fresh ProposedOperation from the combined input,
   - re-runs evaluate_authorization on the fresh operation (mandatory:
     no pre-approved authorization from the initial turn carries
     forward),
   - on ALLOW / REQUIRE_CONFIRMATION: proceeds per D.1 Path A/B/C as
     normal,
   - on CLARIFY again: mints a NEW pending row and returns a NEW
     clarification_prompt (the previous row is consumed, since a new
     clarification replaces it),
   - on DENY: returns refused and consumes the pending row,
   - on clarification_id failure (not found, expired, conversation
     mismatch): returns {status: "clarification-required", message:
     "the pending clarification is no longer active; restate your
     request"}; no new pending row created.

3. **Combined input persistence.** If the eventual combined request
   produces success, the persisted user/assistant pair is
   (original_message + " " + answer) and capability_reply (or the
   executor's success message for Path B). The pending-clarification
   row is a separate domain and is NOT persisted as a conversation
   message; only the successful exchange is.

### C.4 No-conversation path

The pending_clarifications table is only relevant when a
conversation_id is present. The no-conversation path must remain
database-free per the approved Stage 9.1 contract.

**Recommended behaviour:** when conversation_id is None and the
capability would need clarification, return {status:
"clarification-required", message: "<capability> requires a
conversation to complete this request. Select or create a conversation
first."} WITHOUT creating a pending row and WITHOUT a
clarification_prompt. This preserves the DB-free invariant. The user
must select a conversation, restate the request, and answer the
clarification there.

This is a real UX cost: a request that would need clarification cannot
be continued without a conversation. It is honest, preserves the
existing DB-free contract, and is the cheapest correct option. The
alternative - making pending_clarifications work without a
conversation - would break the DB-free contract and require a separate
owner decision.

### C.5 Edge cases

- **Conversation switch during clarification.** The follow-up request
  has a different conversation_id than the pending row. The resolution
  path detects the mismatch, consumes the pending row, and returns
  {status: "clarification-required", message: "the pending
  clarification was attached to a different conversation; restate your
  request in the current conversation"}. No executor runs; no policy
  evaluation runs on the mixed-conversation request.

- **Page reload during clarification.** The pending row persists on
  the server; the browser loses its in-memory clarification_id. On
  next page load the browser has no way to continue the pending row
  automatically. The row expires naturally. A future enhancement could
  expose a GET /api/assistant/clarifications?conversation_id=... to
  let the browser restore the pending prompt on load; that is out of
  scope for Stage 9.2 but flagged for later consideration.

- **Explicit abandonment.** A new DELETE
  /api/assistant/clarifications/{clarification_id} endpoint (small,
  mirrors the confirmation-record deletion precedent at
  src/rop/api/confirmation_records.py) lets the client discard a
  pending clarification. Without this, abandoned rows expire after the
  timeout window. Include this endpoint in Stage 9.2 scope, not as an
  afterthought.

- **Stale clarification_id.** A follow-up referencing an expired or
  already-resolved row returns {status: "clarification-required",
  message: "the pending clarification is no longer active; restate
  your request"}, no new pending row created, no ambiguity guard
  cleared. This is a stale-continuation outcome, distinct from a
  parser failure and distinct from a policy refusal.

- **Persistence of the eventual successful turn.** Covered in C.3
  step 3.

- **Authorization revalidation.** Every follow-up re-derives
  ProposedOperation from scratch and re-runs evaluate_authorization.
  The pending row does not carry a pre-approved authorization. This
  prevents a user from "clarifying" into an operation that would not
  have been ALLOWed if requested directly.

- **Executor choice.** Path B executors are chosen server-side via
  ExecutorRegistry.get(operation_id) after the re-evaluated policy
  returns ALLOW. The clarification_id field on the request has no
  bearing on which executor is chosen; it is only used to locate the
  pending row.

### C.6 Options considered and rejected

- **Client-only state (the previous recommendation).** Rejected: (a)
  the server cannot verify the client's claim about which pending
  clarification is being answered; (b) the follow-up cannot match a
  registered alias; (c) a client could lie.

- **Conversation-message persistence (a persisted "clarification
  question" assistant message).** Rejected: it changes the "only
  successful exchanges persist as user/assistant pairs" contract by
  storing an extra assistant message. A dedicated
  pending_clarifications table keeps the pending state in its own
  domain, like assistant_confirmations.

- **Continuation payload (client re-sends the whole combined message
  plus a hint).** Rejected: the server has no way to distinguish "I am
  answering the reminder clarification" from "I am making a new
  request", so a client could replay the same combined message as a
  fresh request and get a different decision. A server-issued
  clarification_id prevents replay.

- **Reuse conversation_id as the pending identifier.** Rejected: the
  conversation may have multiple pending clarifications across
  capabilities; conflating the two loses the mapping between answer
  and question.

- **Fuzzy matching on the follow-up.** Rejected: the Stage 9.1
  contract explicitly forbids fuzzy matching, substring matching, and
  model-based intent inference. The wire protocol above works with
  exact matching.

### C.7 Contract amendment required

The corrected design requires a Stage 9.1 contract amendment, fully
documented in Section K:

- New optional clarification_id field on AssistantRequest.
- New ClarificationPrompt response field.
- New pending_clarifications table (migration).
- New DELETE /api/assistant/clarifications/{id} endpoint.
- New behaviour: AssistantRequest with clarification_id routes to
  clarification resolution, not fresh selection.
- New behaviour: no-conversation requests that would need
  clarification return a "select a conversation" message without a
  pending row.

Every amendment is backward-compatible for existing clients that do
not send clarification_id; their behaviour is unchanged.



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

A future notes/tasks/reminders capability chooses its path by the risk
classification of each operation:

- A read-only "list notes" operation → Path A.
- A "create note" operation → likely Path B (LOW risk, no
  confirmation).
- A "delete all notes" operation → Path C (CONSEQUENTIAL, requires
  confirmation).

**Registering the executor is a separate owner decision per
capability**, not bundled with the capability's initial registration.
This preserves the three-way independence documented in §B.4:

- Registering a capability does not authorize it.
- Authorizing a capability does not give it an executor.
- Registering an executor does not register a capability.



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

The interaction engine builds on the existing conversation/message
API and UI:

- Requests without a `conversation_id` remain database-free. This is
  preserved by the current `submit_request` structure and by
  `test_assistant_persistence.py::test_no_conversation_does_not_touch_db`.
- With a `conversation_id`, the persistence precheck verifies the
  conversation exists before any dispatch. This preserves the
  "selected conversation is real" contract.
- Successful turns persist as an atomic user/assistant pair. The
  engine must not change this.
- **Clarification state, if persisted, must go through an explicitly
  reviewed contract.** Under the recommended Option 1 (client-only),
  no clarification state is persisted, so the existing "only success
  persists" contract is unchanged.
- **Conversation identifiers never touch clinical reasoning records.**
  No FK, no shared ID, no join.

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

### F.5 Owner decisions still required

The only genuinely open owner decision surfaced by this design is
**C.4: which clarification-state approach to adopt**. Option 1
(client-only) is recommended because it requires no schema change and
no contract amendment. Option 2 or 3 requires an explicit owner
decision to amend either the "only success persists" contract
(Option 2) or add a new persistence table (Option 3).

---

## G. Implementation sequence

Proposed Stage 9.2 implementation steps. Each is small, independently
reviewable, and preserves the production executor registry being
empty. Each step ends with green tests and a design review, not an
automatic merge.

### G.1 - Non-`help` capability with no required parameters

**Intended behaviour:** register a second capability (e.g. `status`)
that requires no target, no scope, and no parameters, and is `LOW`
risk. It returns a static reply. This exercises the "selection →
policy → reply" path end to end with a non-`help` capability.

**Modules:** `capabilities/registry.py` (add alias set),
`authorization/policy.py` (`DEFAULT_POLICY_RULES` add one rule),
`api/assistant.py` (no change needed).

**Dependencies:** none.

**Failure/security cases:** policy does not contain the new rule →
refused. Registry contains the alias but policy does not → refused
(the independence property).

**Tests:** `test_assistant_api.py` extended to cover the new
capability's aliases; `test_authorization_dispatch.py` extended to
prove the new capability flows through `authorize_capability_dispatch`.

**Acceptance:** a new alias returns `success` with the correct reply;
an alias without a policy rule returns `refused`.

**Compatibility:** no schema change; no browser change needed (browser
already handles `success`).

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

### G.3 - Clarification workflow (client-only per §C.4)

**Intended behaviour:** a capability that requires a target
(e.g., a hypothetical `echo` with a `target` field) returns
`clarification-required` when the target is absent. The browser
retains the pending clarification in memory. The follow-up message is
sent with the pending context; the parser sees the follow-up plus
context and either resolves or escalates.

**Modules:** `capabilities/registry.py`, `capabilities/parser.py`,
`api/assistant.py`, `web/static/app.js`,
`web/static/index.html` (if a "clarification pending" indicator is
added).

**Dependencies:** G.2.

**Failure/security cases:** stale pending clarification after
conversation switch (reject). Pending clarification after reload
(graceful degradation: "please restate").

**Tests:** new scenario in `tests/conversations_ui_harness.cjs`
covering: request → `clarification-required` → follow-up →
`success`. And: `clarification-required` → switch conversation →
follow-up → `unsupported-capability` or fresh selection, not silently
applied.

**Acceptance:** the browser retains and correctly attaches the pending
clarification; a switch or reload does not mis-apply it.

**Compatibility:** no API change (follow-up is a new request); browser
change required.

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

### G.5 - Envelope extension for executor outcomes

**Intended behaviour:** add the three new statuses discussed in §E.2
(`execution-failed`, `execution-unknown`, `confirmation-unavailable`).
Update the browser's `describeStatus` to handle them. Extend the
`AssistantResponse` model to allow (but not require) an optional
`challenge_id` on `execution-unknown` for correlation with the
confirmation record.

**Modules:** `schemas/assistant.py`, `authorization/dispatch.py`
(dispatch outcome mapping), `api/assistant.py` (challenge-unavailable
branch), `web/static/app.js`.

**Dependencies:** reviewer approval for the schema change.

**Tests:** new tests for each new status; updated browser tests.

**Acceptance:** every outcome path the interaction engine can take
maps to an honest status.

**Compatibility:** backward-incompatible for any client that
enumerates all statuses. Must be coordinated across all first-party
clients.

### G.6 - Cross-flow integration test

**Intended behaviour:** a behavioural test that exercises every path
in one harness run: unsupported, policy refused, clarification
(client-only), confirmation (test-only executor), and execution-failed
(test-only executor). Verify each status, each message, and each
persistence outcome.

**Modules:** `tests/conversations_ui_harness.cjs`,
`tests/test_assistant_*.py`.

**Dependencies:** G.1-G.5.

**Tests:** this test *is* the test.

**Acceptance:** every enumerated path is demonstrably reachable and
honestly reported.

**Compatibility:** no production change.

### G.7 - Executor approval-gate documentation

**Intended behaviour:** document the process by which a specific
production executor is approved. This is not implementation; it is a
review-gate description that Stage 9.3+ will use.

**Modules:** `docs/task-232-*.md` update, or a new
`docs/executor-approval-process.md`.

**Dependencies:** none.

**Acceptance:** the process is written down and referenced by the
Stage 9.3 design.

**Compatibility:** no change.

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

## J. Summary of open decisions

**For the reviewer to decide before Stage 9.2 implementation begins:**

1. **§C.4 - Clarification state.** Option 1 (client-only, recommended)
   or Option 2 (conversation-based, requires contract amendment) or
   Option 3 (new table, requires migration). This is the single open
   owner decision.

2. **§E.2 - Envelope extension.** Approve, modify, or reject adding
   `execution-failed`, `execution-unknown`, and
   `confirmation-unavailable` as distinct statuses. Without these, the
   eventual executor path cannot honestly distinguish three different
   outcomes.

**Not open decisions (already resolved by Stage 9.1):**

- The roadmap is fixed (§B.3 of the Stage 9 contract).
- The UI is the existing FastAPI + vanilla-JS interface (H.1).
- Conversation/clinical separation is fixed (H.1).
- Reminder defaults (H.3) and retrieval/offline defaults (H.4) are
  approved at the default level; their implementation detail is
  deferred to Stage 9.4/9.5.

---

## K. Proposed Stage 9.1 contract amendment

The corrected design requires the following amendments to the Stage 9.1
contract and to the initial assistant request/response schemas. Each
requires explicit owner approval before implementation begins. Until
approved, Stage 9.2 does not implement any of them.

### K.1 New AssistantRequest field: clarification_id

    clarification_id: UUID | None = None

- Optional. When present, message is the answer to the identified
  pending clarification, not a fresh request.
- When absent, behaviour is unchanged.
- Backward compatible for existing clients that do not send this
  field; they continue to see today's behaviour.
- Existing test test_assistant_api.py::test_unexpected_fields_rejected
  still passes because clarification_id is now a declared field, not an
  unexpected one.

### K.2 New AssistantResponse field: clarification_prompt

    clarification_prompt: ClarificationPrompt | None = None

- Present only when status == "clarification-required".
- Backward compatible: existing clients that read status and message
  continue to work. The message field carries a human-readable string;
  clarification_prompt carries the machine-readable structured
  payload.
- New ClarificationPrompt model carries: clarification_id, capability_
  identifier, question, missing_fields. No user values, no policy
  identity, no executor name.

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

New migration. Fields as documented in C.2.

- No foreign key to assistant_conversations (to preserve domain
  separation; app-level cleanup on conversation delete, not DB cascade).
- No foreign key to clinical reasoning tables.
- Indexed unique column on clarification_id for O(1) lookup by the
  wire value.

### K.5 New persistence domain: pending clarifications

- NOT part of conversation persistence ("only successful turns
  persist" unchanged).
- Cleared on resolution, abandonment, expiry, or conversation delete.
- Not exported in confirmation-record inspect/export (separate domain).
- Stored values: field names only (never user values), capability
  identifier, conversation_id, timestamps. No secrets, no display
  codes, no policy fingerprints.

### K.6 New endpoint: DELETE /api/assistant/clarifications/{id}

Small endpoint mirroring the confirmation-record deletion precedent.
Lets the client discard a pending clarification explicitly. Requires
local-origin guard on the state-changing act, matching the existing
enforcement pattern (enforce_local_origin).

Backward compatible: new endpoint, no existing client affected.

### K.7 No-conversation path

The submit_request handler must not create a pending_clarifications
row when conversation_id is None. Instead it returns
clarification-required with a "select a conversation to continue"
message and no clarification_prompt. This preserves the existing
database-free contract; it is not itself an amendment, it is a design
decision that honours the existing contract.

### K.8 Executor registration approval process

A new documented process (Step G.7). Registering a production executor
requires all of:

- Capability already reviewed and registered.
- Policy rule already reviewed and registered.
- Executor reviewed separately as a distinct change.
- Executor tested end-to-end against the confirmation-decision
  endpoint before merge.
- Production executor registry updated only after all four are
  approved and merged.

This codifies the existing three-way independence (Section B.4) as an
explicit gate. It does not itself register an executor; the production
build_default_executor_registry() continues to return an empty
registry until a specific executor is separately approved.

### K.9 Summary of amendments needing owner approval

Before Stage 9.2 implementation begins, the reviewer must approve or
reject:

1. New optional clarification_id field on AssistantRequest (K.1).
2. New optional clarification_prompt field on AssistantResponse (K.2).
3. Three new AssistantStatus values: confirmation-unavailable,
   execution-failed, execution-unknown (K.3).
4. New pending_clarifications table and migration (K.4).
5. New DELETE /api/assistant/clarifications/{id} endpoint (K.6).
6. Executor registration approval process as documented (K.8).

If any is rejected, the corresponding design section must be revised
before implementation begins. Task 232 does not perform any of these
changes.


## Closing note

This document is a **design**, not an implementation. The interaction
engine is **not implemented** by Task 232. The current endpoint will
continue to serve only the `help` capability, and the production
executor registry will remain empty, until the implementation steps
in §G are separately reviewed and merged.

The reviewer should treat every recommendation in §C, §D, §E, and §G
as subject to approval, not as decided by this document.
