"""Task 213 strict suggestion validation tests."""

from __future__ import annotations

import pytest

from rop.native_inference import NativeInferenceResponse, NativeLabelScore
from rop.native_suggestion_validation import (
    SuggestionValidationError,
    SuggestionValidationPolicy,
    validate_suggestion_response,
)


HASH = "a" * 64


def _policy(**patch):
    payload = {
        "task_id": "bounded-label-suggestion",
        "expected_model_version": "native-1",
        "expected_vocabulary_hash": HASH,
        "allowed_labels": ("ANION_GAP_HIGH", "POTASSIUM_HIGH"),
        "minimum_probability": 0.5,
        "maximum_suggestions": 2,
    }
    payload.update(patch)
    return SuggestionValidationPolicy.model_validate(payload)


def _response(**patch):
    payload = {
        "model_version": "native-1",
        "vocabulary_hash": HASH,
        "scores": (
            NativeLabelScore(label="ANION_GAP_HIGH", probability=0.8),
            NativeLabelScore(label="POTASSIUM_HIGH", probability=0.6),
        ),
        "advisory_only": True,
    }
    payload.update(patch)
    return NativeInferenceResponse.model_validate(payload)


def test_valid_response_remains_explicitly_advisory():
    result = validate_suggestion_response(_response(), _policy())
    assert result.status == "ADVISORY"
    assert result.trusted_evidence is False
    assert result.clinical_decision is False
    assert len(result.result_hash) == 64


@pytest.mark.parametrize(
    ("response_patch", "policy_patch", "code"),
    [
        ({"model_version": "other"}, {}, "MODEL_VERSION_MISMATCH"),
        ({"vocabulary_hash": "b" * 64}, {}, "VOCABULARY_HASH_MISMATCH"),
        ({"scores": (NativeLabelScore(label="UNDECLARED", probability=0.9),)}, {}, "LABEL_OUT_OF_SPACE"),
        ({"scores": (NativeLabelScore(label="ANION_GAP_HIGH", probability=0.4),)}, {}, "BELOW_THRESHOLD"),
        ({"scores": (NativeLabelScore(label="ANION_GAP_HIGH", probability=0.8), NativeLabelScore(label="POTASSIUM_HIGH", probability=0.6))}, {"maximum_suggestions": 1}, "TOO_MANY_SUGGESTIONS"),
    ],
)
def test_invalid_responses_fail_closed(response_patch, policy_patch, code):
    with pytest.raises(SuggestionValidationError) as caught:
        validate_suggestion_response(_response(**response_patch), _policy(**policy_patch))
    assert caught.value.code == code


def test_response_hash_is_deterministic():
    first = validate_suggestion_response(_response(), _policy())
    second = validate_suggestion_response(_response(), _policy())
    assert first.result_hash == second.result_hash
