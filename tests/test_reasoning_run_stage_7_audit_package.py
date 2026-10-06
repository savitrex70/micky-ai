"""Task 162: Stage 7 deterministic audit package tests.

Covers the single deterministic audit package assembled from the
completed Stage 7 evidence surfaces: the Task 154 admission verdict,
the Task 155 request package, the Task 156 request audit, the Task 158
validated proposal, the Task 159 proposal audit, and the Task 161
diagnostics health. The package is a strict, read-only, session-
isolated projection: canonical statuses are carried verbatim, child
findings are harvested without re-deriving any verdict, raw provider
text can never appear, no write and no provider call is possible, and
repeated assembly over identical material is byte-identical.
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
from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
)
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionService,
)
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
    ReasoningRunStage7AuditPackageService,
)
from rop.services.reasoning_run_stage_7_diagnostics import (
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

AUDIT_PACKAGE_KEYS = {
    "session_id",
    "admission_status",
    "request_fingerprint",
    "request_audit_status",
    "proposal_audit_status",
    "diagnostics_status",
    "provider_name",
    "model_name",
    "finding_count",
    "findings",
    "audit_source",
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
            "metadata": {"source": "stage-7-audit-package-test"},
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


def _admission(db: Session, sid: str) -> dict:
    service = ReasoningRunStage7AdmissionService(
        certification_service=_CertificationStub("CERTIFIED")
    )
    admission = service.evaluate(db, UUID(sid))
    assert admission["admission_status"] == "ADMITTED"
    return admission


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


def _package(
    admission: object = None,
    package: object = None,
    request_audit: object = None,
    proposal_result: object = None,
    proposal_audit: object = None,
    diagnostics: object = None,
) -> dict:
    return ReasoningRunStage7AuditPackageService.build(
        admission_result=admission,
        request_package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
        diagnostics_result=diagnostics,
    )


def _table_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f"SELECT COUNT(*) FROM {table.name}")
            ).scalar_one()
            for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
        }


def _healthy_package_payload() -> dict:
    return {
        "session_id": "0b8b1f9a-3f1e-4a1c-9c2f-9a5a1f9a3f1e",
        "admission_status": "ADMITTED",
        "request_fingerprint": "a" * 64,
        "request_audit_status": "CONSISTENT",
        "proposal_audit_status": "CONSISTENT",
        "diagnostics_status": "HEALTHY",
        "provider_name": "fake-provider",
        "model_name": "fake-model",
        "finding_count": 0,
        "findings": [],
        "audit_source": REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
    }


# ---------------------------------------------------------------------------
# Healthy: the full canonical slice with every piece of evidence present
# ---------------------------------------------------------------------------


def test_healthy_slice_is_healthy_package() -> None:
    sid = _seed_full_session("Task 162 healthy package")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, provider = (
            _healthy_material(db, sid)
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        result = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    assert set(result) == AUDIT_PACKAGE_KEYS
    assert result["session_id"] == sid
    assert result["admission_status"] == "ADMITTED"
    assert result["request_fingerprint"] == package["context_fingerprint"]
    assert result["request_audit_status"] == "CONSISTENT"
    assert result["proposal_audit_status"] == "CONSISTENT"
    assert result["diagnostics_status"] == "HEALTHY"
    assert result["provider_name"] == "fake-provider"
    assert result["model_name"] == "fake-model"
    assert result["finding_count"] == 0
    assert result["findings"] == []
    assert result["audit_source"] == REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162
    assert len(provider.calls) == 1


# ---------------------------------------------------------------------------
# Invalid request provenance is reported, never concealed
# ---------------------------------------------------------------------------


def test_invalid_request_is_reported() -> None:
    sid = _seed_full_session("Task 162 request contradiction")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, _, proposal_result, proposal_audit, _, _ = _healthy_material(db, sid)
        forged_package = {**copy.deepcopy(package), "context_fingerprint": "0" * 64}
        inconsistent_audit = _audit_request(db, forged_package)
        assert inconsistent_audit["request_audit_status"] == "INCONSISTENT"
        diagnostics = _diagnose(
            package, inconsistent_audit, proposal_result, proposal_audit
        )
        result = _package(
            admission=admission,
            package=package,
            request_audit=inconsistent_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    assert result["diagnostics_status"] == "UNHEALTHY"
    assert result["request_audit_status"] == "INCONSISTENT"
    assert result["proposal_audit_status"] == "CONSISTENT"
    assert result["request_fingerprint"] == package["context_fingerprint"]
    assert result["session_id"] == sid
    assert "FINGERPRINT_MISMATCH" in result["findings"]


# ---------------------------------------------------------------------------
# Invalid proposal provenance is reported, never concealed
# ---------------------------------------------------------------------------


def test_invalid_proposal_is_reported() -> None:
    sid = _seed_full_session("Task 162 proposal contradiction")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, _, context, _ = _healthy_material(
            db, sid
        )
        tampered = copy.deepcopy(proposal_result)
        tampered["proposal"]["candidate_assessments"][0]["candidate_id"] = str(uuid4())
        inconsistent_audit = ReasoningRunStage7ProposalAuditService.audit(
            proposal_result=tampered, context=context
        )
        assert inconsistent_audit["proposal_audit_status"] == "INCONSISTENT"
        diagnostics = _diagnose(package, request_audit, tampered, inconsistent_audit)
        result = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=tampered,
            proposal_audit=inconsistent_audit,
            diagnostics=diagnostics,
        )

    assert result["diagnostics_status"] == "UNHEALTHY"
    assert result["proposal_audit_status"] == "INCONSISTENT"
    assert result["provider_name"] == "fake-provider"
    assert "unknown_candidate_id" in result["findings"]


# ---------------------------------------------------------------------------
# Provider outage and degraded provenance
# ---------------------------------------------------------------------------


def test_provider_unavailable_is_reported() -> None:
    sid = _seed_full_session("Task 162 provider unavailable")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit = _outage_material(
            db, sid
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        result = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    assert result["diagnostics_status"] == "UNHEALTHY"
    assert result["provider_name"] is None
    assert result["model_name"] is None
    assert result["proposal_audit_status"] == "UNAVAILABLE"
    assert "PROPOSAL_NOT_VALIDATED:MODEL_UNAVAILABLE" in result["findings"]


def test_degraded_provenance_is_reported() -> None:
    sid = _seed_full_session("Task 162 degraded provenance")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )
        missing_request_audit = _package(
            admission=admission,
            package=package,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=_diagnose(package, None, proposal_result, proposal_audit),
        )
        missing_proposal_audit = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            diagnostics=_diagnose(package, request_audit, proposal_result, None),
        )

    assert missing_request_audit["diagnostics_status"] == "DEGRADED"
    assert missing_request_audit["request_audit_status"] is None
    assert "REQUEST_AUDIT_MISSING" in missing_request_audit["findings"]

    assert missing_proposal_audit["diagnostics_status"] == "DEGRADED"
    assert missing_proposal_audit["proposal_audit_status"] is None
    assert "PROPOSAL_AUDIT_MISSING" in missing_proposal_audit["findings"]


# ---------------------------------------------------------------------------
# No material at all is no material
# ---------------------------------------------------------------------------


def test_empty_material_is_no_material() -> None:
    empty = _package()
    diagnostics_only = _package(diagnostics=_diagnose())

    assert empty["diagnostics_status"] == "NO_MATERIAL"
    assert empty["session_id"] == ""
    assert empty["admission_status"] is None
    assert empty["request_fingerprint"] is None
    assert empty["request_audit_status"] is None
    assert empty["proposal_audit_status"] is None
    assert empty["provider_name"] is None
    assert empty["model_name"] is None
    assert empty["finding_count"] == 2
    assert empty["findings"] == ["ADMISSION_MISSING", "DIAGNOSTICS_MISSING"]

    assert diagnostics_only["diagnostics_status"] == "NO_MATERIAL"
    assert diagnostics_only["session_id"] == ""
    assert diagnostics_only["findings"] == [
        "ADMISSION_MISSING",
        "PROPOSAL_RESULT_MISSING",
        "REQUEST_AUDIT_MISSING",
        "REQUEST_PACKAGE_MISSING",
    ]


# ---------------------------------------------------------------------------
# Session isolation and determinism
# ---------------------------------------------------------------------------


def test_session_isolation() -> None:
    sid_a = _seed_full_session("Task 162 session isolation A")
    sid_b = _seed_full_session("Task 162 session isolation B")
    with TestingSessionLocal() as db:
        admission_a = _admission(db, sid_a)
        admission_b = _admission(db, sid_b)
        material_a = _healthy_material(db, sid_a)
        material_b = _healthy_material(db, sid_b)
        result_a = _package(
            admission=admission_a,
            package=material_a[0],
            request_audit=material_a[1],
            proposal_result=material_a[2],
            proposal_audit=material_a[3],
            diagnostics=_diagnose(*material_a[:4]),
        )
        result_b = _package(
            admission=admission_b,
            package=material_b[0],
            request_audit=material_b[1],
            proposal_result=material_b[2],
            proposal_audit=material_b[3],
            diagnostics=_diagnose(*material_b[:4]),
        )
        crossed = _package(
            admission=admission_b,
            package=material_a[0],
            request_audit=material_a[1],
            proposal_result=material_a[2],
            proposal_audit=material_a[3],
            diagnostics=_diagnose(*material_a[:4]),
        )

    assert result_a["session_id"] == sid_a
    assert result_b["session_id"] == sid_b
    assert sid_b not in json.dumps(result_a)
    assert sid_a not in json.dumps(result_b)
    assert crossed["session_id"] == ""
    assert "SESSION_MISMATCH" in crossed["findings"]


def test_repeated_calls_are_identical() -> None:
    sid = _seed_full_session("Task 162 repeated calls")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        materials = {
            "admission": admission,
            "package": package,
            "request_audit": request_audit,
            "proposal_result": proposal_result,
            "proposal_audit": proposal_audit,
            "diagnostics": diagnostics,
        }
        first = _package(**materials)
        second = _package(**copy.deepcopy(materials))

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# Read-only, provider-free inspection
# ---------------------------------------------------------------------------


def test_package_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _seed_full_session("Task 162 read only")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)

    def _no_write(*args: object, **kwargs: object) -> None:
        raise AssertionError("write attempted")

    def _no_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("service invoked while packaging")

    monkeypatch.setattr(Session, "add", _no_write)
    monkeypatch.setattr(Session, "merge", _no_write)
    monkeypatch.setattr(Session, "delete", _no_write)
    monkeypatch.setattr(Session, "commit", _no_write)
    monkeypatch.setattr(ReasoningRunStage7AdmissionService, "evaluate", _no_service)
    monkeypatch.setattr(ReasoningRunStage7RequestService, "build", _no_service)
    monkeypatch.setattr(ReasoningRunStage7RequestAuditService, "audit", _no_service)
    monkeypatch.setattr(ReasoningRunStage7DispatchService, "dispatch", _no_service)
    monkeypatch.setattr(ReasoningRunStage7ProposalService, "build", _no_service)
    monkeypatch.setattr(ReasoningRunStage7ProposalAuditService, "audit", _no_service)
    monkeypatch.setattr(ReasoningRunStage7ResultService, "build", _no_service)
    monkeypatch.setattr(ReasoningRunStage7DiagnosticsService, "diagnose", _no_service)

    counts_before = _table_counts()
    result = _package(
        admission=admission,
        package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
        diagnostics=diagnostics,
    )
    counts_after = _table_counts()

    assert result["diagnostics_status"] == "HEALTHY"
    assert counts_after == counts_before


def test_no_provider_is_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _seed_full_session("Task 162 no provider invocation")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, provider = (
            _healthy_material(db, sid)
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)

    def _no_generate(*args: object, **kwargs: object) -> None:
        raise AssertionError("provider invoked while inspecting a result")

    monkeypatch.setattr(_FakeProvider, "generate_reasoning", _no_generate)
    result = _package(
        admission=admission,
        package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
        diagnostics=diagnostics,
    )

    assert result["diagnostics_status"] == "HEALTHY"
    assert len(provider.calls) == 1


# ---------------------------------------------------------------------------
# No raw provider text in the package
# ---------------------------------------------------------------------------


def test_raw_provider_text_is_never_included() -> None:
    marker = "RAW-LLM-TEXT-MARKER-162"
    sid = _seed_full_session("Task 162 raw provider text")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(
                db,
                sid,
                text_builder=lambda context: _valid_model_output(context, marker),
            )
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        result = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    assert marker in json.dumps(proposal_result)
    assert marker not in json.dumps(result)
    assert "provider_response" not in result


# ---------------------------------------------------------------------------
# Strict schema
# ---------------------------------------------------------------------------


def test_audit_package_schema_is_strict() -> None:
    valid = ReasoningRunStage7AuditPackageRead.model_validate(
        _healthy_package_payload()
    )
    assert valid.diagnostics_status == "HEALTHY"
    assert valid.provider_name == "fake-provider"

    empty = ReasoningRunStage7AuditPackageRead.model_validate(
        {
            **_healthy_package_payload(),
            "session_id": "",
            "admission_status": None,
            "request_fingerprint": None,
            "request_audit_status": None,
            "proposal_audit_status": None,
            "diagnostics_status": "NO_MATERIAL",
            "provider_name": None,
            "model_name": None,
        }
    )
    assert empty.diagnostics_status == "NO_MATERIAL"

    with pytest.raises(ValidationError):
        ReasoningRunStage7AuditPackageRead.model_validate(
            {**_healthy_package_payload(), "raw_provider_text": "smuggled"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7AuditPackageRead.model_validate(
            {**_healthy_package_payload(), "diagnostics_status": "OK"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7AuditPackageRead.model_validate(
            {**_healthy_package_payload(), "admission_status": "MAYBE"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7AuditPackageRead.model_validate(
            {**_healthy_package_payload(), "model_name": None}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7AuditPackageRead.model_validate(
            {**_healthy_package_payload(), "finding_count": 3}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7AuditPackageRead.model_validate(
            {
                **_healthy_package_payload(),
                "findings": ["SESSION_MISMATCH", "SESSION_MISMATCH"],
                "finding_count": 2,
            }
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7AuditPackageRead.model_validate(
            {
                **_healthy_package_payload(),
                "findings": ["SESSION_MISMATCH", "FINGERPRINT_MISMATCH"],
                "finding_count": 2,
            }
        )


# ---------------------------------------------------------------------------
# Boundary shape: material-only, provider-free, source-clean
# ---------------------------------------------------------------------------


def test_audit_package_service_accepts_only_material() -> None:
    signature = inspect.signature(ReasoningRunStage7AuditPackageService.build)
    parameters = signature.parameters
    assert set(parameters) == {
        "admission_result",
        "request_package",
        "request_audit",
        "proposal_result",
        "proposal_audit",
        "diagnostics_result",
    }
    for parameter in parameters.values():
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is None

    import rop.services.reasoning_run_stage_7_audit_package as service_module

    for name in dir(service_module):
        if name.startswith("PROVIDER_"):
            raise AssertionError(f"provider-specific module attribute: {name}")


def test_audit_package_module_source_is_clean() -> None:
    root = Path(__file__).resolve().parents[1]
    modules = (
        root / "src" / "rop" / "services" / "reasoning_run_stage_7_audit_package.py",
        root / "src" / "rop" / "schemas" / "reasoning_run_stage_7_audit_package.py",
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
