"""Task 116: strict Task 057 schema boundary tests.

The public proposal and candidate-assessment schemas must reject
unexpected fields, missing fields, malformed IDs, invalid assessment
values, and empty explanations, while still accepting valid
internally-generated Task 057 results. No real provider, no network.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from rop.schemas.llm_reasoning import (
    LLMReasoningProposalRead,
    ReasoningCandidateAssessmentRead,
    _RawCandidateAssessment,
)

FORBIDDEN_TOP_FIELDS = (
    "winner",
    "score",
    "scores",
    "ranking",
    "rank",
    "recommendation",
    "treatment",
    "diagnosis",
    "tool_call",
    "tool_calls",
    "execute",
    "execution",
    "prompt",
    "text",
    "raw_text",
)

FORBIDDEN_NESTED_FIELDS = (
    "winner",
    "score",
    "ranking",
    "recommendation",
    "treatment",
    "diagnosis",
    "tool_call",
    "execution",
)


def _valid_assessment_dict() -> dict:
    return {
        "candidate_id": str(uuid.uuid4()),
        "assessment": "SUPPORTS",
        "supporting_evidence_ids": [],
        "contradicting_evidence_ids": [],
        "unresolved_information_ids": [],
        "explanation": "evidence supports this candidate",
        "uncertainty_flags": [],
    }


def _valid_proposal_dict() -> dict:
    return {
        "session_id": str(uuid.uuid4()),
        "context_fingerprint": "a" * 64,
        "provider": "fake",
        "model": "fake-model",
        "candidate_assessments": [_valid_assessment_dict()],
        "available": True,
        "proposal_consistent": True,
        "llm_reasoning_source": "LLM_REASONING_TASK_057",
    }


def test_valid_public_shapes_accepted() -> None:
    assessment = ReasoningCandidateAssessmentRead.model_validate(
        _valid_assessment_dict()
    )
    assert assessment.assessment == "SUPPORTS"
    proposal = LLMReasoningProposalRead.model_validate(_valid_proposal_dict())
    assert proposal.proposal_consistent is True


@pytest.mark.parametrize("field", FORBIDDEN_TOP_FIELDS)
def test_forbidden_top_level_field_rejected(field: str) -> None:
    proposal = _valid_proposal_dict()
    proposal[field] = "smuggled"
    with pytest.raises(ValidationError):
        LLMReasoningProposalRead.model_validate(proposal)


@pytest.mark.parametrize("field", FORBIDDEN_NESTED_FIELDS)
def test_forbidden_nested_field_rejected(field: str) -> None:
    assessment = _valid_assessment_dict()
    assessment[field] = "smuggled"
    with pytest.raises(ValidationError):
        ReasoningCandidateAssessmentRead.model_validate(assessment)


@pytest.mark.parametrize(
    "field",
    (
        "session_id",
        "context_fingerprint",
        "provider",
        "model",
        "candidate_assessments",
        "available",
        "proposal_consistent",
        "llm_reasoning_source",
    ),
)
def test_missing_top_level_field_rejected(field: str) -> None:
    proposal = _valid_proposal_dict()
    del proposal[field]
    with pytest.raises(ValidationError):
        LLMReasoningProposalRead.model_validate(proposal)


@pytest.mark.parametrize(
    "field",
    (
        "candidate_id",
        "assessment",
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "unresolved_information_ids",
        "explanation",
        "uncertainty_flags",
    ),
)
def test_missing_nested_field_rejected(field: str) -> None:
    assessment = _valid_assessment_dict()
    del assessment[field]
    with pytest.raises(ValidationError):
        ReasoningCandidateAssessmentRead.model_validate(assessment)


@pytest.mark.parametrize("field", ("session_id", "candidate_id"))
def test_malformed_ids_rejected(field: str) -> None:
    if field == "session_id":
        proposal = _valid_proposal_dict()
        proposal[field] = "not-a-uuid"
        with pytest.raises(ValidationError):
            LLMReasoningProposalRead.model_validate(proposal)
    else:
        assessment = _valid_assessment_dict()
        assessment[field] = "not-a-uuid"
        with pytest.raises(ValidationError):
            ReasoningCandidateAssessmentRead.model_validate(assessment)


@pytest.mark.parametrize(
    "value", ("SUPPORTED", "supports", "REFUTES", "", "WINNER", 42, None)
)
def test_invalid_assessment_values_rejected(value: object) -> None:
    assessment = _valid_assessment_dict()
    assessment["assessment"] = value
    with pytest.raises(ValidationError):
        ReasoningCandidateAssessmentRead.model_validate(assessment)


@pytest.mark.parametrize("value", ("", 123, None))
def test_empty_explanation_rejected(value: object) -> None:
    assessment = _valid_assessment_dict()
    assessment["explanation"] = value
    with pytest.raises(ValidationError):
        ReasoningCandidateAssessmentRead.model_validate(assessment)


@pytest.mark.parametrize(
    "patch",
    (
        {"candidate_assessments": {"not": "a-list"}},
        {"candidate_assessments": "not-a-list"},
        {"available": "definitely"},
        {"session_id": 12345},
    ),
)
def test_unexpected_nested_structures_rejected(patch: dict) -> None:
    proposal = _valid_proposal_dict()
    proposal.update(patch)
    with pytest.raises(ValidationError):
        LLMReasoningProposalRead.model_validate(proposal)


def test_live_service_result_still_validates() -> None:
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    result = _service_with(FakeProvider(response_text=_valid_model_output(ctx))).build(
        context=ctx
    )
    validated = LLMReasoningProposalRead.model_validate(result)
    assert validated.available is True


RAW_REQUIRED_NESTED_FIELDS = (
    "supporting_evidence_ids",
    "contradicting_evidence_ids",
    "unresolved_information_ids",
    "uncertainty_flags",
    "explanation",
)


@pytest.mark.parametrize("field", RAW_REQUIRED_NESTED_FIELDS)
def test_raw_schema_rejects_omitted_nested_field(field: str) -> None:
    """Task 116 correction: the raw model parser must not silently
    default an omitted structural field to an empty list/value."""
    assessment = _valid_assessment_dict()
    del assessment[field]
    with pytest.raises(ValidationError):
        _RawCandidateAssessment.model_validate(assessment)


@pytest.mark.parametrize("field", RAW_REQUIRED_NESTED_FIELDS)
def test_live_path_rejects_omitted_nested_field(field: str) -> None:
    """The REAL Task 057 live path rejects raw provider output missing
    each required nested field with MODEL_OUTPUT_INVALID -- the omitted
    field never silently becomes an empty list."""
    import json

    from rop.services.llm_reasoning import LLMReasoningContractError
    from tests.test_llm_live_boundary_enforcement import (
        FakeProvider,
        _service_with,
        _valid_context,
        _valid_model_output,
    )

    ctx = _valid_context()
    raw = json.loads(_valid_model_output(ctx))
    del raw["candidate_assessments"][0][field]
    provider = FakeProvider(response_text=json.dumps(raw))
    with pytest.raises(LLMReasoningContractError) as exc_info:
        _service_with(provider).build(context=ctx)
    assert exc_info.value.invariant == "MODEL_OUTPUT_INVALID"
