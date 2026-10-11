"""Task 202 contract tests; no runtime, model, provider, or network."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from rop.schemas.native_reasoning import (
    NativeReasonCode,
    NativeReasoningError,
    NativeReasoningErrorCode,
    NativeReasoningErrorMessage,
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


def test_public_contract_field_sets_are_exact() -> None:
    assert set(NativeReasoningRequest.model_fields) == {
        "contract_version",
        "request_id",
        "session_id",
        "context_fingerprint",
        "task",
        "evidence_ids",
    }
    assert set(NativeReasoningResult.model_fields) == {
        "contract_version",
        "request_id",
        "session_id",
        "context_fingerprint",
        "status",
        "conclusion",
        "reason_codes",
        "evidence_ids",
        "missing_information",
        "uncertainty",
        "abstention_reason",
        "suggestions",
    }
    assert set(NativeReasoningSuggestion.model_fields) == {
        "kind",
        "value",
        "reason_code",
        "uncertainty",
        "advisory_only",
    }
    assert set(NativeReasoningError.model_fields) == {
        "contract_version",
        "request_id",
        "code",
        "message",
        "retryable",
    }


@pytest.mark.parametrize(
    "field",
    (
        "contract_version",
        "request_id",
        "session_id",
        "context_fingerprint",
        "task",
        "evidence_ids",
    ),
)
def test_every_request_field_is_required(field: str) -> None:
    request = _request()
    del request[field]
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate(request)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "SUPPORTED_BY_MODEL"),
        ("uncertainty", "CERTAIN"),
    ],
)
def test_result_rejects_unknown_status_and_uncertainty(field: str, value: str) -> None:
    result = _result()
    result[field] = value
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(result)


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


def test_error_code_and_message_must_match() -> None:
    with pytest.raises(ValidationError):
        NativeReasoningError.model_validate(
            {
                "contract_version": "1",
                "request_id": uuid4(),
                "code": NativeReasoningErrorCode.INVALID_REQUEST,
                "message": NativeReasoningErrorMessage.DEPENDENCY_UNAVAILABLE,
                "retryable": False,
            }
        )


def test_error_contract_is_bounded_and_rejects_extra_fields() -> None:
    error = NativeReasoningError.model_validate(
        {
            "contract_version": "1",
            "request_id": uuid4(),
            "code": NativeReasoningErrorCode.DEPENDENCY_UNAVAILABLE,
            "message": NativeReasoningErrorMessage.DEPENDENCY_UNAVAILABLE,
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
                "message": NativeReasoningErrorMessage.INVALID_REQUEST,
                "retryable": "yes",
                "raw_exception": "sensitive",
            }
        )


# --- Task 202 review corrections: status/reason-code matrix and full coverage ---

_STATUS_PATCHES: dict[NativeReasoningStatus, dict[str, object]] = {
    NativeReasoningStatus.SUPPORTED: {},
    NativeReasoningStatus.CONTRADICTED: {
        "status": NativeReasoningStatus.CONTRADICTED,
        "reason_codes": [NativeReasonCode.CONFLICTING_EVIDENCE],
        "evidence_ids": [UUID(int=1), UUID(int=2)],
    },
    NativeReasoningStatus.INSUFFICIENT_EVIDENCE: {
        "status": NativeReasoningStatus.INSUFFICIENT_EVIDENCE,
        "conclusion": None,
        "reason_codes": [NativeReasonCode.EVIDENCE_MISSING],
        "evidence_ids": [],
        "missing_information": ["source provenance"],
        "uncertainty": NativeReasoningUncertainty.UNASSESSED,
    },
    NativeReasoningStatus.UNAVAILABLE: {
        "status": NativeReasoningStatus.UNAVAILABLE,
        "conclusion": None,
        "reason_codes": [NativeReasonCode.EVIDENCE_UNREADABLE],
        "evidence_ids": [],
        "uncertainty": NativeReasoningUncertainty.UNASSESSED,
    },
    NativeReasoningStatus.ABSTAINED: {
        "status": NativeReasoningStatus.ABSTAINED,
        "conclusion": None,
        "reason_codes": [NativeReasonCode.EXPLICIT_ABSTENTION],
        "evidence_ids": [],
        "abstention_reason": "The available inputs do not justify a conclusion.",
        "uncertainty": NativeReasoningUncertainty.UNASSESSED,
    },
    NativeReasoningStatus.UNKNOWN: {
        "status": NativeReasoningStatus.UNKNOWN,
        "conclusion": None,
        "reason_codes": [NativeReasonCode.NO_APPLICABLE_RULE],
        "evidence_ids": [],
        "uncertainty": NativeReasoningUncertainty.UNASSESSED,
    },
}

# Independently stated expectation: codes that may appear alone for each status.
_VALID_SINGLE_CODES: dict[NativeReasoningStatus, set[NativeReasonCode]] = {
    NativeReasoningStatus.SUPPORTED: {NativeReasonCode.RULE_MATCH},
    NativeReasoningStatus.CONTRADICTED: {NativeReasonCode.CONFLICTING_EVIDENCE},
    NativeReasoningStatus.INSUFFICIENT_EVIDENCE: {
        NativeReasonCode.EVIDENCE_MISSING,
        NativeReasonCode.INSUFFICIENT_SUPPORT,
    },
    NativeReasoningStatus.UNAVAILABLE: {
        NativeReasonCode.EVIDENCE_UNREADABLE,
        NativeReasonCode.EVIDENCE_NOT_BOUND,
    },
    NativeReasoningStatus.ABSTAINED: {NativeReasonCode.EXPLICIT_ABSTENTION},
    NativeReasoningStatus.UNKNOWN: {NativeReasonCode.NO_APPLICABLE_RULE},
}


def _status_result(status: NativeReasoningStatus, **patch: object) -> dict:
    return _result(**{**_STATUS_PATCHES[status], **patch})


@pytest.mark.parametrize("status", list(NativeReasoningStatus))
def test_every_status_has_a_valid_result(status: NativeReasoningStatus) -> None:
    result = NativeReasoningResult.model_validate(_status_result(status))
    assert result.status == status


@pytest.mark.parametrize("status", list(NativeReasoningStatus))
@pytest.mark.parametrize("code", list(NativeReasonCode))
def test_status_reason_code_matrix_for_single_codes(
    status: NativeReasoningStatus, code: NativeReasonCode
) -> None:
    payload = _status_result(status, reason_codes=[code])
    if code in _VALID_SINGLE_CODES[status]:
        assert NativeReasoningResult.model_validate(payload).reason_codes == [code]
    else:
        with pytest.raises(ValidationError):
            NativeReasoningResult.model_validate(payload)


@pytest.mark.parametrize("status", list(NativeReasoningStatus))
def test_every_status_rejects_empty_reason_codes(
    status: NativeReasoningStatus,
) -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(_status_result(status, reason_codes=[]))


def test_supported_requires_rule_match_and_rejects_no_applicable_rule() -> None:
    for codes in (
        [],
        [NativeReasonCode.NO_APPLICABLE_RULE],
        [NativeReasonCode.NO_APPLICABLE_RULE, NativeReasonCode.RULE_MATCH],
        [NativeReasonCode.INSUFFICIENT_SUPPORT],
        [NativeReasonCode.EXPLICIT_ABSTENTION],
    ):
        with pytest.raises(ValidationError):
            NativeReasoningResult.model_validate(_result(reason_codes=codes))


@pytest.mark.parametrize(
    ("status", "codes"),
    [
        (
            NativeReasoningStatus.INSUFFICIENT_EVIDENCE,
            [
                NativeReasonCode.EVIDENCE_MISSING,
                NativeReasonCode.INSUFFICIENT_SUPPORT,
            ],
        ),
        (
            NativeReasoningStatus.UNAVAILABLE,
            [
                NativeReasonCode.EVIDENCE_NOT_BOUND,
                NativeReasonCode.EVIDENCE_UNREADABLE,
            ],
        ),
        (
            NativeReasoningStatus.ABSTAINED,
            [
                NativeReasonCode.EXPLICIT_ABSTENTION,
                NativeReasonCode.NO_APPLICABLE_RULE,
            ],
        ),
    ],
)
def test_multi_code_combinations_allowed_for_status(
    status: NativeReasoningStatus, codes: list[NativeReasonCode]
) -> None:
    result = NativeReasoningResult.model_validate(
        _status_result(status, reason_codes=codes)
    )
    assert result.reason_codes == codes


@pytest.mark.parametrize(
    ("status", "codes"),
    [
        (
            NativeReasoningStatus.CONTRADICTED,
            [NativeReasonCode.CONFLICTING_EVIDENCE, NativeReasonCode.EVIDENCE_MISSING],
        ),
        (
            NativeReasoningStatus.INSUFFICIENT_EVIDENCE,
            [NativeReasonCode.EVIDENCE_MISSING, NativeReasonCode.RULE_MATCH],
        ),
        (
            NativeReasoningStatus.UNAVAILABLE,
            [NativeReasonCode.EVIDENCE_UNREADABLE, NativeReasonCode.RULE_MATCH],
        ),
        (
            NativeReasoningStatus.ABSTAINED,
            [NativeReasonCode.EXPLICIT_ABSTENTION, NativeReasonCode.RULE_MATCH],
        ),
        (
            NativeReasoningStatus.UNKNOWN,
            [NativeReasonCode.NO_APPLICABLE_RULE, NativeReasonCode.RULE_MATCH],
        ),
    ],
)
def test_mixed_incompatible_codes_are_rejected(
    status: NativeReasoningStatus, codes: list[NativeReasonCode]
) -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _status_result(status, reason_codes=sorted(codes, key=lambda c: c.value))
        )


def test_abstained_with_only_no_applicable_rule_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _status_result(
                NativeReasoningStatus.ABSTAINED,
                reason_codes=[NativeReasonCode.NO_APPLICABLE_RULE],
            )
        )


def test_unknown_result_is_valid_and_distinct_from_other_statuses() -> None:
    unknown = NativeReasoningResult.model_validate(
        _status_result(NativeReasoningStatus.UNKNOWN)
    )
    assert unknown.conclusion is None
    with_missing = NativeReasoningResult.model_validate(
        _status_result(
            NativeReasoningStatus.UNKNOWN, missing_information=["clinical context"]
        )
    )
    assert with_missing.missing_information == ["clinical context"]


@pytest.mark.parametrize(
    "patch",
    [
        {"conclusion": "A conclusion must not accompany UNKNOWN."},
        {"abstention_reason": "UNKNOWN is not an abstention."},
        {"reason_codes": []},
        {"reason_codes": [NativeReasonCode.CONFLICTING_EVIDENCE]},
        {"reason_codes": [NativeReasonCode.EVIDENCE_UNREADABLE]},
        {"reason_codes": [NativeReasonCode.EXPLICIT_ABSTENTION]},
    ],
)
def test_unknown_rejects_invalid_cross_field_combinations(
    patch: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _status_result(NativeReasoningStatus.UNKNOWN, **patch)
        )


@pytest.mark.parametrize(
    "status",
    [
        NativeReasoningStatus.INSUFFICIENT_EVIDENCE,
        NativeReasoningStatus.UNAVAILABLE,
        NativeReasoningStatus.ABSTAINED,
        NativeReasoningStatus.UNKNOWN,
    ],
)
def test_non_conclusive_statuses_reject_a_conclusion(
    status: NativeReasoningStatus,
) -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _status_result(status, conclusion="Not allowed here.")
        )


@pytest.mark.parametrize(
    "status", [NativeReasoningStatus.SUPPORTED, NativeReasoningStatus.CONTRADICTED]
)
def test_conclusive_statuses_require_conclusion_and_evidence(
    status: NativeReasoningStatus,
) -> None:
    for patch in ({"conclusion": None}, {"evidence_ids": []}):
        with pytest.raises(ValidationError):
            NativeReasoningResult.model_validate(_status_result(status, **patch))
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _status_result(status, uncertainty=NativeReasoningUncertainty.UNASSESSED)
        )


def test_contradicted_requires_two_evidence_references() -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _status_result(
                NativeReasoningStatus.CONTRADICTED, evidence_ids=[UUID(int=1)]
            )
        )


@pytest.mark.parametrize(
    "status",
    [NativeReasoningStatus.SUPPORTED, NativeReasoningStatus.CONTRADICTED],
)
def test_missing_information_is_rejected_for_conclusive_statuses(
    status: NativeReasoningStatus,
) -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _status_result(status, missing_information=["something"])
        )


def test_abstention_reason_only_valid_for_abstained() -> None:
    for status in (
        NativeReasoningStatus.SUPPORTED,
        NativeReasoningStatus.UNKNOWN,
        NativeReasoningStatus.UNAVAILABLE,
    ):
        with pytest.raises(ValidationError):
            NativeReasoningResult.model_validate(
                _status_result(status, abstention_reason="not allowed")
            )


# --- error contract: every code ---

_CODE_RETRYABLE = {
    NativeReasoningErrorCode.INVALID_REQUEST: False,
    NativeReasoningErrorCode.INPUT_UNAVAILABLE: False,
    NativeReasoningErrorCode.DEPENDENCY_UNAVAILABLE: True,
    NativeReasoningErrorCode.RESOURCE_LIMIT: True,
    NativeReasoningErrorCode.CONTRACT_VIOLATION: False,
}


def _error(**patch: object) -> dict:
    error = {
        "contract_version": "1",
        "request_id": uuid4(),
        "code": NativeReasoningErrorCode.INVALID_REQUEST,
        "message": NativeReasoningErrorMessage.INVALID_REQUEST,
        "retryable": False,
    }
    error.update(patch)
    return error


@pytest.mark.parametrize("code", list(NativeReasoningErrorCode))
def test_every_error_code_has_a_valid_canonical_error(
    code: NativeReasoningErrorCode,
) -> None:
    message = NativeReasoningErrorMessage[code.name]
    error = NativeReasoningError.model_validate(
        _error(code=code, message=message, retryable=_CODE_RETRYABLE[code])
    )
    assert error.code == code
    assert error.message == message


def test_error_messages_are_exactly_the_canonical_set() -> None:
    assert {m.name for m in NativeReasoningErrorMessage} == {
        c.name for c in NativeReasoningErrorCode
    }
    assert {m.value for m in NativeReasoningErrorMessage} == {
        "Request is invalid.",
        "Required input is unavailable.",
        "A required dependency is unavailable.",
        "A configured resource limit was reached.",
        "The result did not satisfy its contract.",
    }


@pytest.mark.parametrize("code", list(NativeReasoningErrorCode))
@pytest.mark.parametrize("message", list(NativeReasoningErrorMessage))
def test_error_code_and_message_pairs(
    code: NativeReasoningErrorCode, message: NativeReasoningErrorMessage
) -> None:
    payload = _error(code=code, message=message, retryable=_CODE_RETRYABLE[code])
    if code.name == message.name:
        NativeReasoningError.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            NativeReasoningError.model_validate(payload)


@pytest.mark.parametrize("code", list(NativeReasoningErrorCode))
def test_error_rejects_freeform_message_text(code: NativeReasoningErrorCode) -> None:
    with pytest.raises(ValidationError):
        NativeReasoningError.model_validate(
            _error(code=code, message="Traceback (most recent call last): boom")
        )


def test_error_request_id_may_be_null() -> None:
    assert (
        NativeReasoningError.model_validate(_error(request_id=None)).request_id is None
    )


# --- blank and oversized text ---


@pytest.mark.parametrize("value", ["", " ", "   \t\n"])
def test_blank_conclusion_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(_result(conclusion=value))


def test_oversized_conclusion_is_rejected_and_boundary_is_accepted() -> None:
    NativeReasoningResult.model_validate(_result(conclusion="x" * 4000))
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(_result(conclusion="x" * 4001))


@pytest.mark.parametrize("value", ["", " ", "   \t\n"])
def test_blank_abstention_reason_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _status_result(NativeReasoningStatus.ABSTAINED, abstention_reason=value)
        )


def test_oversized_abstention_reason_is_rejected_and_boundary_is_accepted() -> None:
    NativeReasoningResult.model_validate(
        _status_result(NativeReasoningStatus.ABSTAINED, abstention_reason="x" * 1000)
    )
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _status_result(
                NativeReasoningStatus.ABSTAINED, abstention_reason="x" * 1001
            )
        )


@pytest.mark.parametrize("item", ["", " ", "\t"])
def test_blank_missing_information_item_is_rejected(item: str) -> None:
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _status_result(
                NativeReasoningStatus.INSUFFICIENT_EVIDENCE,
                missing_information=["valid item", item],
            )
        )


def test_oversized_missing_information_item_is_rejected() -> None:
    base = _status_result(NativeReasoningStatus.INSUFFICIENT_EVIDENCE)
    NativeReasoningResult.model_validate({**base, "missing_information": ["x" * 500]})
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            {**base, "missing_information": ["x" * 501]}
        )


def test_missing_information_must_be_sorted_unique_and_bounded() -> None:
    base = _status_result(NativeReasoningStatus.INSUFFICIENT_EVIDENCE)
    for items in (["b", "a"], ["a", "a"]):
        with pytest.raises(ValidationError):
            NativeReasoningResult.model_validate({**base, "missing_information": items})
    too_many = [f"item-{i:03d}" for i in range(65)]
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate({**base, "missing_information": too_many})


def _suggestion(**patch: object) -> dict:
    suggestion = {
        "kind": NativeReasoningSuggestionKind.CANDIDATE_LABEL,
        "value": "possible category",
        "reason_code": NativeReasonCode.NO_APPLICABLE_RULE,
        "uncertainty": NativeReasoningUncertainty.HIGH,
        "advisory_only": True,
    }
    suggestion.update(patch)
    return suggestion


@pytest.mark.parametrize("value", ["", " ", "  \t\n"])
def test_blank_suggestion_value_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        NativeReasoningSuggestion.model_validate(_suggestion(value=value))


def test_oversized_suggestion_value_is_rejected_and_boundary_is_accepted() -> None:
    NativeReasoningSuggestion.model_validate(_suggestion(value="x" * 1000))
    with pytest.raises(ValidationError):
        NativeReasoningSuggestion.model_validate(_suggestion(value="x" * 1001))


def test_oversized_collections_are_rejected() -> None:
    too_many_suggestions = [_suggestion() for _ in range(33)]
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(_result(suggestions=too_many_suggestions))
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            _result(evidence_ids=[UUID(int=i) for i in range(257)])
        )


# --- required / extra / wrong-type across all four public contracts ---

_BUILDERS = {
    NativeReasoningRequest: _request,
    NativeReasoningResult: _result,
    NativeReasoningSuggestion: _suggestion,
    NativeReasoningError: _error,
}
_CONTRACTS = list(_BUILDERS)


@pytest.mark.parametrize("model", _CONTRACTS)
def test_every_field_of_every_contract_is_required(model: type) -> None:
    for field in model.model_fields:
        payload = _BUILDERS[model]()
        del payload[field]
        with pytest.raises(ValidationError):
            model.model_validate(payload)


@pytest.mark.parametrize("model", _CONTRACTS)
def test_every_contract_forbids_extra_fields(model: type) -> None:
    payload = _BUILDERS[model]()
    payload["unexpected_field"] = "value"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("model", _CONTRACTS)
def test_every_contract_accepts_its_baseline_payload(model: type) -> None:
    model.model_validate(_BUILDERS[model]())


_WRONG_TYPES = [
    (NativeReasoningRequest, "contract_version", 1),
    (NativeReasoningRequest, "contract_version", "2"),
    (NativeReasoningRequest, "request_id", 123),
    (NativeReasoningRequest, "session_id", "not-a-uuid"),
    (NativeReasoningRequest, "context_fingerprint", 123),
    (NativeReasoningRequest, "task", 5),
    (NativeReasoningRequest, "evidence_ids", "not-a-list"),
    (NativeReasoningResult, "contract_version", 1),
    (NativeReasoningResult, "request_id", "not-a-uuid"),
    (NativeReasoningResult, "session_id", 123),
    (NativeReasoningResult, "context_fingerprint", 123),
    (NativeReasoningResult, "context_fingerprint", "A" * 64),
    (NativeReasoningResult, "status", 5),
    (NativeReasoningResult, "conclusion", 123),
    (NativeReasoningResult, "reason_codes", "RULE_MATCH"),
    (NativeReasoningResult, "reason_codes", ["NOT_A_CODE"]),
    (NativeReasoningResult, "evidence_ids", "not-a-list"),
    (NativeReasoningResult, "evidence_ids", ["not-a-uuid"]),
    (NativeReasoningResult, "missing_information", "not-a-list"),
    (NativeReasoningResult, "missing_information", [1]),
    (NativeReasoningResult, "uncertainty", 5),
    (NativeReasoningResult, "abstention_reason", 5),
    (NativeReasoningResult, "suggestions", "not-a-list"),
    (NativeReasoningResult, "suggestions", [{"kind": "bogus"}]),
    (NativeReasoningSuggestion, "kind", 5),
    (NativeReasoningSuggestion, "kind", "NOT_A_KIND"),
    (NativeReasoningSuggestion, "value", 123),
    (NativeReasoningSuggestion, "reason_code", 5),
    (NativeReasoningSuggestion, "uncertainty", 5),
    (NativeReasoningSuggestion, "advisory_only", "true"),
    (NativeReasoningError, "contract_version", 1),
    (NativeReasoningError, "request_id", "not-a-uuid"),
    (NativeReasoningError, "code", 5),
    (NativeReasoningError, "code", "INTERNAL"),
    (NativeReasoningError, "message", 5),
    (NativeReasoningError, "retryable", "yes"),
    (NativeReasoningError, "retryable", 1),
]


@pytest.mark.parametrize(("model", "field", "value"), _WRONG_TYPES)
def test_every_contract_rejects_wrongly_typed_fields(
    model: type, field: str, value: object
) -> None:
    payload = _BUILDERS[model]()
    payload[field] = value
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("code", list(NativeReasoningErrorCode))
def test_error_retryable_must_match_canonical_policy(
    code: NativeReasoningErrorCode,
) -> None:
    message = NativeReasoningErrorMessage[code.name]
    canonical = _CODE_RETRYABLE[code]
    accepted = NativeReasoningError.model_validate(
        _error(code=code, message=message, retryable=canonical)
    )
    assert accepted.retryable is canonical
    with pytest.raises(ValidationError):
        NativeReasoningError.model_validate(
            _error(code=code, message=message, retryable=not canonical)
        )


def test_error_retryability_policy_is_exactly_the_documented_mapping() -> None:
    assert _CODE_RETRYABLE == {
        NativeReasoningErrorCode.INVALID_REQUEST: False,
        NativeReasoningErrorCode.INPUT_UNAVAILABLE: False,
        NativeReasoningErrorCode.DEPENDENCY_UNAVAILABLE: True,
        NativeReasoningErrorCode.RESOURCE_LIMIT: True,
        NativeReasoningErrorCode.CONTRACT_VIOLATION: False,
    }
