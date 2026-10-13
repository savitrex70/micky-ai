"""Task 202: strict native reasoning contract tests.

Exercises the public request/result/error contracts only. No model,
no network, no database, no downstream evidence bundles.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from rop.schemas.native_reasoning import (
    NATIVE_REASONING_ERROR_SOURCE_TASK_202,
    NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
    NATIVE_REASONING_RESULT_SOURCE_TASK_202,
    NativeReasoningError,
    NativeReasoningRequest,
    NativeReasoningResult,
)

_FP = "a" * 64
_FP2 = "b" * 64


def _request(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "request_id": uuid4(),
        "session_id": uuid4(),
        "context_fingerprint": _FP,
        "task_id": "evidence-suggestion-v1",
        "evidence_ids": [],
        "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
    }
    base.update(overrides)
    return NativeReasoningRequest.model_validate(base)


def _result(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "result_id": uuid4(),
        "request_id": uuid4(),
        "session_id": uuid4(),
        "context_fingerprint": _FP,
        "status": "SUPPORTED",
        "reason_code": "RULE_MATCH",
        "uncertainty": 0.1,
        "supporting_evidence_ids": sorted([uuid4(), uuid4()], key=str),
        "contradicting_evidence_ids": [],
        "missing_information_ids": [],
        "rule_id": "rule-match-v1",
        "suggestion_text": None,
        "result_source": NATIVE_REASONING_RESULT_SOURCE_TASK_202,
    }
    base.update(overrides)
    return NativeReasoningResult.model_validate(base)


def _error(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "error_code": "INVALID_REQUEST",
        "message": "native reasoning request is invalid",
        "retryable": False,
        "error_source": NATIVE_REASONING_ERROR_SOURCE_TASK_202,
    }
    base.update(overrides)
    return NativeReasoningError.model_validate(base)


# --- requests: valid ---


def test_valid_minimal_request() -> None:
    req = _request()
    assert req.evidence_ids == ()
    assert req.request_source == NATIVE_REASONING_REQUEST_SOURCE_TASK_202


def test_valid_fully_populated_request() -> None:
    ids = sorted([uuid4(), uuid4()], key=str)
    req = _request(task_id="tag-suggestion-v2", evidence_ids=ids)
    assert [str(v) for v in req.evidence_ids] == [str(v) for v in ids]


# --- requests: invalid ---


def test_request_missing_required_field() -> None:
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate(
            {
                "session_id": uuid4(),
                "context_fingerprint": _FP,
                "task_id": "evidence-suggestion-v1",
                "evidence_ids": [],
                "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
            }
        )


def test_request_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        _request(model="anything")


def test_request_rejects_malformed_identifiers() -> None:
    with pytest.raises(ValidationError):
        _request(request_id="not-a-uuid")
    with pytest.raises(ValidationError):
        _request(session_id="not-a-uuid")
    with pytest.raises(ValidationError):
        _request(evidence_ids=["not-a-uuid"])


def test_request_rejects_bad_fingerprint_and_task() -> None:
    with pytest.raises(ValidationError):
        _request(context_fingerprint="ABC")
    with pytest.raises(ValidationError):
        _request(context_fingerprint="A" * 64)
    with pytest.raises(ValidationError):
        _request(task_id="")
    with pytest.raises(ValidationError):
        _request(task_id="Has Spaces!")
    with pytest.raises(ValidationError):
        _request(task_id="x" * 65)


def test_request_rejects_bad_types_and_bounds() -> None:
    with pytest.raises(ValidationError):
        _request(task_id=123)  # type: ignore[dict-item]
    with pytest.raises(ValidationError):
        _request(evidence_ids=[uuid4(), uuid4(), "x"])  # type: ignore[list-item]
    with pytest.raises(ValidationError):
        _request(evidence_ids=[uuid4()] * 65)
    dup = uuid4()
    with pytest.raises(ValidationError):
        _request(evidence_ids=[dup, dup])


def test_request_rejects_wrong_source() -> None:
    with pytest.raises(ValidationError):
        _request(request_source="WRONG")


# --- results: every status ---


def test_result_supported() -> None:
    _result()


def test_result_contradicted() -> None:
    _result(
        status="CONTRADICTED",
        reason_code="RULE_CONTRADICTION_FOUND",
        supporting_evidence_ids=sorted([uuid4()], key=str),
        contradicting_evidence_ids=sorted([uuid4()], key=str),
        rule_id="rule-contradiction-v1",
    )


def test_result_insufficient() -> None:
    _result(
        status="INSUFFICIENT",
        reason_code="EVIDENCE_MISSING",
        supporting_evidence_ids=[],
        missing_information_ids=["dob"],
        rule_id=None,
    )


def test_result_insufficient_allows_partial_supporting() -> None:
    _result(
        status="INSUFFICIENT",
        reason_code="EVIDENCE_UNBOUND",
        supporting_evidence_ids=sorted([uuid4()], key=str),
        missing_information_ids=["consent"],
        rule_id=None,
    )


def test_result_abstained() -> None:
    _result(
        status="ABSTAINED",
        reason_code="NO_JUSTIFIED_BASIS",
        uncertainty=0.9,
        supporting_evidence_ids=[],
        missing_information_ids=[],
        rule_id=None,
    )


def test_result_unavailable() -> None:
    _result(
        status="UNAVAILABLE",
        reason_code="INPUT_UNAVAILABLE",
        uncertainty=1.0,
        supporting_evidence_ids=[],
        missing_information_ids=[],
        rule_id=None,
        suggestion_text=None,
    )


# --- results: invalid combinations ---


@pytest.mark.parametrize(
    "status,reason",
    [
        ("SUPPORTED", "RULE_CONTRADICTION_FOUND"),
        ("SUPPORTED", "EVIDENCE_MISSING"),
        ("SUPPORTED", "NO_JUSTIFIED_BASIS"),
        ("CONTRADICTED", "RULE_MATCH"),
        ("INSUFFICIENT", "RULE_MATCH"),
        ("ABSTAINED", "RULE_MATCH"),
        ("ABSTAINED", "EVIDENCE_MISSING"),
        ("UNAVAILABLE", "RULE_MATCH"),
        ("UNAVAILABLE", "NO_JUSTIFIED_BASIS"),
    ],
)
def test_result_rejects_bad_status_reason(status: str, reason: str) -> None:
    with pytest.raises(ValidationError):
        _result(status=status, reason_code=reason)  # type: ignore[arg-type]


def test_result_abstention_must_not_carry_evidence_or_rule() -> None:
    with pytest.raises(ValidationError):
        _result(
            status="ABSTAINED",
            reason_code="NO_JUSTIFIED_BASIS",
            supporting_evidence_ids=sorted([uuid4()], key=str),
            rule_id=None,
        )
    with pytest.raises(ValidationError):
        _result(
            status="ABSTAINED",
            reason_code="NO_JUSTIFIED_BASIS",
            supporting_evidence_ids=[],
            rule_id="rule-match-v1",
        )


def test_result_supported_requires_evidence_and_rule() -> None:
    with pytest.raises(ValidationError):
        _result(supporting_evidence_ids=[], rule_id="rule-match-v1")
    with pytest.raises(ValidationError):
        _result(
            supporting_evidence_ids=sorted([uuid4()], key=str),
            rule_id=None,
        )


def test_result_contradicted_requires_both_stances() -> None:
    with pytest.raises(ValidationError):
        _result(
            status="CONTRADICTED",
            reason_code="RULE_CONTRADICTION_FOUND",
            supporting_evidence_ids=sorted([uuid4()], key=str),
            contradicting_evidence_ids=[],
            rule_id="rule-contradiction-v1",
        )


def test_result_insufficient_requires_missing() -> None:
    with pytest.raises(ValidationError):
        _result(
            status="INSUFFICIENT",
            reason_code="EVIDENCE_MISSING",
            supporting_evidence_ids=[],
            missing_information_ids=[],
            rule_id=None,
        )


def test_result_unavailable_carries_nothing() -> None:
    with pytest.raises(ValidationError):
        _result(
            status="UNAVAILABLE",
            reason_code="ENGINE_UNAVAILABLE",
            supporting_evidence_ids=[],
            missing_information_ids=["dob"],
            rule_id=None,
        )
    with pytest.raises(ValidationError):
        _result(
            status="UNAVAILABLE",
            reason_code="ENGINE_UNAVAILABLE",
            supporting_evidence_ids=[],
            missing_information_ids=[],
            rule_id=None,
            suggestion_text="advisory",
        )


def test_result_rejects_overlapping_evidence() -> None:
    shared = uuid4()
    with pytest.raises(ValidationError):
        _result(
            status="CONTRADICTED",
            reason_code="RULE_CONTRADICTION_FOUND",
            supporting_evidence_ids=[shared],
            contradicting_evidence_ids=[shared],
            rule_id="rule-contradiction-v1",
        )


def test_result_rejects_unsorted_or_duplicate_refs() -> None:
    first, second = sorted([uuid4(), uuid4()], key=str)
    with pytest.raises(ValidationError):
        _result(supporting_evidence_ids=[second, first])
    with pytest.raises(ValidationError):
        _result(supporting_evidence_ids=[first, first])
    with pytest.raises(ValidationError):
        _result(
            status="INSUFFICIENT",
            reason_code="EVIDENCE_MISSING",
            supporting_evidence_ids=[],
            missing_information_ids=["b", "a"],
            rule_id=None,
        )


def test_result_rejects_malformed_refs() -> None:
    with pytest.raises(ValidationError):
        _result(supporting_evidence_ids=["not-a-uuid"])  # type: ignore[list-item]
    with pytest.raises(ValidationError):
        _result(
            status="INSUFFICIENT",
            reason_code="EVIDENCE_MISSING",
            supporting_evidence_ids=[],
            missing_information_ids=["has space"],
            rule_id=None,
        )
    with pytest.raises(ValidationError):
        _result(
            status="INSUFFICIENT",
            reason_code="EVIDENCE_MISSING",
            supporting_evidence_ids=[],
            missing_information_ids=["../secret"],
            rule_id=None,
        )


def test_result_rejects_unknown_fields_and_bad_binding() -> None:
    with pytest.raises(ValidationError):
        _result(unknown_field="x")
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate(
            {
                "result_id": uuid4(),
                "session_id": uuid4(),
                "context_fingerprint": _FP,
                "status": "SUPPORTED",
                "reason_code": "RULE_MATCH",
                "uncertainty": 0.1,
                "supporting_evidence_ids": [uuid4()],
                "contradicting_evidence_ids": [],
                "missing_information_ids": [],
                "rule_id": "rule-match-v1",
                "result_source": NATIVE_REASONING_RESULT_SOURCE_TASK_202,
            }
        )


def test_result_uncertainty_bounds() -> None:
    _result(uncertainty=0.0)
    _result(uncertainty=1.0)
    with pytest.raises(ValidationError):
        _result(uncertainty=-0.1)
    with pytest.raises(ValidationError):
        _result(uncertainty=1.1)
    with pytest.raises(ValidationError):
        _result(uncertainty=float("nan"))
    with pytest.raises(ValidationError):
        _result(uncertainty=float("inf"))


def test_result_suggestion_bounds() -> None:
    _result(suggestion_text="consider collecting consent")
    with pytest.raises(ValidationError):
        _result(suggestion_text="")
    with pytest.raises(ValidationError):
        _result(suggestion_text="x" * 501)
    with pytest.raises(ValidationError):
        _result(suggestion_text="line1\nline2")


# --- errors ---


def test_error_codes_and_retryability() -> None:
    assert _error().retryable is False
    assert (
        _error(
            error_code="UNAVAILABLE",
            message="native reasoning is unavailable",
            retryable=True,
        ).retryable
        is True
    )
    assert (
        _error(
            error_code="ENGINE_FAILED",
            message="native reasoning engine failed",
            retryable=False,
        ).retryable
        is False
    )
    assert (
        _error(
            error_code="CONTRACT_VIOLATION",
            message="native reasoning result violates the contract",
            retryable=False,
        ).retryable
        is False
    )


def test_error_rejects_noncanonical_message_and_retryable() -> None:
    with pytest.raises(ValidationError):
        _error(message="custom boom")
    with pytest.raises(ValidationError):
        _error(
            error_code="UNAVAILABLE",
            message="native reasoning is unavailable",
            retryable=False,
        )
    with pytest.raises(ValidationError):
        _error(
            error_code="INVALID_REQUEST",
            message="native reasoning request is invalid",
            retryable=True,
        )


def test_error_rejects_leaky_message() -> None:
    with pytest.raises(ValidationError):
        _error(message='File "x.py", line 1: boom')
    with pytest.raises(ValidationError):
        _error(error_code="BAD_CODE", message="x", retryable=False)  # type: ignore[arg-type]


def test_error_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _error(exception_text="boom")


# --- immutability and determinism ---


def test_contracts_are_immutable() -> None:
    req = _request()
    with pytest.raises(ValidationError):
        req.task_id = "other"  # type: ignore[misc]
    res = _result()
    with pytest.raises(ValidationError):
        res.status = "ABSTAINED"  # type: ignore[misc]
    err = _error()
    with pytest.raises(ValidationError):
        err.retryable = True  # type: ignore[misc]


def test_validation_is_deterministic() -> None:
    first = _request(task_id="evidence-suggestion-v1")
    second = _request(
        request_id=first.request_id,
        session_id=first.session_id,
        context_fingerprint=first.context_fingerprint,
        task_id="evidence-suggestion-v1",
        evidence_ids=list(first.evidence_ids),
    )
    assert first == second
    assert first.model_dump() == second.model_dump()


def test_adversarial_malformed_inputs() -> None:
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate(None)
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate({"request_id": {"nested": 1}})
    with pytest.raises(ValidationError):
        NativeReasoningResult.model_validate({"status": "SUPPORTED"})
    with pytest.raises(ValidationError):
        NativeReasoningError.model_validate(
            {
                "error_code": "INVALID_REQUEST",
                "message": "native reasoning request is invalid",
                "retryable": "yes",  # type: ignore[dict-item]
                "error_source": NATIVE_REASONING_ERROR_SOURCE_TASK_202,
            }
        )
    # fingerprint swap must fail binding format, never silently detach
    with pytest.raises(ValidationError):
        _result(context_fingerprint=_FP2[:-1] + "!")


# --- Task 202 correction: deep immutability ---


def test_collections_are_tuples_not_lists() -> None:
    req = _request(evidence_ids=sorted([uuid4(), uuid4()], key=str))
    assert isinstance(req.evidence_ids, tuple)
    res = _result()
    assert isinstance(res.supporting_evidence_ids, tuple)
    assert isinstance(res.contradicting_evidence_ids, tuple)
    assert isinstance(res.missing_information_ids, tuple)


def test_list_array_input_accepted_as_tuple() -> None:
    ids = sorted([uuid4(), uuid4()], key=str)
    req = _request(evidence_ids=[str(v) for v in ids])
    assert [str(v) for v in req.evidence_ids] == [str(v) for v in ids]
    res = _result(
        status="INSUFFICIENT",
        reason_code="EVIDENCE_MISSING",
        supporting_evidence_ids=[],
        missing_information_ids=["a", "b"],
        rule_id=None,
    )
    assert res.missing_information_ids == ("a", "b")


def test_validated_collections_cannot_be_modified_in_place() -> None:
    req = _request(evidence_ids=sorted([uuid4()], key=str))
    with pytest.raises(AttributeError):
        req.evidence_ids.append(uuid4())  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        req.evidence_ids[0] = uuid4()  # type: ignore[index]
    res = _result()
    with pytest.raises(AttributeError):
        res.supporting_evidence_ids.append(uuid4())  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        res.supporting_evidence_ids[0] = uuid4()  # type: ignore[index]
    abstained = _result(
        status="ABSTAINED",
        reason_code="NO_JUSTIFIED_BASIS",
        uncertainty=0.9,
        supporting_evidence_ids=[],
        missing_information_ids=[],
        rule_id=None,
    )
    with pytest.raises(AttributeError):
        abstained.missing_information_ids.append("x")  # type: ignore[attr-defined]


def test_collection_reassignment_remains_prohibited() -> None:
    req = _request()
    with pytest.raises(ValidationError):
        req.evidence_ids = ()  # type: ignore[misc]
    res = _result()
    with pytest.raises(ValidationError):
        res.supporting_evidence_ids = ()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        res.missing_information_ids = ()  # type: ignore[misc]


def test_serialization_preserves_public_array_representation() -> None:
    ids = sorted([uuid4(), uuid4()], key=str)
    req = _request(evidence_ids=ids)
    dumped = req.model_dump(mode="json")
    assert dumped["evidence_ids"] == [str(v) for v in ids]
    assert isinstance(dumped["evidence_ids"], list)
    res = _result()
    dumped_res = res.model_dump(mode="json")
    assert isinstance(dumped_res["supporting_evidence_ids"], list)
    assert isinstance(dumped_res["missing_information_ids"], list)
    # round-trip through JSON-compatible data preserves equality
    assert NativeReasoningRequest.model_validate(dumped) == req
    assert NativeReasoningResult.model_validate(dumped_res) == res


def test_mutation_cannot_bypass_validation_invariants() -> None:
    res = _result()
    # no mutating API exists, so the validated invariant set is intact
    assert len(res.supporting_evidence_ids) > 0
    assert res.status == "SUPPORTED"
    assert res.reason_code == "RULE_MATCH"
    with pytest.raises(AttributeError):
        res.supporting_evidence_ids.clear()  # type: ignore[attr-defined]
    assert len(res.supporting_evidence_ids) > 0


# --- Task 202 correction: required fields ---


def test_request_evidence_ids_and_source_are_required() -> None:
    base = {
        "request_id": uuid4(),
        "session_id": uuid4(),
        "context_fingerprint": _FP,
        "task_id": "evidence-suggestion-v1",
    }
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate(
            {**base, "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202}
        )
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate({**base, "evidence_ids": []})


def test_result_collections_and_source_are_required() -> None:
    base = {
        "result_id": uuid4(),
        "request_id": uuid4(),
        "session_id": uuid4(),
        "context_fingerprint": _FP,
        "status": "ABSTAINED",
        "reason_code": "NO_JUSTIFIED_BASIS",
        "uncertainty": 0.9,
        "rule_id": None,
        "suggestion_text": None,
    }
    complete = {
        **base,
        "supporting_evidence_ids": [],
        "contradicting_evidence_ids": [],
        "missing_information_ids": [],
        "result_source": NATIVE_REASONING_RESULT_SOURCE_TASK_202,
    }
    NativeReasoningResult.model_validate(complete)
    for omitted in (
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "missing_information_ids",
        "result_source",
    ):
        partial = {k: v for k, v in complete.items() if k != omitted}
        with pytest.raises(ValidationError):
            NativeReasoningResult.model_validate(partial)


def test_error_source_is_required() -> None:
    with pytest.raises(ValidationError):
        NativeReasoningError.model_validate(
            {
                "error_code": "INVALID_REQUEST",
                "message": "native reasoning request is invalid",
                "retryable": False,
            }
        )


def test_explicit_empty_collections_follow_status_rules() -> None:
    # request permits an explicitly supplied empty set
    assert _request(evidence_ids=[]).evidence_ids == ()
    # ABSTAINED permits explicitly empty missing list
    ok = _result(
        status="ABSTAINED",
        reason_code="NO_JUSTIFIED_BASIS",
        uncertainty=0.9,
        supporting_evidence_ids=[],
        missing_information_ids=[],
        rule_id=None,
    )
    assert ok.missing_information_ids == ()
    # SUPPORTED rejects explicitly empty supporting list
    with pytest.raises(ValidationError):
        _result(supporting_evidence_ids=[])


# --- Task 202 correction: deterministic request ordering ---


def test_request_accepts_ordered_unique_references() -> None:
    ids = sorted([uuid4(), uuid4(), uuid4()], key=str)
    req = _request(evidence_ids=ids)
    assert [str(v) for v in req.evidence_ids] == [str(v) for v in ids]


def test_request_rejects_unsorted_references() -> None:
    first, second = sorted([uuid4(), uuid4()], key=str)
    with pytest.raises(ValidationError):
        _request(evidence_ids=[second, first])


def test_request_rejects_duplicate_references() -> None:
    dup = uuid4()
    with pytest.raises(ValidationError):
        _request(evidence_ids=[dup, dup])


def test_request_empty_references_permitted_when_explicit() -> None:
    assert _request(evidence_ids=[]).evidence_ids == ()


def test_request_maximum_bound() -> None:
    ids = sorted([uuid4() for _ in range(64)], key=str)
    assert len(_request(evidence_ids=ids).evidence_ids) == 64
    with pytest.raises(ValidationError):
        _request(evidence_ids=sorted([uuid4() for _ in range(65)], key=str))
