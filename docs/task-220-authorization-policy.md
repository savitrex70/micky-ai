# Task 220 — Risk-Based Authorization Policy

A deterministic, independently testable authorization-policy foundation
for Micky AI. `evaluate_authorization()` in
`src/rop/authorization/policy.py` evaluates one proposed operation
against a versioned rule table and returns an immutable
`AuthorizationDecision` (`src/rop/schemas/authorization.py`) stating what
must happen next.

This is a policy evaluation, not a permission flow. It is not wired into
the assistant request path, it does not obtain or record a user's
confirmation, and nothing in the product is gated by it yet.

## What it decides

Four outcomes, each with exactly one stable reason code:

| Outcome | Meaning |
| --- | --- |
| `ALLOW` | Supported, sufficiently specified, and permitted by an explicit policy rule without additional confirmation. |
| `CLARIFY` | The operation could not be selected safely: the target or a required parameter is absent, so there is nothing to confirm. |
| `REQUIRE_CONFIRMATION` | Sufficiently specified, but explicit user permission for this exact operation is required first. |
| `DENY` | Unsupported, prohibited, unclassified, or unusable under the applicable policy. |

An outcome is a statement about what may happen next. It performs
nothing: no execution, no persistence, no logging, no model, no network.
Returning `ALLOW` does not carry out an operation, and returning
`REQUIRE_CONFIRMATION` does not raise a prompt.

## Fail-closed ordering

Rules are applied in a fixed order, and the most restrictive applicable
answer wins:

1. an unusable proposal is denied (`OPERATION_INVALID`);
2. an unregistered operation is denied (`OPERATION_UNSUPPORTED`);
3. a prohibited operation is denied (`OPERATION_PROHIBITED`), even when a
   matching authorization is supplied;
4. an operation whose rule carries no risk level is denied
   (`RISK_UNCLASSIFIED`), so missing risk information can never grant
   permission;
5. an under-specified operation requires clarification
   (`TARGET_MISSING`, `PARAMETER_MISSING`). This check precedes any
   confirmation decision, because confirming an operation that has not
   been specified is not valid authorization;
6. a `LOW`-risk operation is allowed (`ALLOWED_LOW_RISK`);
7. a `CONSEQUENTIAL` operation is allowed only against a supplied scope
   that covers it exactly (`ALLOWED_BY_AUTHORIZATION`); otherwise it
   requires a fresh decision (`AUTHORIZATION_REQUIRED` when nothing is
   supplied, `AUTHORIZATION_SCOPE_MISMATCH` when what is supplied is for
   something materially different).

Risk is never inferred. A rule's classification is either explicit or
the operation is denied.

## One-action scope

`AuthorizedScope` is a comparison input, not a credential. It cannot be
minted, signed, or verified here, and supplying one is an assertion by
the caller that the boundary owning the real permission interaction has
obtained authorization for precisely those material values. Coverage is
exact on operation, target, scope, and parameter set; nothing is
inferred, extended, or inherited. Comparing a parameter map ignores
order, and surrounding whitespace is not a material difference.

## Deliberate absences

- **No confirmation receipt.** This module defines no token, nonce,
  receipt, or confirmation record, and no policy result is treated as
  evidence that a user approved anything. The confirmation flow does not
  exist and is not simulated.
- **No enforcement.** A `DENY` or `REQUIRE_CONFIRMATION` outcome is only
  as strong as the code path that honours it. No such path exists today,
  so a decision cannot by itself stop or start anything. The evaluator is
  isolated on purpose rather than wired to a handler that would appear to
  enforce it.
- **No state-changing capability.** The default policy registers exactly
  one rule: `help`, the only registered capability, classified `LOW`
  because it changes nothing. No state-changing operation is registered,
  so `REQUIRE_CONFIRMATION` is not reachable through the default policy
  today. Its behaviour is defined and tested with explicit policy
  fixtures.
- **No derived permission.** The default rule table is written by hand
  and is deliberately not generated from the capability registry: a
  capability added later is denied as unsupported rather than silently
  inheriting permission. A test asserts this.

## Inputs and errors

`evaluate_authorization(operation, *, policy, authorized=None)` accepts a
`ProposedOperation` or a mapping, together with a policy and an optional
authorization. Both are re-validated on entry so a mutated instance
cannot pass as valid, and unknown fields are rejected.

A structurally broken policy, operation, or authorization raises
`AuthorizationPolicyError` with a stable `AuthorizationErrorCode`. Invalid
policy or operation *content* - a blank operation identifier, an
unclassified rule - is not an exception: it is a decision, so the caller
receives `DENY` or `CLARIFY` and never a silent success. Failure messages
carry only stable codes and never a target, parameter, or message value;
validation causes are suppressed rather than chained, so private input
cannot surface in a traceback.

An outcome that contradicts its own reason is unrepresentable: a decision
is constructed from its reason code, and the model validator rejects any
mismatch.

## Determinism

The same policy, operation, and supplied authorization always produce an
equal decision. Evaluation reads no clock, randomness, environment,
filesystem, database, or network, and it mutates none of its inputs. The
module imports no network, provider, or model facility.

## Tests

`tests/test_authorization_policy.py` asserts behaviour, not the existence
of a class. It covers: an allowed low-risk operation; consequential
operations requiring confirmation; a destructive operation that is
authorized only by an exact matching scope; missing and blank targets;
missing required parameters; confirmation of an under-specified operation
offering no authorization; an unclassified rule denied with and without a
supplied scope; unsupported and prohibited operations denied even with a
matching authorization; prohibition outranking missing specification;
case-sensitive identifier lookup; one-action scope across operation,
target, scope, and parameter set; `covers` failing closed for unusable
input; invalid policy, operation, and authorization input raising
sanitized errors without leaking values; contradictory decisions
rejected; frozen contracts; determinism and purity across repeated
evaluation; no database access; no outcome other than `ALLOW` permitting
execution; unchanged capability-registry behaviour; and a capability
added after the policy was written not silently inheriting permission.

No network, database, model, or real data is required.

## Not established

This work does not implement notes, reminders, memory, file modification,
external actions, or any other personal-assistant capability. It adds no
endpoint, no dependency, no migration, and no configuration. It does not
change clinical reasoning, evidence, audit, provenance, certification, or
session-identity semantics. It does not claim that the interface can
obtain, verify, or enforce a user's confirmation, and it resolves no
other Stage 9 owner decision.
