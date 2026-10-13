"""Task 206: baseline evaluation harness tests.

Validates metric arithmetic and report contents over synthetic
fixtures. No model, network, GPU, database, or clinical content.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from rop.evaluation.cases import EvaluationCaseSet
from rop.evaluation.harness import (
    EvaluationHarnessError,
    case_set_sha256,
    evaluate_case_set,
    load_case_set,
    report_sha256,
)

FIXTURE_PATH = (
    pathlib.Path(__file__).parent.parent
    / "src"
    / "rop"
    / "evaluation"
    / "synthetic_cases_v1.json"
)


def _fixture_data() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _loaded_fixture():
    return load_case_set(_fixture_data())


def _case_by_id(case_id: str) -> dict:
    for case in _fixture_data()["cases"]:
        if case["case_id"] == case_id:
            return copy.deepcopy(case)
    raise AssertionError(f"unknown fixture case: {case_id}")


def _single_case_set(case: dict) -> dict:
    return {
        "case_set_id": "test-single-v1",
        "case_set_version": "1.0",
        "cases": [case],
    }


def test_fixture_covers_all_four_statuses() -> None:
    report = evaluate_case_set(_loaded_fixture(), baseline_revision="test")
    assert report.run_valid
    assert report.valid_cases == 14
    assert report.invalid_input_cases == 2
    assert report.status_distribution == {
        "SUPPORTED": 3,
        "CONTRADICTED": 2,
        "INSUFFICIENT": 2,
        "ABSTAINED": 7,
    }
    assert report.status_agreement.value == 1.0
    assert report.reason_agreement.value == 1.0
    assert report.evidence_exactness.value == 1.0
    assert report.unsupported_references.target_met
    assert report.unsupported_references.unsupported == 0
    assert report.contradiction.correct == 2
    assert report.contradiction.incorrect == 0
    assert report.abstention.correct == 7
    assert report.abstention.incorrect == 0
    assert report.insufficiency.correct == 2
    assert report.model_acceptance.evaluated is False
    assert report.model_acceptance.accepted is False
    assert any(threshold.status == "pending" for threshold in report.thresholds)
    assert report.synthetic_only is True


def test_case_schema_rejects_unknown_fields() -> None:
    case = _case_by_id("supported-basic")
    case["unknown_field"] = True
    with pytest.raises(EvaluationHarnessError):
        load_case_set(_single_case_set(case))


def test_duplicate_case_identifiers_rejected() -> None:
    case = _case_by_id("supported-basic")
    data = _single_case_set(case)
    data["cases"] = [copy.deepcopy(case), copy.deepcopy(case)]
    with pytest.raises(EvaluationHarnessError):
        load_case_set(data)


def test_unsupported_status_and_reason_rejected() -> None:
    case = _case_by_id("supported-basic")
    case["expected_status"] = "READY"
    with pytest.raises(EvaluationHarnessError):
        load_case_set(_single_case_set(case))
    case = _case_by_id("supported-basic")
    case["expected_reason"] = "BOGUS"
    with pytest.raises(EvaluationHarnessError):
        load_case_set(_single_case_set(case))


def test_malformed_dataset_rejected_without_partial_success() -> None:
    data = _fixture_data()
    bad = _case_by_id("supported-basic")
    del bad["binding"]
    data["cases"] = [_case_by_id("contradiction-pair"), bad]
    with pytest.raises(EvaluationHarnessError):
        load_case_set(data)
    with pytest.raises(EvaluationHarnessError):
        load_case_set({"case_set_id": "x", "case_set_version": "1.0", "cases": []})
    with pytest.raises(EvaluationHarnessError):
        load_case_set(["not", "a", "mapping"])


def test_exact_reference_scoring() -> None:
    case = _case_by_id("supported-basic")
    case["expected_supporting"] = []
    report = evaluate_case_set(
        load_case_set(_single_case_set(case)), baseline_revision="test"
    )
    assert report.status_agreement.value == 1.0
    assert report.evidence_exactness.value == 0.0


def test_unsupported_reference_rate_and_zero_denominator() -> None:
    report = evaluate_case_set(
        load_case_set(_single_case_set(_case_by_id("abstention-empty-no-requirement"))),
        baseline_revision="test",
    )
    assert report.unsupported_references.emitted == 0
    assert report.unsupported_references.unsupported == 0
    assert report.unsupported_references.rate == 0.0
    assert report.unsupported_references.denominator_zero is True
    assert report.unsupported_references.target_met is True


def test_false_contradiction_accounting() -> None:
    case = _case_by_id("contradiction-pair")
    case["case_id"] = "false-contradiction-probe"
    case["category"] = "supported"
    case["expected_status"] = "SUPPORTED"
    case["expected_reason"] = "RULE_MATCH"
    report = evaluate_case_set(
        load_case_set(_single_case_set(case)), baseline_revision="test"
    )
    assert report.status_agreement.value == 0.0
    assert report.contradiction.expected == 0
    assert report.contradiction.incorrect == 1


def test_incorrect_abstention_accounting() -> None:
    case = _case_by_id("abstention-no-rules")
    case["case_id"] = "incorrect-abstention-probe"
    case["support_rules"] = [
        {
            "rule_id": "baseline-support-rule-v1",
            "task_id": "baseline-support-v1",
            "condition": {
                "required_evidence_type": "OBSERVATION",
                "min_evidence_count": 1,
                "expected_content": "synthetic baseline observation",
            },
            "uncertainty": 0.2,
        }
    ]
    report = evaluate_case_set(
        load_case_set(_single_case_set(case)), baseline_revision="test"
    )
    assert report.abstention.expected == 1
    assert report.abstention.correct == 0
    assert report.abstention.incorrect == 1


def test_invalid_cases_counted_separately() -> None:
    report = evaluate_case_set(_loaded_fixture(), baseline_revision="test")
    assert report.invalid_passed == 2
    assert report.invalid_failed == 0
    assert report.status_agreement.denominator == 14
    assert report.reason_agreement.denominator == 14


def test_deterministic_reports_and_stable_hashes() -> None:
    first = evaluate_case_set(_loaded_fixture(), baseline_revision="test")
    second = evaluate_case_set(_loaded_fixture(), baseline_revision="test")
    assert first == second
    assert report_sha256(first) == report_sha256(second)
    assert len(report_sha256(first)) == 64


def test_case_ordering_does_not_change_hash() -> None:
    data = _fixture_data()
    data["cases"] = list(reversed(data["cases"]))
    assert case_set_sha256(load_case_set(data)) == case_set_sha256(_loaded_fixture())


def test_unexpected_errors_fail_closed(monkeypatch) -> None:
    def _boom(self, binding):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(
        "rop.services.native_composition.NativeCompositionService.compose", _boom
    )
    report = evaluate_case_set(_loaded_fixture(), baseline_revision="test")
    assert report.run_valid is False
    assert report.errored == report.total_cases
    assert report.invalid_failed == report.invalid_input_cases
    assert report.run_errors
    assert all("unexpected evaluation error" in entry for entry in report.run_errors)
    assert all(entry.startswith("case '") for entry in report.run_errors)


def test_no_network_provider_or_model_dependency() -> None:
    package = pathlib.Path(__file__).parent.parent / "src" / "rop" / "evaluation"
    imported: set[str] = set()
    for name in ("__init__.py", "cases.py", "harness.py", "__main__.py"):
        for line in (package / name).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("import "):
                imported.add(stripped.split()[1].split(".")[0])
            elif stripped.startswith("from "):
                imported.add(stripped.split()[1].split(".")[0])
    forbidden = {
        "anthropic",
        "gemini",
        "httpx",
        "ollama",
        "openai",
        "os",
        "requests",
        "sklearn",
        "socket",
        "subprocess",
        "torch",
        "transformers",
        "urllib",
    }
    assert not (imported & forbidden)


def test_report_cannot_claim_model_acceptance() -> None:
    report = evaluate_case_set(_loaded_fixture(), baseline_revision="test")
    assert report.model_acceptance.accepted is False
    pending = [
        threshold for threshold in report.thresholds if threshold.status == "pending"
    ]
    assert len(pending) == 7
    assert "Synthetic-only" in report.synthetic_disclaimer


def test_baseline_revision_required() -> None:
    with pytest.raises(EvaluationHarnessError):
        evaluate_case_set(_loaded_fixture(), baseline_revision="")
    report = evaluate_case_set(_loaded_fixture(), baseline_revision="abc123")
    assert report.baseline_revision == "abc123"


def test_cli_rejects_undecodable_file(tmp_path, capsys) -> None:
    from rop.evaluation.harness import main

    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe{\x00")
    assert main(["--cases", str(bad)]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_cli_success_and_failing_threshold_exit_codes(tmp_path, capsys) -> None:
    from rop.evaluation.harness import main

    assert main(["--cases", str(FIXTURE_PATH), "--baseline-revision", "test"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["case_set_id"] == "synthetic-baseline-v1"
    failing = _case_by_id("supported-basic")
    failing["case_id"] = "failing-probe"
    failing["category"] = "abstention"
    failing["expected_status"] = "ABSTAINED"
    failing["expected_reason"] = "NO_JUSTIFIED_BASIS"
    failing["expected_supporting"] = []
    target = tmp_path / "failing.json"
    target.write_text(
        json.dumps(
            {
                "case_set_id": "failing-probe-v1",
                "case_set_version": "1.0",
                "cases": [failing],
            }
        ),
        encoding="utf-8",
    )
    assert main(["--cases", str(target), "--baseline-revision", "test"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status_agreement"]["value"] == 0.0


def test_case_set_model_validates() -> None:
    case_set = _loaded_fixture()
    assert isinstance(case_set, EvaluationCaseSet)
    assert case_set.case_set_id == "synthetic-baseline-v1"
    assert len(case_set.cases) == 16
    assert len(case_set_sha256(case_set)) == 64


def test_invalid_cases_evaluated_twice(monkeypatch) -> None:
    from rop.services.native_composition import NativeCompositionService

    calls: list[int] = []
    original = NativeCompositionService.compose

    def _counting(self, binding):
        calls.append(1)
        return original(self, binding)

    monkeypatch.setattr(NativeCompositionService, "compose", _counting)
    case = _case_by_id("invalid-unknown-reference")
    report = evaluate_case_set(
        load_case_set(_single_case_set(case)), baseline_revision="test"
    )
    assert report.invalid_passed == 1
    assert len(calls) == 2


def test_changed_invalid_outcome_fails_determinism(monkeypatch) -> None:
    from rop.services.native_composition import (
        NativeCompositionContractError,
        NativeCompositionService,
    )

    calls = {"count": 0}

    def _flip(self, binding):
        calls["count"] += 1
        if calls["count"] == 1:
            raise NativeCompositionContractError(
                "INVALID_BINDING", "composition binding is invalid"
            )
        return {"status": "ABSTAINED"}

    monkeypatch.setattr(NativeCompositionService, "compose", _flip)
    case = _case_by_id("invalid-unknown-reference")
    report = evaluate_case_set(
        load_case_set(_single_case_set(case)), baseline_revision="test"
    )
    assert report.run_valid is False
    assert any("non-deterministic" in entry for entry in report.run_errors)
    assert report.determinism.repeat_passed is False
    assert any(
        threshold.threshold_id == "determinism" and threshold.status == "failed"
        for threshold in report.thresholds
    )


_CATEGORY_FOR_STATUS = {
    "SUPPORTED": "supported",
    "CONTRADICTED": "contradiction",
    "INSUFFICIENT": "insufficient",
    "ABSTAINED": "abstention",
}

_STATUS_REASONS = {
    "SUPPORTED": "RULE_MATCH",
    "CONTRADICTED": "RULE_CONTRADICTION_FOUND",
    "INSUFFICIENT": "EVIDENCE_MISSING",
    "ABSTAINED": "NO_JUSTIFIED_BASIS",
}


@pytest.mark.parametrize(
    "category,status",
    [
        ("supported", "CONTRADICTED"),
        ("supported", "INSUFFICIENT"),
        ("supported", "ABSTAINED"),
        ("contradiction", "SUPPORTED"),
        ("contradiction", "INSUFFICIENT"),
        ("contradiction", "ABSTAINED"),
        ("insufficient", "SUPPORTED"),
        ("insufficient", "CONTRADICTED"),
        ("insufficient", "ABSTAINED"),
        ("abstention", "SUPPORTED"),
        ("abstention", "CONTRADICTED"),
        ("abstention", "INSUFFICIENT"),
    ],
)
def test_category_status_mismatch_rejected(category: str, status: str) -> None:
    case = _case_by_id("supported-basic")
    case["case_id"] = f"probe-{category}-{status}".replace("_", "-")
    case["category"] = category
    case["expected_status"] = status
    case["expected_reason"] = _STATUS_REASONS[status]
    with pytest.raises(EvaluationHarnessError):
        load_case_set(_single_case_set(case))


@pytest.mark.parametrize(
    "status,reason",
    [
        ("SUPPORTED", "RULE_CONTRADICTION_FOUND"),
        ("SUPPORTED", "EVIDENCE_MISSING"),
        ("SUPPORTED", "NO_JUSTIFIED_BASIS"),
        ("CONTRADICTED", "RULE_MATCH"),
        ("CONTRADICTED", "EVIDENCE_MISSING"),
        ("CONTRADICTED", "NO_JUSTIFIED_BASIS"),
        ("INSUFFICIENT", "RULE_MATCH"),
        ("INSUFFICIENT", "RULE_CONTRADICTION_FOUND"),
        ("INSUFFICIENT", "NO_JUSTIFIED_BASIS"),
        ("ABSTAINED", "RULE_MATCH"),
        ("ABSTAINED", "RULE_CONTRADICTION_FOUND"),
        ("ABSTAINED", "EVIDENCE_MISSING"),
    ],
)
def test_status_reason_mismatch_rejected(status: str, reason: str) -> None:
    case = _case_by_id("supported-basic")
    case["case_id"] = f"probe-{status}-{reason}".replace("_", "-")
    case["category"] = _CATEGORY_FOR_STATUS[status]
    case["expected_status"] = status
    case["expected_reason"] = reason
    with pytest.raises(EvaluationHarnessError):
        load_case_set(_single_case_set(case))


def test_invalid_input_with_outcome_rejected() -> None:
    case = _case_by_id("invalid-unknown-reference")
    case["expected_status"] = "ABSTAINED"
    with pytest.raises(EvaluationHarnessError):
        load_case_set(_single_case_set(case))
    case = _case_by_id("invalid-unknown-reference")
    case["support_rules"] = [
        {
            "rule_id": "baseline-support-rule-v1",
            "task_id": "baseline-support-v1",
            "condition": {
                "required_evidence_type": "OBSERVATION",
                "min_evidence_count": 1,
                "expected_content": "synthetic baseline observation",
            },
            "uncertainty": 0.2,
        }
    ]
    with pytest.raises(EvaluationHarnessError):
        load_case_set(_single_case_set(case))


def test_abstention_with_wrong_refs_not_fully_correct() -> None:
    case = _case_by_id("abstention-no-rules")
    claimed = case["binding"]["evidence"][0]["evidence_id"]
    case["expected_supporting"] = [claimed]
    report = evaluate_case_set(
        load_case_set(_single_case_set(case)), baseline_revision="test"
    )
    assert report.status_agreement.value == 1.0
    assert report.evidence_exactness.value == 0.0
    assert report.abstention.expected == 1
    assert report.abstention.correct == 0
    assert report.abstention.incorrect == 1


def test_abstention_reason_mismatch_impossible() -> None:
    # Reason codes are bound to statuses at load, so an abstention
    # with a non-abstention reason cannot be constructed; reference
    # exactness is the practical correctness vector (see above).
    case = _case_by_id("abstention-no-rules")
    case["expected_reason"] = "RULE_MATCH"
    with pytest.raises(EvaluationHarnessError):
        load_case_set(_single_case_set(case))
