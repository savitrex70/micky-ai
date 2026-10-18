# Task 221 — Authorization at the Assistant Dispatch Boundary

Task 220 built a deterministic authorization evaluator and left it isolated.
This task connects it to the assistant request path so a matched capability
cannot answer unless the policy permits it. It remains the enforcement point
for `ALLOW`, `CLARIFY`, and `DENY`. As of Task 224 it is also the point where
`REQUIRE_CONFIRMATION` can hand off to the server-side confirmation workflow
rather than stopping with an unreachable message.

`authorize_capability_dispatch()` in `src/rop/authorization/dispatch.py` takes
the capability the deterministic registry already resolved and the explicitly
configured policy, and returns the response envelope for the request. The
capability's predefined response is selected only when the decision is
`ALLOW`.

The boundary itself still cannot obtain, record, or verify a user's
confirmation, and it does not claim to. Confirmation is not something the
dispatch boundary decides; when the policy requires it and an executor is
registered, the request endpoint delegates to a server-owned confirmation
service. That service is described in the next section.

## Order of operations

For `POST /api/assistant/requests`:

1. the strict request schema accepts only a `message`; unexpected fields are
   rejected with 422 rather than ignored;
2. the message is matched against the deterministic capability registry;
3. no match returns `unsupported-capability` and dispatches nothing;
4. a match is turned into a `ProposedOperation` carrying the capability's
   validated identifier — no target, no parameters, and no caller-supplied
   authorization;
5. the operation is evaluated against the configured policy;
6. the capability's predefined response is returned only for `ALLOW`;
7. `CLARIFY` and `DENY` return a non-success status and no capability
   response, and every failure to evaluate the policy at all falls back to a
   refusal;
8. `REQUIRE_CONFIRMATION` is handled by the confirmation workflow described
   below; if no executor is registered for the operation, or the origin
   check fails, or a challenge cannot be minted, the request still returns a
   non-success status and executes nothing.

The policy the endpoint consults is written down in
`src/rop/api/assistant.py` (`_POLICY`, the Task 220 default table). It is
deliberately not derived from the registry: registering a capability does not
authorize it, so a capability with no policy rule is refused as unsupported
rather than silently inheriting permission.

## The confirmation workflow (Task 224)

The confirmation workflow is a distinct component from the dispatch boundary.
Its purpose is to make a user's explicit approval of one specific operation
verifiable by the server, without trusting any client-supplied assertion. It
is implemented in:

- `src/rop/services/confirmation.py` — challenge issuance, decision handling,
  code verification, atomic consumption, and executor invocation.
- `src/rop/services/confirmation_recovery.py` — bounded, fail-closed startup
  recovery of any record whose execution outcome was not established.
- `src/rop/repositories/assistant_confirmation.py` — the durable record and
  its guarded SQL transitions.
- `src/rop/api/confirmations.py` — `POST /api/assistant/confirmations/{id}/decision`.
- `src/rop/authorization/executors.py` — the server-side executor registry
  that the confirmation service consults.

What the workflow establishes, in order, when a matched operation evaluates
to `REQUIRE_CONFIRMATION` and an executor is registered:

1. A challenge is minted only from a `REQUIRE_CONFIRMATION` decision that is
   re-checked inside the service. `ALLOW`, `CLARIFY`, `DENY`, an unevaluable
   policy, a missing executor, or a non-consequential rule never mint one.
2. The challenge record binds the exact stored operation (identifier, target,
   scope, parameter map), the effective policy identity from
   `authorization_policy_identity()`, the required risk level and reason, and
   the server-issued five-minute expiry. Only a salted hash of a short
   display code is stored; the plaintext code is returned once to the
   caller and never persisted or logged.
3. Challenge creation is gated by a loopback same-origin check that validates
   the request `Origin`, `Host`, and content type against a configured
   trusted local origin. This check runs before any record is written.
4. On a decision, the service acquires a row lock on the pending record and
   verifies: still pending, not expired at the *transition* instant (not at
   request start), display code match in constant time, and failure budget
   not exhausted. Failure counting and the atomic consumption share one
   transaction, so concurrent guesses cannot exceed the budget and concurrent
   confirmations cannot both win.
5. Policy revalidation is performed before consumption. The stored policy
   identity is recomputed from the currently loaded policy and compared; a
   mismatch invalidates the challenge rather than consuming it. The stored
   operation is then re-evaluated without scope (must still be
   `REQUIRE_CONFIRMATION`) and with a freshly constructed `AuthorizedScope`
   built from the stored values (must be `ALLOW`), and the scope must
   `covers()` the stored operation.
6. Consumption is one atomic compare-and-set that independently enforces the
   pending status, the transition-time expiry, and (on success) the stored
   policy identity. It is committed *before* the executor runs. A crash after
   the side effect cannot roll back consumption and allow replay.
7. The executor, if it runs, receives the canonical stored operation and the
   verified authorization, not any client-supplied value. A successful run
   records `SUCCEEDED`; an established failure records `FAILED` and is never
   retried; an unestablished outcome is labelled `UNKNOWN_AFTER_CONSUME` and
   is never automatically re-executed.
8. Cancellation, rejection, expiry, and invalidation all clear the display-code
   verifier and record `terminal_at`. A challenge is consumed at most once
   and never revived.

A caller interacting with the decision endpoint cannot supply an operation,
target, scope, parameters, an `authorized`/`confirmed` flag, or a policy
identity. The stored record is the authority for which operation is decided,
and the loopback origin check applies to every state-changing request.

### What is still absent by design

- **No production executor is registered.** `build_default_executor_registry()`
  returns an empty registry, so a `REQUIRE_CONFIRMATION` operation cannot
  execute in this build. An empty registry is not permission.
- **No production state-changing capability is registered.** The registry
  still contains only `help`.
- **No browser confirmation UI exists.** The server can mint and decide a
  challenge, but the interface does not yet surface a pending confirmation,
  its display code, or the Confirm/Cancel controls. That is a later task.

## Outcomes and statuses

| Policy outcome | Status | Behaviour |
| --- | --- | --- |
| `ALLOW` | `success` | The registered capability's predefined response is returned. |
| `CLARIFY` | `clarification-required` | Nothing is dispatched. The message states that nothing ran. |
| `REQUIRE_CONFIRMATION` | `confirmation-required` | When an executor is registered and the origin check passes, a durable challenge is minted and its display values are returned in the response's `challenge` field. When no executor is registered, or the challenge cannot be minted, the request returns this status with a static message and executes nothing. |
| `DENY` | `refused` | Nothing is dispatched, including when the operation is unclassified, prohibited, or absent from the policy. |
| Evaluation failure | `refused` | A policy or proposal that cannot be evaluated permits nothing, and the caller receives a static message with no exception text. |

`unsupported-capability` remains the status for a request that matches no
registered capability. The boundary itself can never produce it.

`src/rop/schemas/assistant.py` carries these five statuses in
`AssistantStatus`. Every status other than `success` means no state-changing
operation completed. A `confirmation-required` response is a request for the
user to decide the challenge; it is not evidence that the operation ran.

## The caller cannot assert authorization

The request schema accepts a message and nothing else. There is no
`authorized`, `confirmed`, `scope`, or `permission` field, and a request that
supplies one is rejected. The decision endpoint accepts only a `decision` and
an optional `display_code`; it rejects any attempt to supply an operation,
target, scope, parameter map, `authorized`, `confirmed`, or policy identity.
The stored record is the only source of what operation is being decided.

Two consequences follow:

- **No client-supplied assertion is treated as approval.** Approval is
  established server-side by the confirmation workflow, which re-checks the
  policy, verifies the display code in constant time, and consumes the
  challenge exactly once.
- **The execution boundary is server-owned.** Even with a valid confirmation,
  execution requires a registered server-side executor. No client can select,
  substitute, or supply one, and none is registered in this build.

## Fail-closed behaviour

- A capability the policy does not register is refused.
- An unclassified, prohibited, or under-specified operation is not dispatched.
- A malformed or forged capability identifier is refused; the boundary
  re-validates the proposal rather than trusting the registry.
- Any exception raised while evaluating the policy is caught, and the request
  is refused with a static message. No exception text, capability response,
  target, or user message reaches the caller.
- A challenge whose policy identity has changed, whose operation is no longer
  `REQUIRE_CONFIRMATION`, whose scope no longer covers the stored operation,
  or whose verification fails for any reason is not consumed and does not
  execute. Where the record can safely be updated, it is invalidated or
  expired; otherwise it remains `PENDING` until expiry.
- The dispatch boundary function itself touches no database, model, or
  network. The request endpoint's confirmation path persists a challenge
  through the repository; that is the only write it performs, and it stores
  no user message, no raw display code, and no unverified operation.

## Frontend

`src/rop/web/static/app.js` maps each status to its own wording. Only
`success` is described as a capability responding; the other four all state
that the request was not executed. Replies are written with `textContent`,
so nothing is rendered as HTML. No fake confirmation is displayed. The
`confirmation-required` response's `challenge` field is consumed by the
pending-confirmation card added in Task 226: when the server returns a
valid challenge, the page shows a card with the stored operation
summary, the display code, the expiry in local time, and Confirm/Cancel
actions. The card does not prefill the code input, does not
auto-confirm, does not store codes or confirmation state in
client-side storage, and blocks Enter inside the code field so a
stray keypress cannot submit a confirmation. A decision request is
sent to `POST /api/assistant/confirmations/{id}/decision` and the
outcome is reported honestly - success is only claimed when the
payload also establishes `executed: true`. The default executor
registry remains empty, so no production state-changing operation
can execute in this build.

## Tests

`tests/test_authorization_dispatch.py` asserts the boundary's security
behaviour with controlled policies and a spy on the response-selection step:
`ALLOW` dispatches exactly once; `CLARIFY`, `REQUIRE_CONFIRMATION`, `DENY`, an
unclassified rule, and a missing rule never reach it; a capability registered
after the policy was written is refused; a broken policy and an unexpected
evaluation error fail closed without leaking their detail; a forged malformed
identifier is refused; the boundary accepts no authorization argument; the
status mapping covers every non-`ALLOW` outcome and defaults to `refused`;
and no database or network facility is touched by the boundary.

`tests/test_confirmation_flow.py` covers the confirmation workflow end to
end: challenge issuance only for `REQUIRE_CONFIRMATION` with a registered
executor, binding to the exact operation and policy identity, constant-time
code verification, wrong-code counting and lockout, correct-code-on-fifth
success, concurrent confirmations producing at most one execution,
confirmation racing cancellation, transition-time expiry (including expiry
during policy evaluation), policy-identity change invalidating the
challenge, description-only policy edits leaving the challenge confirmable,
stored-value execution, missing-executor refusal, established-failure
recording, unknown-outcome recording, bounded recovery, and the absence of
any clinical-data coupling.

`tests/test_confirmation_recovery.py` covers bounded startup recovery of
unestablished outcomes and overdue pending challenges, rollback on
transaction failure, fail-closed behaviour when the database is unavailable,
and the lifespan wiring that invokes recovery once when the setting is
enabled (using a stub, no database required).

`tests/test_assistant_api.py` covers the wiring through the real handler: the
endpoint refuses a capability the policy does not permit, returns
`confirmation-required` and `clarification-required` for controlled
consequential capabilities without leaking their replies, does not echo the
matched user text in a refusal, and rejects requests that try to supply an
authorization, confirmation, scope, or permission assertion.

`tests/test_web.py` checks the served JavaScript maps every status to its own
distinct wording, that every non-success wording says the request was not
executed, and that replies are not rendered as HTML.

## Not established

This task does not implement notes, reminders, memory, file modification,
external actions, or any other state-changing capability, so no production
executor is registered and a `REQUIRE_CONFIRMATION` operation cannot execute
in this build. The server-side confirmation workflow that would consume a
user's approval is implemented; the browser confirmation card and the
Confirm/Cancel controls are not, so a user cannot yet decide a challenge
through the interface. The Stage 9 product contract remains a draft, and it
records that the server-side confirmation lifecycle is implemented while the
browser surface is not.
