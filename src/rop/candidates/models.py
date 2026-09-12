from dataclasses import dataclass
from uuid import UUID

from rop.models.hypothesis import HypothesisStatus


@dataclass(frozen=True, slots=True)
class HypothesisRule:
    """A hypothesis definition loaded from YAML knowledge files."""

    name: str
    category: str
    description: str
    required_findings: tuple[str, ...]
    supporting_findings: tuple[str, ...]
    contradicting_findings: tuple[str, ...]
    risk_factors: tuple[str, ...]
    urgency: str
    base_score: float


@dataclass(frozen=True, slots=True)
class CandidateHypothesis:
    """A generated candidate hypothesis for a reasoning session."""

    id: UUID
    session_id: UUID
    name: str
    category: str
    trigger_reason: str
    initial_score: float
    confidence: float
    supporting_observations: tuple[str, ...]
    contradicting_observations: tuple[str, ...]
    missing_information: tuple[str, ...]
    status: HypothesisStatus = HypothesisStatus.PENDING
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class GeneratedCandidate:
    """Intermediate result of candidate generation before persistence."""

    rule: HypothesisRule
    supporting_observations: tuple[str, ...]
    contradicting_observations: tuple[str, ...]
    missing_information: tuple[str, ...]
    initial_score: float
    confidence: float
    trigger_reason: str
