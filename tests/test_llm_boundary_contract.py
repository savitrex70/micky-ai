"""Task 113: canonical LLM boundary contract registry tests.

Proves Tasks 057 and 103-112 reuse one authoritative source instead of
silently maintaining competing copies, and that centralization did not
change valid behavior. No real provider, no network, no DB.
"""

from __future__ import annotations

import uuid

from rop.schemas.llm_reasoning import (
    Assessment,
    LLMReasoningProposalRead,
    ReasoningCandidateAssessmentRead,
    _RawLLMReasoningProposal,
)
from rop.services import llm_reasoning as reasoning_mod
from rop.services import llm_reasoning_audit as audit_mod
from rop.services import llm_request_serialization as serial_mod
from rop.services.llm_boundary_contract import (
    ALLOWED_BOUNDARY_OUTCOMES,
    ASSESSMENT_FIELDS,
    OUTCOME_INPUT_INCONSISTENT,
    OUTCOME_INPUT_UNAVAILABLE,
    OUTCOME_MODEL_OUTPUT_INCONSISTENT,
    OUTCOME_MODEL_OUTPUT_INVALID,
    OUTCOME_MODEL_UNAVAILABLE,
    PAYLOAD_FIELDS,
    PROPOSAL_TOP_FIELDS,
    PROVIDER_RESPONSE_KNOWN_FIELDS,
    PROVIDER_RESPONSE_REQUIRED_FIELDS,
    RAW_PROPOSAL_TOP_FIELDS,
    VALID_ASSESSMENTS,
)
from rop.services.llm_proposal_normalization import (
    _REQUIRED_ASSESSMENT_FIELDS,
    _REQUIRED_TOP_FIELDS,
    normalize_proposal,
    validate_normalized,
)
from rop.services.llm_proposal_normalization import (
    _VALID_ASSESSMENTS as _NORM_VALID,
)
from rop.services.llm_provider_isolation import ProviderFailureBoundary
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
)


def test_canonical_collection_order_is_fixed() -> None:
    assert PROPOSAL_TOP_FIELDS == (
        "session_id",
        "context_fingerprint",
        "provider",
        "model",
        "candidate_assessments",
        "available",
        "proposal_consistent",
        "llm_reasoning_source",
    )
    assert ASSESSMENT_FIELDS == (
        "candidate_id",
        "assessment",
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "unresolved_information_ids",
        "explanation",
        "uncertainty_flags",
    )
    assert RAW_PROPOSAL_TOP_FIELDS == ("candidate_assessments",)
    assert PAYLOAD_FIELDS == (
        "session_id",
        "observations",
        "entities",
        "missing_information",
        "template_context",
        "candidate_state",
        "reasoning_pipeline",
    )
    assert PROVIDER_RESPONSE_REQUIRED_FIELDS == ("provider", "model", "text")
    assert PROVIDER_RESPONSE_KNOWN_FIELDS == (
        "provider",
        "model",
        "text",
        "context_fingerprint",
    )
    assert VALID_ASSESSMENTS == ("SUPPORTS", "WEAKENS", "UNCLEAR")
    assert ALLOWED_BOUNDARY_OUTCOMES == (
        OUTCOME_INPUT_UNAVAILABLE,
        OUTCOME_INPUT_INCONSISTENT,
        OUTCOME_MODEL_UNAVAILABLE,
        OUTCOME_MODEL_OUTPUT_INVALID,
        OUTCOME_MODEL_OUTPUT_INCONSISTENT,
    )


def test_serialization_reuses_canonical_payload_fields() -> None:
    assert serial_mod.ALLOWED_PAYLOAD_FIELDS == PAYLOAD_FIELDS
    assert serial_mod.ALLOWED_PAYLOAD_FIELDS is PAYLOAD_FIELDS


def test_normalization_reuses_canonical_field_sets() -> None:
    assert _REQUIRED_TOP_FIELDS == PROPOSAL_TOP_FIELDS
    assert _REQUIRED_TOP_FIELDS is PROPOSAL_TOP_FIELDS
    assert _REQUIRED_ASSESSMENT_FIELDS == ASSESSMENT_FIELDS
    assert _REQUIRED_ASSESSMENT_FIELDS is ASSESSMENT_FIELDS
    assert _NORM_VALID == VALID_ASSESSMENTS
    assert _NORM_VALID is VALID_ASSESSMENTS


def test_audit_reuses_canonical_field_sets() -> None:
    assert audit_mod._REQUIRED_TOP_FIELDS == PROPOSAL_TOP_FIELDS
    assert audit_mod._REQUIRED_NESTED_FIELDS == ASSESSMENT_FIELDS
    assert audit_mod._VALID_ASSESSMENTS == set(VALID_ASSESSMENTS)


def test_provider_response_shape_matches_registry() -> None:
    assert tuple(LLMReasoningProviderResponse.__dataclass_fields__) == tuple(
        PROVIDER_RESPONSE_REQUIRED_FIELDS
    )
    assert set(PROVIDER_RESPONSE_KNOWN_FIELDS) == {
        "provider",
        "model",
        "text",
        "context_fingerprint",
    }
    assert set(PROVIDER_RESPONSE_REQUIRED_FIELDS) < set(PROVIDER_RESPONSE_KNOWN_FIELDS)


def test_task_057_outcome_aliases_match_registry() -> None:
    assert reasoning_mod._OUTCOME_INPUT_UNAVAILABLE == OUTCOME_INPUT_UNAVAILABLE
    assert reasoning_mod._OUTCOME_INPUT_INCONSISTENT == OUTCOME_INPUT_INCONSISTENT
    assert reasoning_mod._OUTCOME_MODEL_UNAVAILABLE == OUTCOME_MODEL_UNAVAILABLE
    assert reasoning_mod._OUTCOME_MODEL_OUTPUT_INVALID == OUTCOME_MODEL_OUTPUT_INVALID
    assert (
        reasoning_mod._OUTCOME_MODEL_OUTPUT_INCONSISTENT
        == OUTCOME_MODEL_OUTPUT_INCONSISTENT
    )


def test_failure_normalizer_only_returns_registry_outcomes() -> None:
    cases = [
        LLMReasoningProviderError("connection reset by peer"),
        ConnectionError("refused"),
        ValueError("not valid json {{{"),
        KeyError("candidate_id"),
        RuntimeError("reference unknown candidate xyz"),
        RuntimeError("audit provenance broken"),
        RuntimeError("utterly unknown failure mode"),
    ]
    for exc in cases:
        outcome = ProviderFailureBoundary.normalize_failure(exc)
        assert outcome in ALLOWED_BOUNDARY_OUTCOMES
    # Spot-check the authoritative mapping, not just membership.
    assert (
        ProviderFailureBoundary.normalize_failure(
            LLMReasoningProviderError("connection reset")
        )
        == OUTCOME_MODEL_UNAVAILABLE
    )
    assert (
        ProviderFailureBoundary.normalize_failure(ValueError("bad json"))
        == OUTCOME_MODEL_OUTPUT_INVALID
    )


def test_pydantic_schemas_agree_with_registry() -> None:
    assert set(LLMReasoningProposalRead.model_fields) == set(PROPOSAL_TOP_FIELDS)
    assert set(ReasoningCandidateAssessmentRead.model_fields) == set(ASSESSMENT_FIELDS)
    assert set(_RawLLMReasoningProposal.model_fields) == set(RAW_PROPOSAL_TOP_FIELDS)
    assert set(Assessment.__args__) == set(VALID_ASSESSMENTS)


def _valid_proposal_dict() -> dict:
    sid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    return {
        "session_id": sid,
        "context_fingerprint": "a" * 64,
        "provider": "fake",
        "model": "fake-model",
        "candidate_assessments": [
            {
                "candidate_id": cid,
                "assessment": "SUPPORTS",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "unresolved_information_ids": [],
                "explanation": "because",
                "uncertainty_flags": ["b-flag", "a-flag"],
            }
        ],
        "available": True,
        "proposal_consistent": True,
        "llm_reasoning_source": "LLM_REASONING_TASK_057",
    }


def test_valid_behavior_unchanged_after_centralization() -> None:
    proposal = _valid_proposal_dict()
    normalized = normalize_proposal(proposal)
    # Only uncertainty_flags is reordered (sorted); everything else as-is.
    assert normalized["candidate_assessments"][0]["uncertainty_flags"] == [
        "a-flag",
        "b-flag",
    ]
    assert validate_normalized(normalized) == []

    response = LLMReasoningProviderResponse(
        provider="fake", model="fake-model", text="{}"
    )
    assert ProviderFailureBoundary.validate_provider_metadata(response, "") == []
    assert serial_mod.validate_payload({field: None for field in PAYLOAD_FIELDS}) == []

    fp_one = serial_mod.compute_fingerprint({"b": 1, "a": 1})
    fp_two = serial_mod.compute_fingerprint({"a": 1, "b": 1})
    assert fp_one == fp_two
    assert len(fp_one) == 64
