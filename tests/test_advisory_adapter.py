"""Task 213: strict advisory adapter tests.

These tests cover the deterministic gating and advisory-only boundary for the
Task 213 adapter. The model may propose a candidate label, but only a valid,
identity-matched deterministic result may make that suggestion admissible.
"""

from __future__ import annotations

import math
from uuid import UUID

import pytest
from pydantic import ValidationError

from rop.inference.advisory import (
    AdvisoryAdapter,
    AdvisoryAdapterError,
    stable_softmax,
)
from rop.schemas.advisory import (
    MAX_APPROVED_LABELS,
    MAX_LABEL_LENGTH,
    MAX_MAPPING_ENTRIES,
    AdvisoryAdapterResult,
    AdvisoryClassLabelEntry,
    AdvisoryClassLabelMapping,
    AdvisoryErrorCode,
    AdvisoryModelSuggestion,
    AdvisoryRejectionReason,
)
from rop.schemas.inference import InferenceResult
from rop.schemas.native_reasoning import (
    NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
    NATIVE_REASONING_RESULT_SOURCE_TASK_202,
    NativeReasoningRequest,
    NativeReasoningResult,
)

SESSION_ID = UUID(int=100)
OTHER_SESSION_ID = UUID(int=200)
FINGERPRINT = "a" * 64
OTHER_FINGERPRINT = "b" * 64
REQUEST_ID = UUID(int=700)
APPROVED_LABELS = ("alpha", "beta", "gamma")


def _mapping(num_classes: int = 3) -> AdvisoryClassLabelMapping:
    return AdvisoryClassLabelMapping.model_validate(
        {
            "contract_version": "1",
            "mapping_id": "task-213-synthetic-mapping",
            "num_classes": num_classes,
            "entries": [
                {"class_index": 0, "label": "alpha"},
                {"class_index": 2, "label": "beta"},
            ],
        }
    )


def _adapter() -> AdvisoryAdapter:
    return AdvisoryAdapter(
        class_label_mapping=_mapping(), approved_labels=APPROVED_LABELS
    )


def _request() -> NativeReasoningRequest:
    return NativeReasoningRequest.model_validate(
        {
            "request_id": REQUEST_ID,
            "session_id": SESSION_ID,
            "context_fingerprint": FINGERPRINT,
            "task_id": "advisory-suggestion-v1",
            "evidence_ids": [UUID(int=1)],
            "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
        }
    )


def _inference_result(
    *rows: tuple[float, ...],
    artifact_id: str = "artifact-synthetic",
) -> InferenceResult:
    num_classes = len(rows[0])
    return InferenceResult.model_validate(
        {
            "artifact_id": artifact_id,
            "batch_size": len(rows),
            "sequence_length": 4,
            "num_classes": num_classes,
            "logits": rows,
        }
    )


def _deterministic(
    status: str,
    *,
    request_id: UUID = REQUEST_ID,
    session_id: UUID = SESSION_ID,
    fingerprint: str = FINGERPRINT,
) -> NativeReasoningResult:
    payload: dict = {
        "result_id": UUID(int=900),
        "request_id": request_id,
        "session_id": session_id,
        "context_fingerprint": fingerprint,
        "status": status,
        "reason_code": "NO_JUSTIFIED_BASIS",
        "uncertainty": 1.0,
        "supporting_evidence_ids": [],
        "contradicting_evidence_ids": [],
        "missing_information_ids": [],
        "rule_id": None,
        "suggestion_text": None,
        "result_source": NATIVE_REASONING_RESULT_SOURCE_TASK_202,
    }
    if status == "SUPPORTED":
        payload.update(
            {
                "reason_code": "RULE_MATCH",
                "uncertainty": 0.1,
                "supporting_evidence_ids": [UUID(int=1)],
                "rule_id": "rule-match-v1",
            }
        )
    elif status == "CONTRADICTED":
        payload.update(
            {
                "reason_code": "RULE_CONTRADICTION_FOUND",
                "uncertainty": 0.2,
                "supporting_evidence_ids": [UUID(int=1)],
                "contradicting_evidence_ids": [UUID(int=2)],
                "rule_id": "rule-conflict-v1",
            }
        )
    elif status == "INSUFFICIENT":
        payload.update(
            {
                "reason_code": "EVIDENCE_MISSING",
                "uncertainty": 0.9,
                "missing_information_ids": ["second-source"],
            }
        )
    elif status == "ABSTAINED":
        payload.update({"reason_code": "NO_JUSTIFIED_BASIS"})
    elif status == "UNAVAILABLE":
        payload.update({"reason_code": "INPUT_UNAVAILABLE"})
    return NativeReasoningResult.model_validate(payload)


def test_valid_supported_context_produces_an_advisory_only_suggestion() -> None:
    adapter = _adapter()
    request = _request()
    outcome = adapter.propose(
        inference_result=_inference_result((2.0, 0.5, 1.0)),
        request=request,
        deterministic_result=_deterministic("SUPPORTED"),
    )
    assert outcome.admissible is True
    assert outcome.suggestion is not None
    assert outcome.suggestion.advisory_only is True
    assert outcome.suggestion.candidate_label == "alpha"
    assert 0.0 < outcome.suggestion.softmax_score <= 1.0
    assert outcome.rejection_reason is None
    assert outcome.request_id == REQUEST_ID
    assert outcome.session_id == SESSION_ID
    assert outcome.context_fingerprint == FINGERPRINT
    assert outcome.artifact_id == "artifact-synthetic"
    assert AdvisoryAdapterResult.model_validate(outcome.model_dump()) == outcome


def test_missing_deterministic_context_is_non_admissible() -> None:
    outcome = _adapter().propose(
        inference_result=_inference_result((9.0, 0.1, 0.1)),
        request=_request(),
    )
    assert outcome.admissible is False
    assert outcome.suggestion is None
    assert outcome.rejection_reason == AdvisoryRejectionReason.CONTEXT_UNAVAILABLE


def test_invalid_deterministic_context_is_rejected_without_leaking_details() -> None:
    with pytest.raises(AdvisoryAdapterError) as raised:
        _adapter().propose(
            inference_result=_inference_result((9.0, 0.1, 0.1)),
            request=_request(),
            deterministic_result=object(),  # type: ignore[arg-type]
        )
    assert raised.value.code == AdvisoryErrorCode.INVALID_INPUT
    assert "object" not in str(raised.value)


def test_unavailable_deterministic_context_is_non_admissible() -> None:
    outcome = _adapter().propose(
        inference_result=_inference_result((9.0, 0.1, 0.1)),
        request=_request(),
        deterministic_result=_deterministic("UNAVAILABLE"),
    )
    assert outcome.admissible is False
    assert outcome.suggestion is None
    assert outcome.rejection_reason == AdvisoryRejectionReason.CONTEXT_UNAVAILABLE


def test_all_deterministic_rejection_statuses_are_non_admissible() -> None:
    cases = (
        ("CONTRADICTED", AdvisoryRejectionReason.CONTEXT_CONTRADICTED),
        ("INSUFFICIENT", AdvisoryRejectionReason.CONTEXT_INSUFFICIENT),
        ("ABSTAINED", AdvisoryRejectionReason.CONTEXT_ABSTAINED),
        ("UNAVAILABLE", AdvisoryRejectionReason.CONTEXT_UNAVAILABLE),
    )
    for status, reason in cases:
        outcome = _adapter().propose(
            inference_result=_inference_result((9.0, 0.1, 0.1)),
            request=_request(),
            deterministic_result=_deterministic(status),
        )
        assert outcome.admissible is False
        assert outcome.suggestion is None
        assert outcome.rejection_reason == reason


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("CONTRADICTED", AdvisoryRejectionReason.CONTEXT_CONTRADICTED),
        ("INSUFFICIENT", AdvisoryRejectionReason.CONTEXT_INSUFFICIENT),
        ("ABSTAINED", AdvisoryRejectionReason.CONTEXT_ABSTAINED),
    ],
)
def test_non_supportive_deterministic_context_is_non_admissible(
    status: str,
    reason: AdvisoryRejectionReason,
) -> None:
    outcome = _adapter().propose(
        inference_result=_inference_result((9.0, 0.1, 0.1)),
        request=_request(),
        deterministic_result=_deterministic(status),
    )
    assert outcome.admissible is False
    assert outcome.suggestion is None
    assert outcome.rejection_reason == reason


def test_mapping_labels_must_be_unique_and_in_range() -> None:
    with pytest.raises(ValidationError):
        AdvisoryClassLabelMapping.model_validate(
            {
                "contract_version": "1",
                "mapping_id": "task-213-synthetic-mapping",
                "num_classes": 3,
                "entries": [{"class_index": -1, "label": "alpha"}],
            }
        )
    with pytest.raises(ValidationError):
        AdvisoryClassLabelMapping.model_validate(
            {
                "contract_version": "1",
                "mapping_id": "task-213-synthetic-mapping",
                "num_classes": 3,
                "entries": [
                    {"class_index": 0, "label": "alpha"},
                    {"class_index": 0, "label": "beta"},
                ],
            }
        )
    with pytest.raises(ValidationError):
        AdvisoryClassLabelMapping.model_validate(
            {
                "contract_version": "1",
                "mapping_id": "task-213-synthetic-mapping",
                "num_classes": 3,
                "entries": [{"class_index": 3, "label": "alpha"}],
            }
        )
    with pytest.raises(ValidationError):
        AdvisoryClassLabelMapping.model_validate(
            {
                "contract_version": "1",
                "mapping_id": "task-213-synthetic-mapping",
                "num_classes": 3,
                "entries": [
                    {"class_index": 0, "label": "alpha"},
                    {"class_index": 1, "label": "alpha"},
                ],
            }
        )
    with pytest.raises(ValidationError):
        AdvisoryClassLabelMapping.model_validate(
            {
                "contract_version": "1",
                "mapping_id": "task-213-synthetic-mapping",
                "num_classes": 3,
                "entries": [
                    {"class_index": 1, "label": "beta"},
                    {"class_index": 0, "label": "alpha"},
                ],
            }
        )


def test_invalid_mapping_and_approved_label_space_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AdvisoryClassLabelEntry.model_validate({"class_index": 0, "label": "   "})
    with pytest.raises(ValidationError):
        AdvisoryClassLabelEntry.model_validate(
            {"class_index": 0, "label": f"alpha\n{'x' * MAX_LABEL_LENGTH}"}
        )
    with pytest.raises(ValidationError):
        AdvisoryClassLabelEntry.model_validate({"class_index": 0, "label": " alpha"})
    with pytest.raises(ValidationError):
        AdvisoryClassLabelMapping.model_validate(
            {
                "contract_version": "1",
                "mapping_id": "task-213-synthetic-mapping",
                "num_classes": 100,
                "entries": [
                    {"class_index": index, "label": f"label-{index}"}
                    for index in range(MAX_MAPPING_ENTRIES + 1)
                ],
            }
        )

    mapping = AdvisoryClassLabelMapping.model_validate(
        {
            "contract_version": "1",
            "mapping_id": "task-213-synthetic-mapping",
            "num_classes": 3,
            "entries": [{"class_index": 1, "label": "not-approved"}],
        }
    )
    with pytest.raises(AdvisoryAdapterError) as raised:
        AdvisoryAdapter(class_label_mapping=mapping, approved_labels=APPROVED_LABELS)
    assert raised.value.code == AdvisoryErrorCode.INVALID_REQUEST


@pytest.mark.parametrize(
    "approved_labels",
    [
        (),
        "alpha",
        ("alpha", "alpha"),
        ("alpha", ""),
        (" alpha",),
        ("x" * (MAX_LABEL_LENGTH + 1),),
        tuple(f"label-{index}" for index in range(MAX_APPROVED_LABELS + 1)),
        None,
    ],
)
def test_malformed_approved_label_spaces_are_rejected(approved_labels: object) -> None:
    with pytest.raises(AdvisoryAdapterError) as raised:
        AdvisoryAdapter(
            class_label_mapping=_mapping(),
            approved_labels=approved_labels,  # type: ignore[arg-type]
        )
    assert raised.value.code == AdvisoryErrorCode.INVALID_REQUEST


def test_unmapped_winning_class_is_rejected() -> None:
    outcome = _adapter().propose(
        inference_result=_inference_result((0.0, 5.0, 0.0)),
        request=_request(),
        deterministic_result=_deterministic("SUPPORTED"),
    )
    assert outcome.admissible is False
    assert outcome.suggestion is None
    assert outcome.rejection_reason == AdvisoryRejectionReason.UNMAPPED_WINNING_CLASS


def test_deterministic_rejection_takes_precedence_over_unmapped_model_output() -> None:
    outcome = _adapter().propose(
        inference_result=_inference_result((0.0, 5.0, 0.0)),
        request=_request(),
        deterministic_result=_deterministic("CONTRADICTED"),
    )
    assert outcome.admissible is False
    assert outcome.suggestion is None
    assert outcome.rejection_reason == AdvisoryRejectionReason.CONTEXT_CONTRADICTED


def test_detached_deterministic_context_is_rejected() -> None:
    with pytest.raises(AdvisoryAdapterError) as raised:
        _adapter().propose(
            inference_result=_inference_result((2.0, 0.5, 1.0)),
            request=_request(),
            deterministic_result=_deterministic(
                "SUPPORTED", session_id=OTHER_SESSION_ID
            ),
        )
    assert raised.value.code == AdvisoryErrorCode.INVALID_REQUEST
    with pytest.raises(AdvisoryAdapterError) as raised:
        _adapter().propose(
            inference_result=_inference_result((2.0, 0.5, 1.0)),
            request=_request(),
            deterministic_result=_deterministic("SUPPORTED", request_id=UUID(int=701)),
        )
    assert raised.value.code == AdvisoryErrorCode.INVALID_REQUEST

    with pytest.raises(AdvisoryAdapterError) as raised:
        _adapter().propose(
            inference_result=_inference_result((2.0, 0.5, 1.0)),
            request=_request(),
            deterministic_result=_deterministic(
                "SUPPORTED", fingerprint=OTHER_FINGERPRINT
            ),
        )
    assert raised.value.code == AdvisoryErrorCode.INVALID_REQUEST


def test_softmax_is_stable_for_extreme_logits() -> None:
    scores = stable_softmax((1e30, 1e30 - 1e15, 0.0))
    assert all(math.isfinite(value) and value <= 1.0 for value in scores)
    assert math.isclose(sum(scores), 1.0, rel_tol=1e-12, abs_tol=1e-12)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_softmax_rejects_non_finite_logits(value: float) -> None:
    with pytest.raises(AdvisoryAdapterError) as raised:
        stable_softmax((0.0, value))
    assert raised.value.code == AdvisoryErrorCode.INVALID_REQUEST


@pytest.mark.parametrize("logits", [(), "bad", (0.0, "1"), (True, 0.0), (10**1000, 0)])
def test_softmax_rejects_malformed_logits(logits: object) -> None:
    with pytest.raises(AdvisoryAdapterError) as raised:
        stable_softmax(logits)  # type: ignore[arg-type]
    assert raised.value.code == AdvisoryErrorCode.INVALID_REQUEST


def test_equal_logits_produce_uniform_score() -> None:
    outcome = _adapter().propose(
        inference_result=_inference_result((1.0, 1.0, 1.0)),
        request=_request(),
        deterministic_result=_deterministic("SUPPORTED"),
    )
    assert outcome.admissible is True
    assert outcome.suggestion is not None
    assert math.isclose(outcome.suggestion.softmax_score, 1.0 / 3.0, rel_tol=1e-12)


def test_tied_logits_use_the_lowest_class_index() -> None:
    outcome = _adapter().propose(
        inference_result=_inference_result((1.0, 1.0, 1.0)),
        request=_request(),
        deterministic_result=_deterministic("SUPPORTED"),
    )
    assert outcome.suggestion is not None
    assert outcome.suggestion.candidate_label == "alpha"


def test_legacy_softmax_probability_field_is_not_part_of_the_contract() -> None:
    with pytest.raises(ValidationError):
        AdvisoryModelSuggestion.model_validate(
            {
                "candidate_label": "alpha",
                "softmax_probability": 0.5,
                "advisory_only": True,
            }
        )


def test_suggestion_schema_is_strict_and_immutable() -> None:
    outcome = _adapter().propose(
        inference_result=_inference_result((2.0, 0.5, 1.0)),
        request=_request(),
        deterministic_result=_deterministic("SUPPORTED"),
    )
    assert outcome.suggestion is not None
    field_names = set(type(outcome.suggestion).model_fields)
    assert field_names == {"candidate_label", "softmax_score", "advisory_only"}
    result_fields = set(AdvisoryAdapterResult.model_fields)
    for forbidden in ("evidence_ids", "provenance", "status", "source_id"):
        assert forbidden not in result_fields
    with pytest.raises(ValidationError):
        outcome.suggestion.candidate_label = "beta"
    with pytest.raises(ValidationError):
        outcome.admissible = False
    with pytest.raises(ValidationError):
        _mapping().entries[0].label = "beta"


def test_unknown_deterministic_status_is_not_in_the_approved_contract() -> None:
    with pytest.raises(ValidationError):
        _deterministic("UNKNOWN")

    payload = _deterministic("SUPPORTED").model_dump()
    payload["status"] = "UNKNOWN"
    forged = NativeReasoningResult.model_construct(**payload)
    with pytest.raises(AdvisoryAdapterError) as raised:
        _adapter().propose(
            inference_result=_inference_result((2.0, 0.5, 1.0)),
            request=_request(),
            deterministic_result=forged,
        )
    assert raised.value.code == AdvisoryErrorCode.CONTRACT_VIOLATION


def test_fabricated_provenance_fields_fail_schema_validation() -> None:
    with pytest.raises(ValidationError):
        AdvisoryModelSuggestion.model_validate(
            {
                "candidate_label": "alpha",
                "softmax_score": 0.5,
                "advisory_only": True,
                "provenance": {"source_id": "model-claimed"},
            }
        )


def test_non_finite_logits_are_rejected() -> None:
    with pytest.raises(ValidationError):
        InferenceResult.model_validate(
            {
                "artifact_id": "artifact-synthetic",
                "batch_size": 1,
                "sequence_length": 4,
                "num_classes": 3,
                "logits": ((float("nan"), 0.0, 0.0),),
            }
        )


def test_invalid_input_objects_fail_safely() -> None:
    with pytest.raises(AdvisoryAdapterError) as raised:
        _adapter().propose(
            inference_result=object(),  # type: ignore[arg-type]
            request=_request(),
        )
    assert raised.value.code == AdvisoryErrorCode.INVALID_INPUT


def test_multi_row_batches_and_class_count_mismatches_are_rejected() -> None:
    with pytest.raises(AdvisoryAdapterError) as raised:
        _adapter().propose(
            inference_result=_inference_result((2.0, 0.5, 1.0), (2.0, 0.5, 1.0)),
            request=_request(),
            deterministic_result=_deterministic("SUPPORTED"),
        )
    assert raised.value.code == AdvisoryErrorCode.INVALID_REQUEST

    with pytest.raises(AdvisoryAdapterError) as raised:
        _adapter().propose(
            inference_result=_inference_result((2.0, 0.5)),
            request=_request(),
            deterministic_result=_deterministic("SUPPORTED"),
        )
    assert raised.value.code == AdvisoryErrorCode.INVALID_REQUEST


def test_input_contracts_are_not_mutated() -> None:
    request = _request()
    inference = _inference_result((2.0, 0.5, 1.0))
    deterministic = _deterministic("SUPPORTED")
    originals = (
        request.model_dump(),
        inference.model_dump(),
        deterministic.model_dump(),
    )
    _adapter().propose(
        inference_result=inference,
        request=request,
        deterministic_result=deterministic,
    )
    assert request.model_dump() == originals[0]
    assert inference.model_dump() == originals[1]
    assert deterministic.model_dump() == originals[2]


def test_malformed_request_fingerprint_is_rejected_safely() -> None:
    payload = _request().model_dump()
    payload["context_fingerprint"] = "not-a-fingerprint"
    forged = NativeReasoningRequest.model_construct(**payload)
    with pytest.raises(AdvisoryAdapterError) as raised:
        _adapter().propose(
            inference_result=_inference_result((2.0, 0.5, 1.0)),
            request=forged,
            deterministic_result=_deterministic("SUPPORTED"),
        )
    assert raised.value.code == AdvisoryErrorCode.CONTRACT_VIOLATION


def test_adapter_error_messages_are_sanitized() -> None:
    with pytest.raises(AdvisoryAdapterError) as raised:
        _adapter().propose(
            inference_result=_inference_result((1.0, 0.0)),
            request=_request(),
        )
    message = str(raised.value)
    assert "1.0" not in message
    assert raised.value.code == AdvisoryErrorCode.INVALID_REQUEST
