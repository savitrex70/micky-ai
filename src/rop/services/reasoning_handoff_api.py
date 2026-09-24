"""Task 059: read-only API orchestration for the reasoning handoff.

Thin orchestration only. This service exists so the HTTP layer does
not reach directly into Task 055 / 056 / 057 services and does not
reproduce any of their rules. It calls:

    1. Task 055 to build the canonical reasoning context once
    2. Task 056 to audit that exact context
    3. Task 057 to package that exact context and audit

The same Task 055 context object flows through every step. No second
context is built. Task 058's provenance binding is enforced by Task
057, not reimplemented here.

This service does no reasoning, no decision, no persistence beyond
what Task 055's read-only composition already performs, and no HTTP
handling.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.services.reasoning_context import (
    ReasoningContextService,
)
from rop.services.reasoning_context_consistency import (
    ReasoningContextConsistencyService,
)
from rop.services.reasoning_handoff import (
    ReasoningHandoffService,
)


class ReasoningHandoffApiService:
    """Task 059: delegation-only orchestration of Tasks 055-057.

    Exists so the API layer can obtain the validated reasoning handoff
    without duplicating Task 055/056/057 wiring. It does not duplicate
    any contract rule, validation, or semantic check.
    """

    def __init__(
        self,
        reasoning_context_service: ReasoningContextService | None = None,
        reasoning_context_consistency_service: (
            ReasoningContextConsistencyService | None
        ) = None,
        reasoning_handoff_service: ReasoningHandoffService | None = None,
    ) -> None:
        self.reasoning_context_service = (
            reasoning_context_service or ReasoningContextService()
        )
        self.reasoning_context_consistency_service = (
            reasoning_context_consistency_service
            or ReasoningContextConsistencyService()
        )
        self.reasoning_handoff_service = (
            reasoning_handoff_service or ReasoningHandoffService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Return the Task 057 handoff for a session.

        Builds the Task 055 context exactly once, audits that exact
        context via Task 056, then packages the same context and audit
        via Task 057. Any contract error from those services is
        allowed to propagate unchanged -- this layer does not catch,
        translate, or repair it.
        """
        context = self.reasoning_context_service.build_for_session(db, session_id)
        audit = self.reasoning_context_consistency_service.build(context=context)
        return self.reasoning_handoff_service.build(
            reasoning_context=context,
            context_consistency=audit,
        )
