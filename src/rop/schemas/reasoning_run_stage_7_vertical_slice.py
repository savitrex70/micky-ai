"""Task 163: Stage 7 provider-agnostic vertical-slice verdict contract.

Strict projection of the first end-to-end deterministic Stage 7 gate:
the canonical Task 162 audit package is certified into exactly one
vertical-slice verdict. ``READY`` is the only certified state and is
structurally coherent -- it requires an admitted session, healthy
diagnostics, consistent request and proposal provenance, attributable
provider metadata, and no open findings. ``BLOCKED`` and
``UNAVAILABLE`` carry the canonical package findings. Raw provider
text and the raw provider response object can never appear.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ReasoningRunStage7VerticalSliceRead(BaseModel):
    """Strict read model for one certified Stage 7 vertical slice.

    ``slice_status`` is the single canonical verdict: ``READY`` when
    the provider-agnostic boundary is certified whole, ``BLOCKED`` for
    a refused or contradictory path, and ``UNAVAILABLE`` for missing,
    degraded, or unattributable material. ``admission_status`` and
    ``diagnostics_status`` carry the canonical Task 154 and Task 161
    verdicts verbatim and are ``None`` exactly when the corresponding
    material is absent. ``session_id`` is empty when no material claims
    one. ``provider_name`` and ``model_name`` appear only together.
    ``findings`` are deterministic, sorted, and deduplicated;
    ``finding_count`` always equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    slice_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    admission_status: Literal["ADMITTED", "BLOCKED", "UNAVAILABLE"] | None
    diagnostics_status: (
        Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL"] | None
    )
    provider_name: str | None
    model_name: str | None
    finding_count: int
    findings: list[str]
    certification_source: str

    @model_validator(mode="after")
    def _coherent_slice(self) -> ReasoningRunStage7VerticalSliceRead:
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if (self.provider_name is None) != (self.model_name is None):
            raise ValueError("provider_name and model_name must be set together")
        if self.slice_status == "READY":
            if self.admission_status != "ADMITTED":
                raise ValueError("READY requires an admitted admission verdict")
            if self.diagnostics_status != "HEALTHY":
                raise ValueError("READY requires healthy diagnostics")
            if self.session_id == "":
                raise ValueError("READY requires a session identity")
            if self.provider_name is None:
                raise ValueError("READY requires provider attribution")
            if self.findings:
                raise ValueError("READY requires a finding-free package")
        return self
