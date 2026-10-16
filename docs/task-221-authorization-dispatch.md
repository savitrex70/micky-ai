# Task 221 — Authorization at the Assistant Dispatch Boundary

Task 220 built a deterministic authorization evaluator and left it isolated.
This task connects it to the assistant request path so a matched capability
cannot answer unless the policy permits it.

`authorize_capability_dispatch()` in `src/rop/authorization/dispatch.py` takes
the capability the deterministic registry already resolved and the explicitly
configured policy, and returns the response envelope for the request. The
capability's predefined response is selected only when the decision is
`ALLOW`.

This is dispatch enforcement, not a permission flow. The boundary cannot
obtain, record, or verify a user's confirmation, and it does not claim to.

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
7. every other outcome, and every failure to evaluate the policy at all,
   returns a non-success status and no capability response.

The policy the endpoint consults is written down in
`src/rop/api/assistant.py` (`_POLICY`, the Task 220 default table). It is
deliberately not derived from the registry: registering a capability does not
authorize it, so a capability with no policy rule is refused as unsupported
rather than silently inheriting permission.

## Outcomes and statuses

| Policy outcome | Status | Behaviour |
| --- | --- | --- |
| `ALLOW` | `success` | The registered capability's predefined response is returned. |
| `CLARIFY` | `clarification-required` | Nothing is dispatched. The message states that nothing ran. |
| `REQUIRE_CONFIRMATION` | `confirmation-required` | Nothing is dispatched, and the message says confirmation is not available through this interface yet. |
| `DENY` | `refused` | Nothing is dispatched, including when the operation is unclassified, prohibited, or absent from the policy. |
| Evaluation failure | `refused` | A policy or proposal that cannot be evaluated permits nothing, and the caller receives a static message with no exception text. |

`unsupported-capability` remains the status for a request that matches no
registered capability. The boundary itself can never produce it.

`src/rop/schemas/assistant.py` carries these five statuses in
`AssistantStatus`. Every status other than `success` means no operation was
performed and nothing was saved.

## The caller cannot assert authorization

The request schema accepts a message and nothing else. There is no
`authorized`, `confirmed`, `scope`, or `permission` field, and a request that
supplies one is rejected. The boundary exposes no parameter through which an
`AuthorizedScope` or any other permission assertion could be passed, so it
cannot be talked into treating a request as approved.

Two consequences follow, and both are deliberate:

- **No confirmation receipt exists.** Nothing is minted, signed, or accepted
  as proof that a user agreed to anything.
- **A consequential capability could not yet run even if it existed.** With no
  confirmation interaction, `REQUIRE_CONFIRMATION` is terminal: the response
  says the operation was not executed, and there is no way to change that
  through this interface.

## Fail-closed behaviour

- A capability the policy does not register is refused.
- An unclassified, prohibited, under-specified, or confirmation-requiring
  operation is not dispatched.
- A malformed or forged capability identifier is refused; the boundary
  re-validates the proposal rather than trusting the registry.
- Any exception raised while evaluating the policy is caught, and the request
  is refused with a static message. No exception text, capability response,
  target, or user message reaches the caller.
- The boundary touches no database, model, or network, and it records nothing.

## Frontend

`src/rop/web/static/app.js` maps each status to its own wording. Only
`success` is described as a capability responding; the other four all state
that the request was not executed. Replies are written with `textContent`,
so nothing is rendered as HTML. No approval button, no fake confirmation, and
no claim that the user authorized anything is displayed, because no such
confirmation can be obtained yet.

The page notice was corrected as part of this task: it previously said every
request returns `unsupported-capability`, which stopped being true when the
`help` capability was registered.

## Tests

`tests/test_authorization_dispatch.py` asserts the boundary's security
behaviour with controlled policies and a spy on the response-selection step:
`ALLOW` dispatches exactly once; `CLARIFY`, `REQUIRE_CONFIRMATION`, `DENY`, an
unclassified rule, and a missing rule never reach it; a capability registered
after the policy was written is refused; a broken policy and an unexpected
evaluation error fail closed without leaking their detail; a forged malformed
identifier is refused; the boundary accepts no authorization argument; the
status mapping covers every non-`ALLOW` outcome and defaults to `refused`;
and no database or network facility is touched.

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
external actions, or any other state-changing capability, so the boundary has
nothing protected to gate yet and `REQUIRE_CONFIRMATION` is reachable only
through test policies. It does not implement the interaction that obtains a
confirmation, does not record one, and does not expose any endpoint that
accepts an authorization assertion. The Stage 9 product contract remains a
draft: it records that dispatch now consults the policy while the confirmation
workflow stays pending.
