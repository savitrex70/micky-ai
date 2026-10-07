"""Task 159: Stage 7 proposal provenance and consistency audit tests.

Covers the independent deterministic audit of a returned Task 158
proposal result against the canonical Task 055 context. Task 103 is
the authoritative audit: every verdict, dimension flag, and consistency
finding in the projection is Task 103 evidence, and the service never
reimplements, weakens, or extends the canonical checks.

The outer Task 158 envelope is provenance, not decoration. It must
validate against the existing Task 158 contract and agree with the
nested Task 057 proposal on ``session_id``, ``context_fingerprint``,
``provider``, and ``model`` before Task 103 is consulted, so a forged
or internally split envelope is UNAVAILABLE and never reaches the
canonical audit. Corrupting the audited proposal must never touch the
canonical request package, and a missing canonical context is
UNAVAILABLE, never a success.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
from collections.abc import Generator, Mapping
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_run_stage_7_proposal_audit import (
    ReasoningRunStage7ProposalAuditRead,
)
from rop.services.llm_reasoning import LLM_REASONING_TASK_057, LLMReasoningService
from rop.services.llm_reasoning_audit import LLMReasoningAuditService
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
)
from rop.services.llm_request_serialization import serialize_context
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionService,
)
from rop.services.reasoning_run_stage_7_dispatch import (
    ReasoningRunStage7DispatchService,
)
from rop.services.reasoning_run_stage_7_proposal import (
    REASONING_RUN_STAGE_7_PROPOSAL_SOURCE_TASK_158,
    ReasoningRunStage7ProposalService,
)
from rop.services.reasoning_run_stage_7_proposal_audit import (
    REASONING_RUN_STAGE_7_PROPOSAL_AUDIT_SOURCE_TASK_159,
    ReasoningRunStage7ProposalAuditService,
)
from rop.services.reasoning_run_stage_7_request import (
    ReasoningRunStage7RequestService,
)
from rop.services.reasoning_run_stage_7_request_audit import (
    ReasoningRunStage7RequestAuditService,
)

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

PROPOSAL_AUDIT_KEYS = {
    "proposal_audit_status",
    "available",
    "audited_session_id",
    "audited_proposal_fingerprint",
    "proposal_consistent",
    "session_consistent",
    "fingerprint_consistent",
    "candidate_assessments_consistent",
    "evidence_references_consistent",
    "unresolved_info_consistent",
    "candidate_order_consistent",
    "provenance_consistent",
    "metadata_consistent",
    "finding_count",
    "findings",
    "audit_source",
}

_DIMENSION_NAMES = (
    "session_consistent",
    "fingerprint_consistent",
    "candidate_assessments_consistent",
    "evidence_references_consistent",
    "unresolved_info_consistent",
    "candidate_order_consistent",
    "provenance_consistent",
    "metadata_consistent",
)

_CONCRETE_PROVIDER_TOKENS = ("ollama", "openai", "gemini", "anthropic", "claude")
_PROHIBITED_SOURCE_TOKENS = (
    *_CONCRETE_PROVIDER_TOKENS,
    "httpx",
    "aiohttp",
    "urllib3",
    "requests",
    "os.environ",
    "getenv",
    "api_key",
    "socket",
    "entry_points",
)


class _CertificationStub:
    """Returns one coherent Stage 6 verdict for the real admission path."""

    def __init__(self, status: str = "CERTIFIED") -> None:
        self._status = status
        self.calls: list[UUID] = []

    def certify(self, db: Session, session_id: UUID) -> dict[str, object]:
        self.calls.append(session_id)
        certified = self._status == "CERTIFIED"
        return {
            "requested_session_id": str(session_id),
            "certification_status": self._status,
            "certified": certified,
            "release_ready": certified,
        }


class _FakeProvider:
    """Deterministic test-only provider. No network, no model, no state."""

    def __init__(self) -> None:
        self.provider_name = "fake-provider"
        self.model_name = "fake-model"
        self.response: object = LLMReasoningProviderResponse(
            provider="fake-provider",
            model="fake-model",
            text='{"candidate_assessments": []}',
        )
        self.calls: list[object] = []

    def generate_reasoning(self, request: object) -> object:
        self.calls.append(request)
        return self.response


class _FailingProvider:
    """Test-only provider that raises one canonical failure."""

    def __init__(self, error: Exception) -> None:
        self.provider_name = "failing-provider"
        self.model_name = "failing-model"
        self.error = error
        self.calls: list[object] = []

    def generate_reasoning(self, request: object) -> object:
        self.calls.append(request)
        raise self.error


@pytest.fixture(autouse=True)
def _reset_db() -> Generator[None, None, None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    app.dependency_overrides[get_db] = override_get_db
    yield


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "stage-7-proposal-audit-test"},
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


def _context(db: Session, sid: str) -> dict:
    context = ReasoningContextService().build_for_session(db, UUID(sid))
    assert context["available"] is True
    return context


def _build_package(db: Session, sid: str) -> dict:
    service = ReasoningRunStage7RequestService(
        admission_service=ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("CERTIFIED")
        )
    )
    package = service.build(db, UUID(sid))
    assert package["request_status"] == "PACKAGED"
    return package


def _audit(db: Session, package: object) -> dict:
    service = ReasoningRunStage7RequestAuditService(
        admission_service=ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("CERTIFIED")
        )
    )
    audit = service.audit(db, package)
    assert audit["request_audit_status"] == "CONSISTENT"
    return audit


def _dispatch(db: Session, sid: str, provider: object) -> tuple[dict, dict]:
    package = _build_package(db, sid)
    audit = _audit(db, package)
    result = ReasoningRunStage7DispatchService(provider=provider).dispatch(
        request=package, request_audit=audit
    )
    assert result["dispatch_status"] == "DISPATCHED"
    return result, package


def _valid_model_output(context: dict) -> str:
    assessments = [
        {
            "candidate_id": str(candidate.id),
            "assessment": "UNCLEAR",
            "supporting_evidence_ids": [],
            "contradicting_evidence_ids": [],
            "unresolved_information_ids": [],
            "explanation": "insufficient evidence to decide",
            "uncertainty_flags": ["insufficient_evidence"],
        }
        for candidate in context["candidate_state"]
    ]
    return json.dumps({"candidate_assessments": assessments})


def _response(text: str) -> LLMReasoningProviderResponse:
    return LLMReasoningProviderResponse(
        provider="fake-provider", model="fake-model", text=text
    )


def _validated_pipeline(db: Session, sid: str) -> tuple[dict, dict, dict]:
    provider = _FakeProvider()
    context = _context(db, sid)
    provider.response = _response(_valid_model_output(context))
    dispatch, package = _dispatch(db, sid, provider)
    result = ReasoningRunStage7ProposalService().build(
        dispatch_result=dispatch, context=context
    )
    assert result["proposal_status"] == "VALIDATED"
    return result, context, package


def _audit_proposal(proposal_result: object, context: object) -> dict:
    return ReasoningRunStage7ProposalAuditService.audit(
        proposal_result=proposal_result, context=context
    )


def _corrupted(result: dict) -> dict:
    return copy.deepcopy(result)


def _coherently_corrupted(result: dict, field: str, value: object) -> dict:
    """Corrupt one duplicated provenance field in BOTH copies.

    Task 159 requires the Task 158 envelope and the nested Task 057
    proposal to agree on the duplicated provenance fields, so a
    corruption that is meant to reach Task 103 has to be applied to
    both copies. A single-copy change is a binding mismatch instead and
    is covered by its own tests.
    """
    corrupted = _corrupted(result)
    corrupted[field] = value
    corrupted["proposal"][field] = value
    return corrupted


def _spy_task_103(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Record and reject every canonical Task 103 call.

    Used to prove that a rejected Task 158 envelope never reaches the
    authoritative audit, so no CONSISTENT verdict can be manufactured
    from material that failed the provenance gates.
    """
    calls: list[object] = []

    def _spy(*args: object, **kwargs: object) -> dict:
        calls.append(kwargs or args)
        raise AssertionError("Task 103 must not audit a rejected envelope")

    monkeypatch.setattr(LLMReasoningAuditService, "build", _spy)
    return calls


def _table_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f"SELECT COUNT(*) FROM {table.name}")
            ).scalar_one()
            for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
        }


# ---------------------------------------------------------------------------
# Happy path: the canonical Task 103 audit certifies the returned proposal
# ---------------------------------------------------------------------------


def test_valid_proposal_is_consistent() -> None:
    sid = _seed_full_session("Task 159 valid proposal")
    with TestingSessionLocal() as db:
        result, context, package = _validated_pipeline(db, sid)
        audit = _audit_proposal(result, context)

    assert set(audit) == PROPOSAL_AUDIT_KEYS
    assert audit["proposal_audit_status"] == "CONSISTENT"
    assert audit["available"] is True
    assert audit["proposal_consistent"] is True
    for name in _DIMENSION_NAMES:
        assert audit[name] is True, name
    assert audit["finding_count"] == 0
    assert audit["findings"] == []
    assert audit["audit_source"] == REASONING_RUN_STAGE_7_PROPOSAL_AUDIT_SOURCE_TASK_159
    assert result["context_fingerprint"] == package["context_fingerprint"]

    # Binding evidence names the exact audited proposal: the values are
    # the nested Task 057 proposal's own fields, not recomputed ones.
    assert audit["audited_session_id"] == result["proposal"]["session_id"]
    assert (
        audit["audited_proposal_fingerprint"]
        == result["proposal"]["context_fingerprint"]
    )
    assert audit["audited_session_id"] == sid
    assert audit["audited_proposal_fingerprint"] == package["context_fingerprint"]


# ---------------------------------------------------------------------------
# Structural corruption: every case is Task 103 evidence, never a new check
# ---------------------------------------------------------------------------


def test_fingerprint_mismatch_is_inconsistent() -> None:
    sid = _seed_full_session("Task 159 fingerprint mismatch")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        corrupted = _coherently_corrupted(result, "context_fingerprint", "0" * 64)
        audit = _audit_proposal(corrupted, context)
        pristine = _audit_proposal(result, context)

    assert audit["proposal_audit_status"] == "INCONSISTENT"
    assert audit["available"] is True
    assert audit["fingerprint_consistent"] is False
    assert "fingerprint_mismatch" in audit["findings"]
    assert pristine["proposal_audit_status"] == "CONSISTENT"


def test_session_mismatch_is_inconsistent() -> None:
    sid = _seed_full_session("Task 159 session mismatch")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        corrupted = _coherently_corrupted(result, "session_id", str(uuid4()))
        audit = _audit_proposal(corrupted, context)

    assert audit["proposal_audit_status"] == "INCONSISTENT"
    assert audit["session_consistent"] is False
    assert "session_mismatch" in audit["findings"]


def test_unknown_candidate_is_inconsistent() -> None:
    sid = _seed_full_session("Task 159 unknown candidate")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        corrupted = _corrupted(result)
        corrupted["proposal"]["candidate_assessments"][0]["candidate_id"] = str(uuid4())
        audit = _audit_proposal(corrupted, context)

    assert audit["proposal_audit_status"] == "INCONSISTENT"
    assert audit["candidate_assessments_consistent"] is False
    assert "unknown_candidate_id" in audit["findings"]


def test_unknown_evidence_is_inconsistent() -> None:
    sid = _seed_full_session("Task 159 unknown evidence")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)

        supporting = _corrupted(result)
        supporting["proposal"]["candidate_assessments"][0][
            "supporting_evidence_ids"
        ] = [str(uuid4())]
        supporting_audit = _audit_proposal(supporting, context)

        contradicting = _corrupted(result)
        contradicting["proposal"]["candidate_assessments"][0][
            "contradicting_evidence_ids"
        ] = [str(uuid4())]
        contradicting_audit = _audit_proposal(contradicting, context)

        unresolved = _corrupted(result)
        unresolved["proposal"]["candidate_assessments"][0][
            "unresolved_information_ids"
        ] = [str(uuid4())]
        unresolved_audit = _audit_proposal(unresolved, context)

    assert supporting_audit["proposal_audit_status"] == "INCONSISTENT"
    assert supporting_audit["evidence_references_consistent"] is False
    assert "unknown_supporting_evidence_id" in supporting_audit["findings"]

    assert contradicting_audit["proposal_audit_status"] == "INCONSISTENT"
    assert contradicting_audit["evidence_references_consistent"] is False
    assert "unknown_contradicting_evidence_id" in contradicting_audit["findings"]

    assert unresolved_audit["proposal_audit_status"] == "INCONSISTENT"
    assert unresolved_audit["unresolved_info_consistent"] is False
    assert "unknown_missing_info_id" in unresolved_audit["findings"]


def test_candidate_order_mismatch_is_inconsistent() -> None:
    sid = _seed_full_session("Task 159 candidate order")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        assert len(context["candidate_state"]) >= 2
        corrupted = _corrupted(result)
        corrupted["proposal"]["candidate_assessments"].reverse()
        audit = _audit_proposal(corrupted, context)

    assert audit["proposal_audit_status"] == "INCONSISTENT"
    assert audit["candidate_order_consistent"] is False
    assert "candidate_order_mismatch" in audit["findings"]


def test_missing_assessment_is_inconsistent() -> None:
    sid = _seed_full_session("Task 159 missing assessment")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        corrupted = _corrupted(result)
        corrupted["proposal"]["candidate_assessments"] = corrupted["proposal"][
            "candidate_assessments"
        ][:-1]
        audit = _audit_proposal(corrupted, context)

    assert audit["proposal_audit_status"] == "INCONSISTENT"
    assert audit["candidate_assessments_consistent"] is False
    assert "missing_candidate_assessment" in audit["findings"]


def test_extra_assessment_is_inconsistent() -> None:
    sid = _seed_full_session("Task 159 extra assessment")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        corrupted = _corrupted(result)
        extra = copy.deepcopy(corrupted["proposal"]["candidate_assessments"][0])
        extra["candidate_id"] = str(uuid4())
        corrupted["proposal"]["candidate_assessments"].append(extra)
        audit = _audit_proposal(corrupted, context)

    assert audit["proposal_audit_status"] == "INCONSISTENT"
    assert audit["candidate_assessments_consistent"] is False
    assert "extra_candidate_assessment" in audit["findings"]


def test_source_mismatch_is_inconsistent() -> None:
    sid = _seed_full_session("Task 159 source mismatch")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        corrupted = _corrupted(result)
        corrupted["proposal"]["llm_reasoning_source"] = "LLM_REASONING_TASK_999"
        audit = _audit_proposal(corrupted, context)

    assert audit["proposal_audit_status"] == "INCONSISTENT"
    assert audit["provenance_consistent"] is False
    assert any(
        finding.startswith(
            f"source_constant_mismatch:expected={LLM_REASONING_TASK_057}"
        )
        for finding in audit["findings"]
    )


def test_provider_or_model_metadata_failure_is_inconsistent() -> None:
    sid = _seed_full_session("Task 159 metadata failure")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        provider_audit = _audit_proposal(
            _coherently_corrupted(result, "provider", ""), context
        )
        model_audit = _audit_proposal(
            _coherently_corrupted(result, "model", ""), context
        )

    assert provider_audit["proposal_audit_status"] == "INCONSISTENT"
    assert provider_audit["provenance_consistent"] is False
    assert "empty_provider" in provider_audit["findings"]

    assert model_audit["proposal_audit_status"] == "INCONSISTENT"
    assert model_audit["provenance_consistent"] is False
    assert "empty_model" in model_audit["findings"]


def test_flipped_consistency_claim_is_inconsistent() -> None:
    """The status maps Task 103's own overall flag, not a fresh verdict."""
    sid = _seed_full_session("Task 159 flipped claim")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        corrupted = _corrupted(result)
        corrupted["proposal"]["proposal_consistent"] = False
        audit = _audit_proposal(corrupted, context)

    assert audit["proposal_audit_status"] == "INCONSISTENT"
    assert audit["available"] is True
    assert audit["proposal_consistent"] is False
    assert audit["findings"] == []
    for name in _DIMENSION_NAMES:
        assert audit[name] is True, name


# ---------------------------------------------------------------------------
# Missing material: UNAVAILABLE, never a misleading success
# ---------------------------------------------------------------------------


def test_missing_canonical_context_is_unavailable() -> None:
    sid = _seed_full_session("Task 159 missing context")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)

        assert _audit_proposal(result, None)["proposal_audit_status"] == "UNAVAILABLE"
        absent = _audit_proposal(result, None)
        empty = _audit_proposal(result, {})
        broken = _audit_proposal(result, {**context, "candidate_state": None})

    assert absent["findings"] == ["CANONICAL_CONTEXT_MISSING"]
    assert absent["available"] is False
    assert absent["proposal_consistent"] is False
    for name in _DIMENSION_NAMES:
        assert absent[name] is False, name

    assert empty["proposal_audit_status"] == "UNAVAILABLE"
    assert empty["findings"] == ["PROPOSAL_AUDIT_UNAVAILABLE:CONTEXT_INVALID"]

    assert broken["proposal_audit_status"] == "UNAVAILABLE"
    assert broken["findings"] == ["PROPOSAL_AUDIT_UNAVAILABLE:CONTEXT_INVALID"]


def test_missing_proposal_material_is_unavailable() -> None:
    sid = _seed_full_session("Task 159 missing proposal")
    failing = _FailingProvider(LLMReasoningProviderError("no model configured"))
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)

        package = _build_package(db, sid)
        audit = _audit(db, package)
        dispatch = ReasoningRunStage7DispatchService(provider=failing).dispatch(
            request=package, request_audit=audit
        )
        failed = ReasoningRunStage7ProposalService().build(
            dispatch_result=dispatch, context=context
        )
        assert failed["proposal_status"] == "MODEL_UNAVAILABLE"

        absent = _audit_proposal(None, context)
        empty = _audit_proposal({}, context)
        not_validated = _audit_proposal(failed, context)
        no_material = _audit_proposal(
            {"proposal_status": "VALIDATED", "proposal": None}, context
        )

    assert absent["proposal_audit_status"] == "UNAVAILABLE"
    assert absent["findings"] == ["PROPOSAL_RESULT_MISSING"]

    # An empty mapping is not a readable Task 158 envelope, so the
    # strict Task 158 contract rejects it before any status is trusted.
    assert empty["proposal_audit_status"] == "UNAVAILABLE"
    assert empty["findings"] == ["PROPOSAL_RESULT_INVALID:available:missing"]

    assert not_validated["proposal_audit_status"] == "UNAVAILABLE"
    assert not_validated["findings"] == ["PROPOSAL_NOT_VALIDATED:MODEL_UNAVAILABLE"]

    # A VALIDATED envelope without its nested proposal contradicts the
    # Task 158 coherence rule and is rejected by that same contract.
    assert no_material["proposal_audit_status"] == "UNAVAILABLE"
    assert no_material["findings"] == ["PROPOSAL_RESULT_INVALID:available:missing"]

    for verdict in (absent, empty, not_validated, no_material):
        assert verdict["available"] is False
        assert verdict["proposal_consistent"] is False
        for name in _DIMENSION_NAMES:
            assert verdict[name] is False, name


# ---------------------------------------------------------------------------
# Provenance gates: a split, forged, or hostile Task 158 envelope is
# UNAVAILABLE and never reaches the canonical Task 103 audit
# ---------------------------------------------------------------------------


def _assert_unavailable(verdict: dict, expected_finding: str) -> None:
    assert verdict["proposal_audit_status"] == "UNAVAILABLE"
    assert verdict["available"] is False
    assert verdict["proposal_consistent"] is False
    for name in _DIMENSION_NAMES:
        assert verdict[name] is False, name
    # Rejected material certifies no audited proposal at all.
    assert verdict["audited_session_id"] is None
    assert verdict["audited_proposal_fingerprint"] is None
    assert any(
        finding.startswith(expected_finding) for finding in verdict["findings"]
    ), verdict["findings"]


def test_outer_session_split_from_nested_proposal_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _seed_full_session("Task 159 outer session split")
    calls = _spy_task_103(monkeypatch)
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        forged = _corrupted(result)
        forged["session_id"] = str(uuid4())
        audit = _audit_proposal(forged, context)

    _assert_unavailable(audit, "PROPOSAL_SESSION_BINDING_MISMATCH")
    assert calls == []


def test_outer_fingerprint_split_from_nested_proposal_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _seed_full_session("Task 159 outer fingerprint split")
    calls = _spy_task_103(monkeypatch)
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        forged = _corrupted(result)
        forged["context_fingerprint"] = "0" * 64
        audit = _audit_proposal(forged, context)

    _assert_unavailable(audit, "PROPOSAL_FINGERPRINT_BINDING_MISMATCH")
    assert calls == []


def test_outer_provider_split_from_nested_proposal_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _seed_full_session("Task 159 outer provider split")
    calls = _spy_task_103(monkeypatch)
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        forged = _corrupted(result)
        forged["provider"] = "other-provider"
        audit = _audit_proposal(forged, context)

    _assert_unavailable(audit, "PROPOSAL_PROVIDER_BINDING_MISMATCH")
    assert calls == []


def test_outer_model_split_from_nested_proposal_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _seed_full_session("Task 159 outer model split")
    calls = _spy_task_103(monkeypatch)
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        forged = _corrupted(result)
        forged["model"] = "other-model"
        audit = _audit_proposal(forged, context)

    _assert_unavailable(audit, "PROPOSAL_MODEL_BINDING_MISMATCH")
    assert calls == []


def test_forged_envelope_cannot_manufacture_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A VALIDATED status wrapping a genuine proposal is not enough."""
    sid = _seed_full_session("Task 159 forged envelope")
    calls = _spy_task_103(monkeypatch)
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)

        forged = {
            "proposal_status": "VALIDATED",
            "available": True,
            "proposal_source": REASONING_RUN_STAGE_7_PROPOSAL_SOURCE_TASK_158,
            "proposal": copy.deepcopy(result["proposal"]),
        }
        coerced = _audit_proposal(forged, context)
        _assert_unavailable(coerced, "PROPOSAL_RESULT_INVALID:context_fingerprint:")

        incomplete = _corrupted(result)
        del incomplete["proposal_source"]
        _assert_unavailable(
            _audit_proposal(incomplete, context),
            "PROPOSAL_RESULT_INVALID:proposal_source:missing",
        )

        corrupted_status = _corrupted(result)
        corrupted_status["proposal_status"] = "SOMETHING_ELSE"
        assert (
            _audit_proposal(corrupted_status, context)["proposal_audit_status"]
            == "UNAVAILABLE"
        )

    assert calls == []


def test_extra_outer_field_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _seed_full_session("Task 159 extra outer field")
    calls = _spy_task_103(monkeypatch)
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        padded = _corrupted(result)
        padded["unpaid_attestation"] = True
        audit = _audit_proposal(padded, context)

    _assert_unavailable(
        audit, "PROPOSAL_RESULT_INVALID:unpaid_attestation:extra_forbidden"
    )
    assert calls == []


def test_hostile_mapping_fails_closed() -> None:
    class _Hostile(Mapping):
        def __getitem__(self, key: object) -> object:
            raise RuntimeError("hostile mapping")

        def __len__(self) -> int:
            return 1

        def __iter__(self) -> object:
            raise RuntimeError("hostile mapping")

        def keys(self) -> object:
            raise RuntimeError("hostile mapping")

    sid = _seed_full_session("Task 159 hostile mapping")
    with TestingSessionLocal() as db:
        _, context, _ = _validated_pipeline(db, sid)
        audit = _audit_proposal(_Hostile(), context)

    _assert_unavailable(audit, "PROPOSAL_RESULT_INVALID:RuntimeError")


def test_genuine_envelope_still_projects_task_103_exactly() -> None:
    """Task 159 is a projection of Task 103, not a second implementation."""
    sid = _seed_full_session("Task 159 exact projection")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        canonical = LLMReasoningAuditService.build(
            proposal=result["proposal"], context=context
        )
        audit = _audit_proposal(result, context)

    assert audit["proposal_consistent"] is canonical["proposal_consistent"]
    for name in _DIMENSION_NAMES:
        assert audit[name] is canonical[name], name
    assert audit["findings"] == sorted(set(canonical["consistency_issues"]))
    assert audit["finding_count"] == len(audit["findings"])
    assert audit["proposal_audit_status"] == (
        "CONSISTENT" if canonical["proposal_consistent"] else "INCONSISTENT"
    )


def test_inconsistent_proposal_still_projects_task_103_exactly() -> None:
    sid = _seed_full_session("Task 159 exact projection inconsistent")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        corrupted = _coherently_corrupted(result, "context_fingerprint", "0" * 64)
        canonical = LLMReasoningAuditService.build(
            proposal=corrupted["proposal"], context=context
        )
        audit = _audit_proposal(corrupted, context)

    assert audit["proposal_consistent"] is canonical["proposal_consistent"]
    for name in _DIMENSION_NAMES:
        assert audit[name] is canonical[name], name
    assert audit["findings"] == sorted(set(canonical["consistency_issues"]))
    assert audit["proposal_audit_status"] == "INCONSISTENT"


def test_binding_names_the_exact_audited_proposal() -> None:
    """An audited binding always names the proposal Task 103 actually saw."""
    sid = _seed_full_session("Task 159 audited binding")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
        forged_session = str(uuid4())
        corrupted = _coherently_corrupted(result, "session_id", forged_session)
        audit = _audit_proposal(corrupted, context)

    assert audit["proposal_audit_status"] == "INCONSISTENT"
    assert audit["audited_session_id"] == forged_session
    assert audit["audited_session_id"] == corrupted["proposal"]["session_id"]
    assert (
        audit["audited_proposal_fingerprint"]
        == result["proposal"]["context_fingerprint"]
    )
    assert audit["audited_session_id"] != sid


# ---------------------------------------------------------------------------
# Independence: the audit never touches the canonical request package
# ---------------------------------------------------------------------------


def test_audit_independence_preserves_canonical_package() -> None:
    sid = _seed_full_session("Task 159 independence")
    with TestingSessionLocal() as db:
        result, context, package = _validated_pipeline(db, sid)

        result_snapshot = copy.deepcopy(result)
        package_snapshot = copy.deepcopy(package)
        context_snapshot = serialize_context(context)

        pristine = _audit_proposal(result, context)
        assert pristine["proposal_audit_status"] == "CONSISTENT"

        corrupted = _coherently_corrupted(result, "provider", "")
        corrupted["proposal"]["candidate_assessments"][0]["candidate_id"] = str(uuid4())
        corrupted["proposal"]["candidate_assessments"][0]["supporting_evidence_ids"] = [
            str(uuid4())
        ]
        corrupted_audit = _audit_proposal(corrupted, context)

        recheck = _audit_proposal(result, context)

    assert corrupted_audit["proposal_audit_status"] == "INCONSISTENT"
    assert {"empty_provider", "unknown_candidate_id"} <= set(
        corrupted_audit["findings"]
    )

    assert recheck == pristine
    assert result == result_snapshot
    assert package == package_snapshot
    assert package["request_status"] == "PACKAGED"
    assert serialize_context(context) == context_snapshot


# ---------------------------------------------------------------------------
# Read-only and deterministic
# ---------------------------------------------------------------------------


def test_proposal_audit_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _seed_full_session("Task 159 read-only")
    with TestingSessionLocal() as db:
        result, context, _ = _validated_pipeline(db, sid)
    before = _table_counts()

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("write or provider call attempted during proposal audit")

    monkeypatch.setattr(Session, "add", _forbidden)
    monkeypatch.setattr(Session, "merge", _forbidden)
    monkeypatch.setattr(Session, "delete", _forbidden)
    monkeypatch.setattr(Session, "commit", _forbidden)
    monkeypatch.setattr(LLMReasoningService, "build", _forbidden)
    monkeypatch.setattr(LLMReasoningService, "build_for_session", _forbidden)
    monkeypatch.setattr(ReasoningRunStage7DispatchService, "dispatch", _forbidden)
    monkeypatch.setattr(ReasoningRunStage7ProposalService, "build", _forbidden)
    monkeypatch.setattr(ReasoningContextService, "build_for_session", _forbidden)

    audit = _audit_proposal(result, context)

    assert audit["proposal_audit_status"] == "CONSISTENT"
    assert _table_counts() == before


def test_proposal_audit_is_deterministic_and_non_mutating() -> None:
    sid = _seed_full_session("Task 159 determinism")
    with TestingSessionLocal() as db:
        result, context, package = _validated_pipeline(db, sid)

        result_snapshot = copy.deepcopy(result)
        package_snapshot = copy.deepcopy(package)
        context_snapshot = serialize_context(context)

        first = _audit_proposal(result, context)
        second = _audit_proposal(result, context)

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert result == result_snapshot
    assert package == package_snapshot
    assert serialize_context(context) == context_snapshot


# ---------------------------------------------------------------------------
# Schema strictness and provider-neutral source
# ---------------------------------------------------------------------------


def test_proposal_audit_schema_is_strict() -> None:
    valid = {
        "proposal_audit_status": "CONSISTENT",
        "available": True,
        "audited_session_id": "0b8b1f9a-3f1e-4a1c-9c2f-9a5a1f9a3f1e",
        "audited_proposal_fingerprint": "a" * 64,
        "proposal_consistent": True,
        "session_consistent": True,
        "fingerprint_consistent": True,
        "candidate_assessments_consistent": True,
        "evidence_references_consistent": True,
        "unresolved_info_consistent": True,
        "candidate_order_consistent": True,
        "provenance_consistent": True,
        "metadata_consistent": True,
        "finding_count": 0,
        "findings": [],
        "audit_source": REASONING_RUN_STAGE_7_PROPOSAL_AUDIT_SOURCE_TASK_159,
    }
    validated = ReasoningRunStage7ProposalAuditRead.model_validate(valid)
    assert validated.proposal_audit_status == "CONSISTENT"

    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate({**valid, "extra": 1})
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate(
            {**valid, "proposal_audit_status": "DONE"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate(
            {**valid, "available": False}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate(
            {**valid, "proposal_consistent": False}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate(
            {**valid, "session_consistent": False}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate(
            {**valid, "finding_count": 1}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate(
            {**valid, "finding_count": 2, "findings": ["b", "a"]}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate(
            {**valid, "finding_count": 2, "findings": ["dup", "dup"]}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate(
            {**valid, "proposal_audit_status": "INCONSISTENT"}
        )

    # A CONSISTENT verdict must name the exact proposal it certifies: a
    # missing audited binding can never leave CONSISTENT standing.
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate(
            {**valid, "audited_session_id": None}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate(
            {**valid, "audited_proposal_fingerprint": None}
        )

    inconsistent = ReasoningRunStage7ProposalAuditRead.model_validate(
        {
            **valid,
            "proposal_audit_status": "INCONSISTENT",
            "proposal_consistent": False,
            "session_consistent": False,
            "finding_count": 1,
            "findings": ["session_mismatch"],
        }
    )
    assert inconsistent.available is True

    claim_only = ReasoningRunStage7ProposalAuditRead.model_validate(
        {**valid, "proposal_audit_status": "INCONSISTENT", "proposal_consistent": False}
    )
    assert claim_only.findings == []

    unavailable = ReasoningRunStage7ProposalAuditRead.model_validate(
        {
            **valid,
            "proposal_audit_status": "UNAVAILABLE",
            "available": False,
            "proposal_consistent": False,
            "session_consistent": False,
            "fingerprint_consistent": False,
            "candidate_assessments_consistent": False,
            "evidence_references_consistent": False,
            "unresolved_info_consistent": False,
            "candidate_order_consistent": False,
            "provenance_consistent": False,
            "metadata_consistent": False,
            "finding_count": 1,
            "findings": ["CANONICAL_CONTEXT_MISSING"],
        }
    )
    assert unavailable.available is False
    with pytest.raises(ValidationError):
        ReasoningRunStage7ProposalAuditRead.model_validate(
            {**unavailable.model_dump(), "session_consistent": True}
        )


def test_proposal_audit_service_accepts_only_material() -> None:
    signature = inspect.signature(ReasoningRunStage7ProposalAuditService.audit)
    assert set(signature.parameters) == {"proposal_result", "context"}
    for name in ("proposal_result", "context"):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY

    init = inspect.signature(ReasoningRunStage7ProposalAuditService.__init__)
    assert "provider" not in init.parameters

    import rop.services.reasoning_run_stage_7_proposal_audit as module

    for attr in (
        "PROVIDER_REGISTRY",
        "DEFAULT_PROVIDER",
        "AUTO_PROVIDER",
        "PROVIDER_FACTORY",
    ):
        assert not hasattr(module, attr)


def test_no_concrete_provider_module_present() -> None:
    import rop

    root = Path(rop.__file__).resolve().parent
    stems = [path.stem.lower() for path in root.rglob("*.py")]
    for token in _CONCRETE_PROVIDER_TOKENS:
        assert not any(token in stem for stem in stems)
        assert importlib.util.find_spec(f"rop.services.{token}") is None


def test_proposal_audit_module_source_is_clean() -> None:
    import rop.schemas.reasoning_run_stage_7_proposal_audit as schema_module
    import rop.services.reasoning_run_stage_7_proposal_audit as module

    for source in (inspect.getsource(module), inspect.getsource(schema_module)):
        lowered = source.lower()
        for token in _PROHIBITED_SOURCE_TOKENS:
            assert token not in lowered
