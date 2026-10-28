"""Fixed corpus and regression-matrix checks for Stage 10 acceptance."""

import json
from pathlib import Path

from rop.capabilities.stage10_evaluation import evaluate_intent_cases

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "tests" / "fixtures" / "stage10_evaluation_v1.json"


def _load_corpus() -> dict:
    with CORPUS_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def test_fixed_intent_corpus_has_exact_outcomes_and_reported_metrics() -> None:
    corpus = _load_corpus()
    report = evaluate_intent_cases(corpus["intent_cases"])

    assert corpus["schema_version"] == 1
    assert report["case_count"] >= 30
    assert report["passed_cases"] == report["case_count"]
    assert report["failed_cases"] == []
    assert report["outcome_accuracy"] == 1.0
    assert report["false_match_count"] == 0
    assert report["missed_supported_count"] == 0
    assert report["intent_precision"] >= 0.98
    assert report["intent_recall"] >= 0.98
    assert set(report["per_intent"]) == {"help", "workspace"}
    assert "not independent" in report["limitations"]


def test_corpus_contains_supported_ambiguous_and_unsupported_examples() -> None:
    corpus = _load_corpus()
    cases = corpus["intent_cases"]
    statuses = {case["expected_status"] for case in cases}

    assert statuses == {"matched", "ambiguous", "unsupported"}
    assert any(
        case.get("expected_message_contains")
        for case in cases
        if case["expected_status"] == "ambiguous"
    )


def test_regression_matrix_references_existing_automated_tests() -> None:
    corpus = _load_corpus()
    matrix = corpus["regression_tests"]
    required_domains = {
        "intent-positive-and-negative",
        "false-matches-and-near-misses",
        "ambiguous-and-malicious-input",
        "memory-explicit-control",
        "memory-crud-and-persistence",
        "memory-secret-and-clinical-boundaries",
        "memory-clear-confirmation",
        "personal-data-export-and-pagination",
        "clinical-personal-data-separation",
        "retrieval-allowlist",
        "retrieval-path-containment",
        "retrieval-unsupported-formats",
        "retrieval-resource-ceilings",
        "runtime-offline-boundary",
        "startup-offline-boundary",
        "workflow-confirmation-idempotency",
        "workflow-cancellation",
        "conversation-clarification-recovery",
    }
    assert required_domains.issubset({entry["domain"] for entry in matrix})
    assert len(matrix) >= len(required_domains)

    for entry in matrix:
        path_text, separator, test_name = entry["test_node"].partition("::")
        assert separator and test_name.startswith("test_")
        path = ROOT / path_text
        assert path.is_file(), entry["test_node"]
        source = path.read_text(encoding="utf-8")
        assert f"def {test_name}(" in source, entry["test_node"]
