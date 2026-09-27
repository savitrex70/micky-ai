"""Tests for Task 105 LLM output validation.

All tests use the real Task 057 service with a fake provider to produce
a valid context and a baseline proposal, then exercise the pure
validation functions directly with various mutations.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services.llm_output_validation import (
    LLM_OUTPUT_VALIDATION_SOURCE_TASK_105,
    validate_raw_proposal,
)
from rop.services.llm_reasoning import (
    LLMReasoningService,
)
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderResponse,
)
from rop.services.reasoning_context import ReasoningContextService

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def override_get_db():
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


# ---------------------------------------------------------------------------
# Fake provider (same pattern as test_llm_reasoning.py)
# ---------------------------------------------------------------------------


class FakeProvider:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(
        self,
        response_text: str | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self.response_text = response_text
        self.raise_error = raise_error
        self.calls = 0
        self.last_request: Any = None

    def generate_reasoning(self, request: Any) -> LLMReasoningProviderResponse:
        self.calls += 1
        self.last_request = request
        if self.raise_error is not None:
            raise self.raise_error
        return LLMReasoningProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            text=self.response_text or "",
        )


# ---------------------------------------------------------------------------
# Session / context helpers
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-105-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full_session(user_input: str) -> str:
    sid = _create_session(user_input)
    r = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert r.status_code == 201
    g = client.post(f"/sessions/{sid}/generate-candidates")
    assert g.status_code == 201
    e = client.post(f"/sessions/{sid}/evaluate-evidence")
    assert e.status_code == 200
    return sid


def _valid_context(user_input: str = "Task 105 valid") -> dict[str, Any]:
    sid = _seed_full_session(user_input)
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        return ReasoningContextService().build_for_session(db, session_uuid)
    finally:
        db_gen.close()


def _valid_model_output(context: dict[str, Any]) -> str:
    """Build a schema-valid model output referencing every candidate."""
    assessments = []
    for candidate in context["candidate_state"]:
        assessments.append(
            {
                "candidate_id": str(candidate.id),
                "assessment": "UNCLEAR",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "unresolved_information_ids": [],
                "explanation": "insufficient evidence to decide",
                "uncertainty_flags": ["insufficient_evidence"],
            }
        )
    return json.dumps({"candidate_assessments": assessments})


def _service_with(provider: FakeProvider) -> LLMReasoningService:
    return LLMReasoningService(provider=provider)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_context() -> dict[str, Any]:
    return _valid_context()


@pytest.fixture
def valid_proposal(valid_context: dict[str, Any]) -> dict[str, Any]:
    """A known-good raw proposal dict produced by the real Task 057 path."""
    # _valid_model_output is already the raw JSON the model would produce.
    return json.loads(_valid_model_output(valid_context))


# ---------------------------------------------------------------------------
# Test: Valid output passes
# ---------------------------------------------------------------------------


def test_valid_output_passes(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    issues = validate_raw_proposal(valid_proposal, valid_context)
    assert issues == []


# ---------------------------------------------------------------------------
# Test: Extra top-level field rejected
# ---------------------------------------------------------------------------


def test_extra_top_level_field_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["winner"] = "candidate-x"
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


# ---------------------------------------------------------------------------
# Test: Missing assessment fields
# ---------------------------------------------------------------------------


def test_missing_assessment_field_candidate_id(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    del raw["candidate_assessments"][0]["candidate_id"]
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


def test_missing_assessment_field_assessment(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    del raw["candidate_assessments"][0]["assessment"]
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


def test_missing_assessment_field_explanation(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    del raw["candidate_assessments"][0]["explanation"]
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


def test_missing_optional_field_defaults_to_empty(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    """Optional fields default to empty list when missing (Pydantic default_factory)."""
    raw = copy.deepcopy(valid_proposal)
    del raw["candidate_assessments"][0]["supporting_evidence_ids"]
    del raw["candidate_assessments"][0]["contradicting_evidence_ids"]
    del raw["candidate_assessments"][0]["unresolved_information_ids"]
    del raw["candidate_assessments"][0]["uncertainty_flags"]
    issues = validate_raw_proposal(raw, valid_context)
    # Should pass because defaults are applied
    assert issues == []


# ---------------------------------------------------------------------------
# Test: Invalid candidate IDs
# ---------------------------------------------------------------------------


def test_candidate_id_not_in_context(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["candidate_id"] = str(uuid4())
    issues = validate_raw_proposal(raw, valid_context)
    assert any("not found in context candidate_state" in i for i in issues)


def test_candidate_id_non_uuid_string(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["candidate_id"] = "not-a-uuid"
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


def test_candidate_id_wrong_type(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["candidate_id"] = 123
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


# ---------------------------------------------------------------------------
# Test: Invalid assessment values
# ---------------------------------------------------------------------------


def test_invalid_assessment_value(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["assessment"] = "DEFINITELY"
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


def test_assessment_case_sensitive(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["assessment"] = "supports"  # lowercase
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


# ---------------------------------------------------------------------------
# Test: Invalid evidence IDs
# ---------------------------------------------------------------------------


def test_unknown_supporting_evidence_id(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["supporting_evidence_ids"] = [str(uuid4())]
    issues = validate_raw_proposal(raw, valid_context)
    assert any(
        "supporting_evidence_id" in i and "not found in context" in i for i in issues
    )


def test_unknown_contradicting_evidence_id(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["contradicting_evidence_ids"] = [str(uuid4())]
    issues = validate_raw_proposal(raw, valid_context)
    assert any(
        "contradicting_evidence_id" in i and "not found in context" in i for i in issues
    )


def test_evidence_id_non_uuid_string(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["supporting_evidence_ids"] = ["not-a-uuid"]
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


def test_valid_evidence_ids_accepted(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    """Valid evidence IDs from context should pass."""
    raw = copy.deepcopy(valid_proposal)
    if valid_context["observations"]:
        raw["candidate_assessments"][0]["supporting_evidence_ids"] = [
            str(valid_context["observations"][0].id)
        ]
    if valid_context["entities"]:
        raw["candidate_assessments"][0]["contradicting_evidence_ids"] = [
            str(valid_context["entities"][0].id)
        ]
    issues = validate_raw_proposal(raw, valid_context)
    assert issues == []


# ---------------------------------------------------------------------------
# Test: Invalid missing_information IDs
# ---------------------------------------------------------------------------


def test_unknown_missing_information_id(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["unresolved_information_ids"] = [str(uuid4())]
    issues = validate_raw_proposal(raw, valid_context)
    assert any(
        "unresolved_information_id" in i and "not found in context" in i for i in issues
    )


def test_missing_info_id_non_uuid_string(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["unresolved_information_ids"] = ["not-a-uuid"]
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


def test_valid_missing_information_ids_accepted(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    if valid_context["missing_information"]:
        raw["candidate_assessments"][0]["unresolved_information_ids"] = [
            str(valid_context["missing_information"][0].id)
        ]
    issues = validate_raw_proposal(raw, valid_context)
    assert issues == []


# ---------------------------------------------------------------------------
# Test: Empty explanation
# ---------------------------------------------------------------------------


def test_empty_explanation_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["explanation"] = ""
    issues = validate_raw_proposal(raw, valid_context)
    assert any("explanation must be a non-empty string" in i for i in issues)


def test_whitespace_only_explanation_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["explanation"] = "   "
    issues = validate_raw_proposal(raw, valid_context)
    assert any("explanation must be a non-empty string" in i for i in issues)


def test_explanation_non_string_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["explanation"] = 123
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


# ---------------------------------------------------------------------------
# Test: Invalid uncertainty_flags type
# ---------------------------------------------------------------------------


def test_uncertainty_flags_not_list_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["uncertainty_flags"] = "not-a-list"
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


def test_uncertainty_flags_non_string_elements_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["uncertainty_flags"] = ["valid", 123, "also-valid"]
    issues = validate_raw_proposal(raw, valid_context)
    # Non-string elements fail the parse-only schema (list[str]) before
    # element-level checks run; the service's element check remains as
    # defense-in-depth for already-parsed inputs.
    assert any("Top-level schema validation failed" in i for i in issues)


def test_uncertainty_flags_valid_list_passes(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["uncertainty_flags"] = ["flag1", "flag2", "flag3"]
    issues = validate_raw_proposal(raw, valid_context)
    assert issues == []


# ---------------------------------------------------------------------------
# Test: Duplicate candidate_ids
# ---------------------------------------------------------------------------


def test_duplicate_candidate_ids_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    # Duplicate the first assessment
    raw["candidate_assessments"].append(copy.deepcopy(raw["candidate_assessments"][0]))
    issues = validate_raw_proposal(raw, valid_context)
    assert any("duplicate candidate_id" in i for i in issues)


# ---------------------------------------------------------------------------
# Test: Wrong candidate order
# ---------------------------------------------------------------------------


def test_reordered_candidate_assessments_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    if len(valid_context["candidate_state"]) < 2:
        pytest.skip("seed session produced only one candidate")
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"] = list(reversed(raw["candidate_assessments"]))
    issues = validate_raw_proposal(raw, valid_context)
    assert any(
        "order does not match context candidate_state order" in i for i in issues
    )


def test_missing_candidate_assessment_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    if len(valid_context["candidate_state"]) < 2:
        pytest.skip("seed session produced only one candidate")
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"] = raw["candidate_assessments"][:1]
    issues = validate_raw_proposal(raw, valid_context)
    assert any("candidate_assessments count" in i for i in issues)


def test_extra_candidate_assessment_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    # Add an assessment for a non-existent candidate
    extra = copy.deepcopy(raw["candidate_assessments"][0])
    extra["candidate_id"] = str(uuid4())
    raw["candidate_assessments"].append(extra)
    issues = validate_raw_proposal(raw, valid_context)
    assert any("not found in context candidate_state" in i for i in issues)


# ---------------------------------------------------------------------------
# Test: Extra assessment fields (ConfigDict(extra="forbid"))
# ---------------------------------------------------------------------------


def test_extra_assessment_field_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["extra_field"] = "not allowed"
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


def test_extra_nested_field_in_evidence_ids_rejected(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    """Pydantic forbids extra fields at the assessment level, not inside lists."""
    raw = copy.deepcopy(valid_proposal)
    # This is at the assessment level
    raw["candidate_assessments"][0]["confidence"] = 0.95
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


# ---------------------------------------------------------------------------
# Test: Malformed UUID strings
# ---------------------------------------------------------------------------


def test_malformed_uuid_in_candidate_id(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0][
        "candidate_id"
    ] = "12345678-1234-1234-1234"  # too short
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


def test_malformed_uuid_in_evidence_id(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["supporting_evidence_ids"] = [
        "12345678-1234-1234-1234"
    ]
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


def test_malformed_uuid_in_missing_info_id(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["unresolved_information_ids"] = [
        "12345678-1234-1234-1234"
    ]
    issues = validate_raw_proposal(raw, valid_context)
    assert any("Top-level schema validation failed" in i for i in issues)


# ---------------------------------------------------------------------------
# Test: Source constant is exported
# ---------------------------------------------------------------------------


def test_source_constant_exists() -> None:
    assert LLM_OUTPUT_VALIDATION_SOURCE_TASK_105 == "LLM_OUTPUT_VALIDATION_TASK_105"


# ---------------------------------------------------------------------------
# Test: validate_raw_proposal is pure (no mutation)
# ---------------------------------------------------------------------------


def _freeze(value: Any) -> Any:
    """Canonical snapshot for immutability comparison.

    Plain deepcopy equality fails for contexts holding SQLAlchemy ORM
    objects (identity-based __eq__), so snapshots convert ORM instances
    to sorted attribute dicts (minus _sa_instance_state) with UUIDs as
    strings. Any in-place mutation changes the snapshot.
    """
    if isinstance(value, Mapping):
        return {str(k): _freeze(v) for k, v in sorted(value.items(), key=str)}
    if isinstance(value, (list, tuple)):
        return [_freeze(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        return {
            str(k): _freeze(v)
            for k, v in sorted(attrs.items(), key=lambda kv: str(kv[0]))
            if k != "_sa_instance_state"
        }
    return repr(value)


def test_validate_raw_proposal_does_not_mutate_inputs(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any]
) -> None:
    raw_copy = copy.deepcopy(valid_proposal)
    frozen_context = _freeze(valid_context)

    validate_raw_proposal(valid_proposal, valid_context)

    assert valid_proposal == raw_copy
    assert _freeze(valid_context) == frozen_context


# ---------------------------------------------------------------------------
# Test: Integration with real Task 057 service path
# ---------------------------------------------------------------------------


def test_real_task057_output_passes_validation(valid_context: dict[str, Any]) -> None:
    """End-to-end: real Task 057 service produces output that passes validation."""
    provider = FakeProvider(response_text=_valid_model_output(valid_context))
    service = _service_with(provider)
    result = service.build(context=valid_context)

    # Reconstruct raw proposal from result
    raw = {"candidate_assessments": result["candidate_assessments"]}
    issues = validate_raw_proposal(raw, valid_context)
    assert issues == []


# ---------------------------------------------------------------------------
# Test: Empty context edge cases
# ---------------------------------------------------------------------------


def test_empty_candidate_state_accepts_empty_assessments() -> None:
    context = {
        "candidate_state": [],
        "observations": [],
        "entities": [],
        "missing_information": [],
        "template_context": [],
        "reasoning_pipeline": {},
    }
    raw = {"candidate_assessments": []}
    issues = validate_raw_proposal(raw, context)
    assert issues == []


def test_empty_context_with_assessments_rejected() -> None:
    context = {
        "candidate_state": [],
        "observations": [],
        "entities": [],
        "missing_information": [],
        "template_context": [],
        "reasoning_pipeline": {},
    }
    raw = {
        "candidate_assessments": [
            {
                "candidate_id": str(uuid4()),
                "assessment": "UNCLEAR",
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "unresolved_information_ids": [],
                "explanation": "test",
                "uncertainty_flags": [],
            }
        ]
    }
    issues = validate_raw_proposal(raw, context)
    assert any("not found in context candidate_state" in i for i in issues)


# ---------------------------------------------------------------------------
# Test: All assessment types accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("assessment", ["SUPPORTS", "WEAKENS", "UNCLEAR"])
def test_all_valid_assessment_values_accepted(
    valid_context: dict[str, Any], valid_proposal: dict[str, Any], assessment: str
) -> None:
    raw = copy.deepcopy(valid_proposal)
    raw["candidate_assessments"][0]["assessment"] = assessment
    issues = validate_raw_proposal(raw, valid_context)
    assert issues == []
