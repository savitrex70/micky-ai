from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EvidenceRelationship(StrEnum):
    """Relationship between an observation/entity and a hypothesis."""

    STRONGLY_SUPPORTS = "strongly_supports"
    SUPPORTS = "supports"
    NEUTRAL = "neutral"
    CONTRADICTS = "contradicts"
    STRONGLY_CONTRADICTS = "strongly_contradicts"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EvidenceRule:
    """An evidence rule definition loaded from YAML."""

    rule_id: str
    hypothesis: str
    target: str
    required_findings: tuple[str, ...]
    supporting_findings: tuple[str, ...]
    contradicting_findings: tuple[str, ...]
    weight: float
    confidence: float
    reason: str
    source: str


@dataclass(frozen=True, slots=True)
class EvidenceEvaluationResult:
    """Result of evaluating one rule against a session's evidence context.

    ``rule.weight`` is the static weight declared in the rule's YAML
    definition — it never changes based on what was actually observed.
    ``match_strength`` and ``matched_finding_count``/``total_finding_count``
    describe how much of the rule's configured findings were actually
    present, so a future scoring engine can combine the two (e.g.
    ``contribution = rule.weight * match_strength``) instead of treating
    every match of a rule as identical regardless of how much evidence
    backed it.
    """

    rule: EvidenceRule
    passed: bool
    reason: str
    matched_data: dict[str, Any] = field(default_factory=dict)
    relationship: EvidenceRelationship = EvidenceRelationship.NEUTRAL
    matched_finding_count: int = 0
    total_finding_count: int = 0
    match_strength: float = 0.0
    contributing_observation_ids: tuple[str, ...] = ()
    contributing_entity_ids: tuple[str, ...] = ()
