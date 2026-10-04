"""Load evidence evaluation rules from YAML files."""

from pathlib import Path

from rop.evidence_evaluation.models import EvidenceRule


class EvidenceRuleLoadError(Exception):
    """Raised when an evidence rule YAML file cannot be loaded."""


def _parse_rule(raw: dict) -> EvidenceRule:
    """Parse a raw rule dict into an EvidenceRule."""
    rule_id = raw.get("rule_id")
    if not rule_id or not isinstance(rule_id, str):
        raise EvidenceRuleLoadError(f"Rule missing or invalid 'rule_id': {raw}")

    hypothesis = raw.get("hypothesis")
    if not hypothesis or not isinstance(hypothesis, str):
        raise EvidenceRuleLoadError(f"Rule '{rule_id}' missing or invalid 'hypothesis'")

    target = raw.get("target", "observation")

    def _to_tuple(key: str) -> tuple[str, ...]:
        value = raw.get(key, [])
        if not isinstance(value, list):
            raise EvidenceRuleLoadError(
                f"Rule '{rule_id}' has invalid '{key}': must be a list"
            )
        return tuple(value)

    required_findings = _to_tuple("required_findings")
    supporting_findings = _to_tuple("supporting_findings")
    contradicting_findings = _to_tuple("contradicting_findings")

    weight = raw.get("weight", 0.5)
    if not isinstance(weight, (int, float)):
        raise EvidenceRuleLoadError(f"Rule '{rule_id}' has invalid weight: {weight}")

    confidence = raw.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)):
        raise EvidenceRuleLoadError(
            f"Rule '{rule_id}' has invalid confidence: {confidence}"
        )

    reason = raw.get("reason", "")
    source = raw.get("source", "evidence_rules")

    return EvidenceRule(
        rule_id=rule_id,
        hypothesis=hypothesis,
        target=target,
        required_findings=required_findings,
        supporting_findings=supporting_findings,
        contradicting_findings=contradicting_findings,
        weight=float(weight),
        confidence=float(confidence),
        reason=reason,
        source=source,
    )


def parse_evidence_rule(raw: dict) -> EvidenceRule:
    """Parse a raw rule dict into an EvidenceRule."""
    return _parse_rule(raw)


def load_evidence_rules(
    directory: str | Path | None = None,
) -> tuple[EvidenceRule, ...]:
    """Load all evidence rules from YAML files in a directory."""
    import yaml

    if directory is None:
        directory = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "knowledge"
            / "evidence_rules"
        )
    else:
        directory = Path(directory)

    if not directory.exists():
        return ()

    all_rules = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            with path.open(encoding="utf-8") as handle:
                data = yaml.safe_load(handle)

            if data is None:
                continue

            if isinstance(data, dict) and "rules" in data:
                raw_rules = data["rules"]
            elif isinstance(data, list):
                raw_rules = data
            else:
                continue

            all_rules.extend(_parse_rule(r) for r in raw_rules)
        except (yaml.YAMLError, EvidenceRuleLoadError):
            continue

    return tuple(all_rules)
