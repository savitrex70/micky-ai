from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RuleOperator(StrEnum):
    """Supported comparison operators for rule conditions."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    IN = "in"
    NOT_IN = "not_in"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


@dataclass(frozen=True, slots=True)
class RuleCondition:
    """A single condition within a rule."""

    field: str
    operator: RuleOperator
    value: Any = None


@dataclass(frozen=True, slots=True)
class ExpectedOutcome:
    """Expected result when a rule passes."""

    template_name: str | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Rule:
    """A deterministic rule definition."""

    id: str
    description: str
    priority: int
    conditions: tuple[RuleCondition, ...]
    expected_outcome: ExpectedOutcome = field(default_factory=ExpectedOutcome)


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Result of evaluating a single rule against input data."""

    rule: Rule
    passed: bool
    reason: str
    matched_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Aggregated report of all rule evaluations."""

    evaluations: tuple[EvaluationResult, ...]
    total_rules: int
    passed_count: int
    failed_count: int
    summary: str

    @property
    def passed(self) -> list[EvaluationResult]:
        return [eval for eval in self.evaluations if eval.passed]

    @property
    def failed(self) -> list[EvaluationResult]:
        return [eval for eval in self.evaluations if not eval.passed]
