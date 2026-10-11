"""Task 202 contract tests; no runtime, model, provider, or network."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from rop.schemas.native_reasoning import (
    NativeReasonCode,
    NativeReasoningError,
    NativeReasoningErrorCode,
    NativeReasoningRequest,
    NativeReasoningResult,
    NativeReasoningStatus,
    NativeReasoningSuggestion,
    NativeReasoningSuggestionKind,
    NativeReasoningTask,
    NativeReasoningUncertainty,
)


def _request() -> dict:
    return {
        "contract_version": "1",
        "request_id": uuid4(),
        "session_id": uuid4(),
        "context_fingerprint": "a" * 64,
        "task": NativeReasoningTask.EVALUATE_EVIDENCE,
        "evidence_ids": [UUID(int=1), UUID(int=2)],
        "input_summary": "Evaluate the supplied evidence.",
    }


def _result(**patch: object) -> dict:
    request = _request()
    result = {
        "contract_version": "1",
        "request_id": request["request_id"],
        "session_id": request["session_id"],
        "context_fingerprint": request["context_fingerprint"],
        "status": NativeReasoningStatus.SUPPORTED,
        "conclusion": "The conclusion is supported by the supplied evidence.",
        "reason_codes": [NativeReasonCode.RULE_MATCH],
        "evidence_ids": [UUID(int=1)],
        "missing_information": [],
        "uncertainty": NativeReasoningUncertainty.LOW,
        "abstention_reason": None,
        "suggestions": [],
    }
    result.update(patch)
    return result


def test_valid_request_and_result_are_accepted() -> None:
    assert NativeReasoningRequest.model_validate(_request()).contract_version == "1"
    result = NativeReasoningResult.model_validate(_result())
    assert result.status == NativeReasoningStatus.SUPPORTED


def test_request_rejects_missing_extra_and_wrongly_typed_fields() -> None:
    request = _request()
    del request["session_id"]
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate(request)
    request = _request()
    request["provider"] = "external"
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate(request)
    request = _request()
    request["request_id"] = "not-a-uuid"
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate(request)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task", "not-a-task"),
        ("context_fingerprint", "A" * 64),
        ("context_fingerprint", "short"),
        ("input_summary", "  "),
        ("input_summary", "x" * 4001),
        ("evidence_ids", ["not-a-uuid"]),
        ("evidence_ids", [UUID(int=1), UUID(int=1)]),
        ("evidence_ids", [UUID(int=i) for i in range(257)]),
    ],
)
def test_request_rejects_invalid_values(field: str, value: object) -> None:
    request = _request()
    request[field] = value
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate(request)


def test_contradiction_is_not_unavailable_or_insufficient_evidence() -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _result(status=NativeReasoningStatus.CONTRADICTED)
        )
    contradicted = NativeReasoningResult.model_validate(
        _result(
            status=NativeReasoningStatus.CONTRADICTED,
            reason_codes=[NativeReasonCode.CONFLICTING_EVIDENCE],
            evidence_ids=[UUID(int=1), UUID(int=2)],
        )
    )
    unavailable = NativeReasoningResult.model_validate(
        _result(
            status=NativeReasoningStatus.UNAVAILABLE,
            conclusion=None,
            reason_codes=[NativeReasonCode.EVIDENCE_UNREADABLE],
            evidence_ids=[],
        )
    )
    assert contradicted.status != unavailable.status


def test_insufficient_evidence_requires_missing_items_and_reason() -> None:
    base = _result(
        status=NativeReasoningStatus.INSUFFICIENT_EVIDENCE,
        conclusion=None,
        evidence_ids=[],
        reason_codes=[NativeReasonCode.EVIDENCE_MISSING],
        uncertainty=NativeReasoningUncertainty.UNASSESSED,
    )
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(base)
    base["missing_information"] = ["source provenance"]
    result = NativeReasoningResult.model_validate(base)
    assert result.missing_information == ["source provenance"]


def test_abstention_requires_explicit_reason_and_reason_code() -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _result(
                status=NativeReasoningStatus.ABSTAINED,
                conclusion=None,
                evidence_ids=[],
                reason_codes=[NativeReasonCode.EXPLICIT_ABSTENTION],
            )
        )
    result = NativeReasoningResult.model_validate(
        _result(
            status=NativeReasoningStatus.ABSTAINED,
            conclusion=None,
            evidence_ids=[],
            reason_codes=[NativeReasonCode.EXPLICIT_ABSTENTION],
            abstention_reason="The available inputs do not justify a conclusion.",
        )
    )
    assert result.abstention_reason is not None


def test_deterministic_lists_must_be_sorted_and_unique() -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _result(
                reason_codes=[
                    NativeReasonCode.RULE_MATCH,
                    NativeReasonCode.NO_APPLICABLE_RULE,
                ]
            )
        )
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _result(evidence_ids=[UUID(int=2), UUID(int=1)])
        )
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _result(evidence_ids=[UUID(int=1), UUID(int=1)])
        )


def test_suggestion_is_advisory_and_cannot_claim_trusted_evidence() -> None:
    suggestion = NativeReasoningSuggestion.model_validate(
        {
            "kind": NativeReasoningSuggestionKind.CANDIDATE_LABEL,
            "value": "possible category",
            "reason_code": NativeReasonCode.NO_APPLICABLE_RULE,
            "uncertainty": NativeReasoningUncertainty.HIGH,
            "advisory_only": True,
        }
    )
    with pytest.raises(ValidationError):
        NativeReasoningSuggestion.model_validate(
            {
                "kind": NativeReasoningSuggestionKind.CANDIDATE_LABEL,
                "value": "possible category",
                "reason_code": NativeReasonCode.NO_APPLICABLE_RULE,
                "uncertainty": NativeReasoningUncertainty.HIGH,
                "advisory_only": False,
            }
        )
    with pytest.raises(ValidationError):
        NativeReasoningSuggestion.model_validate(
            {
                "kind": NativeReasoningSuggestionKind.CANDIDATE_LABEL,
                "value": "possible category",
                "reason_code": NativeReasonCode.NO_APPLICABLE_RULE,
                "uncertainty": NativeReasoningUncertainty.HIGH,
                "advisory_only": True,
                "evidence_verified": True,
            }
        )
    result = NativeReasoningResult.model_validate(_result(suggestions=[suggestion]))
    assert result.suggestions[0].advisory_only is True


def test_error_contract_is_bounded_and_rejects_extra_fields() -> None:
    error = NativeReasoningError.model_validate(
        {
            "contract_version": "1",
            "request_id": uuid4(),
            "code": NativeReasoningErrorCode.DEPENDENCY_UNAVAILABLE,
            "message": "Required dependency is unavailable.",
            "retryable": True,
        }
    )
    assert error.code == NativeReasoningErrorCode.DEPENDENCY_UNAVAILABLE
    with pytest.raises(ValidationError):
        NativeReasoningError.model_validate(
            {
                "contract_version": "1",
                "request_id": None,
                "code": "INTERNAL",
                "message": "  ",
                "retryable": "yes",
                "raw_exception": "sensitive",
            }
        )
