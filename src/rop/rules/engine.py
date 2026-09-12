"""Generic rule engine for deterministic rule evaluation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rop.rules.models import (
    EvaluationReport,
    EvaluationResult,
    Rule,
    RuleOperator,
)

_OPERATORS: dict[RuleOperator, Callable[..., bool]] = {}


def _get_operators() -> dict[RuleOperator, Callable[..., bool]]:
    """Return the operator function registry (populated on first call)."""
    if _OPERATORS:
        return _OPERATORS

    _OPERATORS[RuleOperator.EXISTS] = lambda field_val, _: field_val is not None
    _OPERATORS[RuleOperator.NOT_EXISTS] = lambda field_val, _: field_val is None

    def _get_nested(data: dict[str, Any], key: str) -> Any:
        current: Any = data
        for part in key.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    _OPERATORS[RuleOperator.EQUALS] = lambda field_val, val: field_val == val
    _OPERATORS[RuleOperator.NOT_EQUALS] = lambda field_val, val: field_val != val
    _OPERATORS[RuleOperator.CONTAINS] = lambda field_val, val: (
        str(val) in str(field_val) if field_val is not None else False
    )
    _OPERATORS[RuleOperator.NOT_CONTAINS] = lambda field_val, val: (
        str(val) not in str(field_val) if field_val is not None else False
    )
    _OPERATORS[RuleOperator.GREATER_THAN] = lambda field_val, val: (
        field_val > val if isinstance(field_val, (int, float)) else False
    )
    _OPERATORS[RuleOperator.LESS_THAN] = lambda field_val, val: (
        field_val < val if isinstance(field_val, (int, float)) else False
    )
    _OPERATORS[RuleOperator.GREATER_THAN_OR_EQUAL] = lambda field_val, val: (
        field_val >= val if isinstance(field_val, (int, float)) else False
    )
    _OPERATORS[RuleOperator.LESS_THAN_OR_EQUAL] = lambda field_val, val: (
        field_val <= val if isinstance(field_val, (int, float)) else False
    )

    def _in_operator(field_val: Any, val: Any) -> bool:
        if isinstance(val, (list, tuple, set)):
            return field_val in val
        return False

    def _not_in_operator(field_val: Any, val: Any) -> bool:
        if isinstance(val, (list, tuple, set)):
            return field_val not in val
        return True

    _OPERATORS[RuleOperator.IN] = _in_operator
    _OPERATORS[RuleOperator.NOT_IN] = _not_in_operator

    return _OPERATORS


def _get_field(data: dict[str, Any], field: str) -> Any:
    current: Any = data
    for part in field.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


@dataclass(frozen=True)
class RuleEngine:
    """Generic deterministic rule engine."""

    rules: tuple[Rule, ...] = field(default_factory=tuple)
    min_confidence: float = 0.01

    def evaluate(self, data: dict[str, Any]) -> EvaluationReport:
        """Evaluate all rules against the given data."""
        evaluations = tuple(self._evaluate_rule(rule, data) for rule in self.rules)
        passed = sum(1 for eval in evaluations if eval.passed)

        return EvaluationReport(
            evaluations=evaluations,
            total_rules=len(evaluations),
            passed_count=passed,
            failed_count=len(evaluations) - passed,
            summary=(
                f"Evaluated {len(evaluations)} rules: "
                f"{passed} passed, {len(evaluations) - passed} failed."
            ),
        )

    def _evaluate_rule(self, rule: Rule, data: dict[str, Any]) -> EvaluationResult:
        matched_data: dict[str, Any] = {}
        failed_reasons: list[str] = []

        for condition in rule.conditions:
            field_value = _get_field(data, condition.field)
            ops = _get_operators()
            op_func = ops.get(condition.operator)

            if op_func is None:
                failed_reasons.append(f"Unknown operator: {condition.operator.value}")
                continue

            passed = op_func(field_value, condition.value)
            if passed:
                matched_data[condition.field] = field_value
            else:
                failed_reasons.append(
                    f"Condition failed: {condition.field} "
                    f"{condition.operator.value} {condition.value!r} "
                    f"(got {field_value!r})"
                )

        passed = len(failed_reasons) == 0
        if passed:
            reason = f"All {len(rule.conditions)} conditions matched."
        else:
            reason = "; ".join(failed_reasons)

        return EvaluationResult(
            rule=rule,
            passed=passed,
            reason=reason,
            matched_data=matched_data,
        )

    def select_best(self, data: dict[str, Any]) -> EvaluationResult | None:
        """Evaluate rules and return the highest-priority passed rule."""
        report = self.evaluate(data)
        passed = report.passed
        if not passed:
            return None
        return min(passed, key=lambda eval: eval.rule.priority)
