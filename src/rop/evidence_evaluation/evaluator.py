"""Evidence evaluation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

from rop.evidence_evaluation.models import (
    EvidenceEvaluationResult,
    EvidenceRelationship,
    EvidenceRule,
)
from rop.models import Entity, Observation


def _normalize(text: str) -> str:
    return text.lower().strip()


class _ContextItem(NamedTuple):
    """One observation or entity contributing text to a session's context."""

    text: str
    source_id: str | None
    is_entity: bool


@dataclass(frozen=True)
class EvidenceEvaluator:
    """Evaluates a session's observations and entities against evidence rules.

    Required, supporting, and contradicting findings are matched against the
    *combined* text of every observation and entity supplied for a
    hypothesis, not against each item in isolation. A rule such as
    "chest pain" + "left arm radiation" can therefore be satisfied even
    when those two findings were recorded as separate observations,
    matching how a clinician actually reads a case: as one evidence
    context, not a sequence of unrelated facts.
    """

    rules: tuple[EvidenceRule, ...] = field(default_factory=tuple)

    def evaluate_hypothesis(
        self,
        hypothesis_name: str,
        observations: list[Observation],
        entities: list[Entity],
    ) -> list[EvidenceEvaluationResult]:
        """Evaluate every rule for ``hypothesis_name`` against the full session
        context.
        """
        items = [
            _ContextItem(
                text=observation.text, source_id=_safe_id(observation), is_entity=False
            )
            for observation in observations
        ] + [
            _ContextItem(text=entity.name, source_id=_safe_id(entity), is_entity=True)
            for entity in entities
        ]
        matching_rules = self._find_matching_rules(hypothesis_name)
        return [self._evaluate_rule(rule, items) for rule in matching_rules]

    def evaluate_observation(
        self,
        hypothesis_name: str,
        observation: Observation,
    ) -> list[EvidenceEvaluationResult]:
        """Evaluate a single observation in isolation.

        Kept for callers that only have one observation available. Prefer
        ``evaluate_hypothesis`` when the full session context is available,
        since a required finding spanning multiple observations will not be
        recognized here.
        """
        items = [
            _ContextItem(
                text=observation.text, source_id=_safe_id(observation), is_entity=False
            )
        ]
        matching_rules = self._find_matching_rules(
            hypothesis_name, target="observation"
        )
        return [self._evaluate_rule(rule, items) for rule in matching_rules]

    def evaluate_entity(
        self,
        hypothesis_name: str,
        entity: Entity,
    ) -> list[EvidenceEvaluationResult]:
        """Evaluate a single entity in isolation. See ``evaluate_observation``."""
        items = [
            _ContextItem(text=entity.name, source_id=_safe_id(entity), is_entity=True)
        ]
        matching_rules = self._find_matching_rules(hypothesis_name, target="entity")
        return [self._evaluate_rule(rule, items) for rule in matching_rules]

    def _evaluate_rule(
        self, rule: EvidenceRule, items: list[_ContextItem]
    ) -> EvidenceEvaluationResult:
        combined_text = " ".join(_normalize(item.text) for item in items)

        required_met = all(
            _normalize(req) in combined_text for req in rule.required_findings
        )
        if not required_met and rule.required_findings:
            return EvidenceEvaluationResult(
                rule=rule,
                passed=False,
                reason="Required findings not present in session context.",
                matched_data={"combined_text": combined_text},
                relationship=EvidenceRelationship.UNKNOWN,
                matched_finding_count=0,
                total_finding_count=len(rule.supporting_findings)
                + len(rule.contradicting_findings),
                match_strength=0.0,
            )

        supporting_matched, supporting_obs_ids, supporting_ent_ids = _match_findings(
            rule.supporting_findings, items
        )
        contradicting_matched, contradicting_obs_ids, contradicting_ent_ids = (
            _match_findings(rule.contradicting_findings, items)
        )

        relationship, reason = self._determine_relationship(
            supporting_matched, contradicting_matched
        )

        total_configured = len(rule.supporting_findings) + len(
            rule.contradicting_findings
        )
        matched_count = len(supporting_matched) + len(contradicting_matched)
        match_strength = (
            round(matched_count / total_configured, 4) if total_configured else 0.0
        )

        return EvidenceEvaluationResult(
            rule=rule,
            passed=len(supporting_matched) > 0 or len(contradicting_matched) > 0,
            reason=reason,
            matched_data={
                "combined_text": combined_text,
                "supporting_matched": supporting_matched,
                "contradicting_matched": contradicting_matched,
            },
            relationship=relationship,
            matched_finding_count=matched_count,
            total_finding_count=total_configured,
            match_strength=match_strength,
            contributing_observation_ids=tuple(
                dict.fromkeys(supporting_obs_ids + contradicting_obs_ids)
            ),
            contributing_entity_ids=tuple(
                dict.fromkeys(supporting_ent_ids + contradicting_ent_ids)
            ),
        )

    def _find_matching_rules(
        self, hypothesis_name: str, target: str | None = None
    ) -> list[EvidenceRule]:
        normalized_hypothesis = _normalize(hypothesis_name)
        matching = []
        for rule in self.rules:
            if _normalize(rule.hypothesis) != normalized_hypothesis:
                continue
            if target is not None and _normalize(rule.target) != _normalize(target):
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


def _safe_id(item: Observation | Entity) -> str | None:
    item_id = getattr(item, "id", None)
    return str(item_id) if item_id is not None else None


def _match_findings(
    findings: tuple[str, ...], items: list[_ContextItem]
) -> tuple[list[str], list[str], list[str]]:
    """Return matched findings, contributing observation ids, and entity ids."""
    matched: list[str] = []
    observation_ids: list[str] = []
    entity_ids: list[str] = []
    for finding in findings:
        norm_finding = _normalize(finding)
        hit = False
        for item in items:
            if norm_finding in _normalize(item.text):
                hit = True
                if item.source_id is not None:
                    if item.is_entity:
                        entity_ids.append(item.source_id)
                    else:
                        observation_ids.append(item.source_id)
        if hit:
            matched.append(finding)
    return matched, observation_ids, entity_ids
