"""Rule loading from YAML."""

from pathlib import Path

from rop.rules.models import (
    ExpectedOutcome,
    Rule,
    RuleCondition,
    RuleOperator,
)


class RuleLoadError(Exception):
    """Raised when a rule file cannot be loaded."""


def _parse_condition(raw: dict) -> RuleCondition:
    """Parse a single condition dict into a RuleCondition."""
    field = raw.get("field")
    operator = raw.get("operator")
    value = raw.get("value")

    if not field or not isinstance(field, str):
        raise RuleLoadError(f"Condition missing or invalid 'field': {raw}")

    if not operator or operator not in {op.value for op in RuleOperator}:
        raise RuleLoadError(
            f"Condition for '{field}' has invalid operator '{operator}'. "
            f"Allowed: {[op.value for op in RuleOperator]}"
        )

    if operator not in ("exists", "not_exists") and value is None:
        raise RuleLoadError(
            f"Condition for '{field}' with operator '{operator}' requires a 'value'"
        )

    return RuleCondition(
        field=field,
        operator=RuleOperator(operator),
        value=value,
    )


def _parse_outcome(raw: dict | None) -> ExpectedOutcome:
    """Parse an expected_outcome dict into ExpectedOutcome."""
    if raw is None:
        return ExpectedOutcome()

    confidence = raw.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)):
        raise RuleLoadError(
            f"Invalid confidence value: {confidence}"
        )

    return ExpectedOutcome(
        template_name=raw.get("template_name"),
        confidence=float(confidence),
        metadata=raw.get("metadata", {}),
    )


def _parse_rule(raw: dict) -> Rule:
    """Parse a raw rule dict into a Rule object."""
    rule_id = raw.get("id")
    if not rule_id or not isinstance(rule_id, str):
        raise RuleLoadError(f"Rule missing or invalid 'id': {raw}")

    description = raw.get("description", "")
    priority = raw.get("priority", 0)

    if not isinstance(priority, int):
        raise RuleLoadError(
            f"Rule '{rule_id}' has invalid priority: {priority}"
        )

    raw_conditions = raw.get("conditions")
    if not raw_conditions or not isinstance(raw_conditions, list):
        raise RuleLoadError(
            f"Rule '{rule_id}' missing or invalid 'conditions'"
        )

    conditions = tuple(_parse_condition(c) for c in raw_conditions)
    expected_outcome = _parse_outcome(raw.get("expected_outcome"))

    return Rule(
        id=rule_id,
        description=description,
        priority=priority,
        conditions=conditions,
        expected_outcome=expected_outcome,
    )


def parse_rule(raw: dict) -> Rule:
    """Parse a raw rule dict into a Rule object."""
    return _parse_rule(raw)


def load_rules_from_file(path: str | Path) -> tuple[Rule, ...]:
    """Load rules from a single YAML file."""
    import yaml

    path = Path(path)
    if not path.exists():
        raise RuleLoadError(f"Rule file not found: {path}")

    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if data is None:
        return ()

    if isinstance(data, dict) and "rules" in data:
        raw_rules = data["rules"]
    elif isinstance(data, list):
        raw_rules = data
    else:
        raise RuleLoadError(
            f"Unexpected YAML structure in {path}: expected 'rules' key or list"
        )

    return tuple(_parse_rule(r) for r in raw_rules)


def load_rules_from_directory(
    directory: str | Path | None = None,
) -> tuple[Rule, ...]:
    """Load all rules from YAML files in a directory."""
    import yaml

    if directory is None:
        directory = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "knowledge"
            / "rules"
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
        except (yaml.YAMLError, RuleLoadError):
            continue

    return tuple(all_rules)
