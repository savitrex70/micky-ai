import time

import pytest

from rop.rules import (
    RuleEngine,
    RuleLoadError,
    load_rules_from_directory,
    load_rules_from_file,
    parse_rule,
)
from rop.rules.models import EvaluationReport, EvaluationResult, Rule, RuleOperator


def _make_rule(
    rule_id: str,
    conditions: list[dict],
    priority: int = 0,
    description: str = "test rule",
) -> Rule:
    return parse_rule(
        {
            "id": rule_id,
            "description": description,
            "priority": priority,
            "conditions": conditions,
        }
    )


def test_rule_loading_from_yaml_file() -> None:
    rules = load_rules_from_file(
        "knowledge/rules/clinical_rules.yaml"
    )

    assert len(rules) == 4
    rule_ids = {rule.id for rule in rules}
    assert "acs_chest_pain" in rule_ids
    assert "stroke_fac_droop" in rule_ids
    assert "pe_shortness_breath" in rule_ids
    assert "diabetes_polyuria" in rule_ids


def test_rule_loading_from_directory() -> None:
    rules = load_rules_from_directory()

    assert len(rules) == 4
    assert all(rule.id for rule in rules)


def test_rule_loading_handles_missing_directory() -> None:
    rules = load_rules_from_directory("/nonexistent/path/to/rules")
    assert rules == ()


def test_parse_rule_valid() -> None:
    rule = parse_rule(
        {
            "id": "test_rule",
            "description": "A test rule",
            "priority": 1,
            "conditions": [
                {"field": "symptoms", "operator": "contains", "value": "fever"},
            ],
            "expected_outcome": {
                "template_name": "infection",
                "confidence": 0.8,
            },
        }
    )

    assert rule.id == "test_rule"
    assert rule.description == "A test rule"
    assert rule.priority == 1
    assert len(rule.conditions) == 1
    assert rule.conditions[0].operator == RuleOperator.CONTAINS
    assert rule.expected_outcome.template_name == "infection"
    assert rule.expected_outcome.confidence == 0.8


def test_parse_rule_invalid_operator() -> None:
    with pytest.raises(RuleLoadError):
        parse_rule(
            {
                "id": "bad_rule",
                "conditions": [
                    {"field": "x", "operator": "invalid_op", "value": "y"},
                ],
            }
        )


def test_parse_rule_missing_id() -> None:
    with pytest.raises(RuleLoadError):
        parse_rule(
            {
                "description": "no id",
                "conditions": [
                    {"field": "x", "operator": "equals", "value": "y"},
                ],
            }
        )


def test_parse_rule_missing_conditions() -> None:
    with pytest.raises(RuleLoadError):
        parse_rule(
            {
                "id": "no_conditions",
                "description": "no conditions",
            }
        )


def test_parse_rule_exists_without_value() -> None:
    rule = parse_rule(
        {
            "id": "exists_rule",
            "conditions": [
                {"field": "notes", "operator": "exists"},
            ],
        }
    )
    assert rule.conditions[0].value is None


def test_parse_rule_missing_value_raises() -> None:
    with pytest.raises(RuleLoadError):
        parse_rule(
            {
                "id": "missing_value",
                "conditions": [
                    {"field": "notes", "operator": "contains"},
                ],
            }
        )


def test_rule_execution_passes() -> None:
    rule = _make_rule(
        "match_rule",
        [
            {"field": "symptoms", "operator": "contains", "value": "chest pain"},
            {"field": "body_location", "operator": "contains", "value": "left arm"},
        ],
        priority=1,
    )
    engine = RuleEngine(rules=(rule,))

    data = {
        "symptoms": "Patient reports chest pain",
        "body_location": "Pain radiates to left arm",
    }

    result = engine.evaluate(data)
    assert isinstance(result, EvaluationReport)
    assert result.total_rules == 1
    assert result.passed_count == 1
    assert result.failed_count == 0
    assert result.evaluations[0].passed
    assert "chest pain" in result.evaluations[0].matched_data["symptoms"]
    assert "left arm" in result.evaluations[0].matched_data["body_location"]
    assert "All 2 conditions matched" in result.evaluations[0].reason


def test_rule_execution_fails() -> None:
    rule = _make_rule(
        "fail_rule",
        [
            {"field": "symptoms", "operator": "contains", "value": "fever"},
        ],
        priority=1,
    )
    engine = RuleEngine(rules=(rule,))

    result = engine.evaluate({"symptoms": "Patient has a mild cough"})
    assert result.failed_count == 1
    assert not result.evaluations[0].passed
    assert "fever" in result.evaluations[0].reason


def test_multiple_rules_select_best() -> None:
    low_priority = _make_rule(
        "low",
        [{"field": "symptoms", "operator": "contains", "value": "headache"}],
        priority=10,
    )
    high_priority = _make_rule(
        "high",
        [{"field": "symptoms", "operator": "contains", "value": "headache"}],
        priority=1,
    )
    engine = RuleEngine(rules=(low_priority, high_priority))

    data = {"symptoms": "Severe headache"}

    best = engine.select_best(data)
    assert best is not None
    assert best.rule.id == "high"


def test_multiple_rules_all_evaluated() -> None:
    rule1 = _make_rule(
        "rule1",
        [{"field": "symptoms", "operator": "contains", "value": "fever"}],
        priority=1,
    )
    rule2 = _make_rule(
        "rule2",
        [{"field": "symptoms", "operator": "contains", "value": "headache"}],
        priority=1,
    )
    engine = RuleEngine(rules=(rule1, rule2))

    data = {"symptoms": "Patient has fever"}

    report = engine.evaluate(data)
    assert report.total_rules == 2
    assert report.passed_count == 1
    assert report.failed_count == 1


def test_select_best_returns_none_when_no_rules_pass() -> None:
    rule = _make_rule(
        "rule1",
        [{"field": "symptoms", "operator": "contains", "value": "fever"}],
        priority=1,
    )
    engine = RuleEngine(rules=(rule,))

    result = engine.select_best({"symptoms": "headache"})
    assert result is None


def test_numeric_comparison_operators() -> None:
    rule = _make_rule(
        "numeric_rule",
        [
            {
                "field": "vital_signs.heart_rate",
                "operator": "greater_than",
                "value": 100,
            },
        ],
        priority=1,
    )
    engine = RuleEngine(rules=(rule,))

    result = engine.evaluate({"vital_signs": {"heart_rate": 120}})
    assert result.evaluations[0].passed

    result_fail = engine.evaluate({"vital_signs": {"heart_rate": 80}})
    assert not result_fail.evaluations[0].passed


def test_in_operator() -> None:
    rule = _make_rule(
        "in_rule",
        [
            {
                "field": "category",
                "operator": "in",
                "value": ["cardiology", "neurology"],
            },
        ],
        priority=1,
    )
    engine = RuleEngine(rules=(rule,))

    result = engine.evaluate({"category": "cardiology"})
    assert result.evaluations[0].passed


def test_nested_field_access() -> None:
    rule = _make_rule(
        "nested_rule",
        [
            {
                "field": "patient.age",
                "operator": "greater_than_or_equal",
                "value": 50,
            },
        ],
        priority=1,
    )
    engine = RuleEngine(rules=(rule,))

    result = engine.evaluate({"patient": {"age": 56}})
    assert result.evaluations[0].passed


def test_not_exists_operator() -> None:
    rule = _make_rule(
        "not_exists_rule",
        [
            {"field": "allergies", "operator": "not_exists"},
        ],
        priority=1,
    )
    engine = RuleEngine(rules=(rule,))

    result = engine.evaluate({"patient": {"age": 56}})
    assert result.evaluations[0].passed


def test_report_serialization() -> None:
    rule = _make_rule(
        "test_rule",
        [{"field": "symptoms", "operator": "contains", "value": "fever"}],
        priority=1,
    )
    engine = RuleEngine(rules=(rule,))

    result = engine.evaluate({"symptoms": "fever present"})

    evaluation = result.evaluations[0]
    assert isinstance(evaluation, EvaluationResult)
    assert evaluation.rule.id == "test_rule"
    assert "fever present" in evaluation.matched_data["symptoms"]


def test_rule_execution_performance() -> None:
    rules = tuple(
        _make_rule(
            f"rule_{i}",
            [
                {"field": "symptoms", "operator": "equals", "value": f"sym_{i:03d}"},
            ],
            priority=i,
        )
        for i in range(100)
    )
    engine = RuleEngine(rules=rules)

    data = {"symptoms": "sym_042"}

    start = time.perf_counter()
    report = engine.evaluate(data)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert report.total_rules == 100
    assert report.passed_count == 1
    assert report.passed[0].rule.id == "rule_42"
    assert elapsed_ms < 500
