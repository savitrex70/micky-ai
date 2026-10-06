"""Task 161: Stage 7 diagnostics health classification contract.

Strict read-only diagnostic view over the completed Stage 7 evidence
surfaces: the Task 155 request package, the Task 156 request audit, the
Task 158 validated proposal, and the Task 159 proposal audit as
aggregated by the Task 160 unified result boundary. The single
deterministic health state is computed from that canonical evidence
only -- never from any model claim of confidence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ReasoningRunStage7DiagnosticsRead(BaseModel):
    """Strict deterministic Stage 7 health classification.

    ``diagnostics_status`` semantics: ``HEALTHY`` -- request valid,
    proposal valid, audits consistent, no unresolved integrity issue;
    ``DEGRADED`` -- a validated result exists but required provenance
    or evidence is unavailable; ``UNHEALTHY`` -- request/proposal
    consistency contradiction or a provider failure that makes the
    result unusable; ``NO_MATERIAL`` -- no admitted reasoning result
    exists. ``available`` is exactly ``diagnostics_status !=
    "NO_MATERIAL"``. ``result_status`` carries the canonical Task 160
    aggregate verdict and ``proposal_status`` the canonical Task 158
    status verbatim, so no health state can conceal the evidence that
    determined it. ``findings`` are deterministic, sorted, and
    deduplicated; ``finding_count`` always equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    result_status: Literal["READY", "INCONSISTENT", "MODEL_UNAVAILABLE", "UNAVAILABLE"]
    proposal_status: Literal[
        "VALIDATED",
        "UNAVAILABLE",
        "MODEL_UNAVAILABLE",
        "MODEL_OUTPUT_INVALID",
        "MODEL_OUTPUT_INCONSISTENT",
    ]
    diagnostics_status: Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "NO_MATERIAL"]
    available: bool
    finding_count: int
    findings: list[str]
    source: str

    @model_validator(mode="after")
    def _coherent_diagnostics(self) -> ReasoningRunStage7DiagnosticsRead:
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if self.available != (self.diagnostics_status != "NO_MATERIAL"):
            raise ValueError("available must match the diagnostics status")

        if self.diagnostics_status == "HEALTHY":
            if self.result_status != "READY":
                raise ValueError("HEALTHY requires a READY reasoning result")
            if self.findings:
                raise ValueError("HEALTHY allows no unresolved integrity finding")
        elif self.diagnostics_status == "DEGRADED":
            if self.result_status != "UNAVAILABLE":
                raise ValueError("DEGRADED requires an unaudited result")
            if self.proposal_status != "VALIDATED":
                raise ValueError("DEGRADED requires an existing validated proposal")
        elif self.diagnostics_status == "UNHEALTHY":
            if self.result_status not in ("INCONSISTENT", "MODEL_UNAVAILABLE"):
                raise ValueError(
                    "UNHEALTHY requires a contradiction or a provider failure"
                )
        else:
            if self.result_status != "UNAVAILABLE":
                raise ValueError("NO_MATERIAL requires the absence of a result")
            if self.proposal_status == "VALIDATED":
                raise ValueError("NO_MATERIAL cannot coexist with a validated proposal")
        return self
