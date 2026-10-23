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
   requires a non-blank printable `message` of 1-2000 characters, and
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

### C.1 When the engine must stop and ask

The engine must return `clarification-required` when, and only when:

1. A registered capability matched the request.
2. The capability requires a target, scope, or parameter that the
   request did not supply, OR
3. Two or more material readings of the request would lead to different
   operations, and the current deterministic parser cannot choose
   without inventing information.

The engine must **never**:

- Guess a missing target or parameter.
- Treat a subsequent "confirm" as clarification. A confirmation for an
  underspecified operation is not valid authorization.
  `test_authorization_policy.py::test_confirmation_of_an_underspecified_operation_is_not_authorization`
  proves this rule at the policy layer; the interaction engine must
  preserve it at the presentation layer.

### C.2 Representing a clarification response

`{status: "clarification-required", message: "<question>", ...}`.
Optionally a new `clarification_id` field, `clarification` object, or
similar, depending on the state approach chosen in C.4.

### C.3 Associating the follow-up with the pending interaction

The current endpoint has no way to associate a follow-up message with
a pending clarification. `AssistantRequest` carries only `message` and
an optional `conversation_id`. Adding a field like
`clarification_response_to` or reusing `conversation_id` for context
are both changes to the public schema.

### C.4 Interaction state - three viable options

The task explicitly requires resolving the state question. Three
options:

**Option 1 - Client-only (no persistence).**
The browser retains a "pending clarification" object in memory. When
the user sends the follow-up, the client attaches the pending
context. On reload or tab close, the pending state is lost, and the
user is shown a "clarification was pending but is no longer attached -
please restate your request" message.

- **Pros:** No schema change; no persistence semantic change; no
  migration; matches the existing `requestOutcomeUnresolved` /
  `challengeUnresolved` client-only guards in `app.js`.
- **Cons:** Does not survive reload; does not survive tab close; does
  not survive a browser crash. If `conversation_id` is set, the user
  can retype the request after reload, so failure is graceful but not
  silent.
- **Owner decision needed?** Only if the product wants reload-survival
  as a Stage 9.2 requirement. Otherwise no.

**Option 2 - Conversation-based (persist a non-terminal assistant
message).**
When the engine returns `clarification-required`, append a message to
the conversation (if one is selected) recording the pending question.
On the next turn, the engine inspects the most recent message; if it
was a `clarification-required` note from the assistant, the new user
message is treated as the answer to that clarification.

- **Pros:** Survives reload; reuses existing persistence; no migration.
- **Cons:** Changes the "only success persists" contract. Today's
  behaviour is that non-success turns are not saved; adding a
  persisted clarification question breaks that invariant. Requires an
  explicit Stage 9.1 contract amendment and owner approval.
- **Owner decision needed?** Yes. This is a product-contract change.

**Option 3 - New `pending_clarifications` table.**
Add a new table keyed by conversation_id, storing the pending
capability identifier and the specific fields the engine is waiting
for. Rows are cleared on resolution or expiry.

- **Pros:** Clean separation from messages; survives reload; does not
  change persistence semantics.
- **Cons:** New migration; new schema; new repository; new expiry
  logic (mirroring the confirmation record); more code to review.

**Recommendation for Stage 9.2:**

Implement **Option 1 (client-only) in Stage 9.2**. Rationale:

- It matches the existing `challengeUnresolved` pattern already used
  for pending confirmations.
- It requires no schema change, no migration, no contract amendment,
  no owner decision to begin.
- The failure mode is graceful: after reload, the user is told
  "clarification was pending but no longer attached - please restate"
  and retypes the request. For a locally-run single-user assistant
  this is acceptable.
- If reload-survival turns out to be a genuine user need, Option 2 or
  3 becomes a Stage 9.2.x follow-up with its own review.

**This is a recommendation, not a decision.** The reviewer should
either approve Option 1 as the Stage 9.2 choice or direct a different
option before any implementation begins. The task prompt's directive
to "present the viable choices, trade-offs, recommended approach, and
any product-contract decision required" is satisfied by naming the
choice and the decision it depends on.

### C.5 Anti-confusion safeguards

Regardless of which state option is chosen:

- The follow-up request must include enough information to prove it is
  an answer to a specific pending clarification, not an unrelated new
  request. Option 1 does this via an in-memory context; Option 2 via
  conversation ordering; Option 3 via a per-conversation pending-row.
- A stale clarification (e.g., the user has since performed a
  different operation, or the conversation was deleted) must be
  detected and rejected as a new request, not silently applied.
- The ambiguity guard (`requestOutcomeUnresolved` in `app.js`) must be
  extended to cover clarification state: starting a new request while
  a clarification is pending must be either allowed (with explicit
  "abandon the clarification" warning) or blocked, decided explicitly,
  not left to chance.

---

## D. Authorization and safe-execution contract

### D.1 Ordered boundary

The interaction engine must process any request through these steps in
order, with no step skippable:

1. **Capability selection.** `CapabilityRegistry.match`. No side
   effects.
2. **Building a validated proposed operation.** The capability's
   parser turns `message` (and any pending clarification) into a
   `ProposedOperation`. Existing operation: `help` has no target,
   scope, or parameters. Future operations must produce a `ProposedOperation`
   from **user-supplied** values, never from defaults.
3. **Required-information validation.** The policy evaluator checks
   `requires_target` and `required_parameters`. Missing values produce
   `CLARIFY`. This is already implemented in the policy; the interaction
   engine must feed it real values (not empty `{}`).
4. **Policy evaluation.**
   `evaluate_authorization(operation, policy=..., authorized=None)`.
   No caller-supplied authorization at this layer. `ALLOW`, `CLARIFY`,
   `REQUIRE_CONFIRMATION`, or `DENY`.
5. **Clarification or refusal.** `CLARIFY` → `clarification-required`;
   `DENY` → `refused`. Both mean nothing was executed.
6. **Confirmation where required.** `REQUIRE_CONFIRMATION` →
   `issue_challenge`. On `ISSUED`, return `confirmation-required` with
   the challenge values. On any other outcome, return
   `confirmation-unavailable` (see §E) - **never** pretend a challenge
   was issued. No capability's reply is returned at this step.
7. **Server-owned executor dispatch.** Only after `confirmation.decide`
   has consumed a challenge (`CONSUMED` status) is the executor
   reachable. The executor is chosen by the server-side
   `ExecutorRegistry`, never by the client. Result is `ExecutorResult.SUCCEEDED`
   or `FAILED`; `ExecutorInterrupted` means unknown.
8. **Outcome reporting and persistence.** `success` for completed
   operations. `execution-failed` for `FAILED`. `execution-unknown` for
   interrupted. Persistence is gated as today: only `success` turns
   persist as user/assistant pairs.

### D.2 Preserved constraints

- **Per-operation, risk-based authorization.** Preserved. No session-
  scoped authorization.
- **Confirmation covers the exact operation and material parameters.**
  Preserved. Material change → new decision. Proven by
  `test_authorization_policy.py::test_authorization_for_one_target_does_not_cover_another`
  and siblings.
- **Client is never trusted for authorization.** Preserved.
  `AssistantRequest` forbids extra fields; `dispatch.py` accepts no
  `AuthorizedScope`, `confirmed` flag, or caller-chosen executor.
- **No production executor registered in Stage 9.2.** Enforced. Task
  232 does not register one; nor should Stage 9.2.x implementation.

### D.3 Integration with future capabilities

Future notes/tasks/reminders capabilities must:

- Register their `Capability` in the registry (aliases).
- Register an `OperationRule` in the policy (risk, required target/
  parameters).
- Register an `Executor` in the executor registry **only after** the
  capability has been independently reviewed and approved (a separate
  owner decision per capability).

None of these three can be inferred from the others. A test-only
executor remains the only way to exercise the `REQUIRE_CONFIRMATION`
path in Stage 9.2.

---

## E. Truthful outcome contract

### E.1 Current five statuses vs required cases

| Required case | Current status | Notes |
|---|---|---|
| Successful response / completed operation | `success` | OK for `help`-style capabilities. |
| Unsupported capability | `unsupported-capability` | OK. |
| Clarification required | `clarification-required` | OK. |
| Confirmation required and successfully issued | `confirmation-required` + `challenge != None` | OK. |
| Confirmation unavailable | `confirmation-required` + `challenge == None` | **Overloaded.** A status-only reader cannot distinguish "show card" from "cannot show card". |
| Refusal by policy | `refused` | OK. |
| Valid operation that fails (executor error) | **Absent.** | Today unreachable (no prod executor), but must exist before any executor is registered. |
| Operation whose outcome cannot be established (interrupted) | **Absent.** | Same. |
| Internal or persistence failure | HTTP 5xx with `detail` (not a status envelope) | The exchange was answered; only the save failed. A distinct envelope status would be honest to the client, but the current HTTP-error approach is defensible because the response has already been produced. |
| Execution succeeded but persistence failed | HTTP 5xx (`_ERROR_SAVE_FAILED`) | Same as above. |

### E.2 Recommended envelope evolution (design only)

For Stage 9.2.x, when a production executor is eventually considered,
the envelope needs at minimum:

- `execution-failed` - status for `ExecutorError`. Response carries
  `message` only. No challenge.
- `execution-unknown` - status for `ExecutorInterrupted` or unexpected
  executor exception. Response carries `message` and, if a
  `challenge_id` was consumed, that ID so the browser can show
  "outcome unknown; inspect confirmation records".
- `confirmation-unavailable` - status distinct from
  `confirmation-required`. Response carries `message` only; no
  `challenge` field. **This is the schema change that most clearly
  fixes an ambiguity.**

Persistence failures do **not** need a new envelope status: the HTTP
5xx path already truthfully communicates "answered but not saved" via
the `detail` message, and it is orthogonal to the operation's own
outcome.

### E.3 Compatibility and migration

Adding new statuses is backward-incompatible for any client that
exhaustively matches `AssistantStatus`. The current browser
`describeStatus` function and any client code must be updated in the
same change that adds the new statuses.

**No schema change is performed by Task 232.** The recommendation is
documented for the Stage 9.2.x implementation review. The reviewer
should explicitly approve or reject adding `execution-failed`,
`execution-unknown`, and `confirmation-unavailable`.

### E.4 Truthful-outcome invariants

Regardless of status additions:

- **A request is never a success merely because it was accepted,
  matched, attempted, or confirmed.** Only `success` with a
  `capability_reply` is a success.
- **Execution failure is never reported as `success`.** The
  `ExecutorResult` contract enforces this: `ExecutorError` is
  established failure, `ExecutorInterrupted` is unknown outcome,
  neither may produce `success`.
- **Unknown outcome is never reported as `refused` or `failed`.**
  `refused` means "not attempted due to policy"; `execution-failed`
  means "attempted and failed"; `execution-unknown` means "attempted
  and cannot be established". These are distinct.
- **Confirmation requirement is never inferred from a challenge
  existing.** A challenge exists only when `issue_challenge` succeeded.

---

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

### G.2 - `CapabilityParser` contract

**Intended behaviour:** introduce a `CapabilityParser` protocol that
each capability uses to turn `(message, pending_clarification)` into a
`ProposedOperation`. `help` and the `status` capability both use a
trivial parser that produces `ProposedOperation(operation_id=capability.identifier)`.

**Modules:** new `src/rop/capabilities/parser.py` (or similar);
`capabilities/registry.py` (extend `Capability` to optionally carry a
parser); `api/assistant.py` (`_dispatch` calls the parser).

**Dependencies:** G.1.

**Failure/security cases:** a parser that raises on malformed input
must map to `clarification-required` (not 500). A parser that
produces a `ProposedOperation` with a wrong `operation_id` must be
refused by the policy.

**Tests:** unit tests for the trivial parser; integration test proving
a capability with a bad parser returns `clarification-required` (or
`refused`), not `success`.

**Acceptance:** the parser contract is documented and the two existing
capabilities pass through it unchanged.

**Compatibility:** no schema change; no browser change.

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

## Closing note

This document is a **design**, not an implementation. The interaction
engine is **not implemented** by Task 232. The current endpoint will
continue to serve only the `help` capability, and the production
executor registry will remain empty, until the implementation steps
in §G are separately reviewed and merged.

The reviewer should treat every recommendation in §C, §D, §E, and §G
as subject to approval, not as decided by this document.
