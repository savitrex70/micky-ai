"""Task 161: Stage 7 diagnostics health classification tests.

Covers the deterministic diagnostic layer over the completed Stage 7
request/result/audit surfaces. Health states are derived exclusively
from canonical deterministic evidence -- a model's own claim of
confidence can never determine health -- and every transition is
covered independently: READY -> HEALTHY, request/proposal contradiction
or provider failure -> UNHEALTHY, unauditable-but-existing result ->
DEGRADED, absent result -> NO_MATERIAL. The service is read-only,
provider-free, and projects only approved aggregate evidence.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
from collections.abc import Callable, Generator
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
from rop.schemas.reasoning_run_stage_7_diagnostics import (
    ReasoningRunStage7DiagnosticsRead,
)
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
)
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionService,
)
from rop.services.reasoning_run_stage_7_diagnostics import (
    REASONING_RUN_STAGE_7_DIAGNOSTICS_SOURCE_TASK_161,
    ReasoningRunStage7DiagnosticsService,
)
from rop.services.reasoning_run_stage_7_dispatch import (
    ReasoningRunStage7DispatchService,
)
from rop.services.reasoning_run_stage_7_proposal import (
    ReasoningRunStage7ProposalService,
)
from rop.services.reasoning_run_stage_7_proposal_audit import (
    ReasoningRunStage7ProposalAuditService,
)
from rop.services.reasoning_run_stage_7_request import (
    ReasoningRunStage7RequestService,
)
from rop.services.reasoning_run_stage_7_request_audit import (
    ReasoningRunStage7RequestAuditService,
)
from rop.services.reasoning_run_stage_7_result import (
    ReasoningRunStage7ResultService,
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

DIAGNOSTICS_KEYS = {
    "session_id",
    "result_status",
    "proposal_status",
    "diagnostics_status",
    "available",
    "finding_count",
    "findings",
    "source",
}

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
            "metadata": {"source": "stage-7-diagnostics-test"},
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


def _audit_request(db: Session, package: object) -> dict:
    service = ReasoningRunStage7RequestAuditService(
        admission_service=ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("CERTIFIED")
        )
    )
    return service.audit(db, package)


def _valid_model_output(context: dict, explanation: str = "") -> str:
    text = explanation or "insufficient evidence to decide"
    assessments = [
        {
            "candidate_id": str(candidate.id),
            "assessment": "UNCLEAR",
            "supporting_evidence_ids": [],
            "contradicting_evidence_ids": [],
            "unresolved_information_ids": [],
            "explanation": text,
            "uncertainty_flags": ["insufficient_evidence"],
        }
        for candidate in context["candidate_state"]
    ]
    return json.dumps({"candidate_assessments": assessments})


def _confident_model_output(context: dict) -> str:
    """A model claim of certainty backed by real recorded evidence."""
    observation_ids = [str(observation.id) for observation in context["observations"]]
    assessments = [
        {
            "candidate_id": str(candidate.id),
            "assessment": "SUPPORTS",
            "supporting_evidence_ids": list(observation_ids),
            "contradicting_evidence_ids": [],
            "unresolved_information_ids": [],
            "explanation": "confident determination from recorded evidence",
            "uncertainty_flags": [],
        }
        for candidate in context["candidate_state"]
    ]
    return json.dumps({"candidate_assessments": assessments})


def _response(text: str) -> LLMReasoningProviderResponse:
    return LLMReasoningProviderResponse(
        provider="fake-provider", model="fake-model", text=text
    )


def _healthy_material(
    db: Session, sid: str, text_builder: Callable[[dict], str] | None = None
) -> tuple[dict, dict, dict, dict, dict, object]:
    context = _context(db, sid)
    provider = _FakeProvider()
    text = (
        _valid_model_output(context) if text_builder is None else text_builder(context)
    )
    provider.response = _response(text)
    package = _build_package(db, sid)
    request_audit = _audit_request(db, package)
    assert request_audit["request_audit_status"] == "CONSISTENT"
    dispatch = ReasoningRunStage7DispatchService(provider=provider).dispatch(
        request=package, request_audit=request_audit
    )
    assert dispatch["dispatch_status"] == "DISPATCHED"
    proposal_result = ReasoningRunStage7ProposalService().build(
        dispatch_result=dispatch, context=context
    )
    assert proposal_result["proposal_status"] == "VALIDATED"
    proposal_audit = ReasoningRunStage7ProposalAuditService.audit(
        proposal_result=proposal_result, context=context
    )
    assert proposal_audit["proposal_audit_status"] == "CONSISTENT"
    return package, request_audit, proposal_result, proposal_audit, context, provider


def _outage_material(db: Session, sid: str) -> tuple[dict, dict, dict, dict]:
    context = _context(db, sid)
    provider = _FailingProvider(
        LLMReasoningProviderError("connection to model host failed")
    )
    package = _build_package(db, sid)
    request_audit = _audit_request(db, package)
    dispatch = ReasoningRunStage7DispatchService(provider=provider).dispatch(
        request=package, request_audit=request_audit
    )
    assert dispatch["dispatch_status"] == "UNAVAILABLE"
    assert dispatch["outcome"] == "MODEL_UNAVAILABLE"
    proposal_result = ReasoningRunStage7ProposalService().build(
        dispatch_result=dispatch, context=context
    )
    assert proposal_result["proposal_status"] == "MODEL_UNAVAILABLE"
    proposal_audit = ReasoningRunStage7ProposalAuditService.audit(
        proposal_result=proposal_result, context=context
    )
    assert proposal_audit["proposal_audit_status"] == "UNAVAILABLE"
    return package, request_audit, proposal_result, proposal_audit


def _model_failure_material(
    db: Session, sid: str, error: Exception
) -> tuple[dict, dict, dict, dict]:
    context = _context(db, sid)
    provider = _FailingProvider(error)
    package = _build_package(db, sid)
    request_audit = _audit_request(db, package)
    dispatch = ReasoningRunStage7DispatchService(provider=provider).dispatch(
        request=package, request_audit=request_audit
    )
    proposal_result = ReasoningRunStage7ProposalService().build(
        dispatch_result=dispatch, context=context
    )
    proposal_audit = ReasoningRunStage7ProposalAuditService.audit(
        proposal_result=proposal_result, context=context
    )
    return package, request_audit, proposal_result, proposal_audit


def _diagnose(
    package: object = None,
    request_audit: object = None,
    proposal_result: object = None,
    proposal_audit: object = None,
) -> dict:
    return ReasoningRunStage7DiagnosticsService.diagnose(
        request_package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
    )


def _table_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f"SELECT COUNT(*) FROM {table.name}")
            ).scalar_one()
            for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
        }


# ---------------------------------------------------------------------------
# HEALTHY: fully audited valid proposal
# ---------------------------------------------------------------------------


def test_fully_audited_valid_proposal_is_healthy() -> None:
    sid = _seed_full_session("Task 161 healthy diagnostics")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, provider = (
            _healthy_material(db, sid)
        )
        result = _diagnose(package, request_audit, proposal_result, proposal_audit)

    assert set(result) == DIAGNOSTICS_KEYS
    assert result["diagnostics_status"] == "HEALTHY"
    assert result["available"] is True
    assert result["session_id"] == sid
    assert result["result_status"] == "READY"
    assert result["proposal_status"] == "VALIDATED"
    assert result["finding_count"] == 0
    assert result["findings"] == []
    assert result["source"] == REASONING_RUN_STAGE_7_DIAGNOSTICS_SOURCE_TASK_161
    assert len(provider.calls) == 1


# ---------------------------------------------------------------------------
# Model confidence never determines health
# ---------------------------------------------------------------------------


def test_confident_claim_with_valid_provenance_is_healthy() -> None:
    sid = _seed_full_session("Task 161 confident valid provenance")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid, text_builder=_confident_model_output)
        )
        result = _diagnose(package, request_audit, proposal_result, proposal_audit)

    assert result["diagnostics_status"] == "HEALTHY"
    assert result["result_status"] == "READY"
    assert result["findings"] == []


def test_confident_claim_with_invalid_provenance_is_unhealthy() -> None:
    sid = _seed_full_session("Task 161 confident invalid provenance")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, _, context, _ = _healthy_material(
            db, sid, text_builder=_confident_model_output
        )
        tampered = copy.deepcopy(proposal_result)
        tampered["proposal"]["candidate_assessments"][0]["candidate_id"] = str(uuid4())
        inconsistent_audit = ReasoningRunStage7ProposalAuditService.audit(
            proposal_result=tampered, context=context
        )
        assert inconsistent_audit["proposal_audit_status"] == "INCONSISTENT"
        result = _diagnose(package, request_audit, tampered, inconsistent_audit)

    assert result["diagnostics_status"] == "UNHEALTHY"
    assert result["available"] is True
    assert result["result_status"] == "INCONSISTENT"
    assert result["proposal_status"] == "VALIDATED"
    assert result["session_id"] == sid
    assert "unknown_candidate_id" in result["findings"]


# ---------------------------------------------------------------------------
# DEGRADED: valid result exists but canonical provenance is unavailable
# ---------------------------------------------------------------------------


def test_canonical_audit_unavailable_is_degraded() -> None:
    sid = _seed_full_session("Task 161 degraded provenance")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )
        missing_proposal_audit = _diagnose(
            package, request_audit, proposal_result, None
        )
        missing_request_audit = _diagnose(
            package, None, proposal_result, proposal_audit
        )
        unavailable_proposal_audit = ReasoningRunStage7ProposalAuditService.audit(
            proposal_result=proposal_result, context=None
        )
        assert unavailable_proposal_audit["proposal_audit_status"] == "UNAVAILABLE"
        unauditable = _diagnose(
            package, request_audit, proposal_result, unavailable_proposal_audit
        )

    for result, marker in (
        (missing_proposal_audit, "PROPOSAL_AUDIT_MISSING"),
        (missing_request_audit, "REQUEST_AUDIT_MISSING"),
        (unauditable, "PROPOSAL_AUDIT_UNAVAILABLE"),
    ):
        assert result["diagnostics_status"] == "DEGRADED"
        assert result["available"] is True
        assert result["result_status"] == "UNAVAILABLE"
        assert result["proposal_status"] == "VALIDATED"
        assert result["session_id"] == sid
        assert marker in result["findings"]


# ---------------------------------------------------------------------------
# NO_MATERIAL: no admitted reasoning result exists
# ---------------------------------------------------------------------------


def test_no_material_is_no_material() -> None:
    sid = _seed_full_session("Task 161 no material")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, _, _, _ = _healthy_material(db, sid)
        empty = _diagnose()
        unavailable_proposal = _diagnose(
            package,
            request_audit,
            {
                **copy.deepcopy(proposal_result),
                "proposal_status": "UNAVAILABLE",
                "available": False,
                "proposal": None,
                "context_fingerprint": None,
                "provider": None,
                "model": None,
            },
            None,
        )

    assert empty["diagnostics_status"] == "NO_MATERIAL"
    assert empty["available"] is False
    assert empty["result_status"] == "UNAVAILABLE"
    assert empty["proposal_status"] == "UNAVAILABLE"
    assert empty["session_id"] == ""
    assert empty["findings"] == [
        "PROPOSAL_RESULT_MISSING",
        "REQUEST_AUDIT_MISSING",
        "REQUEST_PACKAGE_MISSING",
    ]

    assert unavailable_proposal["diagnostics_status"] == "NO_MATERIAL"
    assert unavailable_proposal["available"] is False
    assert unavailable_proposal["result_status"] == "UNAVAILABLE"
    assert unavailable_proposal["proposal_status"] == "UNAVAILABLE"
    assert unavailable_proposal["findings"] == ["PROPOSAL_UNAVAILABLE"]


# ---------------------------------------------------------------------------
# UNHEALTHY: contradiction or provider failure
# ---------------------------------------------------------------------------


def test_request_contradiction_is_unhealthy() -> None:
    sid = _seed_full_session("Task 161 request contradiction")
    with TestingSessionLocal() as db:
        package, _, proposal_result, proposal_audit, _, _ = _healthy_material(db, sid)
        forged_package = {**copy.deepcopy(package), "context_fingerprint": "0" * 64}
        inconsistent_audit = _audit_request(db, forged_package)
        assert inconsistent_audit["request_audit_status"] == "INCONSISTENT"
        result = _diagnose(package, inconsistent_audit, proposal_result, proposal_audit)

    assert result["diagnostics_status"] == "UNHEALTHY"
    assert result["available"] is True
    assert result["result_status"] == "INCONSISTENT"
    assert result["proposal_status"] == "VALIDATED"
    assert "FINGERPRINT_MISMATCH" in result["findings"]


def test_provider_failure_is_unhealthy() -> None:
    sid = _seed_full_session("Task 161 provider failure")
    with TestingSessionLocal() as db:
        result = _diagnose(*_outage_material(db, sid))

    assert result["diagnostics_status"] == "UNHEALTHY"
    assert result["available"] is True
    assert result["result_status"] == "MODEL_UNAVAILABLE"
    assert result["proposal_status"] == "MODEL_UNAVAILABLE"
    assert result["session_id"] == sid
    assert "PROPOSAL_NOT_VALIDATED:MODEL_UNAVAILABLE" in result["findings"]


def test_model_output_failure_is_unhealthy() -> None:
    cases = (
        (ValueError("invalid json output"), "MODEL_OUTPUT_INVALID"),
        (ValueError("unknown candidate reference"), "MODEL_OUTPUT_INCONSISTENT"),
    )
    sid = _seed_full_session("Task 161 model output failure")
    with TestingSessionLocal() as db:
        for error, expected in cases:
            result = _diagnose(*_model_failure_material(db, sid, error))
            assert result["diagnostics_status"] == "UNHEALTHY"
            assert result["available"] is True
            assert result["result_status"] == "INCONSISTENT"
            assert result["proposal_status"] == expected
            assert f"PROPOSAL_NOT_VALIDATED:{expected}" in result["findings"]


# ---------------------------------------------------------------------------
# Determinism, delegation, and read-only behavior
# ---------------------------------------------------------------------------


def test_diagnostics_are_deterministic() -> None:
    sid = _seed_full_session("Task 161 deterministic")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )
        first = _diagnose(package, request_audit, proposal_result, proposal_audit)
        second = _diagnose(package, request_audit, proposal_result, proposal_audit)
        outage = _outage_material(db, sid)
        third = _diagnose(*outage)
        fourth = _diagnose(*outage)
        empty_first = _diagnose()
        empty_second = _diagnose()

    assert first == second
    assert third == fourth
    assert empty_first == empty_second
    assert first["diagnostics_status"] == "HEALTHY"
    assert third["diagnostics_status"] == "UNHEALTHY"
    assert empty_first["diagnostics_status"] == "NO_MATERIAL"
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_diagnostics_delegate_to_canonical_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _seed_full_session("Task 161 delegation")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )

    calls: list[dict] = []
    original = ReasoningRunStage7ResultService.build

    def _record(*args: object, **kwargs: object) -> dict:
        calls.append(dict(kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(ReasoningRunStage7ResultService, "build", staticmethod(_record))
    result = _diagnose(package, request_audit, proposal_result, proposal_audit)

    assert len(calls) == 1
    assert set(calls[0]) == {
        "request_package",
        "request_audit",
        "proposal_result",
        "proposal_audit",
    }
    assert calls[0]["request_package"] is package
    assert calls[0]["proposal_audit"] is proposal_audit
    assert result["diagnostics_status"] == "HEALTHY"


def test_diagnostics_are_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _seed_full_session("Task 161 read only")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )

    def _no_write(*args: object, **kwargs: object) -> None:
        raise AssertionError("write attempted")

    def _no_rebuild(*args: object, **kwargs: object) -> None:
        raise AssertionError("material service invoked while diagnosing")

    monkeypatch.setattr(Session, "add", _no_write)
    monkeypatch.setattr(Session, "merge", _no_write)
    monkeypatch.setattr(Session, "delete", _no_write)
    monkeypatch.setattr(Session, "commit", _no_write)
    monkeypatch.setattr(ReasoningRunStage7RequestService, "build", _no_rebuild)
    monkeypatch.setattr(ReasoningRunStage7RequestAuditService, "audit", _no_rebuild)
    monkeypatch.setattr(ReasoningRunStage7DispatchService, "dispatch", _no_rebuild)
    monkeypatch.setattr(ReasoningRunStage7ProposalService, "build", _no_rebuild)
    monkeypatch.setattr(ReasoningRunStage7ProposalAuditService, "audit", _no_rebuild)

    counts_before = _table_counts()
    result = _diagnose(package, request_audit, proposal_result, proposal_audit)
    counts_after = _table_counts()

    assert result["diagnostics_status"] == "HEALTHY"
    assert counts_after == counts_before


# ---------------------------------------------------------------------------
# Strict schema
# ---------------------------------------------------------------------------


def _healthy_payload() -> dict:
    return {
        "session_id": "0b8b1f9a-3f1e-4a1c-9c2f-9a5a1f9a3f1e",
        "result_status": "READY",
        "proposal_status": "VALIDATED",
        "diagnostics_status": "HEALTHY",
        "available": True,
        "finding_count": 0,
        "findings": [],
        "source": REASONING_RUN_STAGE_7_DIAGNOSTICS_SOURCE_TASK_161,
    }


def test_diagnostics_schema_is_strict() -> None:
    valid = ReasoningRunStage7DiagnosticsRead.model_validate(_healthy_payload())
    assert valid.diagnostics_status == "HEALTHY"

    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {**_healthy_payload(), "raw_text": "smuggled"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {**_healthy_payload(), "diagnostics_status": "WEIRD"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {
                **_healthy_payload(),
                "result_status": "INCONSISTENT",
                "findings": ["FINGERPRINT_MISMATCH"],
                "finding_count": 1,
            }
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {
                **_healthy_payload(),
                "findings": ["PROPOSAL_AUDIT_MISSING"],
                "finding_count": 1,
            }
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {**_healthy_payload(), "available": False}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {**_healthy_payload(), "finding_count": 3}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {**_healthy_payload(), "findings": ["b", "a"], "finding_count": 2}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {**_healthy_payload(), "findings": ["a", "a"], "finding_count": 2}
        )

    degraded = ReasoningRunStage7DiagnosticsRead.model_validate(
        {
            **_healthy_payload(),
            "result_status": "UNAVAILABLE",
            "diagnostics_status": "DEGRADED",
            "findings": ["PROPOSAL_AUDIT_MISSING"],
            "finding_count": 1,
        }
    )
    assert degraded.diagnostics_status == "DEGRADED"

    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {
                **_healthy_payload(),
                "diagnostics_status": "DEGRADED",
                "findings": ["PROPOSAL_AUDIT_MISSING"],
                "finding_count": 1,
            }
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {
                **_healthy_payload(),
                "proposal_status": "UNAVAILABLE",
                "result_status": "UNAVAILABLE",
                "diagnostics_status": "DEGRADED",
                "findings": ["PROPOSAL_AUDIT_MISSING"],
                "finding_count": 1,
            }
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {
                **_healthy_payload(),
                "result_status": "UNAVAILABLE",
                "diagnostics_status": "DEGRADED",
                "available": False,
                "findings": ["PROPOSAL_AUDIT_MISSING"],
                "finding_count": 1,
            }
        )

    unhealthy = ReasoningRunStage7DiagnosticsRead.model_validate(
        {
            **_healthy_payload(),
            "result_status": "INCONSISTENT",
            "diagnostics_status": "UNHEALTHY",
            "findings": ["FINGERPRINT_MISMATCH"],
            "finding_count": 1,
        }
    )
    assert unhealthy.diagnostics_status == "UNHEALTHY"

    model_unavailable = ReasoningRunStage7DiagnosticsRead.model_validate(
        {
            **_healthy_payload(),
            "result_status": "MODEL_UNAVAILABLE",
            "proposal_status": "MODEL_UNAVAILABLE",
            "diagnostics_status": "UNHEALTHY",
            "findings": ["PROPOSAL_NOT_VALIDATED:MODEL_UNAVAILABLE"],
            "finding_count": 1,
        }
    )
    assert model_unavailable.diagnostics_status == "UNHEALTHY"

    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {**_healthy_payload(), "diagnostics_status": "UNHEALTHY"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {
                **_healthy_payload(),
                "result_status": "UNAVAILABLE",
                "proposal_status": "UNAVAILABLE",
                "diagnostics_status": "UNHEALTHY",
                "findings": ["REQUEST_AUDIT_MISSING"],
                "finding_count": 1,
            }
        )

    no_material = ReasoningRunStage7DiagnosticsRead.model_validate(
        {
            **_healthy_payload(),
            "result_status": "UNAVAILABLE",
            "proposal_status": "UNAVAILABLE",
            "diagnostics_status": "NO_MATERIAL",
            "available": False,
            "findings": ["REQUEST_PACKAGE_MISSING"],
            "finding_count": 1,
        }
    )
    assert no_material.diagnostics_status == "NO_MATERIAL"

    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {
                **_healthy_payload(),
                "result_status": "UNAVAILABLE",
                "proposal_status": "VALIDATED",
                "diagnostics_status": "NO_MATERIAL",
                "available": False,
                "findings": ["REQUEST_PACKAGE_MISSING"],
                "finding_count": 1,
            }
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {
                **_healthy_payload(),
                "diagnostics_status": "NO_MATERIAL",
                "available": False,
                "findings": ["REQUEST_PACKAGE_MISSING"],
                "finding_count": 1,
            }
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DiagnosticsRead.model_validate(
            {
                **_healthy_payload(),
                "result_status": "UNAVAILABLE",
                "proposal_status": "UNAVAILABLE",
                "diagnostics_status": "NO_MATERIAL",
                "available": True,
                "findings": ["REQUEST_PACKAGE_MISSING"],
                "finding_count": 1,
            }
        )


# ---------------------------------------------------------------------------
# Boundary shape: material-only, provider-free, source-clean
# ---------------------------------------------------------------------------


def test_diagnostics_service_accepts_only_material() -> None:
    signature = inspect.signature(ReasoningRunStage7DiagnosticsService.diagnose)
    parameters = signature.parameters
    assert set(parameters) == {
        "request_package",
        "request_audit",
        "proposal_result",
        "proposal_audit",
    }
    for parameter in parameters.values():
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    import rop.services.reasoning_run_stage_7_diagnostics as service_module

    for name in dir(service_module):
        if name.startswith("PROVIDER_"):
            raise AssertionError(f"provider-specific module attribute: {name}")


def test_diagnostics_module_source_is_clean() -> None:
    root = Path(__file__).resolve().parents[1]
    modules = (
        root / "src" / "rop" / "services" / "reasoning_run_stage_7_diagnostics.py",
        root / "src" / "rop" / "schemas" / "reasoning_run_stage_7_diagnostics.py",
    )
    for module_path in modules:
        source = module_path.read_text(encoding="utf-8")
        lowered = source.lower()
        for token in _PROHIBITED_SOURCE_TOKENS:
            assert token not in lowered, f"{module_path.name}: {token}"
        spec = importlib.util.spec_from_file_location(
            f"source_scan_{module_path.stem}", module_path
        )
        assert spec is not None
