"""Template matching engine."""

from __future__ import annotations

from rop.models import Entity, Observation
from rop.templates.clinical_template import (
    ClinicalTemplate,
    MatchCandidate,
    TemplateMatchResult,
    TemplateRule,
)


def _normalize(text: str) -> str:
    return text.lower().strip()


def _observation_matches_rule(
    observation: Observation, rule: TemplateRule
) -> bool:
    observation_type = _normalize(observation.type)
    observation_text = _normalize(observation.text)
    category = _normalize(rule.category)
    if observation_type != category:
        return False
    return any(term.lower() in observation_text for term in rule.terms)


def _entity_matches_rule(entity: Entity, rule: TemplateRule) -> bool:
    entity_category = _normalize(entity.category)
    entity_name = _normalize(entity.name)
    category = _normalize(rule.category)
    if entity_category != category:
        return False
    return any(term.lower() in entity_name for term in rule.terms)


def _score_template(
    template: ClinicalTemplate,
    observations: list[Observation],
    entities: list[Entity],
) -> MatchCandidate:
    total_rule_categories = len(template.trigger_rules)
    if total_rule_categories == 0:
        return MatchCandidate(
            template=template,
            score=0.0,
            matched_observation_count=0,
            matched_entity_count=0,
            matched_rule_categories=0,
            total_rule_categories=0,
            matched_observation_texts=(),
            matched_entity_names=(),
        )

    matched_observation_texts: list[str] = []
    matched_entity_names: list[str] = []
    matched_rule_categories = 0
    category_matched_observations: dict[str, bool] = {}
    category_matched_entities: dict[str, bool] = {}

    for rule in template.trigger_rules:
        category_key = rule.category.lower()
        if not category_matched_observations.get(category_key):
            for observation in observations:
                if _observation_matches_rule(observation, rule):
                    matched_observation_texts.append(observation.text)
                    category_matched_observations[category_key] = True
                    break
        if not category_matched_entities.get(category_key):
            for entity in entities:
                if _entity_matches_rule(entity, rule):
                    matched_entity_names.append(entity.name)
                    category_matched_entities[category_key] = True
                    break

    for rule in template.trigger_rules:
        category_key = rule.category.lower()
        if category_matched_observations.get(category_key) or (
            category_matched_entities.get(category_key)
        ):
            matched_rule_categories += 1

    raw_score = matched_rule_categories / total_rule_categories
    priority_factor = 1.0 / max(template.priority, 1)
    score = raw_score * priority_factor

    return MatchCandidate(
        template=template,
        score=score,
        matched_observation_count=len(matched_observation_texts),
        matched_entity_count=len(matched_entity_names),
        matched_rule_categories=matched_rule_categories,
        total_rule_categories=total_rule_categories,
        matched_observation_texts=tuple(dict.fromkeys(matched_observation_texts)),
        matched_entity_names=tuple(dict.fromkeys(matched_entity_names)),
    )


def match_template(
    templates: tuple[ClinicalTemplate, ...],
    observations: list[Observation],
    entities: list[Entity],
    *,
    min_score: float = 0.01,
) -> TemplateMatchResult:
    """Select the best matching clinical template."""
    candidates = tuple(
        _score_template(template, observations, entities) for template in templates
    )
    valid_candidates = tuple(
        candidate for candidate in candidates if candidate.score >= min_score
    )

    if not valid_candidates:
        return _fallback_result(templates, observations, entities, candidates)

    best = max(valid_candidates, key=lambda candidate: candidate.score)
    reason = _build_reason(best)
    return TemplateMatchResult(
        selected_template=best.template,
        confidence=min(best.score, 1.0),
        matched_observations=best.matched_observation_texts,
        matched_entities=best.matched_entity_names,
        reason=reason,
        candidates=candidates,
    )


def _build_reason(candidate: MatchCandidate) -> str:
    template_name = candidate.template.name
    matched_obs = candidate.matched_observation_count
    matched_entities = candidate.matched_entity_count
    matched_rules = candidate.matched_rule_categories
    total_rules = candidate.total_rule_categories
    return (
        f"Selected '{template_name}' with score {candidate.score:.2f}. "
        f"Matched {matched_rules}/{total_rules} rule categories, "
        f"{matched_obs} observations, and {matched_entities} entities."
    )


def _fallback_result(
    templates: tuple[ClinicalTemplate, ...],
    observations: list[Observation],
    entities: list[Entity],
    all_candidates: tuple[MatchCandidate, ...],
) -> TemplateMatchResult:
    general = next(
        (template for template in templates if template.name == "general_assessment"),
        None,
    )
    if general is None:
        general = ClinicalTemplate(
            name="general_assessment",
            category="General",
            description="Default general clinical assessment template.",
            priority=99,
            trigger_rules=(),
            required_information=(
                "age",
                "sex",
                "chief_complaint",
                "vital_signs",
                "medical_history",
                "medications",
            ),
        )

    candidate = MatchCandidate(
        template=general,
        score=0.1,
        matched_observation_count=0,
        matched_entity_count=0,
        matched_rule_categories=0,
        total_rule_categories=0,
        matched_observation_texts=(),
        matched_entity_names=(),
    )

    obs_texts = ", ".join(observation.text for observation in observations) or "none"
    entities_text = ", ".join(entity.name for entity in entities) or "none"
    reason = (
        "No specific template matched sufficiently. "
        f"Falling back to 'general_assessment'. "
        f"Observations: {obs_texts}. Entities: {entities_text}."
    )

    return TemplateMatchResult(
        selected_template=general,
        confidence=0.1,
        matched_observations=(),
        matched_entities=(),
        reason=reason,
        candidates=(candidate,),
    )
