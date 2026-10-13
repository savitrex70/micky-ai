"""Task 203: strict native evidence record tests.

Contract-only tests. No reasoning, no network, no database.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

import rop.schemas as schemas
from rop.schemas.native_evidence import (
    NATIVE_EVIDENCE_SOURCE_TASK_203,
    NativeEvidenceRecord,
    compute_native_evidence_digest,
)
from rop.schemas.native_reasoning import (
    NATIVE_REASONING_ERROR_SOURCE_TASK_202,
    NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
    NATIVE_REASONING_RESULT_SOURCE_TASK_202,
    NativeReasoningError,
    NativeReasoningRequest,
    NativeReasoningResult,
)

_FP = "c" * 64


def _record(**overrides):  # type: ignore[no-untyped-def]
    content = "normalized observation text"
    base = {
        "evidence_id": uuid4(),
        "session_id": uuid4(),
        "context_fingerprint": _FP,
        "evidence_type": "OBSERVATION",
        "source_reference": "chart:encounter-123",
        "provenance_id": "prov-001",
        "content_text": content,
        "content_digest": compute_native_evidence_digest(content),
        "availability": "AVAILABLE",
        "uncertainty": 0.2,
        "evidence_source": NATIVE_EVIDENCE_SOURCE_TASK_203,
    }
    base.update(overrides)
    return NativeEvidenceRecord.model_validate(base)


def _unreadable(**overrides):  # type: ignore[no-untyped-def]
    base = {
        "evidence_id": uuid4(),
        "session_id": uuid4(),
        "context_fingerprint": _FP,
        "evidence_type": "ASSERTION",
        "source_reference": "lab:panel-4",
        "provenance_id": "prov-002",
        "content_text": "",
        "content_digest": compute_native_evidence_digest(""),
        "availability": "UNREADABLE",
        "uncertainty": 1.0,
        "evidence_source": NATIVE_EVIDENCE_SOURCE_TASK_203,
    }
    base.update(overrides)
    return NativeEvidenceRecord.model_validate(base)


def test_valid_minimal_record() -> None:
    rec = _record()
    assert rec.availability == "AVAILABLE"
    assert rec.evidence_source == NATIVE_EVIDENCE_SOURCE_TASK_203


def test_valid_unreadable_record() -> None:
    rec = _unreadable()
    assert rec.content_text == ""


def test_each_evidence_type() -> None:
    assert _record(evidence_type="OBSERVATION").evidence_type == "OBSERVATION"
    assert _record(evidence_type="ASSERTION").evidence_type == "ASSERTION"
    with pytest.raises(ValidationError):
        _record(evidence_type="DIAGNOSIS")  # type: ignore[dict-item]
    with pytest.raises(ValidationError):
        _record(evidence_type="SUPPORTING")  # type: ignore[dict-item]


def test_required_field_omission() -> None:
    content = "normalized observation text"
    complete = {
        "evidence_id": uuid4(),
        "session_id": uuid4(),
        "context_fingerprint": _FP,
        "evidence_type": "OBSERVATION",
        "source_reference": "chart:encounter-123",
        "provenance_id": "prov-001",
        "content_text": content,
        "content_digest": compute_native_evidence_digest(content),
        "availability": "AVAILABLE",
        "uncertainty": 0.2,
        "evidence_source": NATIVE_EVIDENCE_SOURCE_TASK_203,
    }
    NativeEvidenceRecord.model_validate(complete)
    for omitted in complete:
        partial = {k: v for k, v in complete.items() if k != omitted}
        with pytest.raises(ValidationError):
            NativeEvidenceRecord.model_validate(partial)


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _record(is_trusted=True)
    with pytest.raises(ValidationError):
        _record(verified=True)
    with pytest.raises(ValidationError):
        _record(conclusion="flu")


def test_rejects_bad_identifiers_and_binding() -> None:
    with pytest.raises(ValidationError):
        _record(evidence_id="not-a-uuid")
    with pytest.raises(ValidationError):
        _record(session_id="not-a-uuid")
    with pytest.raises(ValidationError):
        _record(context_fingerprint="Z" * 64)
    with pytest.raises(ValidationError):
        _record(context_fingerprint="abc")


def test_rejects_bad_source_references() -> None:
    for bad in [
        "",
        "has space",
        "../secret",
        "/abs/path",
        "C:\\win\\path",
        "D:/win/path",
        "line1\nline2",
        "x" * 256,
    ]:
        with pytest.raises(ValidationError):
            _record(source_reference=bad)
    with pytest.raises(ValidationError):
        _record(provenance_id="has space")
    with pytest.raises(ValidationError):
        _record(provenance_id="")
    with pytest.raises(ValidationError):
        _record(provenance_id="p" * 129)
    assert _record(source_reference="a").source_reference == "a"


def test_rejects_malformed_digest_and_mismatch() -> None:
    with pytest.raises(ValidationError):
        _record(content_digest="Z" * 64)
    with pytest.raises(ValidationError):
        _record(content_digest="a" * 63)
    # well-formed digest for different content must fail verification
    with pytest.raises(ValidationError):
        _record(
            content_text="normalized observation text",
            content_digest=compute_native_evidence_digest("other text"),
        )
    # tampered content with stale digest fails
    good = _record()
    with pytest.raises(ValidationError):
        _record(
            content_text=good.content_text + "!",
            content_digest=good.content_digest,
        )


def test_empty_and_maximum_payloads() -> None:
    # empty content only valid for UNREADABLE
    with pytest.raises(ValidationError):
        _record(content_text="", content_digest=compute_native_evidence_digest(""))
    assert _unreadable().content_text == ""
    biggest = "x" * 2000
    rec = _record(
        content_text=biggest,
        content_digest=compute_native_evidence_digest(biggest),
    )
    assert rec.content_text == biggest
    with pytest.raises(ValidationError):
        too_big = "x" * 2001
        _record(
            content_text=too_big,
            content_digest=compute_native_evidence_digest(too_big),
        )


def test_rejects_over_limit_values() -> None:
    with pytest.raises(ValidationError):
        _record(uncertainty=-0.1)
    with pytest.raises(ValidationError):
        _record(uncertainty=1.1)
    with pytest.raises(ValidationError):
        _record(uncertainty=float("nan"))
    with pytest.raises(ValidationError):
        _record(evidence_type=123)  # type: ignore[dict-item]
    with pytest.raises(ValidationError):
        _record(availability="MAYBE")  # type: ignore[dict-item]


def test_deep_immutability() -> None:
    rec = _record()
    with pytest.raises(ValidationError):
        rec.content_text = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        rec.uncertainty = 0.9  # type: ignore[misc]
    # no mutable collection reachable: every field is an immutable scalar
    for name in (
        "evidence_id",
        "session_id",
        "context_fingerprint",
        "evidence_type",
        "source_reference",
        "provenance_id",
        "content_text",
        "content_digest",
        "availability",
        "uncertainty",
        "evidence_source",
    ):
        value = getattr(rec, name)
        assert not isinstance(value, (list, dict, set, bytearray))


def test_stable_serialization_and_round_trip() -> None:
    rec = _record()
    first = rec.model_dump(mode="json")
    second = _record(
        evidence_id=rec.evidence_id,
        session_id=rec.session_id,
        context_fingerprint=rec.context_fingerprint,
        evidence_type=rec.evidence_type,
        source_reference=rec.source_reference,
        provenance_id=rec.provenance_id,
        content_text=rec.content_text,
        content_digest=rec.content_digest,
        availability=rec.availability,
        uncertainty=rec.uncertainty,
    ).model_dump(mode="json")
    assert first == second
    assert NativeEvidenceRecord.model_validate(first) == rec


def test_deterministic_digest() -> None:
    assert compute_native_evidence_digest("abc") == compute_native_evidence_digest(
        "abc"
    )
    assert compute_native_evidence_digest("abc") != compute_native_evidence_digest(
        "abd"
    )


def test_syntactic_provenance_is_not_verification() -> None:
    # A well-formed provenance id is accepted, but acceptance performs
    # no lookup against any trusted registry: Task 203 has no such
    # mechanism by design, and caller-asserted trust flags are refused.
    rec = _record(provenance_id="prov-external-9")
    assert rec.provenance_id == "prov-external-9"
    with pytest.raises(ValidationError):
        _record(provenance_id="prov-external-9", is_verified=True)
    assert not hasattr(rec, "is_trusted")
    assert not hasattr(rec, "verified")


def test_task_202_contracts_remain_compatible() -> None:
    req = NativeReasoningRequest.model_validate(
        {
            "request_id": uuid4(),
            "session_id": uuid4(),
            "context_fingerprint": "a" * 64,
            "task_id": "evidence-suggestion-v1",
            "evidence_ids": [],
            "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
        }
    )
    assert req.evidence_ids == ()
    res = NativeReasoningResult.model_validate(
        {
            "result_id": uuid4(),
            "request_id": uuid4(),
            "session_id": uuid4(),
            "context_fingerprint": "a" * 64,
            "status": "ABSTAINED",
            "reason_code": "NO_JUSTIFIED_BASIS",
            "uncertainty": 0.9,
            "supporting_evidence_ids": [],
            "contradicting_evidence_ids": [],
            "missing_information_ids": [],
            "rule_id": None,
            "suggestion_text": None,
            "result_source": NATIVE_REASONING_RESULT_SOURCE_TASK_202,
        }
    )
    assert res.status == "ABSTAINED"
    err = NativeReasoningError.model_validate(
        {
            "error_code": "INVALID_REQUEST",
            "message": "native reasoning request is invalid",
            "retryable": False,
            "error_source": NATIVE_REASONING_ERROR_SOURCE_TASK_202,
        }
    )
    assert err.retryable is False
    for name in (
        "NativeEvidenceRecord",
        "NativeReasoningRequest",
        "NativeReasoningResult",
        "NativeReasoningError",
    ):
        assert name in schemas.__all__
