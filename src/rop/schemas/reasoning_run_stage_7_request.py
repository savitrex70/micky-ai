"""Task 155: canonical Stage 7 provider request contract.

The strict read-only request package produced for exactly one admitted
reasoning session. It carries the session identity, the canonical
context fingerprint, the model-safe payload (exactly the Task 104
payload surface), and the request provenance identifier. Nothing else:
no database handles, no ORM objects, no filesystem paths, no
environment values, no credentials, no private runtime state, no audit
records, no arbitrary metadata. No provider is contacted to build it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator


class ReasoningRunStage7RequestRead(BaseModel):
    """Strict provider request package for one admitted session.

    ``request_status`` is the canonical verdict: ``PACKAGED`` (the Task
    154 admission admitted the session and the canonical Task 055
    context was assembled into the payload), ``BLOCKED`` (admission
    refused the session), or ``UNAVAILABLE`` (admission could not be
    decided or the canonical context could not be read). ``available``
    is always exactly ``request_status == "PACKAGED"``.
    ``context_fingerprint`` is the Task 104 fingerprint of the payload
    and, like ``payload``, is present exactly when the status is
    ``PACKAGED``. ``admission_status`` and
    ``stage_6_certification_status`` mirror the consumed Task 154
    verdict. ``request_source`` is the canonical identifier of this
    contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    request_status: Literal["PACKAGED", "BLOCKED", "UNAVAILABLE"]
    available: bool
    session_id: str
    admission_status: Literal["ADMITTED", "BLOCKED", "UNAVAILABLE"]
    stage_6_certification_status: Literal[
        "CERTIFIED", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL", "UNAVAILABLE"
    ]
    context_fingerprint: str | None
    payload: dict[str, Any] | None
    request_source: str

    @model_validator(mode="after")
    def _coherent_package(self) -> ReasoningRunStage7RequestRead:
        packaged = self.request_status == "PACKAGED"
        if self.available != packaged:
            raise ValueError("available must equal (request_status == 'PACKAGED')")
        if packaged != (self.payload is not None):
            raise ValueError("payload must be present exactly when PACKAGED")
        if packaged != (self.context_fingerprint is not None):
            raise ValueError(
                "context_fingerprint must be present exactly when PACKAGED"
            )
        return self
