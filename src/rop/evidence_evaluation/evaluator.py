"""Evidence evaluation engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from rop.evidence_evaluation.models import (
    EvidenceEvaluationResult,
    EvidenceRelationship,
    EvidenceRule,
)
from rop.models import Entity, Observation


def _normalize(text: str) -> str:
    return text.lower().strip()


def _contains_any(text: str, findings: tuple[str, ...]) -> list[str]:
    normalized_text = _normalize(text)
    matched = []
    for finding in findings:
        if _normalize(finding) in normalized_text:
            matched.append(finding)
    return matched


@dataclass(frozen=True)
class EvidenceEvaluator:
    """Evaluates observations and entities against evidence rules."""

    rules: tuple[EvidenceRule, ...] = field(default_factory=tuple)

    def evaluate_observation(
        self,
        hypothesis_name: str,
        observation: Observation,
    ) -> list[EvidenceEvaluationResult]:
        matching_rules = self._find_matching_rules(hypothesis_name, "observation")
        results = []
        for rule in matching_rules:
            supporting = _contains_any(observation.text, rule.supporting_findings)
            contradicting = _contains_any(observation.text, rule.contradicting_findings)

            required_met = True
            for req in rule.required_findings:
                if _normalize(req) not in _normalize(observation.text):
                    required_met = False
                    break

            if not required_met and rule.required_findings:
                continue

            relationship, reason = self._determine_relationship(
                supporting, contradicting
            )

            results.append(
                EvidenceEvaluationResult(
                    rule=rule,
                    passed=len(supporting) > 0 or len(contradicting) > 0,
                    reason=reason,
                    matched_data={
                        "observation_text": observation.text,
                        "supporting_matched": supporting,
                        "contradicting_matched": contradicting,
                    },
                    relationship=relationship,
                )
            )
        return results

    def evaluate_entity(
        self,
        hypothesis_name: str,
        entity: Entity,
    ) -> list[EvidenceEvaluationResult]:
        matching_rules = self._find_matching_rules(hypothesis_name, "entity")
        results = []
        for rule in matching_rules:
            supporting = _contains_any(entity.name, rule.supporting_findings)
            contradicting = _contains_any(entity.name, rule.contradicting_findings)

            required_met = True
            for req in rule.required_findings:
                if _normalize(req) not in _normalize(entity.name):
                    required_met = False
                    break

            if not required_met and rule.required_findings:
                continue

            relationship, reason = self._determine_relationship(
                supporting, contradicting
            )

            results.append(
                EvidenceEvaluationResult(
                    rule=rule,
                    passed=len(supporting) > 0 or len(contradicting) > 0,
                    reason=reason,
                    matched_data={
                        "entity_name": entity.name,
                        "entity_category": entity.category,
                        "supporting_matched": supporting,
                        "contradicting_matched": contradicting,
                    },
                    relationship=relationship,
                )
            )
        return results

    def _find_matching_rules(
        self, hypothesis_name: str, target: str
    ) -> list[EvidenceRule]:
        normalized_hypothesis = _normalize(hypothesis_name)
        matching = []
        for rule in self.rules:
            if _normalize(rule.hypothesis) != normalized_hypothesis:
                continue
            if _normalize(rule.target) != _normalize(target):
                continue
            matching.append(rule)
        return matching

    def _determine_relationship(
        self,
        supporting: list[str],
        contradicting: list[str],
    ) -> tuple[EvidenceRelationship, str]:
        total_supporting = len(supporting)
        total_contradicting = len(contradicting)

        if total_contradicting >= 2:
            return EvidenceRelationship.STRONGLY_CONTRADICTS, (
                f"Multiple contradicting findings matched: {contradicting}"
            )
        if total_contradicting == 1:
            return EvidenceRelationship.CONTRADICTS, (
                f"Contradicting finding matched: {contradicting[0]}"
            )
        if total_supporting >= 2:
            return EvidenceRelationship.STRONGLY_SUPPORTS, (
                f"Multiple supporting findings matched: {supporting}"
            )
        if total_supporting == 1:
            return EvidenceRelationship.SUPPORTS, (
                f"Supporting finding matched: {supporting[0]}"
            )
        return EvidenceRelationship.NEUTRAL, (
            "No supporting or contradicting findings matched."
        )
