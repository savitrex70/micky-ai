"""Task 131: deterministic missing-information lifecycle contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

LifecycleState = Literal["NEW", "PERSISTING", "RESOLVED", "STALE"]


class LifecycleItemRead(BaseModel):
    """One missing-information item with its lifecycle state."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    template: str
    key: str
    label: str
    state: LifecycleState
    reason: str
    satisfying_observation_ids: list[str]
    candidate_ids: list[str]


class MissingInformationLifecycleRead(BaseModel):
    """Session-level lifecycle record over missing-information state."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    available: bool
    lifecycle_consistent: bool
    session_id: str
    profile: str | None
    items: list[LifecycleItemRead]
    consistency_issues: list[str]
    lifecycle_source: str
