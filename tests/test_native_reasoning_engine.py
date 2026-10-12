"""Task 204 composition tests; no model, provider, network, or database."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from uuid import UUID

import pytest
from pydantic import ValidationError

from rop.native_reasoning_engine import (
    TASK_205_STATUS_PRIORITY,
    NativeReasoningCompositionError,
    NativeReasoningEngine,
    NativeRuleFinding,
)
from rop.schemas.native_evidence import (
    NativeEvidenceAvailability,
    NativeEvidenceBundle,
    NativeEvidenceKind,
    NativeEvidenceRecord,
    NativeEvidenceStance,
    NativeEvidenceUncertainty,
    NativeProvenanceKind,
)
from rop.schemas.native_reasoning import (
    NativeReasonCode,
    NativeReasoningError,
    NativeReasoningErrorCode,
    NativeReasoningErrorMessage,
    NativeReasoningRequest,
    NativeReasoningResult,
    NativeReasoningStatus,
    NativeReasoningTask,
    NativeReasoningUncertainty,
)

SESSION_ID = UUID(int=100)
FINGERPRINT = "a" * 64
DISAGREEMENT_TEXT = (
    "Applicable rule outputs disagree; the disagreement cannot be classified "
    "under the current reasoning contract."
)
SENSITIVE_MARKER = "SENSITIVE_INTERNAL_PAYLOAD_204"
# Independent statement of the Task 202 retryability policy.
EXPECTED_RETRYABLE = {
    NativeReasoningErrorCode.INVALID_REQUEST: False,
    NativeReasoningErrorCode.INPUT_UNAVAILABLE: False,
    NativeReasoningErrorCode.DEPENDENCY_UNAVAILABLE: True,
    NativeReasoningErrorCode.RESOURCE_LIMIT: True,
    NativeReasoningErrorCode.CONTRACT_VIOLATION: False,
}


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
    execution = engine.evaluate_with_trace(request, bundle)
    result = execution.result
    assert execution.applied_rule_ids == ("a-rule", "z-rule")
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

    result = NativeReasoningEngine((NeverRunRule(),)).evaluate(_request(), _bundle())
    assert result.status == NativeReasoningStatus.UNKNOWN


def test_different_conclusions_fail_closed_without_inventing_conflict() -> None:
    engine = NativeReasoningEngine(
        (
            FixedRule("rule-a", _finding(conclusion="Conclusion A")),
            FixedRule("rule-b", _finding(conclusion="Conclusion B")),
        )
    )
    result = engine.evaluate(_request(UUID(int=1)), _bundle(_record(UUID(int=1))))
    assert result.status == NativeReasoningStatus.INSUFFICIENT_EVIDENCE
    assert result.status != NativeReasoningStatus.CONTRADICTED
    assert result.reason_codes == [NativeReasonCode.INSUFFICIENT_SUPPORT]
    assert NativeReasonCode.CONFLICTING_EVIDENCE not in result.reason_codes
    assert result.conclusion is None
    assert result.abstention_reason is None
    assert result.uncertainty == NativeReasoningUncertainty.HIGH
    assert result.missing_information == [DISAGREEMENT_TEXT]
    assert result.evidence_ids == [UUID(int=1)]
    # The fallback must satisfy the public Task 202 contract on re-validation.
    assert NativeReasoningResult.model_validate(result.model_dump()) == result


def _insufficient(*items: str) -> NativeRuleFinding:
    return _finding(
        status=NativeReasoningStatus.INSUFFICIENT_EVIDENCE,
        conclusion=None,
        reason_codes=(NativeReasonCode.EVIDENCE_MISSING,),
        evidence_ids=(),
        missing_information=tuple(sorted(items)),
        uncertainty=NativeReasoningUncertainty.UNASSESSED,
    )


def _abstained(reason: str, *items: str) -> NativeRuleFinding:
    return _finding(
        status=NativeReasoningStatus.ABSTAINED,
        conclusion=None,
        reason_codes=(NativeReasonCode.EXPLICIT_ABSTENTION,),
        evidence_ids=(),
        missing_information=tuple(sorted(items)),
        uncertainty=NativeReasoningUncertainty.UNASSESSED,
        abstention_reason=reason,
    )


def _contradicted_via_two_evidence() -> NativeRuleFinding:
    """Task 202 requires a conclusion on conclusive statuses; give a bounded one."""
    return _finding(
        status=NativeReasoningStatus.CONTRADICTED,
        conclusion="Two usable sources disagree on the same point.",
        reason_codes=(NativeReasonCode.CONFLICTING_EVIDENCE,),
        evidence_ids=(UUID(int=1), UUID(int=2)),
        uncertainty=NativeReasoningUncertainty.LOW,
    )


@pytest.mark.parametrize(
    "findings",
    [
        # differing statuses
        (_finding(), _insufficient("source provenance")),
        (_finding(), _abstained("Out of scope.")),
        (_insufficient("a"), _abstained("Out of scope.")),
    ],
)
def test_valid_solo_tier_winner_composes_to_the_winning_status(
    findings: tuple[NativeRuleFinding, ...],
) -> None:
    # Task 205 precedence: the top-tier status wins a disagreement rather than
    # everything degrading to INSUFFICIENT_EVIDENCE. Each scenario has exactly
    # one finding in the winning tier.
    rules = tuple(FixedRule(f"rule-{i}", f) for i, f in enumerate(findings))
    engine = NativeReasoningEngine(rules)
    result = engine.evaluate(_request(UUID(int=1)), _bundle(_record(UUID(int=1))))
    assert NativeReasoningResult.model_validate(result.model_dump()) == result
    expected = min(findings, key=lambda f: TASK_205_STATUS_PRIORITY[f.status])
    assert result.status == expected.status
    assert result.conclusion == expected.conclusion
    assert result.abstention_reason == expected.abstention_reason
    if result.status is not NativeReasoningStatus.INSUFFICIENT_EVIDENCE:
        if expected.status is not NativeReasoningStatus.SUPPORTED:
            assert result.conclusion == expected.conclusion
    assert result.evidence_ids == sorted(set(result.evidence_ids), key=str)
    assert result.missing_information == sorted(set(result.missing_information))


def test_tier_disagreement_still_fails_closed_conservatively() -> None:
    # Same-tier disagreements (two SUPPORTED conclusions) stay conservative.
    engine = NativeReasoningEngine(
        (
            FixedRule("rule-a", _finding(conclusion="A")),
            FixedRule("rule-b", _finding(conclusion="B")),
        )
    )
    result = engine.evaluate(_request(UUID(int=1)), _bundle(_record(UUID(int=1))))
    assert result.status == NativeReasoningStatus.INSUFFICIENT_EVIDENCE
    assert result.reason_codes == [NativeReasonCode.INSUFFICIENT_SUPPORT]
    assert result.conclusion is None
    assert result.abstention_reason is None
    assert DISAGREEMENT_TEXT in result.missing_information


def test_contradiction_is_not_demoted_by_a_simultaneous_insufficient_finding() -> None:
    engine = NativeReasoningEngine(
        (
            FixedRule("rule-a", _contradicted_via_two_evidence()),
            FixedRule("rule-b", _insufficient("second source")),
        )
    )
    records = [_record(UUID(int=i)) for i in (1, 2)]
    result = engine.evaluate(
        _request(*(r.evidence_id for r in records)), _bundle(*records)
    )
    assert result.status == NativeReasoningStatus.CONTRADICTED
    assert NativeReasonCode.CONFLICTING_EVIDENCE in result.reason_codes
    assert NativeReasonCode.INSUFFICIENT_SUPPORT not in result.reason_codes
    assert result.status != NativeReasoningStatus.INSUFFICIENT_EVIDENCE


def test_disagreement_retains_rule_missing_information_in_canonical_order() -> None:
    # Both findings share the winning INSUFFICIENT_EVIDENCE tier, so the
    # conservative fallback runs and carries every rule-supplied item.
    engine = NativeReasoningEngine(
        (
            FixedRule("rule-a", _insufficient("zeta input", "alpha input")),
            FixedRule("rule-b", _abstained("Out of scope.", "beta input")),
        )
    )
    result = engine.evaluate(_request(), _bundle())
    # Task 205 precedence: ABSTAINED (an explicit, richer diagnosis) outranks
    # INSUFFICIENT_EVIDENCE when a solo ABSTAINED finding exists in the tier.
    assert result.status == NativeReasoningStatus.ABSTAINED
    assert result.abstention_reason == "Out of scope."
    assert result.missing_information == sorted(
        ["alpha input", "beta input", "zeta input"]
    )


def test_disagreement_fallback_stays_valid_when_missing_information_overflows() -> None:
    # The conservative fallback must stay under the Task 202 cap of 64 items;
    # rule-supplied entries beyond the cap are deterministically truncated.
    first = _insufficient(*(f"first-{i:03d}" for i in range(40)))
    second = _abstained("Out of scope.", *(f"second-{i:03d}" for i in range(40)))
    engine = NativeReasoningEngine(
        (FixedRule("rule-a", first), FixedRule("rule-b", second))
    )
    result = engine.evaluate(_request(), _bundle())
    # Solo ABSTAINED winner: rule items are deterministically truncated to
    # the Task 202 cap, never padded or inflated with disagreement text.
    assert result.status == NativeReasoningStatus.ABSTAINED
    assert len(result.missing_information) == 64
    assert DISAGREEMENT_TEXT not in result.missing_information


def test_disagreement_fallback_keeps_unique_canonical_evidence_ids() -> None:
    first = _finding(conclusion="A", evidence_ids=(UUID(int=2), UUID(int=3)))
    second = _finding(conclusion="B", evidence_ids=(UUID(int=1), UUID(int=2)))
    engine = NativeReasoningEngine(
        (FixedRule("rule-a", first), FixedRule("rule-b", second))
    )
    records = [_record(UUID(int=i)) for i in (1, 2, 3)]
    result = engine.evaluate(
        _request(*(record.evidence_id for record in records)), _bundle(*records)
    )
    assert result.evidence_ids == [UUID(int=1), UUID(int=2), UUID(int=3)]


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
    assert caught.value.error.retryable is False
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
    assert caught.value.error.retryable is False


def test_binding_failure_returns_safe_typed_error() -> None:
    engine = NativeReasoningEngine(())
    with pytest.raises(NativeReasoningCompositionError) as caught:
        engine.evaluate(
            _request(UUID(int=2)),
            _bundle(_record(UUID(int=1))),
        )
    assert caught.value.error.code == NativeReasoningErrorCode.INPUT_UNAVAILABLE
    assert caught.value.error.retryable is False
    assert caught.value.error.request_id == UUID(int=700)


def test_rule_failure_does_not_expose_raw_exception_text() -> None:
    class BrokenRule:
        rule_id = "broken-rule"
        tasks = frozenset({NativeReasoningTask.EVALUATE_EVIDENCE})

        def evaluate(self, request, evidence):
            raise RuntimeError("sensitive provider payload")

    with pytest.raises(NativeReasoningCompositionError) as caught:
        NativeReasoningEngine((BrokenRule(),)).evaluate(_request(), _bundle())
    assert caught.value.error.code == NativeReasoningErrorCode.DEPENDENCY_UNAVAILABLE
    assert caught.value.error.retryable is True
    assert "sensitive provider payload" not in str(caught.value)


def test_rule_configuration_rejects_duplicate_and_invalid_identifiers() -> None:
    finding = _finding()
    with pytest.raises(ValueError, match="unique"):
        NativeReasoningEngine((FixedRule("same", finding), FixedRule("same", finding)))
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


def test_malformed_rule_output_is_a_non_retryable_contract_violation() -> None:
    class MalformedRule:
        rule_id = "malformed-rule"
        tasks = frozenset({NativeReasoningTask.EVALUATE_EVIDENCE})

        def evaluate(self, request, evidence):
            return {"status": "SUPPORTED"}

    with pytest.raises(NativeReasoningCompositionError) as caught:
        NativeReasoningEngine((MalformedRule(),)).evaluate(_request(), _bundle())
    assert caught.value.error.code == NativeReasoningErrorCode.CONTRACT_VIOLATION
    assert caught.value.error.retryable is False


@pytest.mark.parametrize("code", list(NativeReasoningErrorCode))
def test_engine_errors_follow_the_canonical_retryability_policy(
    code: NativeReasoningErrorCode,
) -> None:
    error = NativeReasoningEngine._error(UUID(int=700), code).error
    assert error.retryable is EXPECTED_RETRYABLE[code]
    assert error.message == NativeReasoningErrorMessage[code.name]
    assert NativeReasoningError.model_validate(error.model_dump()) == error


# --- sensitive exception text must not leak through any reporting path ---


def _raising_rule(exc: Exception):
    class RaisingRule:
        rule_id = "raising-rule"
        tasks = frozenset({NativeReasoningTask.EVALUATE_EVIDENCE})

        def evaluate(self, request, evidence):
            raise exc

    return RaisingRule()


def _validation_error_with_marker() -> ValidationError:
    try:
        NativeRuleFinding.model_validate({"status": SENSITIVE_MARKER})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a validation error")


def _marker_conclusion_rule():
    bad = _finding(
        status=NativeReasoningStatus.CONTRADICTED,
        conclusion=SENSITIVE_MARKER,
        reason_codes=(NativeReasonCode.RULE_MATCH,),
    )
    return FixedRule("marker-conclusion", bad)


def _assert_no_marker(caught: pytest.ExceptionInfo) -> None:
    exc = caught.value
    assert SENSITIVE_MARKER not in str(exc)
    assert SENSITIVE_MARKER not in repr(exc)
    assert SENSITIVE_MARKER not in repr(exc.error)
    assert SENSITIVE_MARKER not in exc.error.model_dump_json()
    # The reporting boundary: a fully formatted traceback, including any chain.
    rendered = "".join(traceback.format_exception(exc))
    assert SENSITIVE_MARKER not in rendered
    # No original exception is chained or implicitly attached.
    assert exc.__cause__ is None
    assert exc.__context__ is None


def test_rule_exception_text_does_not_reach_the_reporting_boundary() -> None:
    rule = _raising_rule(RuntimeError(SENSITIVE_MARKER))
    with pytest.raises(NativeReasoningCompositionError) as caught:
        NativeReasoningEngine((rule,)).evaluate(_request(), _bundle())
    assert caught.value.error.code == NativeReasoningErrorCode.DEPENDENCY_UNAVAILABLE
    _assert_no_marker(caught)


def test_rule_validation_error_text_does_not_reach_the_reporting_boundary() -> None:
    rule = _raising_rule(_validation_error_with_marker())
    with pytest.raises(NativeReasoningCompositionError) as caught:
        NativeReasoningEngine((rule,)).evaluate(_request(), _bundle())
    assert caught.value.error.code == NativeReasoningErrorCode.CONTRACT_VIOLATION
    _assert_no_marker(caught)


def test_invalid_finding_text_does_not_reach_the_reporting_boundary() -> None:
    engine = NativeReasoningEngine((_marker_conclusion_rule(),))
    with pytest.raises(NativeReasoningCompositionError) as caught:
        engine.evaluate(_request(UUID(int=1)), _bundle(_record(UUID(int=1))))
    assert caught.value.error.code == NativeReasoningErrorCode.CONTRACT_VIOLATION
    _assert_no_marker(caught)


def test_binding_failure_does_not_chain_the_original_exception() -> None:
    with pytest.raises(NativeReasoningCompositionError) as caught:
        NativeReasoningEngine(()).evaluate(
            _request(UUID(int=2)), _bundle(_record(UUID(int=1)))
        )
    assert caught.value.error.code == NativeReasoningErrorCode.INPUT_UNAVAILABLE
    _assert_no_marker(caught)


# --- Task 205 correction: contradiction precedence -------------------------


def _supported_finding(*evidence_ids: UUID) -> NativeRuleFinding:
    return _finding(
        conclusion="Supported conclusion.",
        evidence_ids=evidence_ids or (UUID(int=1),),
    )


def _contradiction_finding(conclusion: str, *evidence_ids: UUID) -> NativeRuleFinding:
    return _finding(
        status=NativeReasoningStatus.CONTRADICTED,
        conclusion=conclusion,
        reason_codes=(NativeReasonCode.CONFLICTING_EVIDENCE,),
        evidence_ids=evidence_ids or (UUID(int=1), UUID(int=2)),
        uncertainty=NativeReasoningUncertainty.LOW,
    )


def _two_records() -> tuple[list[NativeEvidenceRecord], NativeEvidenceBundle]:
    records = [_record(UUID(int=i)) for i in (1, 2)]
    return records, _bundle(*records)


def test_contradiction_outranks_support_in_the_priority_table() -> None:
    assert (
        TASK_205_STATUS_PRIORITY[NativeReasoningStatus.CONTRADICTED]
        < TASK_205_STATUS_PRIORITY[NativeReasoningStatus.SUPPORTED]
    )


@pytest.mark.parametrize("contradiction_first", [True, False])
def test_supported_finding_never_discards_a_competing_contradiction(
    contradiction_first: bool,
) -> None:
    contradiction = FixedRule(
        "a-rule" if contradiction_first else "b-rule",
        _contradiction_finding("The sources disagree."),
    )
    support = FixedRule(
        "b-rule" if contradiction_first else "a-rule", _supported_finding()
    )
    records, bundle = _two_records()
    engine = NativeReasoningEngine((contradiction, support))
    result = engine.evaluate(_request(*(r.evidence_id for r in records)), bundle)
    assert result.status == NativeReasoningStatus.CONTRADICTED
    assert result.status != NativeReasoningStatus.SUPPORTED
    assert result.reason_codes == [NativeReasonCode.CONFLICTING_EVIDENCE]
    assert NativeReasonCode.RULE_MATCH not in result.reason_codes
    assert result.conclusion == "The sources disagree."
    assert NativeReasoningResult.model_validate(result.model_dump()) == result


def test_both_rule_orders_compose_to_the_identical_result() -> None:
    records, bundle = _two_records()
    request = _request(*(r.evidence_id for r in records))
    forward = NativeReasoningEngine(
        (
            FixedRule("a-rule", _contradiction_finding("The sources disagree.")),
            FixedRule("b-rule", _supported_finding()),
        )
    ).evaluate(request, bundle)
    reverse = NativeReasoningEngine(
        (
            FixedRule("a-rule", _supported_finding()),
            FixedRule("b-rule", _contradiction_finding("The sources disagree.")),
        )
    ).evaluate(request, bundle)
    assert forward == reverse


def test_incompatible_top_tier_contradictions_stay_contradicted_and_explained() -> None:
    records, bundle = _two_records()
    engine = NativeReasoningEngine(
        (
            FixedRule("a-rule", _contradiction_finding("Conclusion A")),
            FixedRule("b-rule", _contradiction_finding("Conclusion B")),
            FixedRule("c-rule", _supported_finding()),
        )
    )
    result = engine.evaluate(_request(*(r.evidence_id for r in records)), bundle)
    assert result.status == NativeReasoningStatus.CONTRADICTED
    assert result.reason_codes == [NativeReasonCode.CONFLICTING_EVIDENCE]
    assert result.conclusion not in ("Conclusion A", "Conclusion B")
    assert result.conclusion == (
        "Multiple rules report contradictions with incompatible conclusions; "
        "no single conclusion is asserted."
    )
    assert result.evidence_ids == [UUID(int=1), UUID(int=2)]
    assert result.missing_information == []
    assert result.uncertainty != NativeReasoningUncertainty.UNASSESSED
    assert NativeReasoningResult.model_validate(result.model_dump()) == result


def test_incompatible_contradictions_are_order_independent() -> None:
    records, bundle = _two_records()
    request = _request(*(r.evidence_id for r in records))
    one = NativeReasoningEngine(
        (
            FixedRule("a-rule", _contradiction_finding("Conclusion A")),
            FixedRule("b-rule", _contradiction_finding("Conclusion B")),
        )
    ).evaluate(request, bundle)
    other = NativeReasoningEngine(
        (
            FixedRule("a-rule", _contradiction_finding("Conclusion B")),
            FixedRule("b-rule", _contradiction_finding("Conclusion A")),
        )
    ).evaluate(request, bundle)
    assert one == other


def test_matching_top_tier_contradictions_keep_their_shared_conclusion() -> None:
    records, bundle = _two_records()
    engine = NativeReasoningEngine(
        (
            FixedRule("a-rule", _contradiction_finding("Shared conclusion.")),
            FixedRule("b-rule", _contradiction_finding("Shared conclusion.")),
            FixedRule("c-rule", _supported_finding()),
        )
    )
    result = engine.evaluate(_request(*(r.evidence_id for r in records)), bundle)
    assert result.status == NativeReasoningStatus.CONTRADICTED
    assert result.conclusion == "Shared conclusion."
