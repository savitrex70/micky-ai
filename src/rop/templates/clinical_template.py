"""Clinical template system for template matching."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TemplateRule:
    """One trigger rule category and its matching terms."""

    category: str
    terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClinicalTemplate:
    """A clinical template with trigger rules and required information."""

    name: str
    category: str
    description: str
    priority: int
    trigger_rules: tuple[TemplateRule, ...]
    required_information: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """A single template match candidate with its score details."""

    template: ClinicalTemplate
    score: float
    matched_observation_count: int
    matched_entity_count: int
    matched_rule_categories: int
    total_rule_categories: int
    matched_observation_texts: tuple[str, ...]
    matched_entity_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TemplateMatchResult:
    """Result of running template matching for a session."""

    selected_template: ClinicalTemplate
    confidence: float
    matched_observations: tuple[str, ...]
    matched_entities: tuple[str, ...]
    reason: str
    candidates: tuple[MatchCandidate, ...]
