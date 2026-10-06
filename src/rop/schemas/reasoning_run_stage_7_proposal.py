"""Task 158: Stage 7 provider response boundary contract.

Strict read-only projection of one Stage 7 provider-response verdict.
The projection carries the canonical Task 057 outcome value when a raw
provider response could not be validated into a proposal, and -- only
when the complete canonical pipeline validated it -- the approved
public Task 057 proposal surface plus the provider/model identity read
once through the Task 107 helpers. Raw provider text and the raw
provider response object are never part of this projection. Failure
statuses reuse the Task 057 outcome values verbatim; no competing
taxonomy is defined here.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ReasoningRunStage7ProposalRead(BaseModel):
    """Strict proposal verdict for one Task 157 dispatch result.

    ``proposal_status`` is ``VALIDATED`` (the raw provider response
    passed every canonical stage and ``proposal`` carries the approved
    Task 057 public surface), one of the canonical Task 057 outcome
    values (``MODEL_UNAVAILABLE``, ``MODEL_OUTPUT_INVALID``,
    ``MODEL_OUTPUT_INCONSISTENT``), or ``UNAVAILABLE`` (the dispatch or
    the validation material could not be read). ``available`` is
    always exactly ``proposal_status == "VALIDATED"``;
    ``context_fingerprint``, ``provider``, ``model``, and ``proposal``
    are present exactly when ``VALIDATED``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    proposal_status: Literal[
        "VALIDATED",
        "MODEL_UNAVAILABLE",
        "MODEL_OUTPUT_INVALID",
        "MODEL_OUTPUT_INCONSISTENT",
        "UNAVAILABLE",
    ]
    available: bool
    session_id: str
    context_fingerprint: str | None
    provider: str | None
    model: str | None
    proposal: dict[str, Any] | None
    proposal_source: str

    @model_validator(mode="after")
    def _coherent_proposal(self) -> ReasoningRunStage7ProposalRead:
        validated = self.proposal_status == "VALIDATED"
        if self.available != validated:
            raise ValueError("available must equal (proposal_status == 'VALIDATED')")
        if validated != (self.proposal is not None):
            raise ValueError("proposal must be present exactly when VALIDATED")
        if validated != (self.context_fingerprint is not None):
            raise ValueError(
                "context_fingerprint must be present exactly when VALIDATED"
            )
        if validated != (self.provider is not None):
            raise ValueError("provider must be present exactly when VALIDATED")
        if validated != (self.model is not None):
            raise ValueError("model must be present exactly when VALIDATED")
        return self
