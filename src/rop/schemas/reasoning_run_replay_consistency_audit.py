"""Task 141: deterministic replay API consistency audit contract.

The strict read-only audit response for one exact session's replay
material. Follows the established Task 135/139 audit convention
(``available`` / ``audit_consistent`` / ``session_id`` / issue list /
``audit_source``) extended with an explicit ``replay_state`` so the
three required outcomes are never conflated: ``NO_MATERIAL`` (no
replay material exists to audit), ``INCONSISTENT`` (material exists
and is structurally readable but violates the canonical Task 128
replay contract), and ``MALFORMED`` (material exists but is
structurally unverifiable). ``SATISFIED`` covers material that
verifies cleanly. No ORM internals, no database details, no
provider/model information.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReasoningRunReplayConsistencyFindingRead(BaseModel):
    """One audited receipt's replay-contract verdict.

    ``receipt_id`` and ``input_fingerprint`` identify the persisted
    material exactly as historical evidence. ``replay_issues`` is the
    deterministic sorted set of replay-contract invariant violations
    (empty exactly when ``replay_consistent`` is true).

    ``replay_state`` is the per-material three-state verdict:
    ``SATISFIED`` (verifies cleanly against the canonical replay
    contract), ``INCONSISTENT`` (structurally readable but contract-
    violating -- e.g. a session identity or exogenous projection that
    contradicts the receipt's own bound snapshot), or ``MALFORMED``
    (structurally unverifiable -- e.g. a malformed fingerprint or an
    absent/ill-typed input snapshot, so the canonical contract cannot
    even be evaluated).

    ``replay_contract_finding`` names which canonical Task 128 replay
    invariant the material would trip, reusing the existing contract
    vocabulary rather than inventing new verdicts:
    ``VERIFIABLE`` (preconditions verified), ``RECORD_INVALID`` (the
    record could not satisfy replay preconditions), ``RECORD_TAMPERED``
    (the canonical binding verification failed, or the record's own
    evidence contradicts its claimed identity), or ``UNVERIFIABLE``
    (binding evidence was never persisted, so nothing is claimed --
    explicitly never reported as verified and never fabricated).

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
    malformed receipt, which is always examined and counted. An audit
    is consistent exactly when no examined receipt violates a replay
    invariant. Findings are deterministically ordered.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    available: bool
    audit_consistent: bool
    session_id: str
    replay_state: str
    completed_receipts_examined: int
    valid_receipts: int
    invalid_receipts: int
    findings: list[ReasoningRunReplayConsistencyFindingRead]
    audit_source: str
