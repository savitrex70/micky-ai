"""Tests for Task 109 read-only LLM proposal inspection boundary.

All tests seed sessions and build real Task 057 proposals with an
injected fake provider. The inspection itself takes only a proposal
mapping: no DB, no HTTP, no provider calls.
"""

from __future__ import annotations

import copy
import inspect
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import rop.schemas.llm_proposal_inspection as inspection_schema_mod
import rop.services.llm_proposal_inspection as inspection_mod
from rop.database import Base, get_db
from rop.main import app
from rop.schemas.llm_proposal_inspection import LLMProposalInspectionRead
from rop.services.llm_proposal_inspection import (
    LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109,
    LLMProposalInspectionContractError,
    LLMProposalInspectionService,
)
from rop.services.llm_proposal_normalization import (
    compute_normalized_fingerprint,
    normalize_proposal,
)
from rop.services.llm_reasoning import LLM_REASONING_TASK_057, LLMReasoningService
from rop.services.llm_reasoning_provider import LLMReasoningProviderResponse
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

EXPECTED_INSPECTION_KEYS = frozenset(
    {
        "session_id",
        "context_fingerprint",
        "provider",
        "model",
        "available",
        "proposal_consistent",
        "candidate_assessments",
        "evidence_references",
        "unresolved_information_references",
        "uncertainty_flags",
        "inspection_source",
        "proposal_fingerprint",
    }
)


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
            "metadata": {"source": "task-109-test"},
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


def _valid_context(user_input: str = "Task 109 valid") -> dict[str, Any]:
    sid = _seed_full_session(user_input)
    session_uuid = UUID(sid)
    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        return ReasoningContextService().build_for_session(db, session_uuid)
    finally:
        db_gen.close()


def _valid_model_output(context: dict[str, Any]) -> str:
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


def _get_task057_proposal_with_raw(
    user_input: str = "Task 109 valid",
) -> tuple[dict[str, Any], str]:
    ctx = _valid_context(user_input)
    raw_text = _valid_model_output(ctx)
    provider = FakeProvider(response_text=raw_text)
    result = LLMReasoningService(provider=provider).build(context=ctx)
    return result, raw_text


def _get_task057_proposal() -> dict[str, Any]:
    proposal, _ = _get_task057_proposal_with_raw()
    return proposal


def _enriched_proposal() -> dict[str, Any]:
    """Real proposal with overlapping evidence/uncertainty references."""
    proposal = _get_task057_proposal()
    enriched = copy.deepcopy(proposal)
    shared_support = str(uuid4())
    shared_contra = str(uuid4())
    shared_unresolved = str(uuid4())
    for i, assessment in enumerate(enriched["candidate_assessments"]):
        unique_support = str(uuid4())
        unique_unresolved = str(uuid4())
        assessment["supporting_evidence_ids"] = [unique_support, shared_support]
        assessment["contradicting_evidence_ids"] = [shared_contra, shared_support]
        assessment["unresolved_information_ids"] = [
            unique_unresolved,
            shared_unresolved,
        ]
        assessment["uncertainty_flags"] = ["zebra_flag", f"flag_{i % 2}", "common_flag"]
    return enriched


def _collect_str_values(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            found.extend(_collect_str_values(v))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_str_values(item))
    return found


def _session_count() -> int:
    r = client.get("/sessions")
    assert r.status_code == 200
    return len(r.json())


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_source_constant_value() -> None:
    assert LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109 == "LLM_PROPOSAL_INSPECTION_TASK_109"


def test_exact_key_set() -> None:
    proposal = _get_task057_proposal()
    inspection = LLMProposalInspectionService.build(proposal=proposal)
    assert set(inspection.keys()) == set(EXPECTED_INSPECTION_KEYS)
    for forbidden in ("text", "raw_text", "prompt"):
        assert forbidden not in inspection


def test_all_field_values() -> None:
    proposal = _enriched_proposal()
    normalized = normalize_proposal(proposal)
    expected_fingerprint = compute_normalized_fingerprint(normalized)
    inspection = LLMProposalInspectionService.build(proposal=proposal)

    assert inspection["session_id"] == normalized["session_id"]
    assert isinstance(inspection["session_id"], str)
    assert inspection["context_fingerprint"] == proposal["context_fingerprint"]
    assert inspection["provider"] == proposal["provider"] == "fake"
    assert inspection["model"] == proposal["model"] == "fake-model"
    assert inspection["available"] is True
    assert inspection["proposal_consistent"] is True

    # Normalized assessments, same order.
    assert inspection["candidate_assessments"] == normalized["candidate_assessments"]
    assert [a["candidate_id"] for a in inspection["candidate_assessments"]] == [
        str(a["candidate_id"]) for a in proposal["candidate_assessments"]
    ]

    # Flat deduplicated sorted evidence references.
    expected_evidence = sorted(
        {
            eid
            for a in normalized["candidate_assessments"]
            for eid in (a["supporting_evidence_ids"] + a["contradicting_evidence_ids"])
        }
    )
    assert inspection["evidence_references"] == expected_evidence
    assert inspection["evidence_references"] == sorted(
        set(inspection["evidence_references"])
    )

    # Flat deduplicated sorted unresolved references.
    expected_unresolved = sorted(
        {
            eid
            for a in normalized["candidate_assessments"]
            for eid in a["unresolved_information_ids"]
        }
    )
    assert inspection["unresolved_information_references"] == expected_unresolved
    assert inspection["unresolved_information_references"] == sorted(
        set(inspection["unresolved_information_references"])
    )

    # Sorted unique uncertainty flags across assessments.
    expected_flags = sorted(
        {f for a in normalized["candidate_assessments"] for f in a["uncertainty_flags"]}
    )
    assert inspection["uncertainty_flags"] == expected_flags
    assert inspection["uncertainty_flags"] == sorted(
        set(inspection["uncertainty_flags"])
    )

    assert inspection["inspection_source"] == LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109
    assert inspection["proposal_fingerprint"] == expected_fingerprint
    assert len(inspection["proposal_fingerprint"]) == 64


def test_schema_validates_inspection() -> None:
    proposal = _enriched_proposal()
    inspection = LLMProposalInspectionService.build(proposal=proposal)
    validated = LLMProposalInspectionRead.model_validate(inspection)
    assert validated.session_id == inspection["session_id"]
    assert validated.context_fingerprint == inspection["context_fingerprint"]
    assert validated.provider == inspection["provider"]
    assert validated.model == inspection["model"]
    assert validated.available == inspection["available"]
    assert validated.proposal_consistent == inspection["proposal_consistent"]
    assert validated.inspection_source == inspection["inspection_source"]
    assert validated.proposal_fingerprint == inspection["proposal_fingerprint"]
    assert validated.evidence_references == inspection["evidence_references"]
    assert (
        validated.unresolved_information_references
        == inspection["unresolved_information_references"]
    )
    assert validated.uncertainty_flags == inspection["uncertainty_flags"]
    assert len(validated.candidate_assessments) == len(
        inspection["candidate_assessments"]
    )


# ---------------------------------------------------------------------------
# Read-only / immutability / determinism
# ---------------------------------------------------------------------------


def test_read_only_input_unchanged_and_session_count_unchanged() -> None:
    proposal = _get_task057_proposal()
    before_proposal = copy.deepcopy(proposal)
    before_count = _session_count()
    LLMProposalInspectionService.build(proposal=proposal)
    assert proposal == before_proposal
    assert _session_count() == before_count


def test_immutability_output_is_independent_copy() -> None:
    proposal = _enriched_proposal()
    before = copy.deepcopy(proposal)
    first = LLMProposalInspectionService.build(proposal=proposal)
    first_copy = copy.deepcopy(first)
    # Mutating the returned inspection must not affect later builds.
    first["candidate_assessments"].append({"candidate_id": "tampered"})
    first["evidence_references"].append("tampered")
    second = LLMProposalInspectionService.build(proposal=proposal)
    assert second == first_copy
    assert proposal == before


def test_determinism_double_build_equal() -> None:
    proposal = _enriched_proposal()
    first = LLMProposalInspectionService.build(proposal=proposal)
    second = LLMProposalInspectionService.build(proposal=proposal)
    assert first == second


# ---------------------------------------------------------------------------
# Rejection
# ---------------------------------------------------------------------------


def test_reject_none() -> None:
    with pytest.raises(LLMProposalInspectionContractError):
        LLMProposalInspectionService.build(proposal=None)


def test_reject_non_mapping() -> None:
    for bad in (["not", "a", "mapping"], "a-string", 42):
        with pytest.raises(LLMProposalInspectionContractError):
            LLMProposalInspectionService.build(proposal=bad)  # type: ignore[arg-type]


def test_reject_missing_session() -> None:
    proposal = _get_task057_proposal()
    del proposal["session_id"]
    with pytest.raises(LLMProposalInspectionContractError):
        LLMProposalInspectionService.build(proposal=proposal)


def test_reject_invalid_session() -> None:
    for bad_session in (None, "", "not-a-uuid"):
        proposal = _get_task057_proposal()
        proposal["session_id"] = bad_session
        with pytest.raises(LLMProposalInspectionContractError):
            LLMProposalInspectionService.build(proposal=proposal)


def test_reject_empty_assessments_when_available() -> None:
    proposal = _get_task057_proposal()
    proposal["candidate_assessments"] = []
    proposal["available"] = True
    with pytest.raises(LLMProposalInspectionContractError) as ei:
        LLMProposalInspectionService.build(proposal=proposal)
    assert ei.value.invariant == "PROPOSAL_INCONSISTENT"


def test_reject_fingerprint_tamper() -> None:
    proposal = _get_task057_proposal()
    proposal["proposal_fingerprint"] = "0" * 64
    with pytest.raises(LLMProposalInspectionContractError) as ei:
        LLMProposalInspectionService.build(proposal=proposal)
    assert ei.value.invariant == "FINGERPRINT_MISMATCH"


def test_matching_fingerprint_passthrough_accepted() -> None:
    proposal = _get_task057_proposal()
    matching = compute_normalized_fingerprint(normalize_proposal(proposal))
    proposal["proposal_fingerprint"] = matching
    inspection = LLMProposalInspectionService.build(proposal=proposal)
    assert inspection["proposal_fingerprint"] == matching


def test_reject_wrong_llm_reasoning_source() -> None:
    proposal = _get_task057_proposal()
    proposal["llm_reasoning_source"] = "WRONG"
    with pytest.raises(LLMProposalInspectionContractError) as ei:
        LLMProposalInspectionService.build(proposal=proposal)
    assert ei.value.invariant == "INVALID_SOURCE"


def test_reject_wrong_inspection_source() -> None:
    proposal = _get_task057_proposal()
    proposal["inspection_source"] = "WRONG"
    with pytest.raises(LLMProposalInspectionContractError) as ei:
        LLMProposalInspectionService.build(proposal=proposal)
    assert ei.value.invariant == "INVALID_SOURCE"


def test_reject_raw_text_keys() -> None:
    for forbidden in ("text", "raw_text", "prompt"):
        proposal = _get_task057_proposal()
        proposal[forbidden] = "leaked provider text"
        with pytest.raises(LLMProposalInspectionContractError):
            LLMProposalInspectionService.build(proposal=proposal)


# ---------------------------------------------------------------------------
# No raw text leakage
# ---------------------------------------------------------------------------


def test_no_raw_text_leakage() -> None:
    proposal, raw_text = _get_task057_proposal_with_raw()
    assert len(raw_text) > 0
    inspection = LLMProposalInspectionService.build(proposal=proposal)
    assert set(inspection.keys()) == set(EXPECTED_INSPECTION_KEYS)
    for value in _collect_str_values(inspection):
        assert value != raw_text
        assert raw_text not in value


# ---------------------------------------------------------------------------
# Coherent False proposal
# ---------------------------------------------------------------------------


def test_coherent_false_proposal_inspection() -> None:
    sid = uuid4()
    unavailable_proposal = {
        "session_id": sid,
        "context_fingerprint": "a" * 64,
        "provider": "fake",
        "model": "fake-model",
        "candidate_assessments": [],
        "available": False,
        "proposal_consistent": False,
        "llm_reasoning_source": LLM_REASONING_TASK_057,
    }
    inspection = LLMProposalInspectionService.build(proposal=unavailable_proposal)
    assert inspection["available"] is False
    assert inspection["proposal_consistent"] is False
    assert inspection["candidate_assessments"] == []
    assert inspection["evidence_references"] == []
    assert inspection["unresolved_information_references"] == []
    assert inspection["uncertainty_flags"] == []
    assert inspection["session_id"] == str(sid)
    assert inspection["inspection_source"] == LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109
    expected_fp = compute_normalized_fingerprint(
        normalize_proposal(unavailable_proposal)
    )
    assert inspection["proposal_fingerprint"] == expected_fp
    assert set(inspection.keys()) == set(EXPECTED_INSPECTION_KEYS)


# ---------------------------------------------------------------------------
# Boundary safety
# ---------------------------------------------------------------------------


def test_service_module_has_no_database_or_http() -> None:
    src = inspect.getsource(inspection_mod)
    for forbidden in (
        "SessionLocal",
        "create_engine",
        ".query(",
        ".execute(",
        "httpx",
        "requests.",
        "fastapi",
        ".commit(",
        ".flush(",
    ):
        assert forbidden not in src, forbidden


def test_service_module_does_not_reference_decision_or_provider() -> None:
    src = inspect.getsource(inspection_mod)
    for forbidden in (
        "DecisionPolicy",
        "DecisionExecution",
        "select_winner",
        "rank_candidates",
        "generate_reasoning",
    ):
        assert forbidden not in src, forbidden


def test_service_defines_constant_locally() -> None:
    src = inspect.getsource(inspection_mod)
    assert (
        'LLM_PROPOSAL_INSPECTION_SOURCE_TASK_109 = "LLM_PROPOSAL_INSPECTION_TASK_109"'
        in src
    )
    assert "from rop.schemas.llm_proposal_inspection" not in src


def test_schema_has_no_services_import() -> None:
    src = inspect.getsource(inspection_schema_mod)
    assert "rop.services" not in src
    assert "rop_schemas" not in src.replace("rop.schemas", "")


def test_schemas_never_import_from_services() -> None:
    import pathlib

    schemas_dir = (
        pathlib.Path(__file__).resolve().parent.parent / "src" / "rop" / "schemas"
    )
    offenders = []
    for path in schemas_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "rop.services" in text or "from rop import services" in text:
            offenders.append(path.name)
    assert offenders == []
