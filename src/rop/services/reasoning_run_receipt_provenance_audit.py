"""Task 139: read-only reasoning-run receipt provenance consistency audit.

Deterministically audits the provenance of every persisted COMPLETED
receipt belonging to one exact session against the canonical ROP
provenance invariants: exact session binding, canonical 64-character
lowercase SHA-256 input fingerprint, ``COMPLETED`` outcome,
structurally valid ``exogenous_snapshot`` (the Task 124
``EXOGENOUS_SNAPSHOT_FIELDS`` projection), internal provenance
consistency, projectability onto the canonical Task 137 receipt
read schema, and the fingerprint-to-provenance binding verified with
the canonical Task 125 ``verify_snapshot_fingerprint`` over the
receipt's own persisted Task 124 input snapshot.

Strictly read-only over persisted state: no execution, no replay, no
candidate generation, no snapshot builds, no reads of mutable current
session state, no receipt creation or mutation, no transaction
ownership, no provider/model calls. Binding verification is a
compare-only hash check of the receipt's OWN persisted snapshot
against its OWN persisted fingerprint -- never a recomputation from
current state, never a substitution of current session input, and
never hash-of-exogenous-projection (the recorded fingerprint binds
the full snapshot, not its projection). Receipts persisted before
binding evidence existed report an explicit ``NOT_PERSISTED`` binding
status: never silently verified, never fabricated -- and never
counted as consistent, because a receipt whose binding evidence does
not exist cannot be independently verified (``receipt_consistent``
is false with the explicit ``FINGERPRINT_PROVENANCE_NOT_PERSISTED``
issue, without ever claiming the historical receipt is
cryptographically wrong). A persisted receipt is treated as
historical evidence: invalid provenance is reported as an explicit
invalid finding, never silently repaired, recomputed, or converted
into missing history. Missing history (no
completed receipts) is a distinct deterministic result. Reuses the
Task 138 receipt repository query and the Task 137 read projection
unchanged.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.repositories.reasoning_run_receipt import ReasoningRunReceiptRepository
from rop.schemas.reasoning_run_input_snapshot import ReasoningRunInputSnapshotRead
from rop.schemas.reasoning_run_receipt_provenance_audit import (
    ReasoningRunReceiptProvenanceAuditRead,
)
from rop.services.reasoning_run_fingerprint import verify_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    EXOGENOUS_SNAPSHOT_FIELDS,
    exogenous_projection,
)
from rop.services.reasoning_run_receipt import ReasoningRunReceiptService

REASONING_RUN_RECEIPT_PROVENANCE_AUDIT_SOURCE_TASK_139 = (
    "REASONING_RUN_RECEIPT_PROVENANCE_AUDIT_TASK_139"
)

_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class ReasoningRunReceiptProvenanceAuditContractError(Exception):
    """Task 139: the provenance audit result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunReceiptProvenanceAuditService:
    """Deterministic read-only provenance audit of one session's receipts."""

    def __init__(
        self,
        receipt_repository: ReasoningRunReceiptRepository | None = None,
        receipt_service: ReasoningRunReceiptService | None = None,
    ) -> None:
        self.receipt_repository = receipt_repository or ReasoningRunReceiptRepository()
        self.receipt_service = receipt_service or ReasoningRunReceiptService()

    def audit(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Audit every persisted COMPLETED receipt for one exact session.

        Receipts are read through the Task 138 repository method, so
        ordering is deterministic (creation time, then receipt id) and
        only this session's COMPLETED receipts are examined. Read-only:
        no writes, no execution, no replay, no recomputation of stored
        provenance.
        """
        receipts = self.receipt_repository.list_completed_by_session(db, session_id)

        findings: list[dict[str, Any]] = []
        valid_receipts = 0
        invalid_receipts = 0
        for receipt in receipts:
            raw_issues, fingerprint_binding = self._provenance_issues(
                receipt, session_id
            )
            issues = sorted(set(raw_issues))
            consistent = not issues
            if consistent:
                valid_receipts += 1
            else:
                invalid_receipts += 1
            raw_fingerprint = getattr(receipt, "input_fingerprint", None)
            findings.append(
                {
                    "receipt_id": str(receipt.id),
                    "input_fingerprint": (
                        str(raw_fingerprint) if raw_fingerprint is not None else ""
                    ),
                    "receipt_consistent": consistent,
                    "fingerprint_binding": fingerprint_binding,
                    "provenance_issues": issues,
                }
            )

        audit = {
            "available": True,
            "audit_consistent": invalid_receipts == 0,
            "session_id": str(session_id),
            "completed_receipts_examined": len(receipts),
            "valid_receipts": valid_receipts,
            "invalid_receipts": invalid_receipts,
            "findings": findings,
            "audit_source": REASONING_RUN_RECEIPT_PROVENANCE_AUDIT_SOURCE_TASK_139,
        }
        try:
            validated = ReasoningRunReceiptProvenanceAuditRead.model_validate(audit)
        except ValidationError as exc:
            raise ReasoningRunReceiptProvenanceAuditContractError(
                "AUDIT_UNPROJECTABLE",
                "audit result cannot be projected onto the canonical audit schema",
            ) from exc
        return validated.model_dump()

    def _provenance_issues(
        self,
        receipt: Any,
        session_id: UUID,
    ) -> tuple[list[str], str]:
        """Evaluate one persisted receipt; return issues and binding verdict.

        Pure over persisted receipt state: reads the receipt's own
        fields only, never current session state, never builds a
        snapshot. The binding verdict is the canonical Task 125
        comparison of the receipt's persisted input snapshot against
        its persisted fingerprint -- a hash check over historical
        evidence, not a recomputation from mutable state. A receipt
        with no persisted binding evidence reports ``NOT_PERSISTED``
        together with the ``FINGERPRINT_PROVENANCE_NOT_PERSISTED``
        issue, so it is examined, counted invalid, and never silently
        accepted as verified.
        """
        issues: list[str] = []

        receipt_session = getattr(receipt, "session_id", None)
        if receipt_session is None or str(receipt_session) != str(session_id):
            issues.append("SESSION_MISMATCH")

        fingerprint = getattr(receipt, "input_fingerprint", None)
        if (
            not isinstance(fingerprint, str)
            or _FINGERPRINT_RE.match(fingerprint) is None
        ):
            issues.append("MALFORMED_FINGERPRINT")

        if getattr(receipt, "outcome", None) != "COMPLETED":
            issues.append("OUTCOME_NOT_COMPLETED")

        snapshot = getattr(receipt, "exogenous_snapshot", None)
        if not self._exogenous_shape_valid(snapshot):
            issues.append("EXOGENOUS_SNAPSHOT_MALFORMED")
        elif str(snapshot.get("session_id")) != str(receipt_session):
            issues.append("EXOGENOUS_SESSION_MISMATCH")

        projected = self.receipt_service.project_receipt(
            receipt, session_id, fingerprint
        )
        if projected is None:
            issues.append("RECEIPT_UNREADABLE")

        snapshot = getattr(receipt, "input_snapshot", None)
        if snapshot is None:
            # Legacy receipt: binding evidence was never persisted.
            # Explicit status -- never silently verified, never
            # fabricated, and not claimed consistent: unverifiable
            # provenance is not verified provenance. Semantically
            # distinct from INVALID (no evidence exists to verify,
            # so nothing is claimed cryptographically wrong).
            issues.append("FINGERPRINT_PROVENANCE_NOT_PERSISTED")
            binding = "NOT_PERSISTED"
        else:
            if not isinstance(snapshot, dict):
                issues.append("INPUT_SNAPSHOT_MALFORMED")
            else:
                try:
                    ReasoningRunInputSnapshotRead.model_validate(snapshot)
                except ValidationError:
                    issues.append("INPUT_SNAPSHOT_MALFORMED")
            if verify_snapshot_fingerprint(snapshot, fingerprint):
                issues.append("FINGERPRINT_PROVENANCE_MISMATCH")
                binding = "INVALID"
            else:
                binding = "BOUND"
            if isinstance(snapshot, dict) and (
                exogenous_projection(snapshot) != receipt.exogenous_snapshot
            ):
                issues.append("EXOGENOUS_PROJECTION_MISMATCH")

        return issues, binding

    @staticmethod
    def _exogenous_shape_valid(snapshot: Any) -> bool:
        """Structural validity per the Task 124 canonical projection."""
        if not isinstance(snapshot, dict):
            return False
        if set(snapshot) != set(EXOGENOUS_SNAPSHOT_FIELDS):
            return False
        if not isinstance(snapshot.get("session_id"), str):
            return False
        if not isinstance(snapshot.get("user_input"), str):
            return False
        if not isinstance(snapshot.get("observations"), list):
            return False
        if not isinstance(snapshot.get("entities"), list):
            return False
        return True
