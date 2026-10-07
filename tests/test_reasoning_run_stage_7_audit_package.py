"""Task 162: Stage 7 deterministic audit package tests.

Covers the single deterministic audit package assembled from the
completed Stage 7 evidence surfaces: the Task 154 admission verdict,
the Task 155 request package, the Task 156 request audit, the Task 158
validated proposal, the Task 159 proposal audit, and the Task 161
diagnostics health. The package is a strict, read-only, session-isolated
projection: every child mapping must first validate against its own
approved contract before any field is read, so no lone status string,
fingerprint, provider name, session claim, or finding list can be
trusted from an arbitrary mapping. Canonical statuses and findings are
carried verbatim from validated children only, raw provider text can
never appear, no write and no provider call is possible, and repeated
assembly over identical material is byte-identical.
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
from rop.schemas.reasoning_run_stage_7_admission import ReasoningRunStage7AdmissionRead
from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.schemas.reasoning_run_stage_7_diagnostics import (
    ReasoningRunStage7DiagnosticsRead,
)
from rop.schemas.reasoning_run_stage_7_proposal import ReasoningRunStage7ProposalRead
from rop.schemas.reasoning_run_stage_7_proposal_audit import (
    ReasoningRunStage7ProposalAuditRead,
)
from rop.schemas.reasoning_run_stage_7_request import ReasoningRunStage7RequestRead
from rop.schemas.reasoning_run_stage_7_request_audit import (
    ReasoningRunStage7RequestAuditRead,
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


def _blocked_package(package: dict) -> dict:
    """A genuinely coherent Task 155 BLOCKED projection, not a forgery."""
    return {
        **copy.deepcopy(package),
        "request_status": "BLOCKED",
        "available": False,
        "admission_status": "BLOCKED",
        "stage_6_certification_status": "BLOCKED",
        "context_fingerprint": None,
        "payload": None,
    }


def _unavailable_package(package: dict) -> dict:
    """A coherent Task 155 projection that could not package anything."""
    return {
        **copy.deepcopy(package),
        "request_status": "UNAVAILABLE",
        "available": False,
        "admission_status": "UNAVAILABLE",
        "stage_6_certification_status": "UNAVAILABLE",
        "context_fingerprint": None,
        "payload": None,
    }


def _unavailable_proposal(proposal: dict) -> dict:
    """A coherent Task 158 projection carrying no proposal at all."""
    return {
        **copy.deepcopy(proposal),
        "proposal_status": "UNAVAILABLE",
        "available": False,
        "context_fingerprint": None,
        "provider": None,
        "model": None,
        "proposal": None,
    }


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
    # Every child contract is validated independently, so every absent
    # child is named. Nothing is silently treated as merely unusable.
    assert empty["finding_count"] == 6
    assert empty["findings"] == [
        "ADMISSION_MISSING",
        "DIAGNOSTICS_MISSING",
        "PROPOSAL_AUDIT_MISSING",
        "PROPOSAL_RESULT_MISSING",
        "REQUEST_AUDIT_MISSING",
        "REQUEST_PACKAGE_MISSING",
    ]

    assert diagnostics_only["diagnostics_status"] == "NO_MATERIAL"
    assert diagnostics_only["session_id"] == ""
    # The validated Task 161 verdict's own missing-material findings and
    # this service's structural markers name the same absences, so the
    # union keeps one marker per absence without dropping either.
    assert diagnostics_only["findings"] == [
        "ADMISSION_MISSING",
        "PROPOSAL_AUDIT_MISSING",
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


def _healthy_six(db: Session, sid: str) -> dict:
    """The six genuine child mappings for one fully audited interaction."""
    package, request_audit, proposal_result, proposal_audit, _, _ = _healthy_material(
        db, sid
    )
    return {
        "admission": _admission(db, sid),
        "package": package,
        "request_audit": request_audit,
        "proposal_result": proposal_result,
        "proposal_audit": proposal_audit,
        "diagnostics": _diagnose(
            package, request_audit, proposal_result, proposal_audit
        ),
    }


# name, child schema, structural marker, canonical status field, one
# always-present required key, and one string field of the child.
_CHILD_SURFACE = (
    (
        "admission",
        ReasoningRunStage7AdmissionRead,
        "ADMISSION_INVALID",
        "admission_status",
        "admission_source",
        "requested_session_id",
    ),
    (
        "package",
        ReasoningRunStage7RequestRead,
        "REQUEST_PACKAGE_INVALID",
        "request_status",
        "request_source",
        "session_id",
    ),
    (
        "request_audit",
        ReasoningRunStage7RequestAuditRead,
        "REQUEST_AUDIT_INVALID",
        "request_audit_status",
        "audit_source",
        "audited_session_id",
    ),
    (
        "proposal_result",
        ReasoningRunStage7ProposalRead,
        "PROPOSAL_RESULT_INVALID",
        "proposal_status",
        "proposal_source",
        "session_id",
    ),
    (
        "proposal_audit",
        ReasoningRunStage7ProposalAuditRead,
        "PROPOSAL_AUDIT_INVALID",
        "proposal_audit_status",
        "audit_source",
        "audited_session_id",
    ),
    (
        "diagnostics",
        ReasoningRunStage7DiagnosticsRead,
        "DIAGNOSTICS_INVALID",
        "diagnostics_status",
        "source",
        "session_id",
    ),
)

# One incoherent combination per child that defines coherence rules. The
# Task 154 admission contract states its coherence in prose but enforces
# only field shapes, so it has no incoherent combination to reject here;
# Task 162 must not invent one, because that would make it a second
# consistency authority over an approved child.
_CHILD_INCOHERENCE = (
    ("package", "REQUEST_PACKAGE_INVALID", {"context_fingerprint": None}),
    ("request_audit", "REQUEST_AUDIT_INVALID", {"findings": ["SELF_SERVED"]}),
    (
        "proposal_result",
        "PROPOSAL_RESULT_INVALID",
        {"provider": None},
    ),
    (
        "proposal_audit",
        "PROPOSAL_AUDIT_INVALID",
        {"audited_proposal_fingerprint": None},
    ),
    (
        "diagnostics",
        "DIAGNOSTICS_INVALID",
        {"findings": ["SELF_SERVED"], "finding_count": 1},
    ),
)


_CHILD_SCHEMAS = {entry[0]: entry[1] for entry in _CHILD_SURFACE}


def _rejected(materials: dict, name: str, forged: dict, prefix: str) -> dict:
    """Assert a forged child is rejected by its own contract and packaged
    as invalid material, then return the package for further checks."""
    with pytest.raises(ValidationError):
        _CHILD_SCHEMAS[name].model_validate(forged)
    result = _package(**{**materials, name: forged})
    assert any(finding.startswith(prefix) for finding in result["findings"]), (
        name,
        result["findings"],
    )
    return result


# ---------------------------------------------------------------------------
# B. Strict child-schema rejection: no key/value mapping is trusted
# ---------------------------------------------------------------------------


def test_each_child_is_rejected_by_its_own_contract() -> None:
    """An over-extended mapping is unreadable material, not evidence.

    Every child is re-checked against its own approved contract, so a
    forged field is rejected by that contract before this boundary could
    project the status it claims.
    """
    sid = _seed_full_session("Task 162 child contract rejection")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)

    for name, _, prefix, _, _, _ in _CHILD_SURFACE:
        extra = {**copy.deepcopy(materials[name]), "self_served": "SELF-SERVED-162"}
        # The rejection marker deliberately names the offending location,
        # but none of the forged content is projected as evidence.
        _rejected(materials, name, extra, prefix)
        assert "SELF-SERVED-162" not in json.dumps(
            _package(**{**materials, name: extra})
        )

    # Each rejected child contributes nothing at all, so the fields it
    # would have established stay unusable rather than half-trusted.
    for name, _, _, status_field, _, _ in _CHILD_SURFACE:
        forged = {**copy.deepcopy(materials[name]), "self_served": "AUDITED"}
        result = _package(**{**materials, name: forged})
        if name == "admission":
            assert result["admission_status"] is None
        elif name == "package":
            assert result["request_fingerprint"] is None
        elif name in ("request_audit", "proposal_audit"):
            assert result[status_field] is None
        elif name == "proposal_result":
            assert result["provider_name"] is None
            assert result["model_name"] is None
        else:
            assert result["diagnostics_status"] == "NO_MATERIAL"


def test_self_served_status_strings_are_not_trusted() -> None:
    """The reviewer's exact failure: a lone key with a valid value.

    Reading ``admission_status`` or ``diagnostics_status`` out of a
    mapping is not validation. A minimal mapping that names a legal
    status string but satisfies none of the surrounding contract is
    rejected, and the recognized string never reaches the package.
    """
    self_served = {
        "admission": {"admission_status": "ADMITTED"},
        "package": {"context_fingerprint": "a" * 64},
        "request_audit": {"request_audit_status": "CONSISTENT"},
        "proposal_result": {"provider": "fake-provider", "model": "fake-model"},
        "proposal_audit": {"proposal_audit_status": "CONSISTENT"},
        "diagnostics": {"diagnostics_status": "HEALTHY"},
    }

    result = _package(**self_served)

    assert result["admission_status"] is None
    assert result["request_fingerprint"] is None
    assert result["request_audit_status"] is None
    assert result["proposal_audit_status"] is None
    assert result["provider_name"] is None
    assert result["model_name"] is None
    assert result["diagnostics_status"] == "NO_MATERIAL"
    assert result["session_id"] == ""
    for _, _, prefix, _, _, _ in _CHILD_SURFACE:
        assert any(finding.startswith(prefix) for finding in result["findings"]), prefix
    for smuggled_string in ("ADMITTED", "CONSISTENT", "HEALTHY", "fake-provider"):
        assert smuggled_string not in json.dumps(result)
    assert "a" * 64 not in json.dumps(result)


def test_every_child_rejection_shape_is_unreadable_material() -> None:
    """For each child: extra field, malformed value, and missing value.

    Each rejection is asserted twice -- once against the child's own
    contract and once through Task 162 -- so this boundary cannot be made
    to trust a mapping that the approved child itself refuses.
    """
    sid = _seed_full_session("Task 162 child rejection shapes")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)

    for name, _, prefix, _, required_key, string_field in _CHILD_SURFACE:
        genuine = copy.deepcopy(materials[name])
        extra = {**genuine, "self_served": 1}
        _rejected(materials, name, extra, prefix)
        malformed = {**genuine, string_field: None}
        if string_field in ("audited_session_id",):
            # This binding evidence is legitimately None for verdicts
            # that do not certify, so a null there is coherent, not
            # malformed; a non-string is what the contract refuses.
            malformed = {**genuine, string_field: 12345}
        _rejected(materials, name, malformed, prefix)
        missing = {k: v for k, v in genuine.items() if k != required_key}
        _rejected(materials, name, missing, prefix)


def test_invalid_child_status_enums_are_rejected() -> None:
    sid = _seed_full_session("Task 162 child status enums")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)

    for name, _, prefix, status_field, _, _ in _CHILD_SURFACE:
        forged = {**copy.deepcopy(materials[name]), status_field: "MAYBE"}
        _rejected(materials, name, forged, prefix)


def test_incoherent_child_combinations_are_rejected() -> None:
    """A child that contradicts itself is unreadable, never half-believed.

    Coherence is decided by the child schemas alone. The injected finding
    strings prove the rejected mapping contributes nothing at all -- not
    even a single finding -- to the assembled package.
    """
    sid = _seed_full_session("Task 162 child incoherence")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)

    for name, prefix, changes in _CHILD_INCOHERENCE:
        forged = {**copy.deepcopy(materials[name]), **changes}
        result = _rejected(materials, name, forged, prefix)
        assert "SELF_SERVED" not in json.dumps(result)


# ---------------------------------------------------------------------------
# C. Provider metadata only ever comes from a validated proposal
# ---------------------------------------------------------------------------


def test_provider_metadata_requires_a_validated_proposal() -> None:
    """Failure, unavailable, and malformed proposals leak no metadata."""
    sid = _seed_full_session("Task 162 provider metadata gating")
    with TestingSessionLocal() as db:
        baseline_materials = _healthy_six(db, sid)
        baseline = _package(**baseline_materials)
        package, request_audit, proposal_result, proposal_audit = (
            _model_failure_material(db, sid, ValueError("invalid json output"))
        )
        assert proposal_result["proposal_status"] == "MODEL_OUTPUT_INVALID"
        assert proposal_result["provider"] is None
        invalid_output = _package(
            **{**baseline_materials, "proposal_result": proposal_result}
        )
        unavailable = _package(
            **{
                **baseline_materials,
                "proposal_result": _unavailable_proposal(proposal_result),
            }
        )
        # A re-declared VALIDATED envelope with smuggled provider metadata
        # is incoherent, so its own contract rejects it outright.
        smuggled = {
            **copy.deepcopy(proposal_result),
            "proposal_status": "VALIDATED",
            "provider": "not-a-real-provider",
        }
        smuggled_result = _package(
            **{**baseline_materials, "proposal_result": smuggled}
        )

    assert baseline["provider_name"] == "fake-provider"
    assert baseline["model_name"] == "fake-model"
    for result in (invalid_output, unavailable, smuggled_result):
        assert result["provider_name"] is None
        assert result["model_name"] is None
        assert "fake-provider" not in json.dumps(result)
        assert "not-a-real-provider" not in json.dumps(result)
    assert any(
        finding.startswith("PROPOSAL_RESULT_INVALID")
        for finding in smuggled_result["findings"]
    ), smuggled_result["findings"]


# ---------------------------------------------------------------------------
# D. Session identity comes from validated children only
# ---------------------------------------------------------------------------


def test_invalid_material_cannot_establish_session_identity() -> None:
    sid = _seed_full_session("Task 162 invalid session claim")
    other = _seed_full_session("Task 162 invalid session claim source")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        forged_admission = {
            **copy.deepcopy(materials["admission"]),
            "requested_session_id": other,
            "self_served": "ADMITTED",
        }
        result = _package(**{**materials, "admission": forged_admission})

    # The rejected claim never becomes a competing identity, so the
    # validated children still agree on one session.
    assert result["session_id"] == sid
    assert "SESSION_MISMATCH" not in result["findings"]


def test_multiple_conflicting_validated_sessions_is_mismatch() -> None:
    sid_a = _seed_full_session("Task 162 conflicting sessions A")
    sid_b = _seed_full_session("Task 162 conflicting sessions B")
    sid_c = _seed_full_session("Task 162 conflicting sessions C")
    with TestingSessionLocal() as db:
        material_a = _healthy_six(db, sid_a)
        material_b = _healthy_six(db, sid_b)
        material_c = _healthy_six(db, sid_c)
        result = _package(
            admission=material_c["admission"],
            package=material_a["package"],
            request_audit=material_a["request_audit"],
            proposal_result=material_b["proposal_result"],
            proposal_audit=material_b["proposal_audit"],
            diagnostics=material_a["diagnostics"],
        )

    # Three genuine, mutually contradictory claims never resolve to an
    # arbitrary winner.
    assert result["session_id"] == ""
    assert "SESSION_MISMATCH" in result["findings"]
    for sid in (sid_a, sid_b, sid_c):
        assert sid not in json.dumps(result)


# ---------------------------------------------------------------------------
# E. The request fingerprint only ever comes from a PACKAGED request
# ---------------------------------------------------------------------------


def test_unpackaged_request_projects_no_fingerprint() -> None:
    sid = _seed_full_session("Task 162 request fingerprint")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        packaged = _package(**materials)
        blocked = _package(
            **{**materials, "package": _blocked_package(materials["package"])}
        )
        unavailable = _package(
            **{**materials, "package": _unavailable_package(materials["package"])}
        )
        malformed = {
            **copy.deepcopy(materials["package"]),
            "context_fingerprint": "zz",
        }
        with pytest.raises(ValidationError):
            ReasoningRunStage7RequestRead.model_validate(malformed)
        rejected = _package(**{**materials, "package": malformed})

    assert (
        packaged["request_fingerprint"] == materials["package"]["context_fingerprint"]
    )
    assert blocked["request_fingerprint"] is None
    assert blocked["session_id"] == sid
    assert unavailable["request_fingerprint"] is None
    assert rejected["request_fingerprint"] is None
    assert any(
        finding.startswith("REQUEST_PACKAGE_INVALID")
        for finding in rejected["findings"]
    ), rejected["findings"]
    assert "zz" not in json.dumps(rejected)


# ---------------------------------------------------------------------------
# F. Child findings are harvested after validation, never repaired
# ---------------------------------------------------------------------------


def test_incoherent_child_finding_structure_is_rejected_not_repaired() -> None:
    """A child that breaks its own finding contract loses all its findings.

    Sorting and deduplicating here would silently launder exactly the
    malformed evidence the child schema refuses to accept, so the whole
    child is rejected instead and contributes nothing.
    """
    sid = _seed_full_session("Task 162 finding structure not repaired")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        forged_package = {
            **copy.deepcopy(materials["package"]),
            "context_fingerprint": "0" * 64,
        }
        inconsistent_request_audit = _audit_request(db, forged_package)
        assert inconsistent_request_audit["request_audit_status"] == "INCONSISTENT"
        request_findings = list(inconsistent_request_audit["findings"])
        assert request_findings

        count_off = {
            **copy.deepcopy(inconsistent_request_audit),
            "finding_count": 0,
        }
        with pytest.raises(ValidationError):
            ReasoningRunStage7RequestAuditRead.model_validate(count_off)
        request_rejected = _package(**{**materials, "request_audit": count_off})

        tampered = copy.deepcopy(materials["proposal_result"])
        tampered["proposal"]["candidate_assessments"][0]["candidate_id"] = str(uuid4())
        inconsistent_proposal_audit = ReasoningRunStage7ProposalAuditService.audit(
            proposal_result=tampered, context=_context(db, sid)
        )
        assert inconsistent_proposal_audit["proposal_audit_status"] == "INCONSISTENT"
        proposal_findings = list(inconsistent_proposal_audit["findings"])
        assert proposal_findings
        duplicated = {
            **copy.deepcopy(inconsistent_proposal_audit),
            "findings": proposal_findings * 2,
            "finding_count": len(proposal_findings) * 2,
        }
        with pytest.raises(ValidationError):
            ReasoningRunStage7ProposalAuditRead.model_validate(duplicated)
        proposal_rejected = _package(**{**materials, "proposal_audit": duplicated})

    assert any(
        finding.startswith("REQUEST_AUDIT_INVALID")
        for finding in request_rejected["findings"]
    ), request_rejected["findings"]
    assert request_rejected["request_audit_status"] is None
    for finding in request_findings:
        assert finding not in request_rejected["findings"]

    assert any(
        finding.startswith("PROPOSAL_AUDIT_INVALID")
        for finding in proposal_rejected["findings"]
    ), proposal_rejected["findings"]
    assert proposal_rejected["proposal_audit_status"] is None
    for finding in proposal_findings:
        assert finding not in proposal_rejected["findings"]
    assert request_rejected["findings"] == sorted(request_rejected["findings"])
    assert request_rejected["finding_count"] == len(request_rejected["findings"])


def test_validated_child_findings_are_preserved_verbatim() -> None:
    sid = _seed_full_session("Task 162 findings preserved")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        tampered = copy.deepcopy(materials["proposal_result"])
        tampered["proposal"]["candidate_assessments"][0]["candidate_id"] = str(uuid4())
        inconsistent_audit = ReasoningRunStage7ProposalAuditService.audit(
            proposal_result=tampered, context=_context(db, sid)
        )
        diagnostics = _diagnose(
            materials["package"],
            materials["request_audit"],
            tampered,
            inconsistent_audit,
        )
        result = _package(
            **{
                **materials,
                "proposal_result": tampered,
                "proposal_audit": inconsistent_audit,
                "diagnostics": diagnostics,
            }
        )

    assert diagnostics["diagnostics_status"] == "UNHEALTHY"
    assert result["diagnostics_status"] == "UNHEALTHY"
    # The nested proposal still validates, so its metadata is legitimately
    # projected while the contradiction is reported rather than concealed.
    assert result["provider_name"] == "fake-provider"
    for finding in inconsistent_audit["findings"]:
        assert finding in result["findings"]
    for finding in diagnostics["findings"]:
        assert finding in result["findings"]
    assert result["findings"] == sorted(set(result["findings"]))
    assert result["finding_count"] == len(result["findings"])


def test_caller_material_is_never_mutated() -> None:
    sid = _seed_full_session("Task 162 caller material unchanged")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        before = copy.deepcopy(materials)
        _package(**materials)
        _package(**materials)

    assert materials == before


_BINDING_MARKERS = (
    "REQUEST_AUDIT_SESSION_MISMATCH",
    "REQUEST_AUDIT_FINGERPRINT_MISMATCH",
    "PROPOSAL_AUDIT_SESSION_MISMATCH",
    "PROPOSAL_AUDIT_FINGERPRINT_MISMATCH",
)


# ---------------------------------------------------------------------------
# Exact audit-to-material provenance binding
# ---------------------------------------------------------------------------


def test_exact_audit_bindings_are_accepted() -> None:
    sid = _seed_full_session("Task 162 exact audit bindings")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        result = _package(**materials)

    assert materials["request_audit"]["audited_session_id"] == sid
    assert (
        materials["request_audit"]["audited_request_fingerprint"]
        == materials["package"]["context_fingerprint"]
    )
    assert materials["proposal_audit"]["audited_session_id"] == sid
    assert (
        materials["proposal_audit"]["audited_proposal_fingerprint"]
        == materials["proposal_result"]["context_fingerprint"]
    )
    assert result["request_audit_status"] == "CONSISTENT"
    assert result["proposal_audit_status"] == "CONSISTENT"
    assert result["diagnostics_status"] == "HEALTHY"
    for marker in _BINDING_MARKERS:
        assert marker not in result["findings"]


def test_request_audit_fingerprint_binding() -> None:
    """A CONSISTENT audit naming a different request is detached evidence.

    The audit stays structurally perfect -- only its published binding
    fingerprint moves -- so nothing but the exact comparison can catch it.
    The genuine healthy diagnostics verdict is supplied unchanged, which
    proves Task 162 performs this check itself instead of inheriting it.
    """
    sid = _seed_full_session("Task 162 request audit fingerprint binding")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        detached = {
            **copy.deepcopy(materials["request_audit"]),
            "audited_request_fingerprint": "b" * 64,
        }
        ReasoningRunStage7RequestAuditRead.model_validate(detached)
        result = _package(**{**materials, "request_audit": detached})

    assert "REQUEST_AUDIT_FINGERPRINT_MISMATCH" in result["findings"]
    assert "REQUEST_AUDIT_SESSION_MISMATCH" not in result["findings"]
    assert result["request_audit_status"] is None
    assert result["diagnostics_status"] == "HEALTHY"


def test_request_audit_session_binding() -> None:
    sid = _seed_full_session("Task 162 request audit session binding")
    other = str(uuid4())
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        detached = {
            **copy.deepcopy(materials["request_audit"]),
            "audited_session_id": other,
        }
        ReasoningRunStage7RequestAuditRead.model_validate(detached)
        result = _package(**{**materials, "request_audit": detached})

    assert "REQUEST_AUDIT_SESSION_MISMATCH" in result["findings"]
    assert "REQUEST_AUDIT_FINGERPRINT_MISMATCH" not in result["findings"]
    assert result["request_audit_status"] is None
    assert other not in json.dumps(result)


def test_proposal_audit_fingerprint_binding() -> None:
    sid = _seed_full_session("Task 162 proposal audit fingerprint binding")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        detached = {
            **copy.deepcopy(materials["proposal_audit"]),
            "audited_proposal_fingerprint": "c" * 64,
        }
        ReasoningRunStage7ProposalAuditRead.model_validate(detached)
        result = _package(**{**materials, "proposal_audit": detached})

    assert "PROPOSAL_AUDIT_FINGERPRINT_MISMATCH" in result["findings"]
    assert "PROPOSAL_AUDIT_SESSION_MISMATCH" not in result["findings"]
    assert result["proposal_audit_status"] is None


def test_proposal_audit_session_binding() -> None:
    sid = _seed_full_session("Task 162 proposal audit session binding")
    other = str(uuid4())
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        detached = {
            **copy.deepcopy(materials["proposal_audit"]),
            "audited_session_id": other,
        }
        ReasoningRunStage7ProposalAuditRead.model_validate(detached)
        result = _package(**{**materials, "proposal_audit": detached})

    assert "PROPOSAL_AUDIT_SESSION_MISMATCH" in result["findings"]
    assert "PROPOSAL_AUDIT_FINGERPRINT_MISMATCH" not in result["findings"]
    assert result["proposal_audit_status"] is None
    assert other not in json.dumps(result)


def test_cross_package_request_audit_is_rejected() -> None:
    sid_a = _seed_full_session("Task 162 cross package request audit A")
    sid_b = _seed_full_session("Task 162 cross package request audit B")
    with TestingSessionLocal() as db:
        materials_a = _healthy_six(db, sid_a)
        audit_b = _audit_request(db, _build_package(db, sid_b))
        assert audit_b["request_audit_status"] == "CONSISTENT"
        assert audit_b["audited_session_id"] == sid_b
        result = _package(**{**materials_a, "request_audit": audit_b})

    # Session A stays the package identity; the foreign audit is simply
    # unusable evidence, and both of its binding fields fail.
    assert result["session_id"] == sid_a
    assert "REQUEST_AUDIT_SESSION_MISMATCH" in result["findings"]
    assert "REQUEST_AUDIT_FINGERPRINT_MISMATCH" in result["findings"]
    assert result["request_audit_status"] is None


def test_cross_package_proposal_audit_is_rejected() -> None:
    sid_a = _seed_full_session("Task 162 cross package proposal audit A")
    sid_b = _seed_full_session("Task 162 cross package proposal audit B")
    with TestingSessionLocal() as db:
        materials_a = _healthy_six(db, sid_a)
        materials_b = _healthy_six(db, sid_b)
        assert materials_b["proposal_audit"]["proposal_audit_status"] == "CONSISTENT"
        result = _package(
            **{**materials_a, "proposal_audit": materials_b["proposal_audit"]}
        )

    assert result["session_id"] == sid_a
    assert "PROPOSAL_AUDIT_SESSION_MISMATCH" in result["findings"]
    assert "PROPOSAL_AUDIT_FINGERPRINT_MISMATCH" in result["findings"]
    assert result["proposal_audit_status"] is None


def test_cross_fingerprint_request_audit_is_rejected() -> None:
    """Same session, different exact request."""
    sid = _seed_full_session("Task 162 cross fingerprint request audit")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        forged_package = {
            **copy.deepcopy(materials["package"]),
            "context_fingerprint": "d" * 64,
        }
        ReasoningRunStage7RequestRead.model_validate(forged_package)
        result = _package(**{**materials, "package": forged_package})

    assert result["session_id"] == sid
    assert result["request_fingerprint"] == "d" * 64
    assert "REQUEST_AUDIT_FINGERPRINT_MISMATCH" in result["findings"]
    assert "REQUEST_AUDIT_SESSION_MISMATCH" not in result["findings"]
    assert result["request_audit_status"] is None


def test_cross_fingerprint_proposal_audit_is_rejected() -> None:
    """Same session, different exact proposal."""
    sid = _seed_full_session("Task 162 cross fingerprint proposal audit")
    with TestingSessionLocal() as db:
        materials = _healthy_six(db, sid)
        forged_proposal = {
            **copy.deepcopy(materials["proposal_result"]),
            "context_fingerprint": "e" * 64,
        }
        ReasoningRunStage7ProposalRead.model_validate(forged_proposal)
        result = _package(**{**materials, "proposal_result": forged_proposal})

    assert result["session_id"] == sid
    assert result["provider_name"] == "fake-provider"
    assert "PROPOSAL_AUDIT_FINGERPRINT_MISMATCH" in result["findings"]
    assert "PROPOSAL_AUDIT_SESSION_MISMATCH" not in result["findings"]
    assert result["proposal_audit_status"] is None


def test_detached_consistent_audits_never_certify_together() -> None:
    """Both provenance chains detached at once, from another session."""
    sid_a = _seed_full_session("Task 162 both detached A")
    sid_b = _seed_full_session("Task 162 both detached B")
    with TestingSessionLocal() as db:
        materials_a = _healthy_six(db, sid_a)
        materials_b = _healthy_six(db, sid_b)
        result = _package(
            admission=materials_a["admission"],
            package=materials_a["package"],
            request_audit=materials_b["request_audit"],
            proposal_result=materials_a["proposal_result"],
            proposal_audit=materials_b["proposal_audit"],
            diagnostics=materials_a["diagnostics"],
        )

    assert result["session_id"] == sid_a
    assert result["request_audit_status"] is None
    assert result["proposal_audit_status"] is None
    for marker in _BINDING_MARKERS:
        assert marker in result["findings"], marker
    assert result["findings"] == sorted(set(result["findings"]))


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
