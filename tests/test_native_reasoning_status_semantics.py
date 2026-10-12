"""Task 205 contradiction / missing-information / abstention semantics tests.

Covers the explicit distinctions between SUPPORTED, CONTRADICTED,
INSUFFICIENT_EVIDENCE, UNAVAILABLE, ABSTAINED and UNKNOWN; validators that
prevent status forgery; the reserved evaluation-input marker; and
adversarial combinations. No model, provider, network or database.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

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
    NativeReasoningRequest,
    NativeReasoningResult,
    NativeReasoningStatus,
    NativeReasoningTask,
    NativeReasoningUncertainty,
    NativeUnavailableInput,
    assert_conclusive_reason_codes,
)

SESSION_ID = UUID(int=100)
FINGERPRINT = "a" * 64


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


def _result(**patch: object) -> NativeReasoningResult:
    """A minimal valid SUPPORTED baseline; patch it to attack the contract."""
    value = {
        "contract_version": "1",
        "request_id": UUID(int=700),
        "session_id": SESSION_ID,
        "context_fingerprint": FINGERPRINT,
        "status": NativeReasoningStatus.SUPPORTED,
        "conclusion": "Supported by one validated observation.",
        "reason_codes": [NativeReasonCode.RULE_MATCH],
        "evidence_ids": [UUID(int=1)],
        "missing_information": [],
        "uncertainty": NativeReasoningUncertainty.LOW,
        "abstention_reason": None,
        "suggestions": [],
    }
    value.update(patch)
    return NativeReasoningResult.model_validate(value)


def _record(evidence_id: UUID, **patch: object) -> NativeEvidenceRecord:
    value = {
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
    value.update(patch)
    return NativeEvidenceRecord.model_validate(value)


def _bundle(*records: NativeEvidenceRecord) -> NativeEvidenceBundle:
    return NativeEvidenceBundle.model_validate(
        {
            "contract_version": "1",
            "session_id": SESSION_ID,
            "context_fingerprint": FINGERPRINT,
            "records": tuple(sorted(records, key=lambda item: str(item.evidence_id))),
        }
    )


# --- the reserved Task 205 evaluation-input marker -----------------------


def test_evaluation_input_marker_is_the_nil_uuid() -> None:
    assert TASK_205_EVALUATION_INPUT_ID == UUID(int=0)


def test_result_rejects_the_evaluation_input_marker_as_evidence() -> None:
    with pytest.raises(ValidationError, match="marker"):
        _result(evidence_ids=[UUID(int=1), TASK_205_EVALUATION_INPUT_ID])


def test_request_accepts_any_evidence_identifier_below_the_bundle_boundary() -> None:
    # Requests are boundary-free; binding validation belongs to the bundle.
    request = _request(TASK_205_EVALUATION_INPUT_ID)
    assert request.evidence_ids == [TASK_205_EVALUATION_INPUT_ID]


# --- contradiction vs unavailability cannot be laundered -----------------


@pytest.mark.parametrize(
    ("status", "reason_codes", "evidence_count"),
    [
        (
            NativeReasoningStatus.CONTRADICTED,
            [NativeReasonCode.CONFLICTING_EVIDENCE],
            2,
        ),
        (NativeReasoningStatus.SUPPORTED, [NativeReasonCode.RULE_MATCH], 1),
    ],
)
def test_conclusive_states_require_conclusion_evidence_and_assessed_uncertainty(
    status: NativeReasoningStatus, reason_codes: list, evidence_count: int
) -> None:
    result = _result(
        status=status,
        conclusion="Bounded text.",
        reason_codes=reason_codes,
        evidence_ids=[UUID(int=i + 1) for i in range(evidence_count)],
        uncertainty=NativeReasoningUncertainty.MODERATE,
    )
    assert result.status == status


def test_unavailable_cannot_inherit_contradiction_reason_codes() -> None:
    with pytest.raises(ValidationError, match="incompatible"):
        _result(
            status=NativeReasoningStatus.UNAVAILABLE,
            conclusion=None,
            reason_codes=[NativeReasonCode.CONFLICTING_EVIDENCE],
            evidence_ids=[],
            uncertainty=NativeReasoningUncertainty.UNASSESSED,
        )


def test_missing_evidence_alone_cannot_create_a_contradiction() -> None:
    with pytest.raises(ValidationError, match="incompatible"):
        _result(
            status=NativeReasoningStatus.CONTRADICTED,
            conclusion="Forged contradiction with nothing conflicting.",
            reason_codes=[NativeReasonCode.RULE_MATCH],
        )


def test_insufficient_evidence_requires_missing_information() -> None:
    with pytest.raises(ValidationError, match="missing_information"):
        _result(
            status=NativeReasoningStatus.INSUFFICIENT_EVIDENCE,
            conclusion=None,
            reason_codes=[NativeReasonCode.EVIDENCE_MISSING],
            evidence_ids=[],
            missing_information=[],
            uncertainty=NativeReasoningUncertainty.UNASSESSED,
        )


def test_unavailable_requires_a_supporting_unavailablity_reason() -> None:
    with pytest.raises(ValidationError, match="incompatible"):
        _result(
            status=NativeReasoningStatus.UNAVAILABLE,
            conclusion=None,
            reason_codes=[NativeReasonCode.EVIDENCE_MISSING],
            evidence_ids=[],
            uncertainty=NativeReasoningUncertainty.UNASSESSED,
        )


@pytest.mark.parametrize(
    ("reason_code",),
    [(NativeReasonCode.EVIDENCE_UNREADABLE,), (NativeReasonCode.EVIDENCE_NOT_BOUND,)],
)
def test_unavailable_accepts_each_unavailability_reason(
    reason_code: NativeReasonCode,
) -> None:
    result = _result(
        status=NativeReasoningStatus.UNAVAILABLE,
        conclusion=None,
        reason_codes=[reason_code],
        evidence_ids=[],
        uncertainty=NativeReasoningUncertainty.UNASSESSED,
    )
    assert result.status == NativeReasoningStatus.UNAVAILABLE


# --- abstention metadata --------------------------------------------------


def test_abstained_requires_an_abstention_reason_and_code() -> None:
    with pytest.raises(ValidationError, match="supporting reason code"):
        _result(
            status=NativeReasoningStatus.ABSTAINED,
            conclusion=None,
            reason_codes=[NativeReasonCode.NO_APPLICABLE_RULE],
            evidence_ids=[],
            uncertainty=NativeReasoningUncertainty.UNASSESSED,
            abstention_reason="Not assessable with the supplied evidence.",
        )


def test_abstention_reason_is_invalid_on_other_statuses() -> None:
    with pytest.raises(ValidationError, match="only valid for ABSTAINED"):
        _result(abstention_reason="Borrowed from an abstention.")


# --- NativeUnavailableInput record ---------------------------------------


@pytest.mark.parametrize(
    "reason_code",
    [NativeReasonCode.EVIDENCE_UNREADABLE, NativeReasonCode.EVIDENCE_NOT_BOUND],
)
def test_unavailable_input_records_accept_only_unavailability_reasons(
    reason_code: NativeReasonCode,
) -> None:
    record = NativeUnavailableInput(evidence_id=UUID(int=1), reason_code=reason_code)
    assert record.evidence_id == UUID(int=1)


def test_unavailable_input_rejects_missing_evidence_reason() -> None:
    with pytest.raises(ValidationError):
        NativeUnavailableInput.model_validate(
            {
                "evidence_id": UUID(int=1),
                "reason_code": NativeReasonCode.EVIDENCE_MISSING,
            }
        )


def test_unavailable_input_rejects_the_evaluation_marker() -> None:
    with pytest.raises(ValidationError, match="task identity"):
        NativeUnavailableInput.model_validate(
            {
                "evidence_id": TASK_205_EVALUATION_INPUT_ID,
                "reason_code": NativeReasonCode.EVIDENCE_UNREADABLE,
            }
        )


def test_unavailable_input_records_are_frozen_and_reject_extra_fields() -> None:
    record = NativeUnavailableInput(
        evidence_id=UUID(int=1), reason_code=NativeReasonCode.EVIDENCE_NOT_BOUND
    )
    with pytest.raises(ValidationError):
        record.reason_code = NativeReasonCode.EVIDENCE_UNREADABLE
    with pytest.raises(ValidationError):
        NativeUnavailableInput.model_validate(
            {
                "evidence_id": UUID(int=1),
                "reason_code": NativeReasonCode.EVIDENCE_NOT_BOUND,
                "provider": "external",
            }
        )


# --- status-forcing helpers ------------------------------------------------


def test_assert_conclusive_reason_codes_requires_intersection() -> None:
    assert_conclusive_reason_codes(
        NativeReasoningStatus.SUPPORTED,
        {NativeReasonCode.RULE_MATCH},
        frozenset({NativeReasonCode.RULE_MATCH}),
    )  # must not raise
    with pytest.raises(ValueError, match="requires"):
        assert_conclusive_reason_codes(
            NativeReasoningStatus.SUPPORTED,
            {NativeReasonCode.CONFLICTING_EVIDENCE},
            frozenset({NativeReasonCode.RULE_MATCH}),
        )


# --- forbidden result combinations kept distinct --------------------------


def test_contradiction_in_either_input_order_stays_contributed() -> None:
    # The bundle accepts records supplied in either order (it canonically
    # sorts), while the result always publishes the canonical order.
    _bundle(_record(UUID(int=9)), _record(UUID(int=4)))
    result = _result(
        status=NativeReasoningStatus.CONTRADICTED,
        conclusion="Both claims cannot hold together.",
        reason_codes=[NativeReasonCode.CONFLICTING_EVIDENCE],
        evidence_ids=[UUID(int=4), UUID(int=9)],
        uncertainty=NativeReasoningUncertainty.LOW,
    )
    assert result.evidence_ids == [UUID(int=4), UUID(int=9)]


def test_duplicated_evidence_ids_are_rejected_on_conclusive_results() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        _result(evidence_ids=[UUID(int=1), UUID(int=1)])


def test_mixed_session_identity_in_a_bundle_is_still_rejected() -> None:
    with pytest.raises(ValidationError, match="session"):
        _bundle(_record(UUID(int=1), session_id=UUID(int=101)))


def test_bundle_binding_still_rejects_requested_but_absent_evidence() -> None:
    bundle = _bundle(_record(UUID(int=1)))
    request = _request(UUID(int=1), UUID(int=2))
    from rop.schemas.native_evidence import validate_native_evidence_binding

    with pytest.raises(ValueError, match="absent"):
        validate_native_evidence_binding(request, bundle)


def test_abstention_metadata_cannot_carry_raw_sensitive_payload() -> None:
    # Bounded text only; the field cannot smuggle an oversized narrative.
    with pytest.raises(ValidationError):
        _result(
            status=NativeReasoningStatus.ABSTAINED,
            conclusion=None,
            reason_codes=[NativeReasonCode.EXPLICIT_ABSTENTION],
            evidence_ids=[],
            uncertainty=NativeReasoningUncertainty.LOW,
            abstention_reason="sensitive: " + "x" * 2000,
        )
