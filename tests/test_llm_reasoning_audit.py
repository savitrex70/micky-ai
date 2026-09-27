"""Tests for Task 103 LLM reasoning audit.

All tests use an injected fake provider. The unit suite never needs a
running Ollama server. Tests follow existing patterns from test_llm_reasoning.py:
sqlite-memory TestClient, seed via POST /sessions + observations + generate-candidates
+ evaluate-evidence, use real services.
"""

from __future__ import annotations

import ast
import copy
import inspect
import json
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services.llm_reasoning import (
    LLMReasoningService,
)
from rop.services.llm_reasoning_audit import (
    LLM_REASONING_AUDIT_TASK_103,
    LLMReasoningAuditContractError,
    LLMReasoningAuditService,
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


def override_get_db() -> Generator[Session, None, None]:
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


# ---------------------------------------------------------------------------
# Fake provider (same as test_llm_reasoning.py)
# ---------------------------------------------------------------------------


class FakeProvider:
    """Injectable provider used in every unit test."""

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
# Session / context helpers (same as test_llm_reasoning.py)
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-103-test"},
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


def _valid_context(user_input: str = "Task 103 valid") -> dict[str, Any]:
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


def _get_valid_proposal() -> dict[str, Any]:
    """Produce a valid Task 057 proposal using real services + fake provider."""
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    result = _service_with(provider).build(context=ctx)
    return result


# ---------------------------------------------------------------------------
# Valid audit
# ---------------------------------------------------------------------------


def test_valid_audit() -> None:
    """A valid proposal passes all audit checks."""
    proposal = _get_valid_proposal()
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["available"] is True
    assert audit["proposal_consistent"] is True
    assert audit["session_consistent"] is True
    assert audit["fingerprint_consistent"] is True
    assert audit["candidate_assessments_consistent"] is True
    assert audit["evidence_references_consistent"] is True
    assert audit["unresolved_info_consistent"] is True
    assert audit["candidate_order_consistent"] is True
    assert audit["provenance_consistent"] is True
    assert audit["metadata_consistent"] is True
    assert audit["consistency_issues"] == []
    assert audit["audit_source"] == LLM_REASONING_AUDIT_TASK_103


def test_valid_audit_schema_validates() -> None:
    """The audit result validates against LLMReasoningAuditRead."""
    from rop.schemas.llm_reasoning_audit import LLMReasoningAuditRead

    proposal = _get_valid_proposal()
    audit = LLMReasoningAuditService.build(proposal=proposal)
    validated = LLMReasoningAuditRead.model_validate(audit)
    assert validated.audit_source == LLM_REASONING_AUDIT_TASK_103


# ---------------------------------------------------------------------------
# Missing fields
# ---------------------------------------------------------------------------


def test_missing_session_id() -> None:
    proposal = _get_valid_proposal()
    del proposal["session_id"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "missing_field:session_id" in audit["consistency_issues"]
    assert audit["proposal_consistent"] is False


def test_missing_context_fingerprint() -> None:
    proposal = _get_valid_proposal()
    del proposal["context_fingerprint"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "missing_field:context_fingerprint" in audit["consistency_issues"]


def test_missing_provider() -> None:
    proposal = _get_valid_proposal()
    del proposal["provider"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "missing_field:provider" in audit["consistency_issues"]


def test_missing_model() -> None:
    proposal = _get_valid_proposal()
    del proposal["model"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "missing_field:model" in audit["consistency_issues"]


def test_missing_candidate_assessments() -> None:
    proposal = _get_valid_proposal()
    del proposal["candidate_assessments"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "missing_field:candidate_assessments" in audit["consistency_issues"]


def test_missing_available() -> None:
    proposal = _get_valid_proposal()
    del proposal["available"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "missing_field:available" in audit["consistency_issues"]


def test_missing_proposal_consistent() -> None:
    proposal = _get_valid_proposal()
    del proposal["proposal_consistent"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "missing_field:proposal_consistent" in audit["consistency_issues"]


def test_missing_llm_reasoning_source() -> None:
    proposal = _get_valid_proposal()
    del proposal["llm_reasoning_source"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "missing_field:llm_reasoning_source" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Wrong types
# ---------------------------------------------------------------------------


def test_wrong_type_session_id() -> None:
    proposal = _get_valid_proposal()
    proposal["session_id"] = 12345
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "wrong_type:session_id" in audit["consistency_issues"]


def test_wrong_type_context_fingerprint() -> None:
    proposal = _get_valid_proposal()
    proposal["context_fingerprint"] = 12345
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "wrong_type:context_fingerprint" in audit["consistency_issues"]


def test_wrong_type_provider() -> None:
    proposal = _get_valid_proposal()
    proposal["provider"] = 12345
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "wrong_type:provider" in audit["consistency_issues"]


def test_wrong_type_model() -> None:
    proposal = _get_valid_proposal()
    proposal["model"] = 12345
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "wrong_type:model" in audit["consistency_issues"]


def test_wrong_type_candidate_assessments() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"] = "not-a-list"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "wrong_type:candidate_assessments" in audit["consistency_issues"]


def test_wrong_type_available() -> None:
    proposal = _get_valid_proposal()
    proposal["available"] = "true"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "wrong_type:available" in audit["consistency_issues"]


def test_wrong_type_proposal_consistent() -> None:
    proposal = _get_valid_proposal()
    proposal["proposal_consistent"] = "true"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "wrong_type:proposal_consistent" in audit["consistency_issues"]


def test_wrong_type_llm_reasoning_source() -> None:
    proposal = _get_valid_proposal()
    proposal["llm_reasoning_source"] = 12345
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["metadata_consistent"] is False
    assert "wrong_type:llm_reasoning_source" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Session mismatch / invalid UUID
# ---------------------------------------------------------------------------


def test_invalid_session_id_format() -> None:
    proposal = _get_valid_proposal()
    proposal["session_id"] = "not-a-uuid"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["session_consistent"] is False
    assert "invalid_session_id_format" in audit["consistency_issues"]


def test_invalid_session_id_none() -> None:
    proposal = _get_valid_proposal()
    proposal["session_id"] = None
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["session_consistent"] is False
    assert "wrong_type:session_id" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Fingerprint tampering
# ---------------------------------------------------------------------------


def test_fingerprint_wrong_length() -> None:
    proposal = _get_valid_proposal()
    proposal["context_fingerprint"] = "a" * 63
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["fingerprint_consistent"] is False
    assert "invalid_fingerprint_format" in audit["consistency_issues"]


def test_fingerprint_uppercase() -> None:
    proposal = _get_valid_proposal()
    proposal["context_fingerprint"] = "A" * 64
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["fingerprint_consistent"] is False
    assert "invalid_fingerprint_format" in audit["consistency_issues"]


def test_fingerprint_non_hex() -> None:
    proposal = _get_valid_proposal()
    proposal["context_fingerprint"] = "g" * 64
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["fingerprint_consistent"] is False
    assert "invalid_fingerprint_format" in audit["consistency_issues"]


def test_fingerprint_empty() -> None:
    proposal = _get_valid_proposal()
    proposal["context_fingerprint"] = ""
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["fingerprint_consistent"] is False
    assert "invalid_fingerprint_format" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Candidate tampering: wrong IDs
# ---------------------------------------------------------------------------


def test_candidate_id_wrong_format() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["candidate_id"] = "not-a-uuid"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert "invalid_candidate_id_format" in audit["consistency_issues"]


def test_candidate_id_missing() -> None:
    proposal = _get_valid_proposal()
    del proposal["candidate_assessments"][0]["candidate_id"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert "missing_candidate_id" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Candidate tampering: duplicates
# ---------------------------------------------------------------------------


def test_duplicate_candidate_assessment() -> None:
    proposal = _get_valid_proposal()
    if len(proposal["candidate_assessments"]) < 2:
        pytest.skip("need at least 2 candidates")
    # Duplicate the first assessment
    dup = copy.deepcopy(proposal["candidate_assessments"][0])
    proposal["candidate_assessments"].append(dup)
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert any(
        "duplicate_candidate_id" in issue for issue in audit["consistency_issues"]
    )


# ---------------------------------------------------------------------------
# Candidate tampering: reorder
# ---------------------------------------------------------------------------


def test_reordered_candidate_assessments() -> None:
    """Reordering candidates is structurally valid but we flag it.

    Since audit only sees the proposal (not original context), we can't
    verify against context order. The order is internally consistent
    (no duplicates), so candidate_order_consistent remains True.
    This test verifies the audit doesn't crash and reports correctly.
    """
    proposal = _get_valid_proposal()
    if len(proposal["candidate_assessments"]) < 2:
        pytest.skip("need at least 2 candidates")
    proposal["candidate_assessments"] = list(
        reversed(proposal["candidate_assessments"])
    )
    audit = LLMReasoningAuditService.build(proposal=proposal)

    # Order is internally consistent (no dupes), so this passes
    # The audit can't verify against context without the context
    assert audit["candidate_order_consistent"] is True
    assert audit["candidate_assessments_consistent"] is True


# ---------------------------------------------------------------------------
# Evidence tampering
# ---------------------------------------------------------------------------


def test_supporting_evidence_wrong_format() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["supporting_evidence_ids"] = ["not-a-uuid"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["evidence_references_consistent"] is False
    assert "invalid_supporting_evidence_id_format" in audit["consistency_issues"]


def test_contradicting_evidence_wrong_format() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["contradicting_evidence_ids"] = ["not-a-uuid"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["evidence_references_consistent"] is False
    assert "invalid_contradicting_evidence_id_format" in audit["consistency_issues"]


def test_supporting_evidence_not_list() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["supporting_evidence_ids"] = "not-a-list"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["evidence_references_consistent"] is False
    assert "supporting_evidence_not_list" in audit["consistency_issues"]


def test_contradicting_evidence_not_list() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["contradicting_evidence_ids"] = "not-a-list"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["evidence_references_consistent"] is False
    assert "contradicting_evidence_not_list" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Unresolved information tampering
# ---------------------------------------------------------------------------


def test_unresolved_information_wrong_format() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["unresolved_information_ids"] = ["not-a-uuid"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["unresolved_info_consistent"] is False
    assert "invalid_missing_info_id_format" in audit["consistency_issues"]


def test_unresolved_information_not_list() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["unresolved_information_ids"] = "not-a-list"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["unresolved_info_consistent"] is False
    assert "unresolved_info_not_list" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Assessment value tampering
# ---------------------------------------------------------------------------


def test_invalid_assessment_value() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["assessment"] = "DEFINITELY"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert "invalid_assessment_value" in audit["consistency_issues"]


def test_assessment_value_case_sensitive() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["assessment"] = "supports"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert "invalid_assessment_value" in audit["consistency_issues"]


def test_assessment_missing() -> None:
    proposal = _get_valid_proposal()
    del proposal["candidate_assessments"][0]["assessment"]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert "invalid_assessment_value" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Explanation and uncertainty flags
# ---------------------------------------------------------------------------


def test_empty_explanation() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["explanation"] = ""
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert "empty_explanation" in audit["consistency_issues"]


def test_whitespace_only_explanation() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["explanation"] = "   "
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert "empty_explanation" in audit["consistency_issues"]


def test_explanation_not_string() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["explanation"] = 123
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert "empty_explanation" in audit["consistency_issues"]


def test_uncertainty_flags_not_list() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["uncertainty_flags"] = "not-a-list"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert "uncertainty_flags_not_list" in audit["consistency_issues"]


def test_uncertainty_flag_not_string() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0]["uncertainty_flags"] = [123]
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert "uncertainty_flag_not_string" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Provider/model empty
# ---------------------------------------------------------------------------


def test_empty_provider() -> None:
    proposal = _get_valid_proposal()
    proposal["provider"] = ""
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["provenance_consistent"] is False
    assert "empty_provider" in audit["consistency_issues"]


def test_whitespace_provider() -> None:
    proposal = _get_valid_proposal()
    proposal["provider"] = "   "
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["provenance_consistent"] is False
    assert "empty_provider" in audit["consistency_issues"]


def test_empty_model() -> None:
    proposal = _get_valid_proposal()
    proposal["model"] = ""
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["provenance_consistent"] is False
    assert "empty_model" in audit["consistency_issues"]


def test_whitespace_model() -> None:
    proposal = _get_valid_proposal()
    proposal["model"] = "   "
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["provenance_consistent"] is False
    assert "empty_model" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Source constant mismatch
# ---------------------------------------------------------------------------


def test_source_constant_mismatch() -> None:
    proposal = _get_valid_proposal()
    proposal["llm_reasoning_source"] = "WRONG_SOURCE"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["provenance_consistent"] is False
    assert (
        "source_constant_mismatch:expected=LLM_REASONING_TASK_057,got=WRONG_SOURCE"
        in audit["consistency_issues"]
    )


def test_source_constant_case_sensitive() -> None:
    proposal = _get_valid_proposal()
    proposal["llm_reasoning_source"] = "llm_reasoning_task_057"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["provenance_consistent"] is False
    assert "source_constant_mismatch" in audit["consistency_issues"][0]


# ---------------------------------------------------------------------------
# Issue ordering deterministic + dedup
# ---------------------------------------------------------------------------


def test_issue_ordering_deterministic() -> None:
    """Same issues always produce same ordered output."""
    proposal = _get_valid_proposal()
    proposal["provider"] = ""
    proposal["model"] = ""
    proposal["llm_reasoning_source"] = "WRONG"

    audit1 = LLMReasoningAuditService.build(proposal=proposal)
    audit2 = LLMReasoningAuditService.build(proposal=proposal)

    assert audit1["consistency_issues"] == audit2["consistency_issues"]
    # Should be sorted
    assert audit1["consistency_issues"] == sorted(audit1["consistency_issues"])


def test_issue_deduplication() -> None:
    """Duplicate issues are deduplicated."""
    proposal = _get_valid_proposal()
    # Create multiple identical issues by having multiple assessments with same problem
    proposal["candidate_assessments"][0]["explanation"] = ""
    if len(proposal["candidate_assessments"]) > 1:
        proposal["candidate_assessments"][1]["explanation"] = ""

    audit = LLMReasoningAuditService.build(proposal=proposal)

    # Count occurrences of empty_explanation
    empty_exp_count = sum(
        1 for issue in audit["consistency_issues"] if "empty_explanation" in issue
    )
    assert empty_exp_count == 1  # deduplicated


# ---------------------------------------------------------------------------
# Deterministic output
# ---------------------------------------------------------------------------


def test_deterministic_output() -> None:
    """Same input always produces identical audit output."""
    proposal = _get_valid_proposal()

    audit1 = LLMReasoningAuditService.build(proposal=proposal)
    audit2 = LLMReasoningAuditService.build(proposal=proposal)

    assert audit1 == audit2


# ---------------------------------------------------------------------------
# Input immutability
# ---------------------------------------------------------------------------


def test_input_immutability() -> None:
    """Audit does not mutate the input proposal."""
    proposal = _get_valid_proposal()
    # Deep copy for comparison
    import copy

    original = copy.deepcopy(proposal)

    LLMReasoningAuditService.build(proposal=proposal)

    assert proposal == original


# ---------------------------------------------------------------------------
# Coherent false state preservation
# ---------------------------------------------------------------------------


def test_unavailable_proposal_audit() -> None:
    """Unavailable proposal (available=False) produces clean audit with
    legitimate False states, not errors."""
    ctx = _valid_context()
    # Create an unavailable proposal by using a context with available=False
    unavailable_ctx = dict(ctx)
    unavailable_ctx["available"] = False
    unavailable_ctx["context_consistent"] = False

    provider = FakeProvider(response_text="")
    service = _service_with(provider)
    proposal = service.build(context=unavailable_ctx)

    assert proposal["available"] is False
    assert proposal["proposal_consistent"] is False

    audit = LLMReasoningAuditService.build(proposal=proposal)

    # The audit should report the proposal's own flags accurately
    assert audit["available"] is False
    # proposal_consistent reflects the proposal's flag AND all checks
    # Since there are no assessments, most checks pass
    assert audit["metadata_consistent"] is True
    assert audit["session_consistent"] is True
    assert audit["fingerprint_consistent"] is True
    assert audit["candidate_assessments_consistent"] is True
    assert audit["evidence_references_consistent"] is True
    assert audit["unresolved_info_consistent"] is True
    assert audit["candidate_order_consistent"] is True
    assert audit["provenance_consistent"] is True
    assert audit["consistency_issues"] == []


def test_available_false_but_has_assessments() -> None:
    """If available=False but assessments exist, flag it."""
    proposal = _get_valid_proposal()
    proposal["available"] = False
    proposal["proposal_consistent"] = False
    # Leave assessments in place
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["available"] is False
    assert audit["candidate_assessments_consistent"] is False
    assert "unavailable_proposal_has_assessments" in audit["consistency_issues"]


# ---------------------------------------------------------------------------
# Purity check - no forbidden imports in service source
# ---------------------------------------------------------------------------


def test_service_purity_no_forbidden_imports() -> None:
    """The audit service must not import or use forbidden modules."""
    src = inspect.getsource(LLMReasoningAuditService)
    # Also check the module source
    import rop.services.llm_reasoning_audit as mod

    src = inspect.getsource(mod)

    forbidden = (
        "httpx",
        "requests.",
        "get_db",
        "Session(",
        "TestClient",
        "openai",
        "gemini",
        "anthropic",
        "ollama",
        "api_key",
        "urlopen",
        "socket",
    )
    for f in forbidden:
        assert f not in src, f"Forbidden import/usage found: {f}"


def test_service_syntax_valid() -> None:
    """The service module must be syntactically valid Python."""
    import rop.services.llm_reasoning_audit as mod

    src = inspect.getsource(mod)
    ast.parse(src)  # Should not raise


def test_schema_syntax_valid() -> None:
    """The schema module must be syntactically valid Python."""
    import rop.schemas.llm_reasoning_audit as mod

    src = inspect.getsource(mod)
    ast.parse(src)  # Should not raise


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_audit_with_none_proposal_raises() -> None:
    with pytest.raises(LLMReasoningAuditContractError) as ei:
        LLMReasoningAuditService.build(proposal=None)
    assert ei.value.invariant == "INPUT_UNAVAILABLE"


def test_audit_with_non_mapping_raises() -> None:
    with pytest.raises(LLMReasoningAuditContractError) as ei:
        LLMReasoningAuditService.build(proposal="not-a-mapping")
    assert ei.value.invariant == "INPUT_UNAVAILABLE"


def test_audit_with_list_raises() -> None:
    with pytest.raises(LLMReasoningAuditContractError) as ei:
        LLMReasoningAuditService.build(proposal=[1, 2, 3])
    assert ei.value.invariant == "INPUT_UNAVAILABLE"


def test_candidate_assessment_not_mapping() -> None:
    proposal = _get_valid_proposal()
    proposal["candidate_assessments"][0] = "not-a-mapping"
    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    assert "candidate_assessment_not_mapping" in audit["consistency_issues"]


def test_multiple_candidates_all_validated() -> None:
    """All candidates in the list are validated, not just the first."""
    proposal = _get_valid_proposal()
    # Corrupt multiple candidates
    for assessment in proposal["candidate_assessments"]:
        assessment["explanation"] = ""

    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is False
    # Should only have one empty_explanation issue due to dedup
    empty_exp_count = sum(
        1 for issue in audit["consistency_issues"] if "empty_explanation" in issue
    )
    assert empty_exp_count == 1


def test_assessment_with_valid_evidence_ids_format() -> None:
    """Evidence IDs that are valid UUID format pass format check."""
    proposal = _get_valid_proposal()
    valid_uuid = str(uuid4())
    proposal["candidate_assessments"][0]["supporting_evidence_ids"] = [valid_uuid]
    proposal["candidate_assessments"][0]["contradicting_evidence_ids"] = [valid_uuid]
    proposal["candidate_assessments"][0]["unresolved_information_ids"] = [valid_uuid]

    audit = LLMReasoningAuditService.build(proposal=proposal)

    # Format is valid (we don't check against context)
    assert audit["evidence_references_consistent"] is True
    assert audit["unresolved_info_consistent"] is True


def test_all_assessment_values_valid() -> None:
    """All three valid assessment values pass."""
    proposal = _get_valid_proposal()
    for i, assessment in enumerate(proposal["candidate_assessments"]):
        assessment["assessment"] = ["SUPPORTS", "WEAKENS", "UNCLEAR"][i % 3]

    audit = LLMReasoningAuditService.build(proposal=proposal)

    assert audit["candidate_assessments_consistent"] is True
    assert "invalid_assessment_value" not in " ".join(audit["consistency_issues"])
