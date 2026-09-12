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
    """Result of evaluating a single rule against an observation or entity."""

    rule: EvidenceRule
    passed: bool
    reason: str
    matched_data: dict[str, Any] = field(default_factory=dict)
    relationship: EvidenceRelationship = EvidenceRelationship.NEUTRAL
