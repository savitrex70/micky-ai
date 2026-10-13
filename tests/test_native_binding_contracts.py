"""Task 204: native request/evidence binding contract tests.

Contract-only tests. No reasoning, evaluation, network, or database.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

import rop.schemas as schemas
from rop.schemas.native_binding import (
    NATIVE_BINDING_SOURCE_TASK_204,
    NativeEvidenceBinding,
)
from rop.schemas.native_evidence import (
    NATIVE_EVIDENCE_SOURCE_TASK_203,
    NativeEvidenceRecord,
    compute_native_evidence_digest,
)
from rop.schemas.native_reasoning import (
    NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
    NativeReasoningRequest,
)

_FP = "d" * 64
_FP_OTHER = "e" * 64


def _record(
    evidence_id: UUID,
    session_id: UUID,
    fingerprint: str = _FP,
    content: str = "normalized observation text",
) -> NativeEvidenceRecord:
    return NativeEvidenceRecord.model_validate(
        {
            "evidence_id": evidence_id,
            "session_id": session_id,
            "context_fingerprint": fingerprint,
            "evidence_type": "OBSERVATION",
            "source_reference": "chart:encounter-123",
            "provenance_id": "prov-001",
            "content_text": content,
            "content_digest": compute_native_evidence_digest(content),
            "availability": "AVAILABLE",
            "uncertainty": 0.2,
            "evidence_source": NATIVE_EVIDENCE_SOURCE_TASK_203,
        }
    )


def _request(session_id: UUID, evidence_ids: list[UUID]) -> NativeReasoningRequest:
    return NativeReasoningRequest.model_validate(
        {
            "request_id": uuid4(),
            "session_id": session_id,
            "context_fingerprint": _FP,
            "task_id": "evidence-suggestion-v1",
            "evidence_ids": sorted(evidence_ids, key=str),
            "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
        }
    )


def _bind(
    request: NativeReasoningRequest, evidence: list[NativeEvidenceRecord]
) -> NativeEvidenceBinding:
    return NativeEvidenceBinding.model_validate(
        {
            "request": request.model_dump(mode="json"),
            "evidence": [record.model_dump(mode="json") for record in evidence],
            "binding_source": NATIVE_BINDING_SOURCE_TASK_204,
        }
    )


def test_valid_binding() -> None:
    session_id = uuid4()
    first, second = sorted([uuid4(), uuid4()], key=str)
    binding = _bind(
        _request(session_id, [first, second]),
        [_record(first, session_id), _record(second, session_id)],
    )
    assert binding.binding_source == NATIVE_BINDING_SOURCE_TASK_204
    assert [str(record.evidence_id) for record in binding.evidence] == [
        str(first),
        str(second),
    ]


def test_empty_binding_permitted_when_explicit() -> None:
    binding = _bind(_request(uuid4(), []), [])
    assert binding.evidence == ()


def test_matching_session_accepted() -> None:
    session_id = uuid4()
    only = uuid4()
    binding = _bind(_request(session_id, [only]), [_record(only, session_id)])
    assert binding.request.session_id == session_id


def test_mismatching_session_rejected() -> None:
    session_id = uuid4()
    only = uuid4()
    with pytest.raises(ValidationError):
        _bind(_request(session_id, [only]), [_record(only, uuid4())])


def test_mismatching_fingerprint_rejected() -> None:
    session_id = uuid4()
    only = uuid4()
    with pytest.raises(ValidationError):
        _bind(
            _request(session_id, [only]),
            [_record(only, session_id, fingerprint=_FP_OTHER)],
        )


def test_duplicate_evidence_identifiers_rejected() -> None:
    session_id = uuid4()
    only = uuid4()
    request = NativeReasoningRequest.model_validate(
        {
            "request_id": uuid4(),
            "session_id": session_id,
            "context_fingerprint": _FP,
            "task_id": "evidence-suggestion-v1",
            "evidence_ids": [only],
            "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
        }
    )
    with pytest.raises(ValidationError):
        _bind(request, [_record(only, session_id), _record(only, session_id)])


def test_missing_referenced_evidence_rejected() -> None:
    session_id = uuid4()
    first, second = sorted([uuid4(), uuid4()], key=str)
    with pytest.raises(ValidationError):
        _bind(
            _request(session_id, [first, second]),
            [_record(first, session_id)],
        )


def test_unreferenced_supplied_evidence_rejected() -> None:
    session_id = uuid4()
    only = uuid4()
    with pytest.raises(ValidationError):
        _bind(
            _request(session_id, [only]),
            [_record(only, session_id), _record(uuid4(), session_id)],
        )


def test_invalid_request_and_evidence_types_rejected() -> None:
    session_id = uuid4()
    only = uuid4()
    valid_request = _request(session_id, [only])
    valid_record = _record(only, session_id)
    with pytest.raises(ValidationError):
        NativeEvidenceBinding.model_validate(
            {
                "request": "not-a-request",
                "evidence": [valid_record.model_dump(mode="json")],
                "binding_source": NATIVE_BINDING_SOURCE_TASK_204,
            }
        )
    with pytest.raises(ValidationError):
        NativeEvidenceBinding.model_validate(
            {
                "request": valid_request.model_dump(mode="json"),
                "evidence": ["not-a-record"],
                "binding_source": NATIVE_BINDING_SOURCE_TASK_204,
            }
        )
    with pytest.raises(ValidationError):
        NativeEvidenceBinding.model_validate(
            {
                "request": valid_request.model_dump(mode="json"),
                "evidence": [
                    {**valid_record.model_dump(mode="json"), "content_text": "tampered"}
                ],
                "binding_source": NATIVE_BINDING_SOURCE_TASK_204,
            }
        )
    with pytest.raises(ValidationError):
        NativeEvidenceBinding.model_validate(
            {
                "request": valid_request.model_dump(mode="json"),
                "binding_source": NATIVE_BINDING_SOURCE_TASK_204,
            }
        )


def test_collections_deeply_immutable() -> None:
    session_id = uuid4()
    only = uuid4()
    binding = _bind(_request(session_id, [only]), [_record(only, session_id)])
    assert isinstance(binding.evidence, tuple)
    with pytest.raises(AttributeError):
        binding.evidence.append(binding.evidence[0])  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        binding.evidence[0] = binding.evidence[0]  # type: ignore[index]
    with pytest.raises(ValidationError):
        binding.evidence = ()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        binding.evidence[0].content_text = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        binding.request.task_id = "other"  # type: ignore[misc]


def test_deterministic_ordering_and_repeat_construction() -> None:
    session_id = uuid4()
    first, second = sorted([uuid4(), uuid4()], key=str)
    request = _request(session_id, [first, second])
    records = [_record(first, session_id), _record(second, session_id)]
    assert _bind(request, records) == _bind(request, list(records))
    assert _bind(request, records).model_dump(mode="json") == _bind(
        request, list(records)
    ).model_dump(mode="json")
    with pytest.raises(ValidationError):
        _bind(request, list(reversed(records)))


def test_invalid_fingerprints_and_identifiers_rejected() -> None:
    session_id = uuid4()
    only = uuid4()
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate(
            {
                "request_id": uuid4(),
                "session_id": session_id,
                "context_fingerprint": "Z" * 64,
                "task_id": "evidence-suggestion-v1",
                "evidence_ids": [only],
                "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
            }
        )
    with pytest.raises(ValidationError):
        _record(UUID(int=0), UUID(int=0), fingerprint="short")


def test_bypass_flags_and_trust_claims_rejected() -> None:
    session_id = uuid4()
    only = uuid4()
    request = _request(session_id, [only])
    record = _record(only, session_id)
    with pytest.raises(ValidationError):
        NativeEvidenceBinding.model_validate(
            {
                "request": request.model_dump(mode="json"),
                "evidence": [record.model_dump(mode="json")],
                "binding_source": NATIVE_BINDING_SOURCE_TASK_204,
                "skip_binding_checks": True,
            }
        )
    with pytest.raises(ValidationError):
        NativeEvidenceBinding.model_validate(
            {
                "request": request.model_dump(mode="json"),
                "evidence": [record.model_dump(mode="json")],
                "binding_source": NATIVE_BINDING_SOURCE_TASK_204,
                "verified": True,
            }
        )
    assert not hasattr(_bind(request, [record]), "verified")


def test_task_202_and_203_validation_intact() -> None:
    session_id = uuid4()
    only = uuid4()
    assert _request(session_id, [only]).evidence_ids == (only,)
    record = _record(only, session_id)
    assert record.content_digest == compute_native_evidence_digest(
        "normalized observation text"
    )
    with pytest.raises(ValidationError):
        NativeReasoningRequest.model_validate(
            {
                "request_id": uuid4(),
                "session_id": session_id,
                "context_fingerprint": _FP,
                "task_id": "evidence-suggestion-v1",
                "request_source": NATIVE_REASONING_REQUEST_SOURCE_TASK_202,
            }
        )
    with pytest.raises(ValidationError):
        NativeEvidenceRecord.model_validate(
            {
                "evidence_id": only,
                "session_id": session_id,
                "context_fingerprint": _FP,
                "evidence_type": "DIAGNOSIS",
                "source_reference": "chart:encounter-123",
                "provenance_id": "prov-001",
                "content_text": "normalized observation text",
                "content_digest": compute_native_evidence_digest(
                    "normalized observation text"
                ),
                "availability": "AVAILABLE",
                "uncertainty": 0.2,
                "evidence_source": NATIVE_EVIDENCE_SOURCE_TASK_203,
            }
        )
    for name in (
        "NativeEvidenceBinding",
        "NativeEvidenceRecord",
        "NativeReasoningRequest",
        "NativeReasoningResult",
        "NativeReasoningError",
    ):
        assert name in schemas.__all__
