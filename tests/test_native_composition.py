"""Task 204 correction and Task 205 composition semantics tests.

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
    NativeContradictionRule,
    NativeEvidenceRequirement,
)

_FP = "d" * 64
_TASK = "synthetic-composition-test-v1"
_RULE = "synthetic-rule-v1"
_PAIR_TASK = "synthetic-contradiction-test-v1"
_PAIR_RULE = "synthetic-contradiction-rule-v1"
_CONTENT_A = "synthetic flag present"
_CONTENT_B = "synthetic flag absent"


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


def _pair_rule(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "rule_id": _PAIR_RULE,
        "task_id": _PAIR_TASK,
        "affirming_content": _CONTENT_A,
        "denying_content": _CONTENT_B,
        "required_evidence_type": "OBSERVATION",
        "min_evidence_count": 1,
        "uncertainty": 0.3,
    }
    base.update(overrides)
    return NativeContradictionRule(**base)  # type: ignore[arg-type]


def _requirement(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "requirement_id": "consent-record",
        "task_id": _TASK,
        "required_evidence_type": "OBSERVATION",
        "expected_content": "synthetic consent text",
    }
    base.update(overrides)
    return NativeEvidenceRequirement(**base)  # type: ignore[arg-type]


def _binding(
    task_id: str = _TASK,
    evidence_type: str = "OBSERVATION",
    count: int = 2,
    contents: list[str] | None = None,
    types: list[str] | None = None,
) -> NativeEvidenceBinding:
    session_id = uuid4()
    default_content = "normalized observation text"
    ids = sorted([uuid4() for _ in range(count)], key=str)
    if contents is None:
        contents = [default_content] * count
    if types is None:
        types = [evidence_type] * count
    assert len(contents) == count
    assert len(types) == count
    records = []
    for value, content, kind in zip(ids, contents, types, strict=True):
        records.append(
            {
                "evidence_id": str(value),
                "session_id": session_id,
                "context_fingerprint": _FP,
                "evidence_type": kind,
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


# --- Task 205: contradiction semantics ---


def test_configured_pair_produces_contradicted() -> None:
    service = NativeCompositionService(contradiction_rules=[_pair_rule()])
    binding = _binding(task_id=_PAIR_TASK, count=2, contents=[_CONTENT_A, _CONTENT_B])
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.status == "CONTRADICTED"
    assert result.reason_code == "RULE_CONTRADICTION_FOUND"
    assert result.rule_id == _PAIR_RULE
    assert result.uncertainty == 0.3
    assert result.missing_information_ids == ()
    affirming = {
        str(record.evidence_id)
        for record in binding.evidence
        if record.content_text == _CONTENT_A
    }
    denying = {
        str(record.evidence_id)
        for record in binding.evidence
        if record.content_text == _CONTENT_B
    }
    assert {str(value) for value in result.supporting_evidence_ids} == affirming
    assert {str(value) for value in result.contradicting_evidence_ids} == denying
    assert affirming and denying
    assert not (
        {str(value) for value in result.supporting_evidence_ids}
        & {str(value) for value in result.contradicting_evidence_ids}
    )


def test_contradiction_excludes_unrelated_evidence() -> None:
    service = NativeCompositionService(contradiction_rules=[_pair_rule()])
    binding = _binding(
        task_id=_PAIR_TASK,
        count=3,
        contents=[_CONTENT_A, "unrelated text", _CONTENT_B],
    )
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.status == "CONTRADICTED"
    assert len(result.supporting_evidence_ids) == 1
    assert len(result.contradicting_evidence_ids) == 1
    assert len(binding.evidence) == 3


def test_contradiction_is_stable() -> None:
    service = NativeCompositionService(contradiction_rules=[_pair_rule()])
    binding = _binding(task_id=_PAIR_TASK, count=2, contents=[_CONTENT_A, _CONTENT_B])
    assert service.compose(binding) == service.compose(binding)


def test_different_text_alone_is_not_contradiction() -> None:
    service = NativeCompositionService(contradiction_rules=[_pair_rule()])
    binding = _binding(
        task_id=_PAIR_TASK, count=2, contents=["unrelated text a", "unrelated text b"]
    )
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.status != "CONTRADICTED"
    assert result.status == "ABSTAINED"
    assert result.supporting_evidence_ids == ()
    assert result.contradicting_evidence_ids == ()


def test_missing_side_is_not_contradiction() -> None:
    service = NativeCompositionService(contradiction_rules=[_pair_rule()])
    one_sided = NativeReasoningResult.model_validate(
        service.compose(_binding(task_id=_PAIR_TASK, count=1, contents=[_CONTENT_A]))
    )
    assert one_sided.status != "CONTRADICTED"
    assert one_sided.status == "ABSTAINED"


def test_unreadable_side_is_not_contradiction() -> None:
    session_id = uuid4()
    content = _CONTENT_A
    affirming_id = uuid4()
    unreadable_id = uuid4()
    ids = sorted([affirming_id, unreadable_id], key=str)
    by_id = {affirming_id: content, unreadable_id: ""}
    digests = {
        affirming_id: compute_native_evidence_digest(content),
        unreadable_id: compute_native_evidence_digest(""),
    }
    availability = {affirming_id: "AVAILABLE", unreadable_id: "UNREADABLE"}
    binding = NativeEvidenceBinding.model_validate(
        {
            "request": {
                "request_id": uuid4(),
                "session_id": session_id,
                "context_fingerprint": _FP,
                "task_id": _PAIR_TASK,
                "evidence_ids": [str(value) for value in ids],
                "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
            },
            "evidence": [
                {
                    "evidence_id": str(value),
                    "session_id": session_id,
                    "context_fingerprint": _FP,
                    "evidence_type": "OBSERVATION",
                    "source_reference": "chart:encounter-123",
                    "provenance_id": "prov-001",
                    "content_text": by_id[value],
                    "content_digest": digests[value],
                    "availability": availability[value],
                    "uncertainty": 0.2,
                    "evidence_source": NATIVE_EVIDENCE_SOURCE_TASK_203,
                }
                for value in ids
            ],
            "binding_source": NATIVE_BINDING_SOURCE_TASK_204,
        }
    )
    service = NativeCompositionService(contradiction_rules=[_pair_rule()])
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.status != "CONTRADICTED"
    assert result.status == "ABSTAINED"


def test_contradiction_takes_precedence_over_support() -> None:
    service = NativeCompositionService(
        rules=[
            NativeCompositionRule(
                rule_id=_RULE,
                task_id=_PAIR_TASK,
                condition=NativeCompositionCondition(
                    required_evidence_type="OBSERVATION",
                    min_evidence_count=1,
                    expected_content=_CONTENT_A,
                ),
                uncertainty=0.2,
            )
        ],
        contradiction_rules=[_pair_rule()],
    )
    binding = _binding(task_id=_PAIR_TASK, count=2, contents=[_CONTENT_A, _CONTENT_B])
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.status == "CONTRADICTED"
    assert result.rule_id == _PAIR_RULE


def test_contradiction_references_are_unique_ordered_disjoint() -> None:
    service = NativeCompositionService(
        contradiction_rules=[_pair_rule(min_evidence_count=2)]
    )
    binding = _binding(
        task_id=_PAIR_TASK,
        count=4,
        contents=[_CONTENT_A, _CONTENT_B, _CONTENT_A, _CONTENT_B],
    )
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.status == "CONTRADICTED"
    supporting = [str(value) for value in result.supporting_evidence_ids]
    contradicting = [str(value) for value in result.contradicting_evidence_ids]
    assert len(supporting) == len(set(supporting)) == 2
    assert len(contradicting) == len(set(contradicting)) == 2
    assert supporting == sorted(supporting)
    assert contradicting == sorted(contradicting)
    assert not (set(supporting) & set(contradicting))


def test_invalid_contradiction_configuration_fails_closed() -> None:
    with pytest.raises(ValueError):
        _pair_rule(affirming_content="same", denying_content="same")
    with pytest.raises(ValueError):
        _pair_rule(affirming_content="")
    with pytest.raises(ValueError):
        _pair_rule(denying_content="x" * 2001)
    with pytest.raises(ValueError):
        _pair_rule(required_evidence_type="DIAGNOSIS")  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        _pair_rule(min_evidence_count=0)
    with pytest.raises(ValueError):
        _pair_rule(uncertainty="0.3")  # type: ignore[dict-item]
    with pytest.raises(NativeCompositionContractError):
        NativeCompositionService(
            rules=[_rule()], contradiction_rules=[_pair_rule(rule_id=_RULE)]
        )
    with pytest.raises(NativeCompositionContractError):
        NativeCompositionService(contradiction_rules=["not-a-rule"])  # type: ignore[list-item]


# --- Task 205: missing-information semantics ---


def test_absent_requirement_produces_insufficient() -> None:
    service = NativeCompositionService(requirements=[_requirement()])
    result = NativeReasoningResult.model_validate(service.compose(_binding()))
    assert result.status == "INSUFFICIENT"
    assert result.reason_code == "EVIDENCE_MISSING"
    assert result.missing_information_ids == ("consent-record",)
    assert result.contradicting_evidence_ids == ()
    assert result.rule_id is None


def test_missing_identifiers_are_valid_deterministic_unique_ordered() -> None:
    service = NativeCompositionService(
        requirements=[
            _requirement(requirement_id="zeta-record"),
            _requirement(requirement_id="alpha-record", expected_content="other text"),
        ]
    )
    binding = _binding()
    first = NativeReasoningResult.model_validate(service.compose(binding))
    second = NativeReasoningResult.model_validate(service.compose(binding))
    assert first.missing_information_ids == ("alpha-record", "zeta-record")
    assert first.missing_information_ids == second.missing_information_ids
    assert first == second


def test_present_evidence_not_falsely_missing() -> None:
    service = NativeCompositionService(
        rules=[_rule()],
        requirements=[_requirement(expected_content="normalized observation text")],
    )
    result = NativeReasoningResult.model_validate(service.compose(_binding()))
    assert result.status == "SUPPORTED"
    assert result.missing_information_ids == ()


def test_missing_information_is_not_contradiction() -> None:
    service = NativeCompositionService(
        contradiction_rules=[_pair_rule()], requirements=[_requirement()]
    )
    result = NativeReasoningResult.model_validate(service.compose(_binding()))
    assert result.status == "INSUFFICIENT"
    assert result.reason_code == "EVIDENCE_MISSING"


def test_insufficiency_takes_precedence_over_support() -> None:
    service = NativeCompositionService(rules=[_rule()], requirements=[_requirement()])
    result = NativeReasoningResult.model_validate(service.compose(_binding()))
    assert result.status == "INSUFFICIENT"
    assert result.missing_information_ids == ("consent-record",)


def test_empty_binding_without_requirement_abstains() -> None:
    service = NativeCompositionService(requirements=[_requirement()])
    session_id = uuid4()
    binding = NativeEvidenceBinding.model_validate(
        {
            "request": {
                "request_id": uuid4(),
                "session_id": session_id,
                "context_fingerprint": _FP,
                "task_id": "unlisted-task-v1",
                "evidence_ids": [],
                "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
            },
            "evidence": [],
            "binding_source": NATIVE_BINDING_SOURCE_TASK_204,
        }
    )
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.status == "ABSTAINED"


def test_empty_binding_with_requirement_is_insufficient() -> None:
    service = NativeCompositionService(requirements=[_requirement()])
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
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.status == "INSUFFICIENT"
    assert result.missing_information_ids == ("consent-record",)
    assert result.supporting_evidence_ids == ()


def test_detached_references_follow_binding_behavior() -> None:
    service = NativeCompositionService(requirements=[_requirement()])
    binding = _binding().model_dump(mode="json")
    binding["request"]["evidence_ids"] = [str(uuid4())]
    with pytest.raises(NativeCompositionContractError):
        service.compose(binding)


def test_invalid_requirement_configuration_fails_closed() -> None:
    with pytest.raises(ValueError):
        _requirement(requirement_id="has space")
    with pytest.raises(ValueError):
        _requirement(requirement_id="")
    with pytest.raises(ValueError):
        _requirement(task_id="")
    with pytest.raises(ValueError):
        _requirement(expected_content="")
    with pytest.raises(ValueError):
        _requirement(required_evidence_type="DIAGNOSIS")  # type: ignore[dict-item]
    with pytest.raises(NativeCompositionContractError):
        NativeCompositionService(requirements=[_requirement(), _requirement()])
    with pytest.raises(NativeCompositionContractError):
        NativeCompositionService(requirements=["not-a-requirement"])  # type: ignore[list-item]


# --- Task 205: abstention semantics ---


def test_ambiguous_free_text_abstains_without_relation() -> None:
    service = NativeCompositionService(contradiction_rules=[_pair_rule()])
    binding = _binding(
        task_id=_PAIR_TASK, count=2, contents=["ambiguous claim a", "ambiguous claim b"]
    )
    result = NativeReasoningResult.model_validate(service.compose(binding))
    assert result.status == "ABSTAINED"
    assert result.reason_code == "NO_JUSTIFIED_BASIS"
    assert result.supporting_evidence_ids == ()
    assert result.contradicting_evidence_ids == ()
    assert result.missing_information_ids == ()
    assert result.rule_id is None


def test_abstention_results_are_deterministic() -> None:
    service = NativeCompositionService()
    binding = _binding()
    assert service.compose(binding) == service.compose(binding)


def test_extended_configuration_remains_immutable() -> None:
    contradictions = [_pair_rule()]
    required = [_requirement()]
    service = NativeCompositionService(
        contradiction_rules=contradictions, requirements=required
    )
    contradictions.append(_pair_rule(rule_id="synthetic-contradiction-rule-v2"))
    required.append(_requirement(requirement_id="other-record"))
    assert len(service.contradiction_rules) == 1
    assert len(service.requirements) == 1
    with pytest.raises(NativeCompositionContractError):
        service._contradiction_rules = ()  # type: ignore[attr-defined]
    with pytest.raises(NativeCompositionContractError):
        service._requirements = ()  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        service.contradiction_rules = ()  # type: ignore[misc]
    with pytest.raises(AttributeError):
        service.requirements = ()  # type: ignore[misc]


def test_integer_uncertainty_normalizes_to_float() -> None:
    rule = _rule(uncertainty=1)
    assert rule.uncertainty == 1.0
    assert isinstance(rule.uncertainty, float)
    pair = _pair_rule(uncertainty=0)
    assert pair.uncertainty == 0.0
