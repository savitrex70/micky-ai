"""Task 153: Stage 7 entry contract.

Strict read-only response to one question for one session: is the
existing deterministic ROP core structurally permitted to enter the
Stage 7 provider-agnostic model boundary? The contract reports the
boundary seam's presence and coherence, explicit-injection integrity,
prohibited-integration absence, and the canonical Stage 6 handoff
verdict. No model call, no server, no network, no persistence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunStage7EntryRead(BaseModel):
    """Strict Stage 7 entry verdict for one session.

    ``stage_7_status`` is the canonical verdict: ``READY`` (boundary
    seam available, coherent, explicitly injected, and free of
    prohibited integrations -- READY never means a model is
    configured), ``BLOCKED`` (a prohibited indicator, a boundary
    contract mismatch, a broken injection seam, or a refused Stage 6
    handoff), ``UNAVAILABLE`` (boundary material missing or unreadable,
    or a Stage 6 handoff failure without any structural violation
    here). Absence of a concrete provider is the expected healthy state
    and never blocks entry. ``stage_7_source`` is the canonical
    identifier of this entry contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    stage_7_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    boundary_available: bool
    boundary_consistent: bool
    provider_explicitly_injected: bool
    concrete_provider_present: bool
    network_integration_present: bool
    api_key_configuration_present: bool
    stage_7_source: str
    findings: list[str]
    finding_count: int
