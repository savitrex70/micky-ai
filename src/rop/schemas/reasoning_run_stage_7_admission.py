"""Task 154: Stage 7 per-session LLM admission contract.

The strict read-only admission response for one reasoning session. The
separate per-session decision that precedes any Stage 7 reasoning
request: Task 153 confirms the Stage 7 boundary itself is structurally
healthy, while this contract answers whether this specific session is
eligible to enter the LLM reasoning path. The service consumes the
canonical Task 152 Stage 6 certification and never reproduces
certification logic. No persistence, no provider calls, no network.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningRunStage7AdmissionRead(BaseModel):
    """Strict per-session LLM admission for one session.

    ``admission_status`` is the canonical verdict and is always exactly
    ``admitted == (admission_status == "ADMITTED")``:

    ``ADMITTED`` (the canonical Stage 6 certification is ``CERTIFIED``
    and the consumed record is internally coherent), ``BLOCKED``
    (``NO_MATERIAL`` -- an empty deterministic session must never be
    sent to an LLM -- or any ``BLOCKED``/``UNVERIFIABLE``
    certification, or an incoherent certification record), and
    ``UNAVAILABLE`` (the canonical certification cannot be read or
    projected, so the question cannot be answered without fabricating
    evidence).

    ``stage_6_certification_status`` is the consumed Task 152 verdict,
    or ``UNAVAILABLE`` when it could not be read.
    ``stage_6_release_ready`` and ``stage_6_certification_consistent``
    mirror the consumed record and are fail-closed (``False``) when the
    certification cannot be read; ``stage_6_certification_consistent``
    holds the record's canonical coherence invariant (``certified`` is
    true exactly when ``certification_status`` is ``CERTIFIED``, and
    ``release_ready`` mirrors ``certified``). ``admission_source`` is
    the canonical identifier of this admission contract.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    requested_session_id: str
    admission_status: Literal["ADMITTED", "BLOCKED", "UNAVAILABLE"]
    admitted: bool
    stage_6_certification_status: Literal[
        "CERTIFIED", "BLOCKED", "UNVERIFIABLE", "NO_MATERIAL", "UNAVAILABLE"
    ]
    stage_6_release_ready: bool
    stage_6_certification_consistent: bool
    finding_count: int
    findings: list[str]
    admission_source: str
