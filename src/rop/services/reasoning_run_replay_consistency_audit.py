"""Task 141: read-only replay API consistency audit.

Deterministically audits the replay-related historical receipt material
that is actually persisted for one exact session, against the canonical
Task 128 replay contract that the Task 140 replay API depends on.

The audit reuses the canonical contract's own primitives rather than
re-deriving them: the canonical 64-character lowercase SHA-256
fingerprint shape, the Task 125 ``verify_snapshot_fingerprint``
binding check, and the Task 124 exogenous projection. Violations are
detected over the persisted surfaces the receipt actually carries --
session identity, fingerprint, exogenous snapshot, and persisted input
snapshot binding -- by reusing the exact verification the canonical
replay contract already performs, never by inventing a second, weaker
binding rule.

Historical evidence actually available

The current ROP persistence model persists ``session_id``,
``input_fingerprint``, ``outcome``, ``exogenous_snapshot``, and
``input_snapshot``. It does NOT persist the Task 140 request
``original_result`` as historical replay evidence. This audit therefore
verifies only what genuinely exists, and states the original-result
gap explicitly through ``original_result_provenance = NOT_PERSISTED``.

Missing evidence is never treated as tampering and never silently
treated as verified. It is also never manufactured: this audit does not
persist a replay result, does not reconstruct one from current state,
does not re-execute a reasoning run, and does not invoke the replay
engine to fill the gap.

Strictly read-only over persisted state: no execution, no replay, no
candidate generation, no snapshot builds, no reads of mutable current
session state, no receipt creation or mutation, no transaction
ownership, no provider/model calls. Binding verification is a
compare-only hash check of the receipt's OWN persisted snapshot
against its OWN persisted fingerprint -- never a recomputation from
current state, never a substitution of current session input, and
never hash-of-exogenous-projection (the recorded fingerprint binds the
full snapshot, not its projection).

Three outcomes over persisted material are kept strictly distinct:

* ``NO_MATERIAL`` -- no persisted COMPLETED receipt exists for the
  session, so there is nothing to audit. This is a legitimate,
  deterministic result, never an error and never silently reported as
  verified.
* ``INCONSISTENT`` -- material exists and is structurally readable, but
  contradicts the canonical replay contract: the receipt's own bound
  evidence disagrees with its claimed session identity or with its
  persisted exogenous projection, or canonical binding verification
  failed.
* ``MALFORMED`` -- material exists but is structurally unverifiable: a
  malformed fingerprint, an ill-typed or absent input snapshot, or an
  unreadable receipt. The canonical contract cannot even be evaluated,
  so nothing is claimed about it cryptographically.

Material persisted before binding evidence existed reports an explicit
``UNVERIFIABLE`` contract finding: never silently verified, never
fabricated, and never counted as consistent, because binding evidence
that does not exist cannot be independently verified. This is distinct
from the architectural ``original_result_provenance`` gap, which is
reported separately and never drives ``audit_consistent``.

Reuses the Task 138 receipt repository query and the Task 137 read
projection unchanged. The divergence-vs-contract-failure boundary is
preserved: legitimate divergence between current and recorded state is
the POST replay API's HTTP 200 finding, while a genuine contract
failure is its generic HTTP 500 -- this audit reports on persisted
material only and never conflates the two.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.repositories.reasoning_run_receipt import ReasoningRunReceiptRepository
from rop.schemas.reasoning_run_input_snapshot import ReasoningRunInputSnapshotRead
from rop.schemas.reasoning_run_replay_consistency_audit import (
    ReasoningRunReplayConsistencyAuditRead,
)
from rop.services.reasoning_run_fingerprint import verify_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    EXOGENOUS_SNAPSHOT_FIELDS,
    exogenous_projection,
)
from rop.services.reasoning_run_receipt import ReasoningRunReceiptService

REASONING_RUN_REPLAY_CONSISTENCY_AUDIT_SOURCE_TASK_141 = (
    "REASONING_RUN_REPLAY_CONSISTENCY_AUDIT_TASK_141"
)

# Replay states: the three required outcomes plus the clean case.
REPLAY_STATE_NO_MATERIAL = "NO_MATERIAL"
REPLAY_STATE_SATISFIED = "SATISFIED"
REPLAY_STATE_INCONSISTENT = "INCONSISTENT"
REPLAY_STATE_MALFORMED = "MALFORMED"

# Canonical Task 128 replay contract verdicts, reused verbatim. The
# clean verdict is scoped to persisted material because the Task 140
# ``original_result`` is request material, not persisted evidence, and
# is reported separately via ``original_result_provenance``.
REPLAY_CONTRACT_PERSISTED_MATERIAL_VERIFIABLE = "PERSISTED_MATERIAL_VERIFIABLE"
REPLAY_CONTRACT_RECORD_INVALID = "RECORD_INVALID"
REPLAY_CONTRACT_RECORD_TAMPERED = "RECORD_TAMPERED"
REPLAY_CONTRACT_UNVERIFIABLE = "UNVERIFIABLE"

# The Task 140 ``original_result`` is not persisted as historical
# replay evidence by the current architecture, so its historical
# provenance can never be independently verified here. Reported
# explicitly -- never fabricated, never reconstructed, never counted
# as tampering, and never treated as verified.
REPLAY_ORIGINAL_RESULT_PROVENANCE_NOT_PERSISTED = "NOT_PERSISTED"

# Structural malformation makes the canonical contract unevaluable, so
# it can never reach the weaker tamper verdict.
_MALFORMING_ISSUES = frozenset(
    {
        "REPLAY_MALFORMED_FINGERPRINT",
        "REPLAY_OUTCOME_NOT_COMPLETED",
        "REPLAY_EXOGENOUS_SNAPSHOT_MALFORMED",
        "REPLAY_RECEIPT_UNREADABLE",
        "REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED",
        "REPLAY_INPUT_SNAPSHOT_MALFORMED",
    }
)

_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class ReasoningRunReplayConsistencyAuditContractError(Exception):
    """Task 141: the replay consistency audit result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunReplayConsistencyAuditService:
    """Deterministic read-only consistency audit of one session's replay material."""

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

        ``audit_consistent`` describes the persisted material only.
        The Task 140 ``original_result`` is not persisted as historical
        replay evidence, so its provenance is reported separately and
        never makes the audit inconsistent.
        """
        receipts = self.receipt_repository.list_completed_by_session(db, session_id)

        findings: list[dict[str, Any]] = []
        valid_receipts = 0
        invalid_receipts = 0
        for receipt in receipts:
            raw_issues, replay_state, contract_finding = self._replay_contract_issues(
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
                    "replay_consistent": consistent,
                    "replay_state": replay_state,
                    "replay_contract_finding": contract_finding,
                    "replay_issues": issues,
                }
            )

        audit = {
            "available": True,
            "audit_consistent": invalid_receipts == 0,
            "session_id": str(session_id),
            "replay_state": self._aggregate_replay_state(findings, len(receipts)),
            "original_result_provenance": (
                REPLAY_ORIGINAL_RESULT_PROVENANCE_NOT_PERSISTED
            ),
            "completed_receipts_examined": len(receipts),
            "valid_receipts": valid_receipts,
            "invalid_receipts": invalid_receipts,
            "findings": findings,
            "audit_source": REASONING_RUN_REPLAY_CONSISTENCY_AUDIT_SOURCE_TASK_141,
        }
        try:
            validated = ReasoningRunReplayConsistencyAuditRead.model_validate(audit)
        except ValidationError as exc:
            raise ReasoningRunReplayConsistencyAuditContractError(
                "AUDIT_UNPROJECTABLE",
                "audit result cannot be projected onto the canonical audit schema",
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _aggregate_replay_state(
        findings: list[dict[str, Any]],
        receipts_examined: int,
    ) -> str:
        """Collapse per-material verdicts into the session-level state.

        ``NO_MATERIAL`` is decided by the receipt count alone, so it
        can never be reported for a session that does hold material.
        Structural malformation outranks tampering: if any material is
        unverifiable the session is ``MALFORMED``, because the canonical
        contract could not be evaluated for all of it.
        """
        if receipts_examined == 0:
            return REPLAY_STATE_NO_MATERIAL
        states = {finding["replay_state"] for finding in findings}
        if REPLAY_STATE_MALFORMED in states:
            return REPLAY_STATE_MALFORMED
        if REPLAY_STATE_INCONSISTENT in states:
            return REPLAY_STATE_INCONSISTENT
        return REPLAY_STATE_SATISFIED

    def _replay_contract_issues(
        self,
        receipt: Any,
        session_id: UUID,
    ) -> tuple[list[str], str, str]:
        """Evaluate one persisted receipt against the canonical replay contract.

        Pure over persisted receipt state: reads the receipt's own
        fields only, never current session state, never builds a
        snapshot, never replays, and never reconstructs an original
        replay result. The tamper verdict reuses the exact Task 125
        binding verification the canonical replay contract already
        applies, and reports it under the contract's own
        ``RECORD_TAMPERED`` vocabulary rather than a bespoke rule.
        """
        issues: list[str] = []

        # Surface 1 -- session identity. A receipt whose own evidence
        # names a different session than the receipt claims has had its
        # identity tampered with.
        receipt_session = getattr(receipt, "session_id", None)
        if receipt_session is None or str(receipt_session) != str(session_id):
            issues.append("REPLAY_SESSION_MISMATCH")

        # Surface 2 -- fingerprint shape, exactly as the canonical
        # contract requires it before replay means anything.
        fingerprint = getattr(receipt, "input_fingerprint", None)
        malformed_fingerprint = (
            not isinstance(fingerprint, str)
            or _FINGERPRINT_RE.match(fingerprint) is None
        )
        if malformed_fingerprint:
            issues.append("REPLAY_MALFORMED_FINGERPRINT")

        if getattr(receipt, "outcome", None) != "COMPLETED":
            issues.append("REPLAY_OUTCOME_NOT_COMPLETED")

        snapshot = getattr(receipt, "exogenous_snapshot", None)
        if not self._exogenous_shape_valid(snapshot):
            issues.append("REPLAY_EXOGENOUS_SNAPSHOT_MALFORMED")
        elif str(snapshot.get("session_id")) != str(receipt_session):
            issues.append("REPLAY_EXOGENOUS_SESSION_MISMATCH")

        projected = self.receipt_service.project_receipt(
            receipt, session_id, fingerprint
        )
        if projected is None:
            issues.append("REPLAY_RECEIPT_UNREADABLE")

        # Persisted input snapshot: structure, canonical binding, and
        # agreement with the persisted exogenous projection, via the
        # canonical contract's own compare-only verification. The Task
        # 140 ``original_result`` is not persisted and is never
        # reconstructed here; its provenance is reported separately as
        # NOT_PERSISTED.
        input_snapshot = getattr(receipt, "input_snapshot", None)
        if input_snapshot is None:
            # Material persisted before binding evidence existed.
            # Explicitly unverifiable -- never silently verified, never
            # fabricated, and not claimed consistent.
            issues.append("REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED")
        else:
            if not isinstance(input_snapshot, dict):
                issues.append("REPLAY_INPUT_SNAPSHOT_MALFORMED")
            else:
                try:
                    ReasoningRunInputSnapshotRead.model_validate(input_snapshot)
                except ValidationError:
                    issues.append("REPLAY_INPUT_SNAPSHOT_MALFORMED")
            # The canonical contract's own tamper check: a recording
            # that fails it could never replay as genuine.
            if verify_snapshot_fingerprint(input_snapshot, fingerprint):
                issues.append("REPLAY_RECORD_TAMPERED")
            if isinstance(input_snapshot, dict) and (
                exogenous_projection(input_snapshot) != receipt.exogenous_snapshot
            ):
                issues.append("REPLAY_EXOGENOUS_PROJECTION_MISMATCH")

        replay_state, contract_finding = self._classify(issues)
        return issues, replay_state, contract_finding

    @staticmethod
    def _classify(issues: list[str]) -> tuple[str, str]:
        """Map issues to the per-material replay state and contract finding."""
        if not issues:
            return (
                REPLAY_STATE_SATISFIED,
                REPLAY_CONTRACT_PERSISTED_MATERIAL_VERIFIABLE,
            )

        issue_set = set(issues)
        if issue_set & _MALFORMING_ISSUES:
            # Structurally unverifiable: the canonical contract cannot
            # be evaluated, so nothing is claimed about the record --
            # never silently downgraded to the weaker tamper verdict.
            if issue_set == {"REPLAY_INPUT_SNAPSHOT_NOT_PERSISTED"}:
                return REPLAY_STATE_MALFORMED, REPLAY_CONTRACT_UNVERIFIABLE
            return REPLAY_STATE_MALFORMED, REPLAY_CONTRACT_RECORD_INVALID

        # Structurally readable but contract-violating: the record's own
        # evidence contradicts its claimed identity, its bound snapshot,
        # or the canonical binding verification.
        return REPLAY_STATE_INCONSISTENT, REPLAY_CONTRACT_RECORD_TAMPERED

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
