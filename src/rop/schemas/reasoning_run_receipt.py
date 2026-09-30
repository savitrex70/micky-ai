"""Task 137: canonical reasoning-run receipt inspection contract."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ReasoningRunReceiptRead(BaseModel):
    """Task 137: the canonical read-only representation of a completed
    reasoning-run receipt. Immutable historical evidence."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    session_id: UUID
    input_fingerprint: str
    exogenous_snapshot: dict
    outcome: str
    created_at: datetime
