"""Task 135: deterministic consistency audit for the idempotency API.

Independently verifies that a Task 134 HTTP result faithfully
represents its canonical Task 127 envelope: session identity,
disposition vocabulary, fingerprint shapes, disposition/result
coherence, reused/executed fingerprint binding, and nested execution
structural validity (via Task 045's own validator).

Pure and read-only: no database, no execution, no mutation, no
recomputation of Task 127's decision. The Task 135 HTTP endpoint
(``POST /sessions/{id}/reasoning-run/idempotency-consistency``) is a
thin read-only adapter over this service; structurally invalid
envelopes are rejected by the strict request schema before they ever
reach this audit.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.schemas.reasoning_run_idempotency_consistency import (
    ReasoningRunIdempotencyConsistencyRead,
)
from rop.services.reasoning_run_execution_consistency import (
    ReasoningRunExecutionConsistencyService,
)

REASONING_RUN_IDEMPOTENCY_CONSISTENCY_SOURCE_TASK_135 = (
    "REASONING_RUN_IDEMPOTENCY_CONSISTENCY_TASK_135"
)

_DISPOSITIONS = (
    "EXECUTED_NEW",
    "REUSED_IDENTICAL",
    "STALE_CHANGED",
)

_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class ReasoningRunIdempotencyConsistencyContractError(Exception):
    """Task 135: the supplied envelope cannot be audited at all."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunIdempotencyConsistencyService:
    """Pure audit of one Task 134 idempotency envelope."""

    def __init__(
        self,
        execution_consistency_service: (
            ReasoningRunExecutionConsistencyService | None
        ) = None,
    ) -> None:
        self.execution_consistency_service = (
            execution_consistency_service or ReasoningRunExecutionConsistencyService()
        )

    def build(
        self,
        *,
        envelope: Mapping[str, Any] | None = None,
        session_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """Audit the supplied idempotency envelope. Pure."""
        if envelope is None:
            raise ReasoningRunIdempotencyConsistencyContractError(
                "MISSING_ENVELOPE", "envelope is required"
            )
        if not isinstance(envelope, Mapping):
            raise ReasoningRunIdempotencyConsistencyContractError(
                "ENVELOPE_TYPE",
                "envelope is not a mapping: " + type(envelope).__name__,
            )

        issues: list[str] = []

        raw_envelope_session = envelope.get("session_id")
        envelope_session: str | None = None
        if isinstance(raw_envelope_session, UUID):
            envelope_session = str(raw_envelope_session)
        elif isinstance(raw_envelope_session, str):
            try:
                UUID(raw_envelope_session)
            except (ValueError, TypeError):
                issues.append("SESSION_ID_INVALID")
            else:
                envelope_session = raw_envelope_session
        else:
            issues.append("SESSION_ID_INVALID")

        if session_id is not None and envelope_session is not None:
            if str(session_id) != envelope_session:
                issues.append("SESSION_ID_MISMATCH")

        disposition = envelope.get("disposition")
        if disposition not in _DISPOSITIONS:
            issues.append("INVALID_DISPOSITION")

        current = envelope.get("current_input_fingerprint")
        if not isinstance(current, str) or _FINGERPRINT_RE.match(current) is None:
            issues.append("MALFORMED_CURRENT_FINGERPRINT")

        known = envelope.get("known_input_fingerprint")
        if known is not None and (
            not isinstance(known, str) or _FINGERPRINT_RE.match(known) is None
        ):
            issues.append("MALFORMED_KNOWN_FINGERPRINT")

        result = envelope.get("result")
        if disposition == "STALE_CHANGED":
            if result is not None:
                issues.append("STALE_RESULT_PRESENT")
        elif disposition in ("EXECUTED_NEW", "REUSED_IDENTICAL"):
            if not isinstance(result, Mapping):
                issues.append("MISSING_RESULT")
            else:
                nested_fp = result.get("input_fingerprint")
                if disposition == "REUSED_IDENTICAL" and nested_fp != known:
                    issues.append("REUSED_FINGERPRINT_MISMATCH")
                if disposition == "EXECUTED_NEW" and nested_fp != current:
                    issues.append("EXECUTED_FINGERPRINT_MISMATCH")
                try:
                    nested = self.execution_consistency_service.build(execution=result)
                except Exception:
                    issues.append("NESTED_RESULT_MALFORMED")
                else:
                    if isinstance(nested, Mapping) and nested.get("consistency_issues"):
                        issues.append("NESTED_RESULT_INCONSISTENT")

        ordered = sorted(set(issues))
        audit = {
            "available": True,
            "audit_consistent": not ordered,
            "session_id": envelope_session or "",
            "disposition": (disposition if disposition in _DISPOSITIONS else None),
            "consistency_issues": ordered,
            "audit_source": REASONING_RUN_IDEMPOTENCY_CONSISTENCY_SOURCE_TASK_135,
        }
        return ReasoningRunIdempotencyConsistencyRead.model_validate(audit).model_dump()
