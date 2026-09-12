"""Candidate hypothesis generation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from rop.candidates.models import (
    GeneratedCandidate,
    HypothesisRule,
)
from rop.models import Entity, Observation
from rop.schemas import MissingInformationRead
from rop.templates import ClinicalTemplate


def _normalize(text: str) -> str:
    return text.lower().strip()


def _collect_observation_texts(
    observations: list[Observation],
    entities: list[Entity],
) -> list[str]:
    texts = []
    for obs in observations:
        texts.append(_normalize(obs.text))
    for entity in entities:
        texts.append(_normalize(entity.name))
    return texts


def _collect_missing_info(
    missing_items: list[MissingInformationRead] | list[dict[str, Any]] | None,
) -> list[str]:
    if not missing_items:
        return []

    result = []
    for item in missing_items:
        if isinstance(item, MissingInformationRead):
            result.append(_normalize(item.item))
        elif isinstance(item, dict):
            field_name = item.get("field_name", item.get("item", ""))
            result.append(_normalize(field_name))
        else:
            result.append(_normalize(str(item)))
    return result


def _find_matching_observations(
    observations: list[str],
    findings: tuple[str, ...],
) -> list[str]:
    matched = []
    for finding in findings:
        normalized_finding = _normalize(finding)
        for obs in observations:
            if normalized_finding in obs:
                matched.append(finding)
                break
    return matched


def _check_required_findings(
    all_texts: list[str],
    rule: HypothesisRule,
    missing_fields: list[str],
) -> tuple[bool, list[str]]:
    missing_required = []
    for finding in rule.required_findings:
        normalized_finding = _normalize(finding)
        in_observations = any(normalized_finding in text for text in all_texts)
        in_missing = normalized_finding in missing_fields
        if not in_observations and not in_missing:
            missing_required.append(finding)

    return len(missing_required) == 0, missing_required


def _score_candidate(
    rule: HypothesisRule,
    supporting_matched: list[str],
    contradicting_matched: list[str],
) -> float:
    score = rule.base_score
    score += len(supporting_matched) * 0.05
    score -= len(contradicting_matched) * 0.1
    if len(contradicting_matched) > 0:
        score *= 0.7
    return round(max(score, 0.0), 4)


@dataclass(frozen=True)
class CandidateGenerator:
    """Generates candidate hypotheses from observations and rules."""

    rules: tuple[HypothesisRule, ...] = field(default_factory=tuple)

    def generate(
        self,
        session_id: UUID,
        observations: list[Observation],
        entities: list[Entity],
        template: ClinicalTemplate | None = None,
        missing_information: (
            list[MissingInformationRead] | list[dict[str, Any]] | None
        ) = None,
    ) -> tuple[GeneratedCandidate, ...]:
        all_texts = _collect_observation_texts(observations, entities)
        missing_fields = _collect_missing_info(missing_information)

        if template is not None:
            rules_to_use = self._filter_rules_by_template(template)
        else:
            rules_to_use = self.rules

        candidates = []
        for rule in rules_to_use:
            required_met, missing_required = _check_required_findings(
                all_texts, rule, missing_fields
            )
            if not required_met:
                continue

            supporting_matched = _find_matching_observations(
                all_texts, rule.supporting_findings
            )
            contradicting_matched = _find_matching_observations(
                all_texts, rule.contradicting_findings
            )

            score = _score_candidate(rule, supporting_matched, contradicting_matched)
            confidence = round(min(score, 1.0), 4)

            matched_findings = []
            matched_findings.extend(supporting_matched)
            matched_findings.extend(contradicting_matched)

            if matched_findings:
                trigger_reason = (
                    f"Required findings matched. "
                    f"Supporting: {len(supporting_matched)}, "
                    f"Contradicting: {len(contradicting_matched)}."
                )
            else:
                trigger_reason = (
                    "Required findings matched. "
                    "No supporting or contradicting findings found."
                )

            missing_info_for_candidate = tuple(
                f for f in missing_fields if f in rule.required_findings
            )

            candidates.append(
                GeneratedCandidate(
                    rule=rule,
                    supporting_observations=tuple(supporting_matched),
                    contradicting_observations=tuple(contradicting_matched),
                    missing_information=missing_info_for_candidate,
                    initial_score=score,
                    confidence=confidence,
                    trigger_reason=trigger_reason,
                )
            )

        candidates.sort(key=lambda c: c.initial_score, reverse=True)
        return tuple(candidates)

    def _filter_rules_by_template(
        self, template: ClinicalTemplate
    ) -> tuple[HypothesisRule, ...]:
        matching_rules = []
        for rule in self.rules:
            for category in rule.category.split(","):
                if _normalize(category) in _normalize(template.category):
                    matching_rules.append(rule)
                    break
                if _normalize(template.name) in _normalize(rule.name):
                    matching_rules.append(rule)
                    break
                if rule.name.replace("_", " ") in _normalize(template.name):
                    matching_rules.append(rule)
                    break

        if matching_rules:
            return tuple(matching_rules)
        return self.rules
