"""Task 160: Stage 7 unified reasoning result contract.

The single provider-neutral result surface for one Stage 7 session: the
Task 155 request package status, the Task 156 request audit verdict, the
Task 158 proposal status, and the Task 159 proposal audit verdict
combined into one strict read-only projection. Only approved aggregate
evidence is exposed -- never raw provider text, never the raw provider
response object, never provider-specific fields.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ReasoningRunStage7ResultRead(BaseModel):
    """Strict unified Stage 7 result for one exact session.

    ``result_status`` is the canonical aggregate verdict with
    deterministic precedence: ``UNAVAILABLE`` (required result material
    missing -- no consistency claim is certified), ``INCONSISTENT``
    (request or proposal integrity failure), ``MODEL_UNAVAILABLE``
    (the provider could not produce a response; the canonical Task 057
    outcome value is reused verbatim), or ``READY`` (request and
    proposal are both valid and audited). ``proposal_status`` carries
    the canonical Task 158 status verbatim, so a
    ``MODEL_OUTPUT_INVALID`` or ``MODEL_OUTPUT_INCONSISTENT`` provider
    outcome remains visible even though it aggregates to
    ``INCONSISTENT``. ``findings`` are deterministic, sorted, and
    deduplicated; ``finding_count`` always equals ``len(findings)``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: str
    request_fingerprint: str | None
    request_status: Literal["PACKAGED", "UNAVAILABLE"]
    proposal_status: Literal[
        "VALIDATED",
        "UNAVAILABLE",
        "MODEL_UNAVAILABLE",
        "MODEL_OUTPUT_INVALID",
        "MODEL_OUTPUT_INCONSISTENT",
    ]
    request_consistent: bool
    proposal_consistent: bool
    provider_name: str | None
    model_name: str | None
    result_status: Literal["READY", "INCONSISTENT", "MODEL_UNAVAILABLE", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    source: str

    @model_validator(mode="after")
    def _coherent_result(self) -> ReasoningRunStage7ResultRead:
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        if (self.provider_name is None) != (self.model_name is None):
            raise ValueError("provider_name and model_name must be set together")

        ready_pillars = (
            self.request_status == "PACKAGED"
            and self.proposal_status == "VALIDATED"
            and self.request_consistent
            and self.proposal_consistent
        )
        if self.result_status == "READY":
            if not ready_pillars:
                raise ValueError(
                    "READY requires a packaged request and a validated, "
                    "audited proposal"
                )
            if self.session_id == "":
                raise ValueError("READY requires a session identity")
            if self.request_fingerprint is None:
                raise ValueError("READY requires a request fingerprint")
            if self.provider_name is None:
                raise ValueError("READY requires provider and model metadata")
        elif ready_pillars:
            raise ValueError(
                "result_status must be READY when the request and proposal "
                "are both valid and consistent"
            )

        if self.result_status == "MODEL_UNAVAILABLE":
            if self.request_status != "PACKAGED":
                raise ValueError("MODEL_UNAVAILABLE requires a packaged request")
            if self.proposal_status != "MODEL_UNAVAILABLE":
                raise ValueError(
                    "MODEL_UNAVAILABLE requires the canonical provider failure status"
                )
            if not self.request_consistent:
                raise ValueError("MODEL_UNAVAILABLE requires a consistent request")
            if self.proposal_consistent:
                raise ValueError("MODEL_UNAVAILABLE cannot claim an audited proposal")
            if self.provider_name is not None:
                raise ValueError("MODEL_UNAVAILABLE carries no provider metadata")
        elif self.result_status == "INCONSISTENT":
            if self.request_consistent and self.proposal_consistent:
                raise ValueError(
                    "INCONSISTENT requires a request or proposal integrity failure"
                )
        elif self.result_status == "UNAVAILABLE":
            if self.request_consistent or self.proposal_consistent:
                raise ValueError("UNAVAILABLE certifies no consistency claim")
            if self.provider_name is not None:
                raise ValueError("UNAVAILABLE carries no provider metadata")
        return self
