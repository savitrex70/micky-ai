"""Task 157: Stage 7 explicit provider dispatch contract.

Strict read-only projection of one explicit provider dispatch. The
projection records whether the approved Task 155 request package,
audited consistent by Task 156, was handed to an explicitly injected
generic provider, plus the canonical Task 057 outcome when a provider
failure prevented the dispatch. The raw provider response is untrusted
provider surface and is never part of this projection; the Task 158
response boundary is its only reader.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

BoundaryOutcome = Literal[
    "INPUT_UNAVAILABLE",
    "INPUT_INCONSISTENT",
    "MODEL_UNAVAILABLE",
    "MODEL_OUTPUT_INVALID",
    "MODEL_OUTPUT_INCONSISTENT",
]


class ReasoningRunStage7DispatchRead(BaseModel):
    """Strict dispatch verdict for one approved request package.

    ``dispatch_status`` is the canonical verdict: ``DISPATCHED`` (the
    package was packaged, its audit was consistent, and its request was
    handed to the explicitly injected provider), ``BLOCKED`` (the
    package or its audit failed integrity, so no provider was
    contacted), or ``UNAVAILABLE`` (required material could not be read,
    or a provider failure prevented the dispatch -- ``outcome`` then
    carries the canonical Task 057 classification). ``available`` is
    always exactly ``dispatch_status == "DISPATCHED"``.
    ``request_fingerprint`` is present exactly when ``DISPATCHED`` and
    is the exact fingerprint handed to the provider. ``outcome`` is
    present exactly when ``UNAVAILABLE``.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    dispatch_status: Literal["DISPATCHED", "BLOCKED", "UNAVAILABLE"]
    available: bool
    session_id: str
    request_status: Literal["PACKAGED", "BLOCKED", "UNAVAILABLE"] | None
    request_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"] | None
    request_fingerprint: str | None
    outcome: BoundaryOutcome | None
    dispatch_source: str

    @model_validator(mode="after")
    def _coherent_dispatch(self) -> ReasoningRunStage7DispatchRead:
        if self.available != (self.dispatch_status == "DISPATCHED"):
            raise ValueError("available must equal (dispatch_status == 'DISPATCHED')")
        if self.dispatch_status == "DISPATCHED":
            if self.request_status != "PACKAGED":
                raise ValueError("DISPATCHED requires request_status == 'PACKAGED'")
            if self.request_audit_status != "CONSISTENT":
                raise ValueError(
                    "DISPATCHED requires request_audit_status == 'CONSISTENT'"
                )
            if self.request_fingerprint is None:
                raise ValueError("DISPATCHED requires a request_fingerprint")
            if self.outcome is not None:
                raise ValueError("DISPATCHED must not carry an outcome")
        else:
            if self.request_fingerprint is not None:
                raise ValueError(
                    "request_fingerprint is present exactly when DISPATCHED"
                )
            if self.dispatch_status == "BLOCKED" and self.outcome is not None:
                raise ValueError("BLOCKED must not carry an outcome")
            if self.dispatch_status == "UNAVAILABLE" and self.outcome is None:
                raise ValueError("UNAVAILABLE requires a canonical outcome")
        return self
