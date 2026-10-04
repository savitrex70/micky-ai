"""Task 130: deterministic evidence-hypothesis lineage contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LineageEvidenceRead(BaseModel):
    """One evaluated evidence row traced to its hypothesis."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    evidence_id: str
    rule_id: str
    relationship: str
    weight: float
    contribution: float
    observation_id: str | None
    entity_id: str | None


class HypothesisLineageRead(BaseModel):
    """Complete traceability record for one hypothesis/candidate."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    hypothesis_id: str
    hypothesis_name: str
    originating_observation_ids: list[str]
    originating_entity_ids: list[str]
    supporting_evidence: list[LineageEvidenceRead]
    contradicting_evidence: list[LineageEvidenceRead]
    total_support_contribution: float
    total_contradiction_contribution: float
    hypothesis_score: float
    score_source: str
    rank: int | None
    is_tied: bool | None
    unresolved_information: list[str]
    lineage_complete: bool


class EvidenceHypothesisLineageRead(BaseModel):
    """Session-level lineage contract over all hypotheses."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    available: bool
    lineage_consistent: bool
    session_id: str
    lineages: list[HypothesisLineageRead]
    consistency_issues: list[str]
    lineage_source: str
