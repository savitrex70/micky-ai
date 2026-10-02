"""Task 139: deterministic receipt provenance consistency audit contract.

The strict read-only audit response for one exact session's persisted
COMPLETED reasoning-run receipts. Follows the established Task 135
audit convention (``available`` / ``audit_consistent`` / ``session_id``
/ issue list / ``audit_source``) extended with explicit provenance
counts and one deterministic finding per audited receipt. No ORM
internals, no database details, no provider/model information.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReasoningRunReceiptProvenanceFindingRead(BaseModel):
    """One audited receipt's provenance verdict.

    ``receipt_id`` and ``input_fingerprint`` identify the persisted
    receipt exactly as historical evidence; ``provenance_issues`` is
    the deterministic sorted set of provenance invariant violations
    (empty exactly when ``receipt_consistent`` is true).
    ``fingerprint_binding`` is the canonical Task 125 verdict for the
    fingerprint-to-provenance binding: ``BOUND`` (the persisted
    canonical snapshot hash-verifies against the persisted
    fingerprint), ``INVALID`` (persisted evidence exists but hash
    verification failed -- an invalid receipt), or
    ``NOT_PERSISTED`` (the receipt predates persisted binding
    evidence; reported explicitly, never silently accepted as
    verified and never fabricated). ``NOT_PERSISTED`` receipts are
    never counted as consistent or valid: binding evidence that does
    not exist cannot be independently verified, so
    ``receipt_consistent`` is false with the explicit
    ``FINGERPRINT_PROVENANCE_NOT_PERSISTED`` issue -- without ever
    claiming the historical receipt is cryptographically wrong.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    receipt_id: str
    input_fingerprint: str
    receipt_consistent: bool
    fingerprint_binding: str
    provenance_issues: list[str]


class ReasoningRunReceiptProvenanceAuditRead(BaseModel):
    """Strict provenance consistency audit for one session's receipts.

    ``completed_receipts_examined`` counts the persisted COMPLETED
    receipts audited for the exact requested ``session_id``; zero
    means the session has no completed history (distinct from an
    invalid receipt, which is always examined and counted). An audit
    is consistent exactly when no examined receipt violates a
    provenance invariant. Findings are deterministically ordered.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    available: bool
    audit_consistent: bool
    session_id: str
    completed_receipts_examined: int
    valid_receipts: int
    invalid_receipts: int
    findings: list[ReasoningRunReceiptProvenanceFindingRead]
    audit_source: str
