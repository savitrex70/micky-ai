# Task 213 — Strict Model-Output Validation and Advisory Integration Adapter

The deterministic ROP reasoning and evidence chain remains authoritative and
is fully usable without a model. This document describes the narrow boundary
that turns untrusted Task 212 `InferenceResult` records into explicitly
**advisory-only** candidate-label suggestions.

## What the adapter accepts and returns

`AdvisoryAdapter.propose()` in `src/rop/inference/advisory.py` accepts:

- one validated `InferenceResult` (Task 212, raw logits — treated as untrusted
  even when the schema validates);
- one validated `NativeReasoningRequest` (Task 202), which supplies the only
  trusted identity and context binding;
- optionally one validated `NativeReasoningResult`, which is required for an
  admissible result and supplies the deterministic context gate;
- and was constructed with an explicit, schema-validated
  `AdvisoryClassLabelMapping` whose every label belongs to an approved label
  space supplied by the caller.

It returns a frozen, strict `AdvisoryAdapterResult` carrying the caller-bound
identity (`request_id`, `session_id`, `context_fingerprint`, plus the
`artifact_id` of the inference artifact used) and exactly one of:

- `admissible=True` with an `AdvisoryModelSuggestion`
  (`candidate_label`, `softmax_score`, `advisory_only: True`); or
- `admissible=False` with an explicit `AdvisoryRejectionReason`.

Structural problems (wrong types, forged records, wrong class count,
multi-row batches, detached deterministic identity) raise a sanitized,
typed `AdvisoryAdapterError`; they are never repaired, clamped, or
reinterpreted.

## Class-index to label mapping

The mapping is explicit configuration (`AdvisoryClassLabelMapping` in
`src/rop/schemas/advisory.py`): a versioned record of `(class_index, label)`
entries that must be unique, sorted, within the model's class count, and
drawn only from the caller-approved label space.

**Prerequisite status:** no production class-label mapping is approved by the
project at the time of writing. The adapter therefore never invents semantic
labels: without an approved mapping instance no suggestion can be produced,
and a winning class index the mapping does not declare fails closed with
`UNMAPPED_WINNING_CLASS`. Defining and approving a real mapping for a narrow
task is a prerequisite for any operational use of this adapter.

## Score semantics

`softmax_score` is a numerically stable softmax (max-subtraction, `fsum`
normalization) over the raw logits. Raw logits are not probabilities. The
softmax value is a bounded comparative score, **not** a calibrated confidence,
not a correctness likelihood, and not an assessed uncertainty. The canonical
and only accepted field is `softmax_score`; the legacy name
`softmax_probability` is not part of the contract and is rejected by schema
validation (`extra="forbid"`). The value remains a relative model-output
score rather than a real probability.

## Identity binding

`InferenceResult` carries no identity fields. The published result binds to
the validated `NativeReasoningRequest` supplied by the caller: this is
caller-supplied association established at the adapter boundary, not
model-derived identity. A deterministic context whose identity does not match
the request (different session, fingerprint, or request) is rejected as
detached, so a result from one case/session cannot be associated with another.
Model output can never overwrite context, session, source, or provenance
identity — the advisory contracts contain no fields that could carry them.

## Evidence references and provenance

A model-generated label is not evidence. The advisory suggestion contract
carries no evidence references at all, and the adapter never creates evidence
records, source references, provenance values, or evidence identifiers from
model output. Fabricated `provenance`/`evidence_ids` fields are rejected by
schema validation (`extra="forbid"`). The Task 202–205 evidence contracts are
unmodified.

## Contradiction, missing information, and abstention

Missing deterministic context yields a non-admissible result with
`CONTEXT_UNAVAILABLE`. A supplied context must pass the Task 202 schema checks
and match the request identity exactly. `CONTRADICTED`, `INSUFFICIENT`,
`UNAVAILABLE`, and `ABSTAINED` contexts make the suggestion non-admissible
with the corresponding explicit reason, regardless of the model score. Task
202 does not define an `UNKNOWN` status; a forged or unsupported status fails
schema validation and raises a sanitized contract error. The adapter never
resolves a contradiction by preferring the model's label, never infers a
positive claim from absent evidence, never converts unavailable input into
support, and never fabricates a substitute label. A `SUPPORTED` deterministic
context still yields only an advisory suggestion. The deterministic rejection
reason takes precedence over model mapping outcomes. The adapter never mutates
the deterministic result, the request, or the inference input.

## Output is advisory only

`AdvisoryModelSuggestion.advisory_only` is the literal `True`; there is no
field or status value implying certification, approval, clinical meaning,
evidence verification, release readiness, or authoritative truth. The
deterministic path remains authoritative and fully usable without a model.

## Tests

`tests/test_advisory_adapter.py` covers supported and rejected deterministic
statuses, missing/unavailable/invalid contexts, identity and fingerprint
binding, explicit mapping bounds and validation, unmapped classes,
single-row/class-count requirements, finite and extreme logits, stable score
semantics and tie-breaking, strict immutable schemas, evidence/provenance
fabrication attempts, non-mutation of inputs, and sanitized failures. No
trained artifact, network, or external dataset is required.
