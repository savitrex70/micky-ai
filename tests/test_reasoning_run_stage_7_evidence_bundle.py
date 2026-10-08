"""Task 165: Stage 7 canonical evidence bundle tests.

Deterministic evidence aggregation boundary over the already-published
Task 162 audit package, Task 163 vertical-slice verdict, and Task 164
consistency audit. The genuine material is produced once, up front,
with the real Task 154-164 services and a test-only fake provider; the
assembler is then exercised purely on already-validated Pydantic
objects. The assembler is read-only, deterministic, session-isolated,
and provider-neutral: it never calls any child service, never writes to
a database, never invokes a provider, and never recomputes a
fingerprint.
"""

from __future__ import annotations

import ast
import copy
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    ReasoningRunStage7EvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
    ReasoningRunStage7VerticalSliceAuditRead,
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
from rop.services.reasoning_run_stage_7_evidence_bundle import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
    ReasoningRunStage7EvidenceBundleService,
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
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
    ReasoningRunStage7VerticalSliceService,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    ReasoningRunStage7VerticalSliceAuditService,
)

# ---------------------------------------------------------------------------
# Bundle keys constant
# ---------------------------------------------------------------------------

BUNDLE_KEYS = {
    "session_id",
    "slice_status",
    "admission_status",
    "diagnostics_status",
    "provider_name",
    "model_name",
    "finding_count",
    "findings",
    "certification_source",
    "slice_audit_status",
    "audit_available",
    "audit_consistent",
    "published_slice_status",
    "expected_slice_status",
    "audit_finding_count",
    "audit_findings",
    "audit_source",
    "request_fingerprint",
    "request_audit_status",
    "proposal_audit_status",
    "t162_audit_source",
    "bundle_status",
    "bundle_finding_count",
    "bundle_findings",
    "bundle_source",
}

# ---------------------------------------------------------------------------
# Source hygiene constants
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# In-memory DB and test client setup (mirrors Task 164 test infrastructure)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Session and seeding helpers
# ---------------------------------------------------------------------------


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "stage-7-evidence-bundle-test"},
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


# ---------------------------------------------------------------------------
# Material production helpers
# ---------------------------------------------------------------------------


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
    db: Session, sid: str
) -> tuple[dict, dict, dict, dict, dict, object]:
    context = _context(db, sid)
    provider = _FakeProvider()
    text = _valid_model_output(context)
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


def _pkg162(
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


def _healthy_pkg162(db: Session, sid: str) -> dict:
    package, request_audit, proposal_result, proposal_audit, _, _ = _healthy_material(
        db, sid
    )
    return _pkg162(
        admission=_admission(db, sid),
        package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
        diagnostics=_diagnose(package, request_audit, proposal_result, proposal_audit),
    )


def _blocked_pkg162(db: Session, sid: str) -> dict:
    admission = _admission(db, sid)
    package, request_audit, proposal_result, proposal_audit = _outage_material(db, sid)
    return _pkg162(
        admission=admission,
        package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
        diagnostics=_diagnose(package, request_audit, proposal_result, proposal_audit),
    )


def _certify(package: object = None) -> dict:
    return ReasoningRunStage7VerticalSliceService.certify(audit_package=package)


def _audit164(package: object = None, verdict: object = None) -> dict:
    return ReasoningRunStage7VerticalSliceAuditService.audit(
        audit_package=package, vertical_slice=verdict
    )


# ---------------------------------------------------------------------------
# Material production for the assembler
# ---------------------------------------------------------------------------


def _produce_ready_inputs(label: str) -> tuple[str, dict, dict, dict]:
    """Return (sid, pkg162_dict, slice163_dict, audit164_dict) all READY/CONSISTENT."""
    sid = _seed_full_session(label)
    with TestingSessionLocal() as db:
        pkg = _healthy_pkg162(db, sid)
    assert pkg["audit_source"] == REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162
    verdict = _certify(pkg)
    assert verdict["slice_status"] == "READY"
    audit = _audit164(pkg, verdict)
    assert audit["slice_audit_status"] == "CONSISTENT"
    return sid, pkg, verdict, audit


def _produce_blocked_inputs(label: str) -> tuple[str, dict, dict, dict]:
    """Return (sid, pkg162_dict, slice163_dict, audit164_dict) blocked."""
    sid = _seed_full_session(label)
    with TestingSessionLocal() as db:
        pkg = _blocked_pkg162(db, sid)
    verdict = _certify(pkg)
    assert verdict["slice_status"] == "BLOCKED"
    audit = _audit164(pkg, verdict)
    assert audit["slice_audit_status"] == "CONSISTENT"
    return sid, pkg, verdict, audit


# ---------------------------------------------------------------------------
# Assembler helper
# ---------------------------------------------------------------------------


def _assemble(
    pkg162: dict | None = None,
    slice163: dict | None = None,
    audit164: dict | None = None,
) -> dict:
    """Validate dicts through child schemas and call assemble()."""
    return ReasoningRunStage7EvidenceBundleService.assemble(
        pkg162=ReasoningRunStage7AuditPackageRead.model_validate(pkg162),
        slice163=ReasoningRunStage7VerticalSliceRead.model_validate(slice163),
        audit164=ReasoningRunStage7VerticalSliceAuditRead.model_validate(audit164),
    )


def _with(mapping: dict, **changes: Any) -> dict:
    return {**copy.deepcopy(mapping), **changes}


# ---------------------------------------------------------------------------
# Category 1 — READY bundle
# ---------------------------------------------------------------------------


def test_genuine_ready_bundle_is_ready() -> None:
    sid, pkg, verdict, audit = _produce_ready_inputs("Task 165 genuine ready")

    result = _assemble(pkg, verdict, audit)

    assert result["bundle_status"] == "READY"
    assert result["bundle_findings"] == []
    assert result["bundle_finding_count"] == 0
    assert result["session_id"] == sid
    assert result["bundle_source"] == (
        REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165
    )
    assert set(result) == BUNDLE_KEYS
    assert result["slice_status"] == "READY"
    assert result["slice_audit_status"] == "CONSISTENT"
    assert result["audit_available"] is True
    assert result["audit_consistent"] is True


def test_ready_bundle_preserves_t163_fields_verbatim() -> None:
    sid, pkg, verdict, audit = _produce_ready_inputs("Task 165 t163 fields")

    result = _assemble(pkg, verdict, audit)

    assert result["findings"] == []
    assert result["finding_count"] == 0
    assert result["certification_source"] == (
        REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163
    )
    assert result["admission_status"] == "ADMITTED"
    assert result["diagnostics_status"] == "HEALTHY"
    assert result["provider_name"] is not None and result["provider_name"] != ""
    assert result["model_name"] is not None and result["model_name"] != ""


def test_ready_bundle_preserves_t162_attribution_verbatim() -> None:
    sid, pkg, verdict, audit = _produce_ready_inputs("Task 165 t162 attribution")
    import re

    result = _assemble(pkg, verdict, audit)

    assert result["request_fingerprint"] is not None
    assert re.fullmatch(r"[0-9a-f]{64}", result["request_fingerprint"])
    assert result["request_audit_status"] == "CONSISTENT"
    assert result["proposal_audit_status"] == "CONSISTENT"
    assert result["t162_audit_source"] == (
        REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162
    )


# ---------------------------------------------------------------------------
# Category 2 — BLOCKED bundle
# ---------------------------------------------------------------------------


def test_blocked_slice_status_produces_blocked_bundle() -> None:
    _, pkg, verdict, audit = _produce_blocked_inputs("Task 165 blocked slice")

    result = _assemble(pkg, verdict, audit)

    assert result["bundle_status"] == "BLOCKED"
    # A BLOCKED verdict is an explicit gate refusal, not a structural bundle finding
    assert "STAGE_7_SESSION_MISMATCH" not in result["bundle_findings"]
    assert "T162_AUDIT_SOURCE_NOT_CANONICAL" not in result["bundle_findings"]
    assert "T163_CERTIFICATION_SOURCE_NOT_CANONICAL" not in result["bundle_findings"]
    assert "T164_AUDIT_SOURCE_NOT_CANONICAL" not in result["bundle_findings"]


def test_blocked_admission_produces_blocked_bundle() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 blocked admission")
    tampered_pkg = _with(pkg, admission_status="BLOCKED")
    ReasoningRunStage7AuditPackageRead.model_validate(tampered_pkg)

    result = _assemble(tampered_pkg, verdict, audit)

    assert result["bundle_status"] == "BLOCKED"


def test_unhealthy_diagnostics_produces_blocked_bundle() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 unhealthy diagnostics")
    tampered_pkg = _with(pkg, diagnostics_status="UNHEALTHY")
    ReasoningRunStage7AuditPackageRead.model_validate(tampered_pkg)

    result = _assemble(tampered_pkg, verdict, audit)

    assert result["bundle_status"] == "BLOCKED"


def test_inconsistent_request_audit_produces_blocked_bundle() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs(
        "Task 165 inconsistent request audit"
    )
    tampered_pkg = _with(pkg, request_audit_status="INCONSISTENT")
    ReasoningRunStage7AuditPackageRead.model_validate(tampered_pkg)

    result = _assemble(tampered_pkg, verdict, audit)

    assert result["bundle_status"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Category 3 — UNAVAILABLE bundle
# ---------------------------------------------------------------------------


def test_inconsistent_audit164_prevents_ready() -> None:
    sid, pkg, verdict, _ = _produce_ready_inputs("Task 165 inconsistent audit164")
    # Build a valid INCONSISTENT audit for this session
    tampered_verdict = _with(verdict, session_id=str(uuid4()))
    inconsistent_audit = _audit164(pkg, tampered_verdict)
    assert inconsistent_audit["slice_audit_status"] == "INCONSISTENT"

    result = _assemble(pkg, verdict, inconsistent_audit)

    assert result["bundle_status"] == "UNAVAILABLE"
    # Must NOT be BLOCKED (INCONSISTENT audit is not a BLOCKED condition)
    assert result["bundle_status"] != "BLOCKED"


def test_unavailable_audit164_prevents_ready() -> None:
    sid, pkg, verdict, _ = _produce_ready_inputs("Task 165 unavailable audit164")
    # Build a valid UNAVAILABLE audit by passing no inputs
    unavailable_audit = _audit164()
    assert unavailable_audit["slice_audit_status"] == "UNAVAILABLE"

    # The UNAVAILABLE audit has session_id="" so all three won't agree
    result = _assemble(pkg, verdict, unavailable_audit)

    assert result["bundle_status"] == "UNAVAILABLE"


def test_missing_request_fingerprint_prevents_ready() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 missing fingerprint")
    tampered_pkg = _with(pkg, request_fingerprint=None)

    result = _assemble(tampered_pkg, verdict, audit)

    assert result["bundle_status"] == "UNAVAILABLE"
    assert "REQUEST_FINGERPRINT_MISSING_OR_MALFORMED" in result["bundle_findings"]


@pytest.mark.parametrize(
    "fingerprint",
    ["", "a" * 63, "a" * 65, "g" * 64, "A" * 64, ("a" * 63) + "\n"],
)
def test_malformed_request_fingerprint_prevents_ready(fingerprint: str) -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 malformed fingerprint")
    tampered_pkg = _with(pkg, request_fingerprint=fingerprint)

    result = _assemble(tampered_pkg, verdict, audit)

    assert result["bundle_status"] == "UNAVAILABLE"
    assert "REQUEST_FINGERPRINT_MISSING_OR_MALFORMED" in result["bundle_findings"]


def test_missing_provider_attribution_prevents_ready() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 missing attribution")
    tampered_pkg = _with(pkg, provider_name=None, model_name=None)

    result = _assemble(tampered_pkg, verdict, audit)

    assert result["bundle_status"] == "UNAVAILABLE"
    assert "PROVIDER_ATTRIBUTION_MISSING" in result["bundle_findings"]


def test_session_mismatch_produces_unavailable() -> None:
    sid, pkg, verdict, audit = _produce_ready_inputs("Task 165 session mismatch")
    other_sid = str(uuid4())
    assert other_sid != sid
    tampered_verdict = _with(verdict, session_id=other_sid)
    ReasoningRunStage7VerticalSliceRead.model_validate(tampered_verdict)

    result = _assemble(pkg, tampered_verdict, audit)

    assert result["bundle_status"] == "UNAVAILABLE"
    assert "STAGE_7_SESSION_MISMATCH" in result["bundle_findings"]
    # The foreign session must not appear as the canonical bundle identity
    assert result["session_id"] != other_sid
    # Verify the foreign sid doesn't appear in identity field
    assert result["session_id"] == ""


def test_t162_noncanonical_source_produces_unavailable() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 t162 non-canonical source")
    tampered_pkg = _with(pkg, audit_source="FORGED")
    ReasoningRunStage7AuditPackageRead.model_validate(tampered_pkg)

    result = _assemble(tampered_pkg, verdict, audit)

    assert result["bundle_status"] == "UNAVAILABLE"
    assert "T162_AUDIT_SOURCE_NOT_CANONICAL" in result["bundle_findings"]


def test_t163_noncanonical_source_produces_unavailable() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 t163 non-canonical source")
    tampered_verdict = _with(verdict, certification_source="FORGED")
    ReasoningRunStage7VerticalSliceRead.model_validate(tampered_verdict)

    result = _assemble(pkg, tampered_verdict, audit)

    assert result["bundle_status"] == "UNAVAILABLE"
    assert "T163_CERTIFICATION_SOURCE_NOT_CANONICAL" in result["bundle_findings"]


def test_t164_noncanonical_source_produces_unavailable() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 t164 non-canonical source")
    tampered_audit = _with(audit, audit_source="FORGED")
    ReasoningRunStage7VerticalSliceAuditRead.model_validate(tampered_audit)

    result = _assemble(pkg, verdict, tampered_audit)

    assert result["bundle_status"] == "UNAVAILABLE"
    assert "T164_AUDIT_SOURCE_NOT_CANONICAL" in result["bundle_findings"]


# ---------------------------------------------------------------------------
# Category 4 — Session binding
# ---------------------------------------------------------------------------


def test_all_three_sessions_must_agree() -> None:
    sid_a, pkg_a, verdict_a, audit_a = _produce_ready_inputs("Task 165 session A")
    sid_b, pkg_b, verdict_b, audit_b = _produce_ready_inputs("Task 165 session B")
    assert sid_a != sid_b

    # Mix: pkg162 from A, slice163 from B (same session_id as B), audit164 from A
    tampered_verdict = _with(verdict_b, session_id=sid_b)
    tampered_audit = _with(audit_a)  # session_id is sid_a

    result = _assemble(pkg_a, tampered_verdict, tampered_audit)

    assert result["bundle_status"] == "UNAVAILABLE"
    assert "STAGE_7_SESSION_MISMATCH" in result["bundle_findings"]


def test_session_id_empty_string_prevents_ready() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 empty session")
    # Tamper pkg162 to have empty session_id
    tampered_pkg = _with(pkg, session_id="")
    ReasoningRunStage7AuditPackageRead.model_validate(tampered_pkg)

    result = _assemble(tampered_pkg, verdict, audit)

    # The three session_ids won't all agree on a non-empty value
    assert result["bundle_status"] == "UNAVAILABLE"
    assert "STAGE_7_SESSION_MISMATCH" in result["bundle_findings"]


def test_correct_session_id_in_ready_bundle() -> None:
    sid, pkg, verdict, audit = _produce_ready_inputs("Task 165 correct session id")

    result = _assemble(pkg, verdict, audit)

    assert result["bundle_status"] == "READY"
    assert result["session_id"] == sid


# ---------------------------------------------------------------------------
# Category 5 — Child finding preservation
# ---------------------------------------------------------------------------


def test_t163_findings_preserved_verbatim() -> None:
    _, pkg, verdict, audit = _produce_blocked_inputs("Task 165 t163 findings preserved")
    # BLOCKED verdict carries findings
    assert verdict["findings"]

    result = _assemble(pkg, verdict, audit)

    assert result["findings"] == verdict["findings"]


def test_t164_audit_findings_preserved_verbatim() -> None:
    sid, pkg, verdict, _ = _produce_ready_inputs("Task 165 t164 findings preserved")
    # Produce an INCONSISTENT audit (which carries findings)
    tampered_verdict = _with(verdict, session_id=str(uuid4()))
    inconsistent_audit = _audit164(pkg, tampered_verdict)
    assert inconsistent_audit["slice_audit_status"] == "INCONSISTENT"
    assert inconsistent_audit["findings"]

    result = _assemble(pkg, verdict, inconsistent_audit)

    assert result["audit_findings"] == inconsistent_audit["findings"]


def test_bundle_findings_are_distinct_from_child_findings() -> None:
    sid, pkg, verdict, audit = _produce_ready_inputs(
        "Task 165 distinct bundle findings"
    )
    # Trigger a session mismatch (bundle-level structural finding)
    other_sid = str(uuid4())
    tampered_verdict = _with(verdict, session_id=other_sid)

    result = _assemble(pkg, tampered_verdict, audit)

    # bundle_findings contains only structural codes
    for finding in result["bundle_findings"]:
        assert (
            finding.startswith("STAGE_7_")
            or finding.startswith("T16")
            or finding
            in (
                "REQUEST_FINGERPRINT_MISSING_OR_MALFORMED",
                "PROVIDER_ATTRIBUTION_MISSING",
            )
        ), finding
    # bundle_findings must not be copies of child findings
    child_findings = set(result["findings"]) | set(result["audit_findings"])
    bundle_set = set(result["bundle_findings"])
    assert bundle_set.isdisjoint(child_findings) or not child_findings


# ---------------------------------------------------------------------------
# Category 6 — Determinism and immutability
# ---------------------------------------------------------------------------


def test_repeated_assembly_is_identical() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 determinism")

    first = _assemble(pkg, verdict, audit)
    second = _assemble(pkg, verdict, audit)

    assert first == second
    assert json.dumps(first, sort_keys=False) == json.dumps(second, sort_keys=False)


def test_assembly_is_independent_of_input_key_order() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 key order independence")

    normal = _assemble(pkg, verdict, audit)
    reversed_pkg = dict(reversed(list(pkg.items())))
    reversed_verdict = dict(reversed(list(verdict.items())))
    reversed_audit = dict(reversed(list(audit.items())))
    reordered = _assemble(reversed_pkg, reversed_verdict, reversed_audit)

    assert normal == reordered


def test_assembly_never_mutates_its_inputs() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 no mutation")
    pkg_copy = copy.deepcopy(pkg)
    verdict_copy = copy.deepcopy(verdict)
    audit_copy = copy.deepcopy(audit)

    _assemble(pkg, verdict, audit)

    assert pkg == pkg_copy
    assert verdict == verdict_copy
    assert audit == audit_copy


# ---------------------------------------------------------------------------
# Category 7 — No service, no DB, no provider
# ---------------------------------------------------------------------------


def test_assembly_never_invokes_child_services(monkeypatch: pytest.MonkeyPatch) -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 no child services")

    def _raise(*args: object, **kwargs: object) -> object:
        raise AssertionError("child service must not be called by assembler")

    monkeypatch.setattr(
        "rop.services.reasoning_run_stage_7_audit_package.ReasoningRunStage7AuditPackageService.build",
        _raise,
    )
    monkeypatch.setattr(
        "rop.services.reasoning_run_stage_7_vertical_slice.ReasoningRunStage7VerticalSliceService.certify",
        _raise,
    )
    monkeypatch.setattr(
        "rop.services.reasoning_run_stage_7_vertical_slice_audit.ReasoningRunStage7VerticalSliceAuditService.audit",
        _raise,
    )

    # The assembler receives already-validated objects; no child service is called
    result = _assemble(pkg, verdict, audit)
    assert result["bundle_status"] == "READY"


def test_assembly_never_writes_to_db(monkeypatch: pytest.MonkeyPatch) -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 no db writes")

    def _raise(*args: object, **kwargs: object) -> object:
        raise AssertionError("DB write must not be called by assembler")

    monkeypatch.setattr("sqlalchemy.orm.Session.add", _raise)
    monkeypatch.setattr("sqlalchemy.orm.Session.commit", _raise)
    monkeypatch.setattr("sqlalchemy.orm.Session.merge", _raise)
    monkeypatch.setattr("sqlalchemy.orm.Session.delete", _raise)

    result = _assemble(pkg, verdict, audit)
    assert result["bundle_status"] == "READY"


# ---------------------------------------------------------------------------
# Category 8 — Schema strictness
# ---------------------------------------------------------------------------


def test_bundle_schema_is_strict() -> None:
    assert ReasoningRunStage7EvidenceBundleRead.model_config["extra"] == "forbid"
    assert ReasoningRunStage7EvidenceBundleRead.model_config["from_attributes"] is True
    assert set(ReasoningRunStage7EvidenceBundleRead.model_fields) == BUNDLE_KEYS


def test_bundle_schema_rejects_extra_fields() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 schema extra fields")
    result = _assemble(pkg, verdict, audit)
    assert result["bundle_status"] == "READY"

    result_with_extra = {**result, "unexpected_field": "x"}
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleRead.model_validate(result_with_extra)


def test_bundle_schema_rejects_incoherent_states() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 schema incoherent")
    valid_result = _assemble(pkg, verdict, audit)

    # Wrong finding_count
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleRead.model_validate(
            {**valid_result, "finding_count": 99}
        )

    # Unsorted findings
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleRead.model_validate(
            {
                **valid_result,
                "findings": ["Z_FINDING", "A_FINDING"],
                "finding_count": 2,
            }
        )

    # audit_available mismatch
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleRead.model_validate(
            {**valid_result, "audit_available": False}
        )

    # READY bundle with non-empty bundle_findings
    with pytest.raises(ValidationError):
        ReasoningRunStage7EvidenceBundleRead.model_validate(
            {
                **valid_result,
                "bundle_findings": ["STAGE_7_SESSION_MISMATCH"],
                "bundle_finding_count": 1,
            }
        )


def test_assemble_returns_valid_bundle_schema() -> None:
    _, ready_pkg, ready_verdict, ready_audit = _produce_ready_inputs(
        "Task 165 schema validation ready"
    )
    _, blocked_pkg, blocked_verdict, blocked_audit = _produce_blocked_inputs(
        "Task 165 schema validation blocked"
    )
    _, unavail_pkg, unavail_verdict, _ = _produce_ready_inputs(
        "Task 165 schema validation unavailable"
    )
    unavail_audit = _audit164()  # UNAVAILABLE audit

    for pkg, v, a in [
        (ready_pkg, ready_verdict, ready_audit),
        (blocked_pkg, blocked_verdict, blocked_audit),
        (unavail_pkg, unavail_verdict, unavail_audit),
    ]:
        result = _assemble(pkg, v, a)
        # Each must validate through the schema
        validated = ReasoningRunStage7EvidenceBundleRead.model_validate(result)
        assert validated.bundle_status in {"READY", "BLOCKED", "UNAVAILABLE"}


# ---------------------------------------------------------------------------
# Category 9 — Source hygiene
# ---------------------------------------------------------------------------

_SERVICE_FILE = (
    Path(__file__).parent.parent
    / "src"
    / "rop"
    / "services"
    / "reasoning_run_stage_7_evidence_bundle.py"
)
_SCHEMA_FILE = (
    Path(__file__).parent.parent
    / "src"
    / "rop"
    / "schemas"
    / "reasoning_run_stage_7_evidence_bundle.py"
)


def test_service_imports_only_published_contracts() -> None:
    source = _SERVICE_FILE.read_text()
    tree = ast.parse(source)
    rop_imports: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("rop.")
        ):
            names = [alias.name for alias in node.names]
            rop_imports.setdefault(node.module, []).extend(names)

    # Only these rop modules should be imported
    expected_rop_modules = {
        "rop.schemas.reasoning_run_stage_7_audit_package",
        "rop.schemas.reasoning_run_stage_7_evidence_bundle",
        "rop.schemas.reasoning_run_stage_7_vertical_slice",
        "rop.schemas.reasoning_run_stage_7_vertical_slice_audit",
        "rop.services.reasoning_run_stage_7_audit_package",
        "rop.services.reasoning_run_stage_7_vertical_slice",
        "rop.services.reasoning_run_stage_7_vertical_slice_audit",
    }
    assert (
        set(rop_imports) == expected_rop_modules
    ), f"unexpected: {set(rop_imports) - expected_rop_modules}"

    # Only source constants may be imported from service modules
    allowed_service_imports = {
        "REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162",
        "REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163",
        "REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164",
    }
    for module, names in rop_imports.items():
        if "services" in module and "evidence_bundle" not in module:
            for name in names:
                assert (
                    name in allowed_service_imports
                ), f"non-constant imported from {module}: {name}"


def test_service_never_recomputes_fingerprint() -> None:
    source = _SERVICE_FILE.read_text()
    assert "hashlib" not in source
    assert "sha256" not in source
    assert "hexdigest" not in source
    assert "compute_fingerprint" not in source


def test_service_module_source_is_clean() -> None:
    for path in (_SERVICE_FILE, _SCHEMA_FILE):
        source = path.read_text().lower()
        for token in _PROHIBITED_SOURCE_TOKENS:
            assert (
                token not in source
            ), f"prohibited token '{token}' found in {path.name}"


def test_no_raw_provider_text_in_bundle() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 no raw provider text")

    result = _assemble(pkg, verdict, audit)
    serialized = json.dumps(result)

    # A sentinel raw-text value must not appear
    assert "RAW-PROVIDER-TEXT" not in serialized
    # Extra fields from forgery attempts must not bleed through
    # (provider_name/model_name are structural fields and are allowed)
    assert "unexpected_field" not in serialized


def test_session_isolation() -> None:
    sid_a, pkg_a, verdict_a, audit_a = _produce_ready_inputs("Task 165 isolation A")
    sid_b, pkg_b, verdict_b, audit_b = _produce_ready_inputs("Task 165 isolation B")
    assert sid_a != sid_b

    result_a = _assemble(pkg_a, verdict_a, audit_a)
    result_b = _assemble(pkg_b, verdict_b, audit_b)

    assert result_a["session_id"] == sid_a
    assert result_b["session_id"] == sid_b
    assert result_a["session_id"] != result_b["session_id"]

    # Cross-assembled: pkg162 from A, slice163 from B, audit164 from A
    cross = _assemble(pkg_a, verdict_b, audit_a)
    assert cross["bundle_status"] == "UNAVAILABLE"
    assert "STAGE_7_SESSION_MISMATCH" in cross["bundle_findings"]


# ---------------------------------------------------------------------------
# Category 10 — Direct schema hardening (bypasses assemble() completely)
# ---------------------------------------------------------------------------

_T162_SOURCE_FIELD = "t162_audit_source"
_SCHEMA_VALIDATE = ReasoningRunStage7EvidenceBundleRead.model_validate


def _genuine_ready_bundle(label: str = "Task 165 schema ready") -> dict:
    _, pkg, verdict, audit = _produce_ready_inputs(label)
    bundle = _assemble(pkg, verdict, audit)
    assert bundle["bundle_status"] == "READY"
    return bundle


def _genuine_blocked_bundle() -> dict:
    _, pkg, verdict, audit = _produce_blocked_inputs("Task 165 schema blocked")
    bundle = _assemble(pkg, verdict, audit)
    assert bundle["bundle_status"] == "BLOCKED"
    return bundle


def _genuine_unavailable_bundle() -> dict:
    _, pkg, verdict, _ = _produce_ready_inputs("Task 165 schema unavailable")
    bundle = _assemble(pkg, verdict, _audit164())
    assert bundle["bundle_status"] == "UNAVAILABLE"
    return bundle


def test_schema_accepts_genuine_ready_blocked_and_unavailable_bundles() -> None:
    for bundle in (
        _genuine_ready_bundle(),
        _genuine_blocked_bundle(),
        _genuine_unavailable_bundle(),
    ):
        validated = _SCHEMA_VALIDATE(bundle)
        assert validated.model_dump() == bundle


@pytest.mark.parametrize(
    "field",
    ["t162_audit_source", "certification_source", "audit_source", "bundle_source"],
)
@pytest.mark.parametrize("forged", ["FORGED", "", " ", "FORGED\n"])
def test_schema_rejects_forged_source_in_ready_bundle(field: str, forged: str) -> None:
    bundle = _genuine_ready_bundle()
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE({**bundle, field: forged})


@pytest.mark.parametrize(
    "field",
    ["t162_audit_source", "certification_source", "audit_source"],
)
def test_schema_rejects_unexplained_forged_source_in_non_ready_bundle(
    field: str,
) -> None:
    unavailable = _genuine_unavailable_bundle()
    blocked = _genuine_blocked_bundle()
    for bundle in (unavailable, blocked):
        with pytest.raises(ValidationError):
            _SCHEMA_VALIDATE({**bundle, field: "FORGED"})


def test_schema_always_requires_the_canonical_bundle_source() -> None:
    for bundle in (_genuine_unavailable_bundle(), _genuine_blocked_bundle()):
        with pytest.raises(ValidationError):
            _SCHEMA_VALIDATE({**bundle, "bundle_source": "FORGED"})


@pytest.mark.parametrize(
    "fingerprint",
    [
        None,
        "",
        "a" * 63,
        "a" * 65,
        "g" * 64,
        "A" * 64,
        ("a" * 32) + ("A" * 32),
        ("a" * 64) + "\n",
        " " + ("a" * 63),
        ("a" * 64) + " ",
        " " + ("a" * 64) + " ",
    ],
)
def test_schema_rejects_forged_fingerprint_in_ready_bundle(
    fingerprint: str | None,
) -> None:
    bundle = _genuine_ready_bundle()
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE({**bundle, "request_fingerprint": fingerprint})


@pytest.mark.parametrize(
    "fingerprint",
    ["", "a" * 63, "A" * 64, ("a" * 64) + "\n", " " + ("a" * 64)],
)
def test_schema_rejects_malformed_fingerprint_in_any_status(
    fingerprint: str,
) -> None:
    for bundle in (_genuine_unavailable_bundle(), _genuine_blocked_bundle()):
        with pytest.raises(ValidationError):
            _SCHEMA_VALIDATE({**bundle, "request_fingerprint": fingerprint})


def test_schema_allows_absent_fingerprint_for_non_ready_bundle() -> None:
    bundle = {
        **_genuine_unavailable_bundle(),
        "request_fingerprint": None,
        "bundle_findings": ["REQUEST_FINGERPRINT_MISSING_OR_MALFORMED"],
        "bundle_finding_count": 1,
    }
    assert _SCHEMA_VALIDATE(bundle).request_fingerprint is None


_READY_TAMPERS: dict[str, dict[str, Any]] = {
    "slice_status": {"slice_status": "UNAVAILABLE"},
    "slice_status_blocked": {"slice_status": "BLOCKED"},
    "admission_status": {"admission_status": "UNAVAILABLE"},
    "admission_status_none": {"admission_status": None},
    "diagnostics_status": {"diagnostics_status": "DEGRADED"},
    "diagnostics_status_none": {"diagnostics_status": None},
    "request_audit_status": {"request_audit_status": "UNAVAILABLE"},
    "request_audit_status_none": {"request_audit_status": None},
    "proposal_audit_status": {"proposal_audit_status": "UNAVAILABLE"},
    "proposal_audit_status_none": {"proposal_audit_status": None},
    "provider_name_none": {"provider_name": None},
    "provider_name_blank": {"provider_name": "   "},
    "provider_name_empty": {"provider_name": ""},
    "model_name_none": {"model_name": None},
    "model_name_blank": {"model_name": "   "},
    "model_name_empty": {"model_name": ""},
    "both_names_none": {"provider_name": None, "model_name": None},
    "finding_count": {"finding_count": 1},
    "findings": {"findings": ["X_FINDING"]},
    "findings_with_count": {"findings": ["X_FINDING"], "finding_count": 1},
    "slice_audit_status_inconsistent": {
        "slice_audit_status": "INCONSISTENT",
        "audit_consistent": False,
    },
    "slice_audit_status_unavailable": {
        "slice_audit_status": "UNAVAILABLE",
        "audit_available": False,
        "audit_consistent": False,
    },
    "audit_available": {"audit_available": False},
    "audit_consistent": {"audit_consistent": False},
    "published_slice_status": {"published_slice_status": "BLOCKED"},
    "published_slice_status_none": {"published_slice_status": None},
    "expected_slice_status": {"expected_slice_status": "BLOCKED"},
    "expected_slice_status_none": {"expected_slice_status": None},
    "audit_finding_count": {"audit_finding_count": 1},
    "audit_findings": {"audit_findings": ["X_AUDIT_FINDING"]},
    "audit_findings_with_count": {
        "audit_findings": ["X_AUDIT_FINDING"],
        "audit_finding_count": 1,
    },
    "request_fingerprint_none": {"request_fingerprint": None},
    "session_id_empty": {"session_id": ""},
    "session_id_blank": {"session_id": "   "},
    "bundle_findings": {
        "bundle_findings": ["STAGE_7_SESSION_MISMATCH"],
        "bundle_finding_count": 1,
    },
    "bundle_finding_count": {"bundle_finding_count": 1},
}


@pytest.mark.parametrize("tamper", sorted(_READY_TAMPERS))
def test_schema_rejects_ready_bundle_with_broken_ready_invariant(tamper: str) -> None:
    bundle = _genuine_ready_bundle()
    forged = {**bundle, **_READY_TAMPERS[tamper]}
    assert forged != bundle
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE(forged)


def test_schema_rejects_blocked_bundle_without_a_blocking_condition() -> None:
    forged = {**_genuine_ready_bundle(), "bundle_status": "BLOCKED"}
    # No blocked admission, healthy diagnostics, consistent audits, READY
    # Task 163, CONSISTENT Task 164, no findings.
    assert forged["admission_status"] == "ADMITTED"
    assert forged["diagnostics_status"] == "HEALTHY"
    assert forged["request_audit_status"] == "CONSISTENT"
    assert forged["proposal_audit_status"] == "CONSISTENT"
    assert forged["slice_status"] == "READY"
    assert forged["slice_audit_status"] == "CONSISTENT"
    assert forged["findings"] == [] and forged["audit_findings"] == []
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE(forged)


@pytest.mark.parametrize(
    "changes",
    [
        {"slice_status": "UNAVAILABLE"},
        {"admission_status": "UNAVAILABLE"},
        {"diagnostics_status": "DEGRADED"},
        {"diagnostics_status": "NO_MATERIAL"},
        {"request_audit_status": "UNAVAILABLE"},
        {"proposal_audit_status": None},
        {"slice_audit_status": "INCONSISTENT", "audit_consistent": False},
    ],
)
def test_schema_rejects_blocked_bundle_with_only_non_blocking_degradation(
    changes: dict[str, Any],
) -> None:
    forged = {**_genuine_ready_bundle(), **changes, "bundle_status": "BLOCKED"}
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE(forged)


@pytest.mark.parametrize(
    "changes",
    [
        {"slice_status": "BLOCKED"},
        {"admission_status": "BLOCKED"},
        {"diagnostics_status": "UNHEALTHY"},
        {"request_audit_status": "INCONSISTENT"},
        {"proposal_audit_status": "INCONSISTENT"},
    ],
)
def test_schema_accepts_blocked_bundle_with_a_published_blocking_condition(
    changes: dict[str, Any],
) -> None:
    bundle = {**_genuine_ready_bundle(), **changes, "bundle_status": "BLOCKED"}
    assert _SCHEMA_VALIDATE(bundle).bundle_status == "BLOCKED"


def test_schema_rejects_unavailable_bundle_that_withholds_ready_evidence() -> None:
    forged = {**_genuine_ready_bundle(), "bundle_status": "UNAVAILABLE"}
    assert forged["bundle_findings"] == [] and forged["bundle_finding_count"] == 0
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE(forged)


def test_schema_accepts_unavailable_bundle_explained_by_a_bundle_finding() -> None:
    bundle = {
        **_genuine_ready_bundle(),
        "bundle_status": "UNAVAILABLE",
        "bundle_findings": ["PROVIDER_ATTRIBUTION_MISSING"],
        "bundle_finding_count": 1,
    }
    assert _SCHEMA_VALIDATE(bundle).bundle_status == "UNAVAILABLE"


@pytest.mark.parametrize(
    "changes",
    [
        {"slice_status": "UNAVAILABLE"},
        {"admission_status": None},
        {"request_fingerprint": None},
        {"provider_name": None, "model_name": None},
        {"session_id": ""},
        {
            "slice_audit_status": "UNAVAILABLE",
            "audit_available": False,
            "audit_consistent": False,
        },
    ],
)
def test_schema_accepts_unavailable_bundle_when_evidence_is_incomplete(
    changes: dict[str, Any],
) -> None:
    bundle = {**_genuine_ready_bundle(), **changes, "bundle_status": "UNAVAILABLE"}
    assert _SCHEMA_VALIDATE(bundle).bundle_status == "UNAVAILABLE"


def test_schema_still_rejects_extra_fields_and_blank_attribution_xor() -> None:
    bundle = _genuine_ready_bundle()
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE({**bundle, "unexpected_field": "x"})
    unavailable = _genuine_unavailable_bundle()
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE({**unavailable, "provider_name": "p", "model_name": None})


def test_schema_imports_only_source_constants_from_services() -> None:
    tree = ast.parse(_SCHEMA_FILE.read_text())
    allowed = {
        "REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162",
        "REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163",
        "REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("rop.services"):
                imported.update(alias.name for alias in node.names)
            assert not node.module.startswith("rop.models")
            assert not node.module.startswith("rop.repositories")
    assert imported == allowed
    source = _SCHEMA_FILE.read_text()
    for forbidden in ("hashlib", "sha256", "hexdigest", "Session"):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# Category 11 — Service output stays schema-coherent under tampered inputs
# ---------------------------------------------------------------------------


def test_service_withholds_malformed_fingerprint_instead_of_publishing_it() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 withheld fingerprint")
    for bad in ("", "a" * 63, "A" * 64, ("a" * 64) + "\n"):
        result = _assemble(_with(pkg, request_fingerprint=bad), verdict, audit)
        assert result["request_fingerprint"] is None
        assert result["bundle_status"] == "UNAVAILABLE"
        assert "REQUEST_FINGERPRINT_MISSING_OR_MALFORMED" in result["bundle_findings"]


def test_service_publishes_the_blocking_state_that_makes_a_bundle_blocked() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 published blocking")

    admission = _assemble(_with(pkg, admission_status="BLOCKED"), verdict, audit)
    assert admission["bundle_status"] == "BLOCKED"
    assert admission["admission_status"] == "BLOCKED"

    diagnostics = _assemble(_with(pkg, diagnostics_status="UNHEALTHY"), verdict, audit)
    assert diagnostics["bundle_status"] == "BLOCKED"
    assert diagnostics["diagnostics_status"] == "UNHEALTHY"


@pytest.mark.parametrize(
    "changes",
    [
        {"admission_status": "UNAVAILABLE"},
        {"admission_status": None},
        {"diagnostics_status": "DEGRADED"},
        {"diagnostics_status": "NO_MATERIAL"},
    ],
)
def test_service_never_shows_ready_evidence_it_withholds(
    changes: dict[str, Any],
) -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 no withheld ready")

    result = _assemble(_with(pkg, **changes), verdict, audit)

    assert result["bundle_status"] == "UNAVAILABLE"
    # Coherent by construction: the same payload passes the strict contract.
    assert _SCHEMA_VALIDATE(result).bundle_status == "UNAVAILABLE"


def test_service_blank_task_163_attribution_is_not_ready() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 blank t163 attribution")

    result = _assemble(pkg, _with(verdict, provider_name=" ", model_name=" "), audit)

    assert result["bundle_status"] == "UNAVAILABLE"
    assert _SCHEMA_VALIDATE(result).bundle_status == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Category 12 — Bidirectional aggregate BLOCKED invariant (direct schema)
# ---------------------------------------------------------------------------

_BLOCKING_CHANGES: dict[str, dict[str, Any]] = {
    "slice_status": {"slice_status": "BLOCKED"},
    "admission_status": {"admission_status": "BLOCKED"},
    "diagnostics_status": {"diagnostics_status": "UNHEALTHY"},
    "request_audit_status": {"request_audit_status": "INCONSISTENT"},
    "proposal_audit_status": {"proposal_audit_status": "INCONSISTENT"},
}


def test_schema_rejects_unavailable_bundle_with_all_ready_evidence() -> None:
    forged = {**_genuine_ready_bundle(), "bundle_status": "UNAVAILABLE"}
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE(forged)


@pytest.mark.parametrize("blocker", sorted(_BLOCKING_CHANGES))
def test_schema_rejects_unavailable_bundle_with_a_published_blocking_state(
    blocker: str,
) -> None:
    forged = {
        **_genuine_ready_bundle(),
        **_BLOCKING_CHANGES[blocker],
        "bundle_status": "UNAVAILABLE",
    }
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE(forged)


@pytest.mark.parametrize("blocker", sorted(_BLOCKING_CHANGES))
def test_schema_rejects_unavailable_bundle_with_blocker_and_incomplete_evidence(
    blocker: str,
) -> None:
    # Incomplete evidence and an explaining bundle finding do not excuse a
    # published blocking state: BLOCKED outranks UNAVAILABLE.
    forged = {
        **_genuine_unavailable_bundle(),
        **_BLOCKING_CHANGES[blocker],
        "request_fingerprint": None,
        "bundle_findings": ["REQUEST_FINGERPRINT_MISSING_OR_MALFORMED"],
        "bundle_finding_count": 1,
        "bundle_status": "UNAVAILABLE",
    }
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE(forged)


@pytest.mark.parametrize("blocker", sorted(_BLOCKING_CHANGES))
def test_blocking_condition_holds_if_and_only_if_bundle_is_blocked(
    blocker: str,
) -> None:
    base = _genuine_ready_bundle()
    blocking = {**base, **_BLOCKING_CHANGES[blocker]}

    # Blocking condition present: only BLOCKED is coherent.
    assert _SCHEMA_VALIDATE({**blocking, "bundle_status": "BLOCKED"})
    for status in ("READY", "UNAVAILABLE"):
        with pytest.raises(ValidationError):
            _SCHEMA_VALIDATE({**blocking, "bundle_status": status})

    # No blocking condition: BLOCKED is never coherent; READY is.
    assert _SCHEMA_VALIDATE(base).bundle_status == "READY"
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE({**base, "bundle_status": "BLOCKED"})


def test_schema_blocked_precedence_survives_noncanonical_source_findings() -> None:
    # A blocked bundle that also names a forged source stays BLOCKED...
    bundle = {
        **_genuine_ready_bundle(),
        **_BLOCKING_CHANGES["slice_status"],
        "t162_audit_source": "FORGED",
        "bundle_findings": ["T162_AUDIT_SOURCE_NOT_CANONICAL"],
        "bundle_finding_count": 1,
        "bundle_status": "BLOCKED",
    }
    assert _SCHEMA_VALIDATE(bundle).bundle_status == "BLOCKED"
    # ...and cannot be downgraded to UNAVAILABLE.
    with pytest.raises(ValidationError):
        _SCHEMA_VALIDATE({**bundle, "bundle_status": "UNAVAILABLE"})


def test_service_blocked_precedence_matches_the_schema_predicate() -> None:
    _, pkg, verdict, audit = _produce_ready_inputs("Task 165 blocked precedence")
    forged_source_and_blocker = _with(
        pkg, audit_source="FORGED", request_audit_status="INCONSISTENT"
    )

    result = _assemble(forged_source_and_blocker, verdict, audit)

    assert result["bundle_status"] == "BLOCKED"
    assert "T162_AUDIT_SOURCE_NOT_CANONICAL" in result["bundle_findings"]
    assert _SCHEMA_VALIDATE(result).bundle_status == "BLOCKED"
