"""Load hypothesis rules from YAML knowledge files."""

from pathlib import Path

from rop.candidates.models import HypothesisRule


class HypothesisRuleLoadError(Exception):
    """Raised when a hypothesis YAML file cannot be loaded."""


def _parse_rule(raw: dict) -> HypothesisRule:
    """Parse a raw hypothesis dict into a HypothesisRule."""
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise HypothesisRuleLoadError(
            f"Rule missing or invalid 'name': {raw}"
        )

    category = raw.get("category", "General")
    description = raw.get("description", "")
    required_findings = tuple(raw.get("required_findings", []))
    supporting_findings = tuple(raw.get("supporting_findings", []))
    contradicting_findings = tuple(raw.get("contradicting_findings", []))
    risk_factors = tuple(raw.get("risk_factors", []))
    urgency = raw.get("urgency", "low")

    base_score = raw.get("base_score", 0.5)
    if not isinstance(base_score, (int, float)):
        raise HypothesisRuleLoadError(
            f"Rule '{name}' has invalid base_score: {base_score}"
        )

    return HypothesisRule(
        name=name,
        category=category,
        description=description,
        required_findings=required_findings,
        supporting_findings=supporting_findings,
        contradicting_findings=contradicting_findings,
        risk_factors=risk_factors,
        urgency=urgency,
        base_score=float(base_score),
    )


def load_hypothesis_rules(
    directory: str | Path | None = None,
) -> tuple[HypothesisRule, ...]:
    """Load all hypothesis rules from YAML files in a directory."""
    import yaml

    if directory is None:
        directory = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "knowledge"
            / "hypotheses"
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

            if isinstance(data, dict) and "hypotheses" in data:
                raw_rules = data["hypotheses"]
            elif isinstance(data, list):
                raw_rules = data
            else:
                continue

            all_rules.extend(_parse_rule(r) for r in raw_rules)
        except (yaml.YAMLError, HypothesisRuleLoadError):
            continue

    return tuple(all_rules)
