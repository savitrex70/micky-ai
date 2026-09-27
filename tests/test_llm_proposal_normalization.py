"""Tests for Task 106 LLM proposal normalization boundary.

All tests use seeded sessions and real Task 057 proposals.
No git, no tests run, no __init__.py edits. ast.parse syntax check only.
"""

from __future__ import annotations

import copy
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services.llm_proposal_normalization import (
    LLM_PROPOSAL_NORMALIZATION_SOURCE_TASK_106,
    LLMProposalNormalizationContractError,
    compute_normalized_fingerprint,
    normalize_proposal,
    validate_normalized,
)
from rop.services.llm_reasoning import LLMReasoningService
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
# Fake provider for Task 057
# ---------------------------------------------------------------------------


class FakeProvider:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, response_text: str | None = None) -> None:
        self.response_text = response_text
        self.calls = 0
        self.last_request: Any = None

    def generate_reasoning(self, request: Any) -> LLMReasoningProviderResponse:
        self.calls += 1
        self.last_request = request
        return LLMReasoningProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            text=self.response_text or "",
        )


# ---------------------------------------------------------------------------
# Session / context helpers (mirroring test_llm_reasoning.py)
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-106-test"},
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


def _valid_context(user_input: str = "Task 106 valid") -> dict[str, Any]:
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
                "uncertainty_flags": ["insufficient_evidence", "low_confidence"],
            }
        )
    return json.dumps({"candidate_assessments": assessments})


def _get_task057_proposal() -> dict[str, Any]:
    """Get a real Task 057 proposal from a seeded session."""
    ctx = _valid_context()
    provider = FakeProvider(response_text=_valid_model_output(ctx))
    service = LLMReasoningService(provider=provider)
    result = service.build(context=ctx)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_normalize_proposal_preserves_semantics() -> None:
    """Test exact semantic preservation of all fields."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    # session_id normalized to string
    assert isinstance(normalized["session_id"], str)
    assert normalized["session_id"] == str(proposal["session_id"])

    # context_fingerprint as-is
    assert normalized["context_fingerprint"] == proposal["context_fingerprint"]

    # provider, model as-is
    assert normalized["provider"] == proposal["provider"]
    assert normalized["model"] == proposal["model"]

    # available, proposal_consistent as-is
    assert normalized["available"] == proposal["available"]
    assert normalized["proposal_consistent"] == proposal["proposal_consistent"]

    # llm_reasoning_source as-is
    assert normalized["llm_reasoning_source"] == proposal["llm_reasoning_source"]

    # candidate_assessments: list normalized preserving EXACT order
    assert len(normalized["candidate_assessments"]) == len(
        proposal["candidate_assessments"]
    )

    for norm_assess, orig_assess in zip(
        normalized["candidate_assessments"],
        proposal["candidate_assessments"],
        strict=True,
    ):
        # candidate_id -> string
        assert isinstance(norm_assess["candidate_id"], str)
        assert norm_assess["candidate_id"] == str(orig_assess["candidate_id"])

        # assessment as-is
        assert norm_assess["assessment"] == orig_assess["assessment"]

        # supporting_evidence_ids -> list[str] (preserve order)
        assert norm_assess["supporting_evidence_ids"] == [
            str(eid) for eid in orig_assess["supporting_evidence_ids"]
        ]

        # contradicting_evidence_ids -> list[str] (preserve order)
        assert norm_assess["contradicting_evidence_ids"] == [
            str(eid) for eid in orig_assess["contradicting_evidence_ids"]
        ]

        # unresolved_information_ids -> list[str] (preserve order)
        assert norm_assess["unresolved_information_ids"] == [
            str(eid) for eid in orig_assess["unresolved_information_ids"]
        ]

        # explanation as-is
        assert norm_assess["explanation"] == orig_assess["explanation"]

        # uncertainty_flags -> list[str] sorted alphabetically
        expected_flags = sorted(str(f) for f in orig_assess["uncertainty_flags"])
        assert norm_assess["uncertainty_flags"] == expected_flags
        # Verify they are actually sorted
        assert norm_assess["uncertainty_flags"] == sorted(
            norm_assess["uncertainty_flags"]
        )


def test_deterministic_fingerprint_same_input_same_hash() -> None:
    """Same input = same hash."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    fp1 = compute_normalized_fingerprint(normalized)
    fp2 = compute_normalized_fingerprint(normalized)

    assert fp1 == fp2
    assert len(fp1) == 64
    assert all(c in "0123456789abcdef" for c in fp1)


def test_fingerprint_stability_across_normalizations() -> None:
    """Fingerprint is stable across multiple normalizations of same proposal."""
    proposal = _get_task057_proposal()

    fp1 = compute_normalized_fingerprint(normalize_proposal(proposal))
    fp2 = compute_normalized_fingerprint(normalize_proposal(proposal))
    fp3 = compute_normalized_fingerprint(normalize_proposal(proposal))

    assert fp1 == fp2 == fp3


def test_input_immutability_original_not_mutated() -> None:
    """Original proposal is not mutated by normalize_proposal."""
    proposal = _get_task057_proposal()

    # Deep copy for comparison
    proposal_copy = copy.deepcopy(proposal)

    normalize_proposal(proposal)

    # Original should be unchanged
    assert proposal == proposal_copy

    # Also verify nested structures unchanged
    for orig, copy_ in zip(
        proposal["candidate_assessments"],
        proposal_copy["candidate_assessments"],
        strict=True,
    ):
        assert orig == copy_


def test_semantic_preservation_uncertainty_flags_sorted_only_allowed_reordering() -> (
    None
):
    """Uncertainty flags sorted alphabetically is the only allowed reordering."""
    proposal = _get_task057_proposal()

    # Introduce unsorted uncertainty flags in the proposal
    proposal["candidate_assessments"][0]["uncertainty_flags"] = [
        "zebra",
        "alpha",
        "beta",
    ]

    normalized = normalize_proposal(proposal)

    # Flags should be sorted
    assert normalized["candidate_assessments"][0]["uncertainty_flags"] == [
        "alpha",
        "beta",
        "zebra",
    ]

    # But all other list orders must be preserved
    for norm_assess, orig_assess in zip(
        normalized["candidate_assessments"],
        proposal["candidate_assessments"],
        strict=True,
    ):
        # Evidence ID order preserved
        assert norm_assess["supporting_evidence_ids"] == [
            str(eid) for eid in orig_assess["supporting_evidence_ids"]
        ]
        assert norm_assess["contradicting_evidence_ids"] == [
            str(eid) for eid in orig_assess["contradicting_evidence_ids"]
        ]
        assert norm_assess["unresolved_information_ids"] == [
            str(eid) for eid in orig_assess["unresolved_information_ids"]
        ]


def test_candidate_order_preserved_from_input() -> None:
    """Candidate assessment order is preserved from input (matches context order)."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    original_ids = [str(a["candidate_id"]) for a in proposal["candidate_assessments"]]
    normalized_ids = [a["candidate_id"] for a in normalized["candidate_assessments"]]

    assert normalized_ids == original_ids


def test_evidence_id_order_preserved() -> None:
    """Evidence ID order is preserved within each assessment."""
    proposal = _get_task057_proposal()

    # Add multiple evidence IDs in specific order
    if proposal["candidate_assessments"]:
        obs_ids = [str(uuid4()) for _ in range(3)]
        proposal["candidate_assessments"][0]["supporting_evidence_ids"] = obs_ids

    normalized = normalize_proposal(proposal)

    if normalized["candidate_assessments"]:
        assert (
            normalized["candidate_assessments"][0]["supporting_evidence_ids"] == obs_ids
        )


def test_uncertainty_flags_sorted_deterministically() -> None:
    """Uncertainty flags are sorted deterministically (alphabetically)."""
    proposal = _get_task057_proposal()

    # Use flags that would sort differently than input order
    unsorted_flags = ["delta", "alpha", "epsilon", "beta", "gamma"]
    if proposal["candidate_assessments"]:
        proposal["candidate_assessments"][0]["uncertainty_flags"] = unsorted_flags

    normalized = normalize_proposal(proposal)

    expected = sorted(unsorted_flags)
    actual = normalized["candidate_assessments"][0]["uncertainty_flags"]
    assert actual == expected
    assert actual == ["alpha", "beta", "delta", "epsilon", "gamma"]


def test_validate_normalized_passes_for_valid_output() -> None:
    """validate_normalized returns empty list for valid normalized proposal."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    errors = validate_normalized(normalized)
    assert errors == []


def test_validate_normalized_catches_missing_fields() -> None:
    """validate_normalized catches missing required fields."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    # Remove a required field
    del normalized["session_id"]
    errors = validate_normalized(normalized)
    assert any("missing required field: session_id" in e for e in errors)


def test_validate_normalized_catches_wrong_types() -> None:
    """validate_normalized catches type mismatches."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    normalized["available"] = "not_a_bool"
    errors = validate_normalized(normalized)
    assert any("available must be bool" in e for e in errors)


def test_validate_normalized_catches_invalid_assessment_value() -> None:
    """validate_normalized catches invalid assessment enum values."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    normalized["candidate_assessments"][0]["assessment"] = "INVALID"
    errors = validate_normalized(normalized)
    assert any("must be SUPPORTS/WEAKENS/UNCLEAR" in e for e in errors)


def test_validate_normalized_catches_unsorted_uncertainty_flags() -> None:
    """validate_normalized catches unsorted uncertainty_flags."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    # Manually unsort the flags
    normalized["candidate_assessments"][0]["uncertainty_flags"] = ["zebra", "alpha"]
    errors = validate_normalized(normalized)
    assert any("uncertainty_flags must be sorted alphabetically" in e for e in errors)


def test_validate_normalized_catches_non_string_evidence_ids() -> None:
    """validate_normalized catches non-string evidence IDs."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    normalized["candidate_assessments"][0]["supporting_evidence_ids"] = [123]
    errors = validate_normalized(normalized)
    assert any("must be string" in e for e in errors)


def test_normalize_proposal_handles_empty_candidate_assessments() -> None:
    """Normalization works with empty candidate_assessments (unavailable case)."""
    # Create an unavailable context result
    from rop.services.llm_reasoning import LLM_REASONING_TASK_057

    unavailable_proposal = {
        "session_id": uuid4(),
        "context_fingerprint": "a" * 64,
        "provider": "fake",
        "model": "fake-model",
        "candidate_assessments": [],
        "available": False,
        "proposal_consistent": False,
        "llm_reasoning_source": LLM_REASONING_TASK_057,
    }

    normalized = normalize_proposal(unavailable_proposal)

    assert normalized["candidate_assessments"] == []
    assert normalized["available"] is False
    assert normalized["proposal_consistent"] is False

    errors = validate_normalized(normalized)
    assert errors == []


def test_normalize_proposal_handles_none_session_id() -> None:
    """Normalization rejects None session_id instead of fabricating null."""
    proposal = _get_task057_proposal()
    proposal["session_id"] = None

    with pytest.raises(LLMProposalNormalizationContractError) as ei:
        normalize_proposal(proposal)
    assert ei.value.invariant == "INVALID_ID"


def test_normalize_rejects_missing_top_field() -> None:
    proposal = _get_task057_proposal()
    del proposal["provider"]

    with pytest.raises(LLMProposalNormalizationContractError) as ei:
        normalize_proposal(proposal)
    assert ei.value.invariant == "MISSING_FIELD"


def test_normalize_rejects_extra_top_field() -> None:
    proposal = _get_task057_proposal()
    proposal["winner"] = "candidate-x"

    with pytest.raises(LLMProposalNormalizationContractError) as ei:
        normalize_proposal(proposal)
    assert ei.value.invariant == "UNEXPECTED_FIELD"


def test_normalize_rejects_non_mapping() -> None:
    with pytest.raises(LLMProposalNormalizationContractError) as ei:
        normalize_proposal(None)  # type: ignore[arg-type]
    assert ei.value.invariant == "INPUT_UNAVAILABLE"


def test_normalize_rejects_malformed_nested_assessment() -> None:
    proposal = _get_task057_proposal()
    proposal["candidate_assessments"][0] = "not-a-mapping"

    with pytest.raises(LLMProposalNormalizationContractError) as ei:
        normalize_proposal(proposal)
    assert ei.value.invariant == "MALFORMED_ASSESSMENT"


def test_normalize_rejects_nested_missing_field() -> None:
    proposal = _get_task057_proposal()
    del proposal["candidate_assessments"][0]["explanation"]

    with pytest.raises(LLMProposalNormalizationContractError) as ei:
        normalize_proposal(proposal)
    assert ei.value.invariant == "MISSING_FIELD"


def test_normalize_rejects_nested_extra_field() -> None:
    proposal = _get_task057_proposal()
    proposal["candidate_assessments"][0]["tool_call"] = "x"

    with pytest.raises(LLMProposalNormalizationContractError) as ei:
        normalize_proposal(proposal)
    assert ei.value.invariant == "UNEXPECTED_FIELD"


def test_normalize_rejects_invalid_candidate_id() -> None:
    proposal = _get_task057_proposal()
    proposal["candidate_assessments"][0]["candidate_id"] = "not-a-uuid"

    with pytest.raises(LLMProposalNormalizationContractError) as ei:
        normalize_proposal(proposal)
    assert ei.value.invariant == "INVALID_ID"


def test_normalize_rejects_invalid_assessment_value() -> None:
    proposal = _get_task057_proposal()
    proposal["candidate_assessments"][0]["assessment"] = "DEFINITELY"

    with pytest.raises(LLMProposalNormalizationContractError) as ei:
        normalize_proposal(proposal)
    assert ei.value.invariant == "INVALID_ASSESSMENT"


def test_normalize_rejects_empty_explanation() -> None:
    proposal = _get_task057_proposal()
    proposal["candidate_assessments"][0]["explanation"] = "  "

    with pytest.raises(LLMProposalNormalizationContractError) as ei:
        normalize_proposal(proposal)
    assert ei.value.invariant == "INVALID_EXPLANATION"


def test_compute_normalized_fingerprint_uses_canonical_json() -> None:
    """Fingerprint uses canonical JSON with sorted keys for dicts."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    # The fingerprint should be deterministic regardless of key insertion order
    # Create a copy with different key order
    reordered = {k: normalized[k] for k in reversed(list(normalized.keys()))}

    fp1 = compute_normalized_fingerprint(normalized)
    fp2 = compute_normalized_fingerprint(reordered)

    assert fp1 == fp2


def test_schema_matches_normalized_output() -> None:
    """NormalizedLLMReasoningProposalRead schema matches normalized output."""
    from rop.schemas.llm_proposal_normalization import (
        NormalizedLLMReasoningProposalRead,
    )

    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    # Should validate without error
    validated = NormalizedLLMReasoningProposalRead.model_validate(normalized)

    assert validated.session_id == normalized["session_id"]
    assert validated.context_fingerprint == normalized["context_fingerprint"]
    assert validated.provider == normalized["provider"]
    assert validated.model == normalized["model"]
    assert validated.available == normalized["available"]
    assert validated.proposal_consistent == normalized["proposal_consistent"]
    assert validated.llm_reasoning_source == normalized["llm_reasoning_source"]
    assert len(validated.candidate_assessments) == len(
        normalized["candidate_assessments"]
    )

    for v_assess, n_assess in zip(
        validated.candidate_assessments,
        normalized["candidate_assessments"],
        strict=True,
    ):
        assert v_assess.candidate_id == n_assess["candidate_id"]
        assert v_assess.assessment == n_assess["assessment"]
        assert v_assess.supporting_evidence_ids == n_assess["supporting_evidence_ids"]
        assert (
            v_assess.contradicting_evidence_ids
            == n_assess["contradicting_evidence_ids"]
        )
        assert (
            v_assess.unresolved_information_ids
            == n_assess["unresolved_information_ids"]
        )
        assert v_assess.explanation == n_assess["explanation"]
        assert v_assess.uncertainty_flags == n_assess["uncertainty_flags"]


def test_normalization_source_constant_preserved() -> None:
    """LLM_PROPOSAL_NORMALIZATION_SOURCE_TASK_106 constant exists."""
    assert (
        LLM_PROPOSAL_NORMALIZATION_SOURCE_TASK_106
        == "LLM_PROPOSAL_NORMALIZATION_TASK_106"
    )


def test_normalize_proposal_is_pure_no_side_effects() -> None:
    """normalize_proposal is pure: no mutation, deterministic."""
    proposal = _get_task057_proposal()

    # Call multiple times
    result1 = normalize_proposal(proposal)
    result2 = normalize_proposal(proposal)

    # Results should be equal
    assert result1 == result2

    # Original unchanged
    assert proposal["candidate_assessments"][0]["uncertainty_flags"] == [
        "insufficient_evidence",
        "low_confidence",
    ]


def test_compute_normalized_fingerprint_is_pure() -> None:
    """compute_normalized_fingerprint is pure: no mutation, deterministic."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    # Call multiple times
    fp1 = compute_normalized_fingerprint(normalized)
    fp2 = compute_normalized_fingerprint(normalized)

    assert fp1 == fp2

    # Input unchanged
    fp3 = compute_normalized_fingerprint(normalized)
    assert fp1 == fp3


def test_validate_normalized_is_pure() -> None:
    """validate_normalized is pure: no mutation."""
    proposal = _get_task057_proposal()
    normalized = normalize_proposal(proposal)

    # Call multiple times
    errors1 = validate_normalized(normalized)
    errors2 = validate_normalized(normalized)

    assert errors1 == errors2 == []

    # Input unchanged
    assert normalized["candidate_assessments"][0]["uncertainty_flags"] == sorted(
        normalized["candidate_assessments"][0]["uncertainty_flags"]
    )
