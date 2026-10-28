"""Metrics for the fixed, project-owned Stage 10 intent evaluation corpus."""

from collections.abc import Mapping, Sequence
from typing import Any

from rop.capabilities.intent_interpreter import IntentInterpretation, interpret_request

_ALLOWED_STATUSES = {"matched", "ambiguous", "unsupported"}
_ALLOWED_INTENTS = {"help", "workspace"}


def _case_outcome(case: Mapping[str, Any], result: IntentInterpretation):
    expected_status = case.get("expected_status")
    expected_intent = case.get("expected_intent")
    reasons: list[str] = []
    if expected_status not in _ALLOWED_STATUSES:
        raise ValueError(f"invalid expected status for case {case.get('id')!r}")
    if expected_intent is not None and expected_intent not in _ALLOWED_INTENTS:
        raise ValueError(f"invalid expected intent for case {case.get('id')!r}")
    if (expected_status == "matched") != (expected_intent is not None):
        raise ValueError(f"expected status/intent disagree for case {case.get('id')!r}")
    if result.status != expected_status:
        reasons.append("status_mismatch")
    if result.intent != expected_intent:
        reasons.append("intent_mismatch")
    if "expected_command" in case and result.command != case["expected_command"]:
        reasons.append("command_mismatch")
    expected_message = case.get("expected_message_contains")
    if expected_message is not None and (
        not isinstance(expected_message, str)
        or result.message is None
        or expected_message not in result.message
    ):
        reasons.append("message_mismatch")
    return not reasons, reasons


def evaluate_intent_cases(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate fixed cases; the result is limited to this project-owned corpus."""
    if not cases:
        raise ValueError("the evaluation corpus must not be empty")
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    true_positive = false_positive = false_negative = 0
    expected_matched = predicted_matched = false_matches = missed_supported = 0
    per_intent = {
        name: {"true_positive": 0, "false_positive": 0, "false_negative": 0}
        for name in sorted(_ALLOWED_INTENTS)
    }

    for case in cases:
        case_id = case.get("id")
        phrase = case.get("phrase")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError("each evaluation case must have a unique non-empty id")
        seen.add(case_id)
        if not isinstance(phrase, str):
            raise ValueError(f"case {case_id!r} has no string phrase")

        result = interpret_request(phrase)
        correct, reasons = _case_outcome(case, result)
        expected_intent = case.get("expected_intent")
        predicted_intent = result.intent if result.status == "matched" else None
        expected_status = case.get("expected_status")
        expected_matched += expected_intent is not None
        predicted_matched += predicted_intent is not None

        if predicted_intent == expected_intent and expected_intent is not None:
            true_positive += 1
            per_intent[expected_intent]["true_positive"] += 1
        elif predicted_intent is not None:
            false_positive += 1
            per_intent[predicted_intent]["false_positive"] += 1
        if expected_intent is not None and predicted_intent != expected_intent:
            false_negative += 1
            per_intent[expected_intent]["false_negative"] += 1
        if result.status == "matched" and expected_status != "matched":
            false_matches += 1
        if expected_status == "matched" and result.status != "matched":
            missed_supported += 1

        results.append({
            "id": case_id,
            "passed": correct,
            "failure_reasons": reasons,
            "expected_status": expected_status,
            "actual_status": result.status,
            "expected_intent": expected_intent,
            "actual_intent": predicted_intent,
        })

    passed = sum(item["passed"] for item in results)
    precision = true_positive / predicted_matched if predicted_matched else 0.0
    recall = true_positive / expected_matched if expected_matched else 0.0
    per_intent_metrics = {}
    for name, counts in per_intent.items():
        denominator_precision = counts["true_positive"] + counts["false_positive"]
        denominator_recall = counts["true_positive"] + counts["false_negative"]
        per_intent_metrics[name] = {
            **counts,
            "precision": (
                counts["true_positive"] / denominator_precision
                if denominator_precision else 0.0
            ),
            "recall": (
                counts["true_positive"] / denominator_recall
                if denominator_recall else 0.0
            ),
        }

    return {
        "case_count": len(cases),
        "passed_cases": passed,
        "failed_cases": [item for item in results if not item["passed"]],
        "outcome_accuracy": passed / len(cases),
        "expected_matched": expected_matched,
        "predicted_matched": predicted_matched,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "false_match_count": false_matches,
        "missed_supported_count": missed_supported,
        "intent_precision": precision,
        "intent_recall": recall,
        "per_intent": per_intent_metrics,
        "limitations": (
            "Fixed project-owned phrase corpus only; not independent or statistically "
            "representative evidence of general language understanding."
        ),
    }


__all__ = ["evaluate_intent_cases"]
