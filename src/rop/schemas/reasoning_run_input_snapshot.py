"""Task 124: canonical deterministic reasoning-run input snapshot contract.

The public snapshot shape: every input collection a reasoning run
depends on, frozen as JSON-safe data with explicit ordering and a fixed
provenance source. Validated with ``extra="forbid"`` so no stage can
smuggle unapproved input state into the snapshot.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from rop.schemas.candidate_hypothesis import CandidateHypothesisRead
from rop.schemas.entity import EntityRead
from rop.schemas.evaluated_evidence import EvaluatedEvidenceRead
from rop.schemas.missing_information import MissingInformationRead
from rop.schemas.observation import ObservationRead
from rop.schemas.template_match import TemplateMatchRead


class ReasoningRunInputSnapshotRead(BaseModel):
    """One frozen record of all reasoning-run inputs, read exactly once
    before execution."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    session_id: UUID
    user_input: str
    observations: list[ObservationRead]
    entities: list[EntityRead]
    missing_information: list[MissingInformationRead]
    template_matches: list[TemplateMatchRead]
    candidates: list[CandidateHypothesisRead]
    evidence: list[EvaluatedEvidenceRead]
    candidate_order: list[str]
    evidence_order: list[str]
    snapshot_source: str
