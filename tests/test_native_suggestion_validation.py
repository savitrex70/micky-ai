"""Task 213 strict suggestion validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rop.native_inference import NativeInferenceResponse, NativeLabelScore
from rop.native_suggestion_validation import (
    SUGGESTION_VALIDATION_CONTRACT_VERSION,
    SuggestionValidationError,
    SuggestionValidationPolicy,
    ValidatedSuggestionSet,
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
        (
            {"scores": (NativeLabelScore(label="UNDECLARED", probability=0.9),)},
            {},
            "LABEL_OUT_OF_SPACE",
        ),
        (
            {"scores": (NativeLabelScore(label="ANION_GAP_HIGH", probability=0.4),)},
            {},
            "BELOW_THRESHOLD",
        ),
        (
            {
                "scores": (
                    NativeLabelScore(label="ANION_GAP_HIGH", probability=0.8),
                    NativeLabelScore(label="POTASSIUM_HIGH", probability=0.6),
                )
            },
            {"maximum_suggestions": 1},
            "TOO_MANY_SUGGESTIONS",
        ),
    ],
)
def test_invalid_responses_fail_closed(response_patch, policy_patch, code):
    with pytest.raises(SuggestionValidationError) as caught:
        validate_suggestion_response(
            _response(**response_patch), _policy(**policy_patch)
        )
    assert caught.value.code == code


def test_response_hash_is_deterministic():
    first = validate_suggestion_response(_response(), _policy())
    second = validate_suggestion_response(_response(), _policy())
    assert first.result_hash == second.result_hash


# --- policy identity binding ----------------------------------------------------


def test_policy_hash_is_deterministic_and_present_on_the_result():
    first = validate_suggestion_response(_response(), _policy())
    assert first.policy_hash == _policy().policy_hash()
    assert len(first.policy_hash) == 64
    assert first.contract_version == SUGGESTION_VALIDATION_CONTRACT_VERSION == "2"


@pytest.mark.parametrize(
    "patch",
    [
        {"task_id": "another-task"},
        {"expected_model_version": "native-2"},
        {"expected_vocabulary_hash": "b" * 64},
        {"allowed_labels": ("ANION_GAP_HIGH", "POTASSIUM_HIGH", "SODIUM_LOW")},
        {"allowed_labels": ("ANION_GAP_HIGH", "SODIUM_LOW")},
        {"minimum_probability": 0.4},
        {"minimum_probability": 0.0},
        {"maximum_suggestions": 3},
    ],
)
def test_every_material_policy_field_changes_the_policy_and_result_identity(patch):
    single = (NativeLabelScore(label="ANION_GAP_HIGH", probability=0.8),)
    base = validate_suggestion_response(_response(scores=single), _policy())
    changed_policy = _policy(**patch)
    # The response is adjusted only as far as needed to stay valid under the
    # changed policy, so the validated suggestions themselves are identical.
    response_patch = {"scores": single}
    if "expected_model_version" in patch:
        response_patch["model_version"] = patch["expected_model_version"]
    if "expected_vocabulary_hash" in patch:
        response_patch["vocabulary_hash"] = patch["expected_vocabulary_hash"]
    changed = validate_suggestion_response(_response(**response_patch), changed_policy)
    assert changed_policy.policy_hash() != _policy().policy_hash()
    assert changed.policy_hash != base.policy_hash
    assert changed.result_hash != base.result_hash


def test_same_scores_under_a_different_threshold_get_different_result_hashes():
    loose = validate_suggestion_response(_response(), _policy(minimum_probability=0.1))
    strict = validate_suggestion_response(_response(), _policy(minimum_probability=0.5))
    assert loose.suggestions == strict.suggestions
    assert loose.result_hash != strict.result_hash


def test_result_hash_cannot_be_forged_or_detached_from_its_policy():
    result = validate_suggestion_response(_response(), _policy())
    payload = result.model_dump()
    payload["policy_hash"] = _policy(minimum_probability=0.1).policy_hash()
    with pytest.raises(ValidationError):
        ValidatedSuggestionSet.model_validate(payload)
    payload = result.model_dump()
    payload["result_hash"] = "0" * 64
    with pytest.raises(ValidationError):
        ValidatedSuggestionSet.model_validate(payload)


def test_policy_hash_is_domain_separated_from_a_plain_digest():
    import hashlib
    import json

    policy = _policy()
    plain = hashlib.sha256(
        json.dumps(
            policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    assert policy.policy_hash() != plain


@pytest.mark.parametrize("bad", [True, False, 2.0, "2", None, 0, 33])
def test_maximum_suggestions_requires_a_strict_in_range_integer(bad):
    with pytest.raises(ValidationError):
        _policy(maximum_suggestions=bad)


def test_policy_rejects_an_unsupported_contract_version():
    with pytest.raises(ValidationError):
        _policy(contract_version="1")


def test_noncanonical_and_duplicate_responses_remain_rejected():
    with pytest.raises(ValidationError):
        _response(
            scores=(
                NativeLabelScore(label="POTASSIUM_HIGH", probability=0.6),
                NativeLabelScore(label="ANION_GAP_HIGH", probability=0.8),
            )
        )
    with pytest.raises(ValidationError):
        _response(
            scores=(
                NativeLabelScore(label="ANION_GAP_HIGH", probability=0.8),
                NativeLabelScore(label="ANION_GAP_HIGH", probability=0.8),
            )
        )


def test_non_advisory_response_remains_rejected():
    response = _response().model_copy(update={"advisory_only": False})
    with pytest.raises(SuggestionValidationError) as caught:
        validate_suggestion_response(response, _policy())
    assert caught.value.code == "ADVISORY_FLAG_REQUIRED"
