"""Task 205 correction: declared unavailable inputs reach UNAVAILABLE end to end."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import pytest

from rop.native_reasoning_engine import (
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
    TASK_205_EVALUATION_INPUT_ID,
    NativeReasonCode,
    NativeReasoningErrorCode,
    NativeReasoningRequest,
    NativeReasoningResult,
    NativeReasoningStatus,
    NativeReasoningTask,
    NativeReasoningUncertainty,
    NativeUnavailableInput,
)

SESSION_ID = UUID(int=100)
FINGERPRINT = "a" * 64
ALLOWED_UNAVAILABLE_CODES = {
    NativeReasonCode.EVIDENCE_UNREADABLE,
    NativeReasonCode.EVIDENCE_NOT_BOUND,
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


def _request(*evidence_ids: UUID) -> NativeReasoningRequest:
    return NativeReasoningRequest.model_validate(
        {
            "contract_version": "1",
            "request_id": UUID(int=700),
            "session_id": SESSION_ID,
            "context_fingerprint": FINGERPRINT,
            "task": NativeReasoningTask.EVALUATE_EVIDENCE,
            "evidence_ids": list(evidence_ids),
        }
    )


def _bundle(*records: NativeEvidenceRecord) -> NativeEvidenceBundle:
    return NativeEvidenceBundle.model_validate(
        {
            "contract_version": "1",
            "session_id": SESSION_ID,
            "context_fingerprint": FINGERPRINT,
            "records": tuple(sorted(records, key=lambda item: str(item.evidence_id))),
        }
    )


def _unavailable(evidence_id: UUID, code: NativeReasonCode) -> NativeUnavailableInput:
    return NativeUnavailableInput(evidence_id=evidence_id, reason_code=code)


@dataclass
class RecordingRule:
    rule_id: str = "recording-rule"
    finding: NativeRuleFinding | None = None
    tasks: frozenset[NativeReasoningTask] = frozenset(
        {NativeReasoningTask.EVALUATE_EVIDENCE}
    )
    calls: list[int] = field(default_factory=list)

    def evaluate(self, request, evidence):
        self.calls.append(len(evidence))
        return self.finding


def _insufficient_finding() -> NativeRuleFinding:
    return NativeRuleFinding(
        status=NativeReasoningStatus.INSUFFICIENT_EVIDENCE,
        conclusion=None,
        reason_codes=(NativeReasonCode.EVIDENCE_MISSING,),
        evidence_ids=(),
        missing_information=("second source",),
        uncertainty=NativeReasoningUncertainty.UNASSESSED,
        abstention_reason=None,
    )


@pytest.mark.parametrize("code", sorted(ALLOWED_UNAVAILABLE_CODES, key=str))
def test_declared_unavailable_input_yields_unavailable_citing_that_input(
    code: NativeReasonCode,
) -> None:
    rule = RecordingRule()
    missing_id = UUID(int=2)
    result = NativeReasoningEngine((rule,)).evaluate(
        _request(UUID(int=1), missing_id),
        _bundle(_record(UUID(int=1))),
        (_unavailable(missing_id, code),),
    )
    assert result.status == NativeReasoningStatus.UNAVAILABLE
    assert result.reason_codes == [code]
    assert result.evidence_ids == [missing_id]
    assert result.conclusion is None
    assert result.abstention_reason is None
    assert result.missing_information == []
    assert rule.calls == []
    assert NativeReasoningResult.model_validate(result.model_dump()) == result


def test_unavailable_result_cites_every_declared_input_and_only_allowed_codes() -> None:
    first, second = UUID(int=2), UUID(int=3)
    result = NativeReasoningEngine(()).evaluate(
        _request(UUID(int=1), first, second),
        _bundle(_record(UUID(int=1))),
        (
            _unavailable(second, NativeReasonCode.EVIDENCE_NOT_BOUND),
            _unavailable(first, NativeReasonCode.EVIDENCE_UNREADABLE),
        ),
    )
    assert result.status == NativeReasoningStatus.UNAVAILABLE
    assert result.evidence_ids == [first, second]
    assert result.reason_codes == [
        NativeReasonCode.EVIDENCE_NOT_BOUND,
        NativeReasonCode.EVIDENCE_UNREADABLE,
    ]
    assert set(result.reason_codes) <= ALLOWED_UNAVAILABLE_CODES
    assert UUID(int=1) not in result.evidence_ids


def test_declaration_order_does_not_change_the_result() -> None:
    first, second = UUID(int=2), UUID(int=3)
    declarations = (
        _unavailable(first, NativeReasonCode.EVIDENCE_UNREADABLE),
        _unavailable(second, NativeReasonCode.EVIDENCE_NOT_BOUND),
    )
    request = _request(first, second)
    engine = NativeReasoningEngine(())
    assert engine.evaluate(request, _bundle(), declarations) == engine.evaluate(
        request, _bundle(), tuple(reversed(declarations))
    )


def test_absent_fact_stays_insufficient_evidence_never_unavailable() -> None:
    rule = RecordingRule(finding=_insufficient_finding())
    result = NativeReasoningEngine((rule,)).evaluate(
        _request(UUID(int=1)), _bundle(_record(UUID(int=1)))
    )
    assert result.status == NativeReasoningStatus.INSUFFICIENT_EVIDENCE
    assert result.status != NativeReasoningStatus.UNAVAILABLE
    assert result.reason_codes == [NativeReasonCode.EVIDENCE_MISSING]
    assert not set(result.reason_codes) & ALLOWED_UNAVAILABLE_CODES


def test_fully_bound_request_without_declarations_still_runs_rules() -> None:
    rule = RecordingRule()
    result = NativeReasoningEngine((rule,)).evaluate(
        _request(UUID(int=1)), _bundle(_record(UUID(int=1)))
    )
    assert rule.calls == [1]
    assert result.status == NativeReasoningStatus.UNKNOWN


def test_requested_id_with_no_record_and_no_declaration_is_rejected() -> None:
    with pytest.raises(NativeReasoningCompositionError) as raised:
        NativeReasoningEngine(()).evaluate(_request(UUID(int=9)), _bundle())
    assert raised.value.error.code == NativeReasoningErrorCode.INPUT_UNAVAILABLE


def test_arbitrary_declaration_for_an_unrequested_id_is_rejected() -> None:
    with pytest.raises(NativeReasoningCompositionError) as raised:
        NativeReasoningEngine(()).evaluate(
            _request(UUID(int=1)),
            _bundle(_record(UUID(int=1))),
            (_unavailable(UUID(int=77), NativeReasonCode.EVIDENCE_UNREADABLE),),
        )
    assert raised.value.error.code == NativeReasoningErrorCode.INVALID_REQUEST


def test_duplicate_unavailable_declarations_are_rejected() -> None:
    declaration = _unavailable(UUID(int=2), NativeReasonCode.EVIDENCE_UNREADABLE)
    conflicting = _unavailable(UUID(int=2), NativeReasonCode.EVIDENCE_NOT_BOUND)
    for declarations in ((declaration, declaration), (declaration, conflicting)):
        with pytest.raises(NativeReasoningCompositionError) as raised:
            NativeReasoningEngine(()).evaluate(
                _request(UUID(int=2)), _bundle(), declarations
            )
        assert raised.value.error.code == NativeReasoningErrorCode.INVALID_REQUEST


def test_id_both_bundled_and_declared_unavailable_is_rejected() -> None:
    with pytest.raises(NativeReasoningCompositionError) as raised:
        NativeReasoningEngine(()).evaluate(
            _request(UUID(int=1)),
            _bundle(_record(UUID(int=1))),
            (_unavailable(UUID(int=1), NativeReasonCode.EVIDENCE_NOT_BOUND),),
        )
    assert raised.value.error.code == NativeReasoningErrorCode.INPUT_UNAVAILABLE


def test_non_declaration_objects_are_rejected() -> None:
    with pytest.raises(NativeReasoningCompositionError) as raised:
        NativeReasoningEngine(()).evaluate(
            _request(UUID(int=2)),
            _bundle(),
            ({"evidence_id": UUID(int=2), "reason_code": "EVIDENCE_UNREADABLE"},),  # type: ignore[arg-type]
        )
    assert raised.value.error.code == NativeReasoningErrorCode.INVALID_REQUEST


def test_reserved_marker_cannot_be_declared_even_when_validation_is_bypassed() -> None:
    forged = NativeUnavailableInput.model_construct(
        evidence_id=TASK_205_EVALUATION_INPUT_ID,
        reason_code=NativeReasonCode.EVIDENCE_UNREADABLE,
    )
    with pytest.raises(NativeReasoningCompositionError) as raised:
        NativeReasoningEngine(()).evaluate(
            _request(TASK_205_EVALUATION_INPUT_ID), _bundle(), (forged,)
        )
    assert raised.value.error.code == NativeReasoningErrorCode.INVALID_REQUEST


def test_reserved_marker_is_rejected_as_a_requested_input() -> None:
    with pytest.raises(NativeReasoningCompositionError) as raised:
        NativeReasoningEngine(()).evaluate(
            _request(TASK_205_EVALUATION_INPUT_ID), _bundle()
        )
    assert raised.value.error.code == NativeReasoningErrorCode.INVALID_REQUEST


def test_reserved_marker_never_appears_in_any_result() -> None:
    result = NativeReasoningEngine(()).evaluate(
        _request(UUID(int=2)),
        _bundle(),
        (_unavailable(UUID(int=2), NativeReasonCode.EVIDENCE_NOT_BOUND),),
    )
    assert TASK_205_EVALUATION_INPUT_ID not in result.evidence_ids


def test_session_mismatch_still_fails_with_a_safe_error_despite_declarations() -> None:
    other = NativeEvidenceBundle.model_validate(
        {
            "contract_version": "1",
            "session_id": UUID(int=101),
            "context_fingerprint": FINGERPRINT,
            "records": (),
        }
    )
    with pytest.raises(NativeReasoningCompositionError) as raised:
        NativeReasoningEngine(()).evaluate(
            _request(UUID(int=2)),
            other,
            (_unavailable(UUID(int=2), NativeReasonCode.EVIDENCE_UNREADABLE),),
        )
    assert raised.value.error.code == NativeReasoningErrorCode.INPUT_UNAVAILABLE
