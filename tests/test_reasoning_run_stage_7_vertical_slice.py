"""Task 163: Stage 7 provider-agnostic vertical-slice gate tests.

First end-to-end deterministic certification of the Stage 7
provider-agnostic path built by Tasks 154-162, exercised through the
test-only fake provider: admission, request package, request audit,
explicit provider dispatch, response validation, proposal audit,
diagnostics, and the deterministic audit package are certified into
exactly one vertical-slice verdict. The gate is read-only,
deterministic, session-isolated, and provider-neutral: no network, no
concrete provider module, no API key, no raw provider text, and no
claim that a real model has been integrated.
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
from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
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
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
    ReasoningRunStage7VerticalSliceService,
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

VERTICAL_SLICE_KEYS = {
    "session_id",
    "slice_status",
    "admission_status",
    "diagnostics_status",
    "provider_name",
    "model_name",
    "finding_count",
    "findings",
    "certification_source",
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
            "metadata": {"source": "stage-7-vertical-slice-test"},
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


def _certify(package: object = None) -> dict:
    return ReasoningRunStage7VerticalSliceService.certify(audit_package=package)


def _table_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f"SELECT COUNT(*) FROM {table.name}")
            ).scalar_one()
            for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
        }


def _ready_slice_payload() -> dict:
    return {
        "session_id": "0b8b1f9a-3f1e-4a1c-9c2f-9a5a1f9a3f1e",
        "slice_status": "READY",
        "admission_status": "ADMITTED",
        "diagnostics_status": "HEALTHY",
        "provider_name": "fake-provider",
        "model_name": "fake-model",
        "finding_count": 0,
        "findings": [],
        "certification_source": REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
    }


# ---------------------------------------------------------------------------
# The canonical path certifies READY end to end
# ---------------------------------------------------------------------------


def test_healthy_vertical_slice_is_ready() -> None:
    sid = _seed_full_session("Task 163 healthy slice")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, provider = (
            _healthy_material(db, sid)
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        audit_package = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    verdict = _certify(audit_package)

    assert set(verdict) == VERTICAL_SLICE_KEYS
    assert verdict["slice_status"] == "READY"
    assert verdict["session_id"] == sid
    assert verdict["admission_status"] == "ADMITTED"
    assert verdict["diagnostics_status"] == "HEALTHY"
    assert verdict["provider_name"] == "fake-provider"
    assert verdict["model_name"] == "fake-model"
    assert verdict["finding_count"] == 0
    assert verdict["findings"] == []
    assert (
        verdict["certification_source"]
        == REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163
    )
    assert len(provider.calls) == 1


def test_stage_6_certification_is_required() -> None:
    sid = _seed_full_session("Task 163 stage 6 required")
    with TestingSessionLocal() as db:
        admission = ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("UNVERIFIABLE")
        ).evaluate(db, UUID(sid))
        assert admission["admission_status"] == "BLOCKED"

        package = ReasoningRunStage7RequestService(
            admission_service=ReasoningRunStage7AdmissionService(
                certification_service=_CertificationStub("UNVERIFIABLE")
            )
        ).build(db, UUID(sid))
        assert package["request_status"] == "BLOCKED"

        request_audit = ReasoningRunStage7RequestAuditService(
            admission_service=ReasoningRunStage7AdmissionService(
                certification_service=_CertificationStub("UNVERIFIABLE")
            )
        ).audit(db, package)
        assert request_audit["request_audit_status"] == "UNAVAILABLE"

        provider = _FakeProvider()
        dispatch = ReasoningRunStage7DispatchService(provider=provider).dispatch(
            request=package, request_audit=request_audit
        )
        assert dispatch["dispatch_status"] == "BLOCKED"
        assert provider.calls == []

        context = _context(db, sid)
        proposal_result = ReasoningRunStage7ProposalService().build(
            dispatch_result=dispatch, context=context
        )
        proposal_audit = ReasoningRunStage7ProposalAuditService.audit(
            proposal_result=proposal_result, context=context
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        audit_package = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    verdict = _certify(audit_package)

    assert verdict["slice_status"] == "BLOCKED"
    assert verdict["admission_status"] == "BLOCKED"
    assert verdict["diagnostics_status"] == "NO_MATERIAL"
    assert "STAGE_6_CERTIFICATION_NOT_CERTIFIED:UNVERIFIABLE" in verdict["findings"]
    assert "REQUEST_NOT_PACKAGED:BLOCKED" in verdict["findings"]


# ---------------------------------------------------------------------------
# Admission material is required for any READY claim
# ---------------------------------------------------------------------------


def test_admission_material_is_required() -> None:
    sid = _seed_full_session("Task 163 admission required")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        audit_package = _package(
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    verdict = _certify(audit_package)

    assert verdict["slice_status"] == "UNAVAILABLE"
    assert verdict["admission_status"] is None
    assert "ADMISSION_MISSING" in verdict["findings"]


# ---------------------------------------------------------------------------
# Provider failures and invalid model output block, never certify
# ---------------------------------------------------------------------------


def test_provider_unavailable_is_blocked() -> None:
    sid = _seed_full_session("Task 163 provider unavailable")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit = _outage_material(
            db, sid
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        audit_package = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    verdict = _certify(audit_package)

    assert verdict["slice_status"] == "BLOCKED"
    assert verdict["diagnostics_status"] == "UNHEALTHY"
    assert verdict["provider_name"] is None
    assert verdict["model_name"] is None
    assert "PROPOSAL_NOT_VALIDATED:MODEL_UNAVAILABLE" in verdict["findings"]


def test_invalid_model_output_is_blocked() -> None:
    cases = (
        (ValueError("invalid json output"), "MODEL_OUTPUT_INVALID"),
        (ValueError("unknown candidate reference"), "MODEL_OUTPUT_INCONSISTENT"),
    )
    sid = _seed_full_session("Task 163 invalid model output")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        for error, expected in cases:
            package, request_audit, proposal_result, proposal_audit = (
                _model_failure_material(db, sid, error)
            )
            assert proposal_result["proposal_status"] == expected
            diagnostics = _diagnose(
                package, request_audit, proposal_result, proposal_audit
            )
            audit_package = _package(
                admission=admission,
                package=package,
                request_audit=request_audit,
                proposal_result=proposal_result,
                proposal_audit=proposal_audit,
                diagnostics=diagnostics,
            )
            verdict = _certify(audit_package)
            assert verdict["slice_status"] == "BLOCKED"
            assert f"PROPOSAL_NOT_VALIDATED:{expected}" in verdict["findings"]


# ---------------------------------------------------------------------------
# Contradictory request and proposal provenance block, never certify
# ---------------------------------------------------------------------------


def test_request_contradiction_is_blocked() -> None:
    sid = _seed_full_session("Task 163 request contradiction")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, _, proposal_result, proposal_audit, _, _ = _healthy_material(db, sid)
        forged_package = {**copy.deepcopy(package), "context_fingerprint": "0" * 64}
        inconsistent_audit = _audit_request(db, forged_package)
        assert inconsistent_audit["request_audit_status"] == "INCONSISTENT"
        diagnostics = _diagnose(
            package, inconsistent_audit, proposal_result, proposal_audit
        )
        audit_package = _package(
            admission=admission,
            package=package,
            request_audit=inconsistent_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    verdict = _certify(audit_package)

    assert verdict["slice_status"] == "BLOCKED"
    assert verdict["diagnostics_status"] == "UNHEALTHY"
    assert "FINGERPRINT_MISMATCH" in verdict["findings"]


def test_proposal_contradiction_is_blocked() -> None:
    sid = _seed_full_session("Task 163 proposal contradiction")
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
        audit_package = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=tampered,
            proposal_audit=inconsistent_audit,
            diagnostics=diagnostics,
        )

    verdict = _certify(audit_package)

    assert verdict["slice_status"] == "BLOCKED"
    assert verdict["provider_name"] == "fake-provider"
    assert "unknown_candidate_id" in verdict["findings"]


# ---------------------------------------------------------------------------
# Missing audit material is UNAVAILABLE, never a fabricated verdict
# ---------------------------------------------------------------------------


def test_degraded_provenance_is_unavailable() -> None:
    sid = _seed_full_session("Task 163 degraded provenance")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )
        degraded = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            diagnostics=_diagnose(package, request_audit, proposal_result, None),
        )

    verdict = _certify(degraded)

    assert verdict["slice_status"] == "UNAVAILABLE"
    assert verdict["diagnostics_status"] == "DEGRADED"
    assert "PROPOSAL_AUDIT_MISSING" in verdict["findings"]


def test_empty_package_is_unavailable() -> None:
    absent = _certify()
    empty_package = _certify(_package())
    diagnostics_only = _certify(_package(diagnostics=_diagnose()))

    assert absent["slice_status"] == "UNAVAILABLE"
    assert absent["finding_count"] == 1
    assert absent["findings"] == ["AUDIT_PACKAGE_MISSING"]
    assert absent["admission_status"] is None
    assert absent["provider_name"] is None

    assert empty_package["slice_status"] == "UNAVAILABLE"
    assert empty_package["findings"] == ["ADMISSION_MISSING", "DIAGNOSTICS_MISSING"]

    assert diagnostics_only["slice_status"] == "UNAVAILABLE"
    assert diagnostics_only["diagnostics_status"] == "NO_MATERIAL"


# ---------------------------------------------------------------------------
# Session isolation and determinism
# ---------------------------------------------------------------------------


def test_session_isolation() -> None:
    sid_a = _seed_full_session("Task 163 session isolation A")
    sid_b = _seed_full_session("Task 163 session isolation B")
    with TestingSessionLocal() as db:
        admission_a = _admission(db, sid_a)
        admission_b = _admission(db, sid_b)
        material_a = _healthy_material(db, sid_a)
        material_b = _healthy_material(db, sid_b)
        verdict_a = _certify(
            _package(
                admission=admission_a,
                package=material_a[0],
                request_audit=material_a[1],
                proposal_result=material_a[2],
                proposal_audit=material_a[3],
                diagnostics=_diagnose(*material_a[:4]),
            )
        )
        verdict_b = _certify(
            _package(
                admission=admission_b,
                package=material_b[0],
                request_audit=material_b[1],
                proposal_result=material_b[2],
                proposal_audit=material_b[3],
                diagnostics=_diagnose(*material_b[:4]),
            )
        )
        crossed = _certify(
            _package(
                admission=admission_b,
                package=material_a[0],
                request_audit=material_a[1],
                proposal_result=material_a[2],
                proposal_audit=material_a[3],
                diagnostics=_diagnose(*material_a[:4]),
            )
        )

    assert verdict_a["slice_status"] == "READY"
    assert verdict_b["slice_status"] == "READY"
    assert verdict_a["session_id"] == sid_a
    assert verdict_b["session_id"] == sid_b
    assert sid_b not in json.dumps(verdict_a)
    assert sid_a not in json.dumps(verdict_b)
    assert crossed["slice_status"] == "UNAVAILABLE"
    assert crossed["session_id"] == ""
    assert "SESSION_MISMATCH" in crossed["findings"]


def test_repeated_calls_are_identical() -> None:
    sid = _seed_full_session("Task 163 repeated calls")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        healthy = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )
        missing_admission = _package(
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    materials = (healthy, missing_admission, _package(), None)
    for material in materials:
        first = _certify(material)
        second = _certify(copy.deepcopy(material))
        assert first == second
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
        assert set(first) == VERTICAL_SLICE_KEYS


# ---------------------------------------------------------------------------
# Certification is read-only, provider-free inspection
# ---------------------------------------------------------------------------


def test_certify_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _seed_full_session("Task 163 read only")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        audit_package = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    def _no_write(*args: object, **kwargs: object) -> None:
        raise AssertionError("write attempted")

    def _no_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("service invoked while certifying")

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
    monkeypatch.setattr(ReasoningRunStage7AuditPackageService, "build", _no_service)

    counts_before = _table_counts()
    verdict = _certify(audit_package)
    counts_after = _table_counts()

    assert verdict["slice_status"] == "READY"
    assert counts_after == counts_before


def test_no_provider_is_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _seed_full_session("Task 163 no provider invocation")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, provider = (
            _healthy_material(db, sid)
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        audit_package = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    assert len(provider.calls) == 1

    def _no_generate(*args: object, **kwargs: object) -> None:
        raise AssertionError("provider invoked while certifying a slice")

    monkeypatch.setattr(_FakeProvider, "generate_reasoning", _no_generate)
    verdict = _certify(audit_package)

    assert verdict["slice_status"] == "READY"
    assert len(provider.calls) == 1


# ---------------------------------------------------------------------------
# Raw provider text never reaches the certification verdict
# ---------------------------------------------------------------------------


def test_raw_provider_text_is_never_included() -> None:
    marker = "RAW-LLM-TEXT-MARKER-163"
    sid = _seed_full_session("Task 163 raw provider text")
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
        audit_package = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )

    assert proposal_result["proposal_status"] == "VALIDATED"
    assert marker in json.dumps(proposal_result)
    assert marker not in json.dumps(audit_package)
    verdict = _certify(audit_package)
    assert verdict["slice_status"] == "READY"
    assert marker not in json.dumps(verdict)
    assert "provider_response" not in verdict
    assert "raw_provider_text" not in verdict


# ---------------------------------------------------------------------------
# The verdict contract is strict and self-consistent
# ---------------------------------------------------------------------------


def _assert_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7VerticalSliceRead.model_validate(payload)


def test_vertical_slice_schema_is_strict() -> None:
    ready = _ready_slice_payload()
    validated = ReasoningRunStage7VerticalSliceRead.model_validate(ready)
    assert validated.slice_status == "READY"

    blocked = {
        **ready,
        "slice_status": "BLOCKED",
        "diagnostics_status": "UNHEALTHY",
        "provider_name": None,
        "model_name": None,
        "finding_count": 1,
        "findings": ["PROPOSAL_NOT_VALIDATED:MODEL_UNAVAILABLE"],
    }
    assert (
        ReasoningRunStage7VerticalSliceRead.model_validate(blocked).slice_status
        == "BLOCKED"
    )

    unavailable = {
        **ready,
        "session_id": "",
        "slice_status": "UNAVAILABLE",
        "admission_status": None,
        "diagnostics_status": "NO_MATERIAL",
        "provider_name": None,
        "model_name": None,
        "finding_count": 1,
        "findings": ["ADMISSION_MISSING"],
    }
    assert (
        ReasoningRunStage7VerticalSliceRead.model_validate(unavailable).slice_status
        == "UNAVAILABLE"
    )

    _assert_rejected({**ready, "raw_provider_text": "leak"})
    _assert_rejected({**ready, "slice_status": "OK"})
    _assert_rejected({**ready, "admission_status": "UNAVAILABLE"})
    _assert_rejected({**ready, "diagnostics_status": "DEGRADED"})


def test_vertical_slice_schema_rejects_incoherent_states() -> None:
    ready = _ready_slice_payload()
    blocked_base = {
        **ready,
        "slice_status": "BLOCKED",
        "diagnostics_status": "UNHEALTHY",
    }

    _assert_rejected({**ready, "session_id": ""})
    _assert_rejected({**ready, "model_name": None})
    _assert_rejected({**ready, "finding_count": 1, "findings": ["SLICE_NOISE"]})
    _assert_rejected({**ready, "finding_count": 3})
    _assert_rejected({**blocked_base, "finding_count": 2, "findings": ["B", "B"]})
    _assert_rejected({**blocked_base, "finding_count": 2, "findings": ["B", "A"]})


# ---------------------------------------------------------------------------
# Architecture: the boundary stays provider-agnostic
# ---------------------------------------------------------------------------


def test_vertical_slice_service_accepts_only_package() -> None:
    signature = inspect.signature(ReasoningRunStage7VerticalSliceService.certify)
    parameters = signature.parameters
    assert set(parameters) == {"audit_package"}
    assert parameters["audit_package"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["audit_package"].default is None

    import rop.services.reasoning_run_stage_7_vertical_slice as service_module

    for name in dir(service_module):
        if name.startswith("PROVIDER_"):
            raise AssertionError(f"provider-specific module attribute: {name}")


def test_no_concrete_provider_module_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    source_root = root / "src" / "rop"
    provider_module = source_root / "services" / "llm_reasoning_provider.py"
    assert provider_module.is_file()

    for module_path in sorted(source_root.rglob("*.py")):
        name = module_path.stem.lower()
        for token in _CONCRETE_PROVIDER_TOKENS:
            assert token not in name, f"{module_path}: {token}"

    provider_source = provider_module.read_text(encoding="utf-8").lower()
    banned = (
        *_CONCRETE_PROVIDER_TOKENS,
        "httpx",
        "aiohttp",
        "urllib3",
        "requests",
        "socket",
        "api_key",
        "getenv",
        "os.environ",
    )
    for token in banned:
        assert token not in provider_source, token


def test_vertical_slice_module_source_is_clean() -> None:
    root = Path(__file__).resolve().parents[1]
    modules = (
        root / "src" / "rop" / "services" / "reasoning_run_stage_7_vertical_slice.py",
        root / "src" / "rop" / "schemas" / "reasoning_run_stage_7_vertical_slice.py",
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
