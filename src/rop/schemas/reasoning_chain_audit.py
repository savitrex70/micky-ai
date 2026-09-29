"""Task 129: independent full deterministic reasoning-chain audit contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReasoningChainAuditRead(BaseModel):
    """Strict result of the independent full-chain audit."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    available: bool
    chain_consistent: bool
    session_consistent: bool
    input_consistent: bool
    extraction_consistent: bool
    missing_info_consistent: bool
    template_consistent: bool
    candidate_consistent: bool
    evidence_consistent: bool
    scoring_consistent: bool
    ranking_consistent: bool
    pipeline_consistent: bool
    execution_consistent: bool
    provenance_consistent: bool
    input_fingerprint: str
    consistency_issues: list[str]
    audit_source: str
