"""Task 204 correction: deterministic composition tests.

Behavioral tests over synthetic fixtures. No model, provider,
network, database, or clinical content.
"""

from __future__ import annotations

import pathlib
from uuid import uuid4

import pytest
from pydantic import ValidationError

from rop.schemas.native_binding import (
    NATIVE_BINDING_SOURCE_TASK_204,
    NativeEvidenceBinding,
)
from rop.schemas.native_evidence import (
    NATIVE_EVIDENCE_SOURCE_TASK_203,
    compute_native_evidence_digest,
)
from rop.schemas.native_reasoning import (
    NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
    NativeReasoningResult,
)
from rop.services.native_composition import (
    NativeCompositionCondition,
    NativeCompositionContractError,
    NativeCompositionRule,
    NativeCompositionService,
)

_FP = "d" * 64
_TASK = "synthetic-composition-test-v1"
_RULE = "synthetic-rule-v1"


def _condition(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "required_evidence_type": "OBSERVATION",
        "min_evidence_count": 1,
        "expected_content": "normalized observation text",
    }
    base.update(overrides)
    return NativeCompositionCondition(**base)  # type: ignore[arg-type]


def _rule(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "rule_id": _RULE,
        "task_id": _TASK,
        "condition": _condition(),
        "uncertainty": 0.2,
    }
    base.update(overrides)
    return NativeCompositionRule(**base)  # type: ignore[arg-type]


def _binding(
    task_id: str = _TASK,
    evidence_type: str = "OBSERVATION",
    count: int = 2,
    contents: list[str] | None = None,
) -> NativeEvidenceBinding:
    session_id = uuid4()
    default_content = "normalized observation text"
    ids = sorted([uuid4() for _ in range(count)], key=str)
    if contents is None:
        contents = [default_content] * count
    assert len(contents) == count
    records = []
    for value, content in zip(ids, contents, strict=True):
        records.append(
            {
                "evidence_id": str(value),
                "session_id": session_id,
                "context_fingerprint": _FP,
                "evidence_type": evidence_type,
                "source_reference": "chart:encounter-123",
                "provenance_id": "prov-001",
                "content_text": content,
                "content_digest": compute_native_evidence_digest(content),
                "availability": "AVAILABLE",
                "uncertainty": 0.2,
                "evidence_source": NATIVE_EVIDENCE_SOURCE_TASK_203,
            }
        )
    return NativeEvidenceBinding.model_validate(
        {
            "request": {
                "request_id": uuid4(),
                "session_id": session_id,
                "context_fingerprint": _FP,
                "task_id": task_id,
                "evidence_ids": [str(value) for value in ids],
                "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
            },
            "evidence": records,
            "binding_source": NATIVE_BINDING_SOURCE_TASK_204,
        }
    )


def test_rule_produces_stable_supported_result() -> None:
    service = NativeCompositionService(
        [_rule(condition=_condition(min_evidence_count=2))]
    )
    result = NativeReasoningResult.model_validate(service.compose(_binding(count=2)))
    assert result.status == "SUPPORTED"
    assert result.reason_code == "RULE_MATCH"
    assert result.rule_id == _RULE
    assert result.uncertainty == 0.2
    assert result.suggestion_text is None
    assert len(result.supporting_evidence_ids) == 2
    assert result.contradicting_evidence_ids == ()
    assert result.missing_information_ids == ()


def test_equivalent_inputs_produce_equivalent_results() -> None:
    service = NativeCompositionService([_rule()])
    binding = _binding()
    first = service.compose(binding)
    second = service.compose(binding)
    assert first == second
    rebuilt = NativeEvidenceBinding.model_validate(binding.model_dump(mode="json"))
    assert service.compose(rebuilt) == first


def test_result_identity_matches_input_binding() -> None:
    service = NativeCompositionService([_rule()])
    binding = _binding()
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.request_id == binding.request.request_id
    assert result.session_id == binding.request.session_id
    assert result.context_fingerprint == binding.request.context_fingerprint


def test_result_references_only_supplied_evidence() -> None:
    service = NativeCompositionService([_rule()])
    binding = _binding()
    result = NativeReasoningResult.model_validate(service.compose(binding))
    supplied = {str(record.evidence_id) for record in binding.evidence}
    assert {str(value) for value in result.supporting_evidence_ids} == supplied
    assert str(uuid4()) not in supplied


def test_output_ordering_and_rule_attribution_stable() -> None:
    service = NativeCompositionService([_rule()])
    binding = _binding(count=3)
    first = service.compose(binding)
    second = service.compose(binding)
    assert first["supporting_evidence_ids"] == sorted(first["supporting_evidence_ids"])
    assert first["supporting_evidence_ids"] == second["supporting_evidence_ids"]
    assert first["rule_id"] == _RULE == second["rule_id"]
    assert first["result_id"] == second["result_id"]


def test_malformed_or_incompatible_inputs_rejected() -> None:
    service = NativeCompositionService([_rule()])
    for bad in (None, "binding", ["binding"], 42, True):
        with pytest.raises(NativeCompositionContractError):
            service.compose(bad)  # type: ignore[arg-type]
    binding = _binding()
    tampered = binding.model_dump(mode="json")
    tampered["evidence"] = tampered["evidence"][:1]
    with pytest.raises(NativeCompositionContractError):
        service.compose(tampered)
    with pytest.raises(NativeCompositionContractError):
        service.compose({**binding.model_dump(mode="json"), "binding_source": "WRONG"})


def test_invalid_rule_declarations_fail_closed() -> None:
    with pytest.raises(ValueError):
        _rule(rule_id="Has Spaces!")
    with pytest.raises(ValueError):
        _rule(task_id="")
    with pytest.raises(ValueError):
        _rule(uncertainty="0.2")  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _rule(uncertainty=True)  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _rule(uncertainty=1.5)
    with pytest.raises(ValueError):
        _rule(condition="not-a-condition")  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _rule(condition=None)  # type: ignore[dict-item]
    with pytest.raises(TypeError):
        NativeCompositionRule(rule_id=_RULE, task_id=_TASK, uncertainty=0.2)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        _condition(required_evidence_type="DIAGNOSIS")  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _condition(min_evidence_count=0)
    with pytest.raises(ValueError):
        _condition(min_evidence_count=-1)
    with pytest.raises(ValueError):
        _condition(min_evidence_count="2")  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _condition(min_evidence_count=True)  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _condition(min_evidence_count=65)
    with pytest.raises(ValueError):
        _condition(expected_content="")  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _condition(expected_content="x" * 2001)  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _condition(expected_content=123)  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _condition(expected_content=None)  # type: ignore[dict-item]
    with pytest.raises(TypeError):
        NativeCompositionCondition(required_evidence_type="OBSERVATION")  # type: ignore[call-arg]
    with pytest.raises(NativeCompositionContractError):
        NativeCompositionService([_rule(), _rule()])
    with pytest.raises(NativeCompositionContractError):
        NativeCompositionService(["not-a-rule"])  # type: ignore[list-item]


def test_type_match_alone_cannot_support_without_true_condition() -> None:
    service = NativeCompositionService(
        [_rule(condition=_condition(min_evidence_count=2))]
    )
    short = NativeReasoningResult.model_validate(service.compose(_binding(count=1)))
    assert short.status == "ABSTAINED"
    assert short.reason_code == "NO_JUSTIFIED_BASIS"
    assert short.rule_id is None
    assert short.supporting_evidence_ids == ()


def test_structural_eligibility_without_content_match_abstains() -> None:
    # Task, type, and count all match, but no record carries the
    # configured content: structural eligibility is not justification.
    service = NativeCompositionService(
        [_rule(condition=_condition(min_evidence_count=2))]
    )
    binding = _binding(count=2, contents=["other text a", "other text b"])
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.status == "ABSTAINED"
    assert result.reason_code == "NO_JUSTIFIED_BASIS"
    assert result.rule_id is None
    assert result.supporting_evidence_ids == ()


def test_supported_references_only_satisfying_evidence() -> None:
    service = NativeCompositionService(
        [_rule(condition=_condition(min_evidence_count=2))]
    )
    binding = _binding(
        count=3,
        contents=[
            "normalized observation text",
            "unrelated text",
            "normalized observation text",
        ],
    )
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.status == "SUPPORTED"
    satisfying = {
        str(record.evidence_id)
        for record in binding.evidence
        if record.content_text == "normalized observation text"
    }
    assert satisfying and len(satisfying) == 2
    assert {str(value) for value in result.supporting_evidence_ids} == satisfying


def test_condition_matching_excludes_foreign_values() -> None:
    condition = _condition()
    assert condition.matching(("not-a-record",)) == ()  # type: ignore[arg-type]


def test_false_condition_never_supports() -> None:
    service = NativeCompositionService(
        [_rule(condition=_condition(min_evidence_count=3))]
    )
    result = NativeReasoningResult.model_validate(service.compose(_binding(count=2)))
    assert result.status != "SUPPORTED"
    assert result.status == "ABSTAINED"
    assert result.rule_id is None


def test_identical_rule_configurations_produce_equivalent_results() -> None:
    first = NativeCompositionService([_rule()])
    second = NativeCompositionService(
        [_rule(condition=_condition(min_evidence_count=1))]
    )
    binding = _binding()
    assert first.compose(binding) == second.compose(binding)


def test_service_configuration_cannot_be_replaced() -> None:
    rules = [_rule()]
    service = NativeCompositionService(rules)
    rules.append(_rule(rule_id="synthetic-rule-v2"))
    assert service.rules == (rules[0],)
    with pytest.raises(AttributeError):
        service.rules[0].rule_id = "changed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        service.rules.append(service.rules[0])  # type: ignore[attr-defined]
    with pytest.raises(NativeCompositionContractError):
        service._rules = ()  # type: ignore[attr-defined]
    with pytest.raises(NativeCompositionContractError):
        service._rules_locked = False  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        service.rules = ()  # type: ignore[misc]
    assert service.rules == (rules[0],)
    assert service.compose(_binding())["status"] == "SUPPORTED"


def test_uncovered_inputs_abstain_without_fabrication() -> None:
    service = NativeCompositionService([_rule()])
    unlisted = NativeReasoningResult.model_validate(
        service.compose(_binding(task_id="unlisted-task-v1"))
    )
    assert unlisted.status == "ABSTAINED"
    assert unlisted.reason_code == "NO_JUSTIFIED_BASIS"
    assert unlisted.supporting_evidence_ids == ()
    assert unlisted.rule_id is None
    mistyped = NativeReasoningResult.model_validate(
        service.compose(_binding(evidence_type="ASSERTION"))
    )
    assert mistyped.status == "ABSTAINED"
    assert mistyped.rule_id is None
    empty_ruleless = NativeReasoningResult.model_validate(
        NativeCompositionService().compose(_binding())
    )
    assert empty_ruleless.status == "ABSTAINED"
    assert empty_ruleless.uncertainty == 1.0


def test_empty_binding_abstains() -> None:
    session_id = uuid4()
    binding = NativeEvidenceBinding.model_validate(
        {
            "request": {
                "request_id": uuid4(),
                "session_id": session_id,
                "context_fingerprint": _FP,
                "task_id": _TASK,
                "evidence_ids": [],
                "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
            },
            "evidence": [],
            "binding_source": NATIVE_BINDING_SOURCE_TASK_204,
        }
    )
    result = NativeReasoningResult.model_validate(
        NativeCompositionService([_rule()]).compose(binding)
    )
    assert result.status == "ABSTAINED"
    assert result.reason_code == "NO_JUSTIFIED_BASIS"


def test_no_model_provider_or_network_dependency() -> None:
    service = NativeCompositionService([_rule()])
    assert not hasattr(service, "provider")
    assert not hasattr(service, "model")
    source = (
        pathlib.Path(__file__)
        .parent.parent.joinpath("src", "rop", "services", "native_composition.py")
        .read_text()
    )
    imported_modules: set[str] = set()
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            imported_modules.add(stripped.split()[1].split(".")[0])
        elif stripped.startswith("from "):
            imported_modules.add(stripped.split()[1].split(".")[0])
    forbidden = {
        "anthropic",
        "gemini",
        "httpx",
        "ollama",
        "openai",
        "requests",
        "sklearn",
        "socket",
        "torch",
        "transformers",
        "urllib",
    }
    assert not (imported_modules & forbidden)
    assert "rop.services.llm_reasoning_provider" not in source
    # composition works with no provider configured and no network
    assert service.compose(_binding())["status"] == "SUPPORTED"


def test_binding_behavior_intact() -> None:
    binding = _binding()
    assert binding.binding_source == NATIVE_BINDING_SOURCE_TASK_204
    tampered = binding.model_dump(mode="json")
    tampered["evidence"][0]["session_id"] = str(uuid4())
    with pytest.raises(ValidationError):
        NativeEvidenceBinding.model_validate(tampered)
