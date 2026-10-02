"""Task 140: canonical deterministic reasoning-run replay API request."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ReasoningRunReplayRequest(BaseModel):
    """Request body for the deterministic reasoning-run replay API.

    Carries the recorded original execution result together with the
    canonical Task 124 input snapshot that produced it. The API passes
    this recorded material directly to the Task 128 replay service,
    which verifies the fingerprint-to-snapshot binding before
    replaying; the request layer performs no fingerprint,
    canonicalization, or replay logic of its own. Unexpected fields
    are rejected (``extra="forbid"``) so no undocumented material can
    reach replay evaluation.
    """

    model_config = ConfigDict(extra="forbid")

    original_result: dict[str, Any]
    original_snapshot: dict[str, Any]
