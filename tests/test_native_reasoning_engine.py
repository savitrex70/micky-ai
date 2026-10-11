"""Task 204 deterministic composition tests; no model, provider, network, or database."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest
from pydantic import ValidationError

from rop.native_reasoning_engine import (
    NativeReasoningCompositionError,
    NativeReasoningEngine,
    NativeRuleFinding,
)
from rop.schemas.native_evidence import (
    NativeEvidenceAvailability,
    NativeEvidenceBundle,
    NativeEvidenceKind,
    NativeEvidenceProvenance,
    NativeEvidenceRecord,
    NativeEvidenceStance,
    NativeEvidenceUncertainty,
    NativeProvenanceKind,
)
from rop.schemas.native_reasoning import (
    NativeReasonCode,
    NativeReasoningErrorCode,
    NativeReasoningRequest,
    NativeReasoningStatus,
    NativeReasoningTask,
    NativeReasoningUncertainty,
)

SESSION_ID = UUID(int=100)
FINGERPRINT = "a" * 64


def _record(evidence_id: UUID) -> NativeEvidenceRecord:
    return NativeEvidenceRecord.model_validate(
        {
            "contract_version": "1",
            "evidence_id": evidence_id,
            "session_id": SESSION_ID,
            "context_fingerprint": FINGERPRINT,
            "assertion": f"Observation {evidence_id.int}",
            "kind": NativeEvidenceKind.OBSERVATION,
            "stance": NativeEvidenceStance.SUPPORTS,
            "provenance": {
                "source_id": UUID(int=900 + evidence_id.int),
                "source_kind": NativeProvenanceKind.DOCUMENT,
                "source_reference": f"source:document-{evidence_id.int}",
                "source_fingerprint": "b" * 64,
                "availability": NativeEvidenceAvailability.AVAILABLE,
            },
            "derived_from_ids": (),
            "uncertainty": NativeEvidenceUncertainty.LOW,
        }
    )


def _request(*evidence_ids: UUID, **patch: object) -> NativeReasoningRequest:
    value = {
        "contract_version": "1",
        "request_id": UUID(int=700),
        "session_id": SESSION_ID,
        "context_fingerprint": FINGERPRINT,
        "task": NativeReasoningTask.EVALUATE_EVIDENCE,
        "evidence_ids": list(evidence_ids),
    }
    value.update(patch)
    return NativeReasoningRequest.model_validate(value)


def _bundle(*records: NativeEvidenceRecord, **patch: object) -> NativeEvidenceBundle:
    value = {
        "contract_version": "1",
        "session_id": SESSION_ID,
        "context_fingerprint": FINGERPRINT,
        "records": tuple(sorted(records, key=lambda item: str(item.evidence_id))),
        "contract_version": "1",
    }
    value.update(patch)
    return NativeEvidenceBundle.model_validate(value)


def _finding(
    *,
    conclusion: str | None = "The rule conclusion.",
    status: NativeReasoningStatus = NativeReasoningStatus.SUPPORTED,
    evidence_ids: tuple[UUID, ...] = (UUID(int=1),),
    reason_codes: tuple[NativeReasonCode, ...] = (NativeReasonCode.RULE_MATCH,),
    uncertainty: NativeReasoningUncertainty = NativeReasoningUncertainty.LOW,
    missing_information: tuple[str, ...] = (),
    abstention_reason: str | None = None,
) -> NativeRuleFinding:
    return NativeRuleFinding(
        status=status,
        conclusion=conclusion,
        reason_codes=reason_codes,
        evidence_ids=evidence_ids,
        missing_information=missing_information,
        uncertainty=uncertainty,
        abstention_reason=abstention_reason,
    )


@dataclass(frozen=True)
class FixedRule:
    rule_id: str
    finding: NativeRuleFinding | None
    tasks: frozenset[NativeReasoningTask] = frozenset(
        {NativeReasoningTask.EVALUATE_EVIDENCE}
    )

    def evaluate(self, request, evidence):
        return self.finding


def test_rules_are_injected_sorted_and_do_not_change_input_evidence() -> None:
    first = _record(UUID(int=1))
    second = _record(UUID(int=2))
    bundle = _bundle(second, first)
    request = _request(UUID(int=2), UUID(int=1))
    engine = NativeReasoningEngine(
        (
            FixedRule("z-rule", _finding(evidence_ids=(UUID(int=2),))),
            FixedRule("a-rule", _finding(evidence_ids=(UUID(int=1),))),
        )
    )
    result = engine.evaluate(request, bundle)
    assert result.status == NativeReasoningStatus.SUPPORTED
    assert result.conclusion == "The rule conclusion."
    assert result.evidence_ids == [UUID(int=1), UUID(int=2)]
    assert result.reason_codes == [NativeReasonCode.RULE_MATCH]
    assert bundle.records == (first, second)


def test_no_applicable_rule_returns_explicit_unknown() -> None:
    engine = NativeReasoningEngine(())
    result = engine.evaluate(_request(), _bundle())
    assert result.status == NativeReasoningStatus.UNKNOWN
    assert result.reason_codes == [NativeReasonCode.NO_APPLICABLE_RULE]
    assert result.conclusion is None


def test_rule_for_another_task_is_not_invoked() -> None:
    class NeverRunRule:
        rule_id = "classify-only"
        tasks = frozenset({NativeReasoningTask.CLASSIFY})

        def evaluate(self, request, evidence):
            raise AssertionError("task-inapplicable rule was invoked")

    result = NativeReasoningEngine((NeverRunRule(),)).evaluate(
        _request(), _bundle()
    )
    assert result.status == NativeReasoningStatus.UNKNOWN


def test_different_supported_conclusions_fail_closed_without_inventing_conflict() -> None:
    engine = NativeReasoningEngine(
        (
            FixedRule("rule-a", _finding(conclusion="Conclusion A")),
            FixedRule("rule-b", _finding(conclusion="Conclusion B")),
        )
    )
    result = engine.evaluate(_request(), _bundle(_record(UUID(int=1))))
    assert result.status == NativeReasoningStatus.UNKNOWN
    assert NativeReasonCode.CONFLICTING_EVIDENCE not in result.reason_codes
    assert NativeReasonCode.INSUFFICIENT_SUPPORT in result.reason_codes
    assert result.conclusion is None


def test_rule_cannot_return_evidence_outside_the_request() -> None:
    engine = NativeReasoningEngine(
        (FixedRule("out-of-scope", _finding(evidence_ids=(UUID(int=2),))),)
    )
    with pytest.raises(NativeReasoningCompositionError) as caught:
        engine.evaluate(
            _request(UUID(int=1)),
            _bundle(_record(UUID(int=1)), _record(UUID(int=2))),
        )
    assert caught.value.error.code == NativeReasoningErrorCode.CONTRACT_VIOLATION
    assert "Observation" not in str(caught.value)


def test_rule_result_must_satisfy_public_result_contract() -> None:
    bad_finding = _finding(
        status=NativeReasoningStatus.CONTRADICTED,
        reason_codes=(NativeReasonCode.RULE_MATCH,),
        evidence_ids=(UUID(int=1),),
    )
    engine = NativeReasoningEngine((FixedRule("bad-output", bad_finding),))
    with pytest.raises(NativeReasoningCompositionError) as caught:
        engine.evaluate(_request(UUID(int=1)), _bundle(_record(UUID(int=1))))
    assert caught.value.error.code == NativeReasoningErrorCode.CONTRACT_VIOLATION


def test_binding_failure_returns_safe_typed_error() -> None:
    engine = NativeReasoningEngine(())
    with pytest.raises(NativeReasoningCompositionError) as caught:
        engine.evaluate(
            _request(UUID(int=2)),
            _bundle(_record(UUID(int=1))),
        )
    assert caught.value.error.code == NativeReasoningErrorCode.INPUT_UNAVAILABLE
    assert caught.value.error.request_id == UUID(int=700)


def test_rule_failure_does_not_expose_raw_exception_text() -> None:
    class BrokenRule:
        rule_id = "broken-rule"
        tasks = frozenset({NativeReasoningTask.EVALUATE_EVIDENCE})

        def evaluate(self, request, evidence):
            raise RuntimeError("sensitive provider payload")

    with pytest.raises(NativeReasoningCompositionError) as caught:
        NativeReasoningEngine((BrokenRule(),)).evaluate(
            _request(), _bundle()
        )
    assert caught.value.error.code == NativeReasoningErrorCode.DEPENDENCY_UNAVAILABLE
    assert "sensitive provider payload" not in str(caught.value)


def test_rule_configuration_rejects_duplicate_and_invalid_identifiers() -> None:
    finding = _finding()
    with pytest.raises(ValueError, match="unique"):
        NativeReasoningEngine(
            (FixedRule("same", finding), FixedRule("same", finding))
        )
    with pytest.raises(ValueError, match="canonical"):
        NativeReasoningEngine((FixedRule("Not Canonical", finding),))


def test_finding_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        NativeRuleFinding.model_validate(
            {
                "status": NativeReasoningStatus.SUPPORTED,
                "conclusion": "A",
                "reason_codes": (NativeReasonCode.RULE_MATCH,),
                "evidence_ids": (UUID(int=1),),
                "missing_information": (),
                "uncertainty": NativeReasoningUncertainty.LOW,
                "abstention_reason": None,
                "provider": "external",
            }
        )
