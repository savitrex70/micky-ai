"""Task 141: deterministic replay API consistency audit contract.

The strict read-only audit response for one exact session's persisted
replay-related receipt material. Follows the established Task 135/139
audit convention (``available`` / ``audit_consistent`` / ``session_id``
/ issue list / ``audit_source``) extended with an explicit
``replay_state`` so the three required outcomes are never conflated:
``NO_MATERIAL`` (no persisted material exists to audit),
``INCONSISTENT`` (material exists and contradicts the canonical Task
128 replay contract), and ``MALFORMED`` (material exists but is
structurally unverifiable). ``SATISFIED`` covers persisted material
that verifies cleanly.

The audit reports only on evidence that actually exists in the
current persistence architecture. No ORM internals, no database
details, no provider/model information.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReasoningRunReplayConsistencyFindingRead(BaseModel):
    """One audited receipt's replay-contract verdict.

    ``receipt_id`` and ``input_fingerprint`` identify the persisted
    material exactly as historical evidence. ``replay_issues`` is the
    deterministic sorted set of replay-contract invariant violations
    (empty exactly when ``replay_consistent`` is true).

    ``replay_state`` is the per-material verdict over persisted
    material only: ``SATISFIED`` (verifies cleanly against the
    canonical replay contract), ``INCONSISTENT`` (structurally
    readable but contract-violating -- e.g. a session identity or
    exogenous projection that contradicts the receipt's own bound
    snapshot), or ``MALFORMED`` (structurally unverifiable -- e.g. a
    malformed fingerprint or an absent/ill-typed input snapshot, so the
    canonical contract cannot even be evaluated).

    ``replay_contract_finding`` names which canonical Task 128 replay
    invariant the material would trip, reusing the existing contract
    vocabulary rather than inventing new verdicts:
    ``PERSISTED_MATERIAL_VERIFIABLE`` (every check this audit can
    actually perform passed -- scoped deliberately to *persisted
    material*, because the Task 140 ``original_result`` is request
    material and is not part of what this verdict covers),
    ``RECORD_INVALID`` (the record could not satisfy replay
    preconditions), ``RECORD_TAMPERED`` (the canonical binding
    verification failed, or the record's own evidence contradicts its
    claimed identity), or ``UNVERIFIABLE`` (the required binding
    evidence was never persisted, so nothing is claimed -- explicitly
    never reported as verified and never fabricated).

    A malformed verdict is never silently downgraded: structurally
    unverifiable material cannot reach the tamper verdict, so
    ``MALFORMED`` is reported instead of a weaker ``INCONSISTENT``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    receipt_id: str
    input_fingerprint: str
    replay_consistent: bool
    replay_state: str
    replay_contract_finding: str
    replay_issues: list[str]


class ReasoningRunReplayConsistencyAuditRead(BaseModel):
    """Strict replay API consistency audit for one session.

    ``completed_receipts_examined`` counts the persisted COMPLETED
    receipts audited for the exact requested ``session_id``; zero
    yields ``replay_state="NO_MATERIAL"``, which is a distinct
    deterministic result -- never conflated with an inconsistent or
    malformed receipt, which is always examined and counted. Findings
    are deterministically ordered.

    ``audit_consistent`` is true exactly when no examined receipt
    violates an invariant *over the evidence that is persisted*. It is
    a statement about persisted material only, and deliberately does
    not imply that every replay artifact was verified.

    ``original_result_provenance`` states the historical provenance of
    the Task 140 ``original_result`` explicitly. The current ROP
    persistence model persists ``session_id``, ``input_fingerprint``,
    ``outcome``, ``exogenous_snapshot``, and ``input_snapshot`` -- it
    does not persist the Task 140 request ``original_result`` as
    historical replay evidence. Its value is therefore always
    ``NOT_PERSISTED``: the audit cannot independently verify
    original-result provenance.

    ``NOT_PERSISTED`` is an architectural evidence limitation, not an
    inconsistency and not a verification. Missing evidence is never
    reported as tampering, never silently treated as verified, and
    never manufactured -- by reconstructing it from current state,
    re-executing a run, or invoking the replay engine.
    ``original_result_provenance`` is reported separately from
    ``replay_issues`` precisely so that this architectural gap never
    drives ``audit_consistent``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    available: bool
    audit_consistent: bool
    session_id: str
    replay_state: str
    original_result_provenance: str
    completed_receipts_examined: int
    valid_receipts: int
    invalid_receipts: int
    findings: list[ReasoningRunReplayConsistencyFindingRead]
    audit_source: str
