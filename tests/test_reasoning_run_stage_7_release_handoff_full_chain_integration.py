"""Task 191: full Stage 7 integration over the real Task 154-188 services.

Coverage starts at the Task 154 admission boundary and runs through Task 188.
The Task 153 entry boundary (``ReasoningRunStage7EntryService``) is not
invoked here and is not claimed as covered.

The genuine material is produced once, up front, with the real Stage 7
services and a test-only fake provider; every downstream boundary is
then exercised purely on the already-published real results. Only the
genuine external I/O boundaries (Stage 6 certification and the LLM
provider) use test doubles. No real provider, network, or database
beyond the session-level in-memory test infrastructure is used.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionRead,
)

# Canonical schema aliases for validation between real boundaries.
from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    ReasoningRunStage7EvidenceBundleRead as _B165,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (  # noqa: E402
    ReasoningRunStage7EvidenceBundleAuditRead as _A166,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (  # noqa: E402
    ReasoningRunStage7EvidenceBundleAuditConsistencyRead as _C167,
)
from rop.schemas.reasoning_run_stage_7_evidence_package import (  # noqa: E402
    ReasoningRunStage7EvidencePackageRead as _PKG168,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit import (  # noqa: E402
    ReasoningRunStage7EvidencePackageAuditRead as _A169,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit_consistency import (  # noqa: E402,E501
    ReasoningRunStage7EvidencePackageAuditConsistencyRead as _C170,
)
from rop.schemas.reasoning_run_stage_7_final_attestation_audit import (  # noqa: E402
    ReasoningRunStage7FinalAttestationAuditRead as _AT172,
)
from rop.schemas.reasoning_run_stage_7_final_attestation_consistency import (  # noqa: E402,E501
    ReasoningRunStage7FinalAttestationConsistencyRead as _AT173,
)
from rop.schemas.reasoning_run_stage_7_final_evidence_attestation import (  # noqa: E402
    ReasoningRunStage7FinalEvidenceAttestationRead as _AT171,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_audit import (  # noqa: E402
    ReasoningRunStage7FinalReleaseGateAuditRead as _A184,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_audit_consistency import (  # noqa: E402
    ReasoningRunStage7FinalReleaseGateAuditConsistencyRead as _C185,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_projection import (  # noqa: E402
    ReasoningRunStage7FinalReleaseGateProjectionRead as _P183,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package import (  # noqa: E402
    ReasoningRunStage7ReleaseHandoffEvidencePackageRead as _P186,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit import (  # noqa: E402
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead as _A187,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit_consistency import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead as _C188,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (  # noqa: E402
    ReasoningRunStage7ReleaseReadinessAuditRead as _A175,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit_consistency import (  # noqa: E402
    ReasoningRunStage7ReleaseReadinessAuditConsistencyRead as _C176,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle import (  # noqa: E402
    ReasoningRunStage7ReleaseReadinessEvidenceBundleRead as _B177,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (  # noqa: E402
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead as _A178,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead as _C179,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation import (  # noqa: E402
    ReasoningRunStage7ReleaseReadinessFinalAttestationRead as _A180,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_audit import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead as _A181,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_consistency import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead as _C182,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (  # noqa: E402
    ReasoningRunStage7ReleaseReadinessProjectionRead as _P174,
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
from rop.services.reasoning_run_stage_7_evidence_bundle import (
    ReasoningRunStage7EvidenceBundleService,
)
from rop.services.reasoning_run_stage_7_evidence_bundle_audit import (
    ReasoningRunStage7EvidenceBundleAuditService,
)
from rop.services.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    ReasoningRunStage7EvidenceBundleAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_evidence_package import (
    ReasoningRunStage7EvidencePackageService,
)
from rop.services.reasoning_run_stage_7_evidence_package_audit import (
    ReasoningRunStage7EvidencePackageAuditService,
)
from rop.services.reasoning_run_stage_7_evidence_package_audit_consistency import (
    ReasoningRunStage7EvidencePackageAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_final_attestation_audit import (
    ReasoningRunStage7FinalAttestationAuditService,
)
from rop.services.reasoning_run_stage_7_final_attestation_consistency import (
    ReasoningRunStage7FinalAttestationConsistencyService,
)
from rop.services.reasoning_run_stage_7_final_evidence_attestation import (
    ReasoningRunStage7FinalEvidenceAttestationService,
)
from rop.services.reasoning_run_stage_7_final_release_gate_audit import (
    ReasoningRunStage7FinalReleaseGateAuditService,
)
from rop.services.reasoning_run_stage_7_final_release_gate_audit_consistency import (
    ReasoningRunStage7FinalReleaseGateAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_final_release_gate_projection import (
    ReasoningRunStage7FinalReleaseGateProjectionService,
)
from rop.services.reasoning_run_stage_7_proposal import (
    ReasoningRunStage7ProposalService,
)
from rop.services.reasoning_run_stage_7_proposal_audit import (
    ReasoningRunStage7ProposalAuditService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package_audit import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_audit import (
    ReasoningRunStage7ReleaseReadinessAuditService,
)
from rop.services.reasoning_run_stage_7_release_readiness_audit_consistency import (
    ReasoningRunStage7ReleaseReadinessAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleService,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_final_attestation import (
    ReasoningRunStage7ReleaseReadinessFinalAttestationService,
)
from rop.services.reasoning_run_stage_7_release_readiness_final_attestation_audit import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService,
)
from rop.services.reasoning_run_stage_7_release_readiness_final_attestation_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_projection import (
    ReasoningRunStage7ReleaseReadinessProjectionService,
)
from rop.services.reasoning_run_stage_7_request import ReasoningRunStage7RequestService
from rop.services.reasoning_run_stage_7_request_audit import (
    ReasoningRunStage7RequestAuditService,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceService,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    ReasoningRunStage7VerticalSliceAuditService,
)

# ---------------------------------------------------------------------------
# In-memory DB and test client setup (mirrors upstream Stage 7 test projects)
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

    def __init__(self, text: str) -> None:
        self.provider_name = "fake-provider"
        self.model_name = "fake-model"
        self._text = text
        self.calls: list[object] = []

    def generate_reasoning(self, request: object) -> object:
        self.calls.append(request)
        return LLMReasoningProviderResponse(
            provider="fake-provider",
            model="fake-model",
            text=self._text,
        )


class _FailingProvider:
    """Test-only provider that raises one canonical outage failure."""

    def __init__(self) -> None:
        self.provider_name = "failing-provider"
        self.model_name = "failing-model"
        self.calls: list[object] = []

    def generate_reasoning(self, request: object) -> object:
        self.calls.append(request)
        raise LLMReasoningProviderError("connection to model host failed")


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
            "metadata": {"source": "stage-7-full-chain-integration"},
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
# Real Stage 7 material production (Tasks 154-164)
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


def _healthy_pkg162(db: Session, sid: str) -> tuple[dict, dict, dict, dict]:
    """Produce the real Task 162 audit package plus Request/Proposal audits."""
    context = _context(db, sid)
    provider = _FakeProvider(_valid_model_output(context))
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
    return package, request_audit, proposal_result, proposal_audit


def _diagnose(package, request_audit, proposal_result, proposal_audit) -> dict:
    return ReasoningRunStage7DiagnosticsService.diagnose(
        request_package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
    )


def _pkg162(admission, package, request_audit, proposal_result, proposal_audit, diag):
    return ReasoningRunStage7AuditPackageService.build(
        admission_result=admission,
        request_package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
        diagnostics_result=diag,
    )


def _certify(package) -> dict:
    return ReasoningRunStage7VerticalSliceService.certify(audit_package=package)


def _audit164(package, verdict) -> dict:
    return ReasoningRunStage7VerticalSliceAuditService.audit(
        audit_package=package, vertical_slice=verdict
    )


# ---------------------------------------------------------------------------
# Real Task 165-170 production helpers
# ---------------------------------------------------------------------------


def _produce_upstream_ready(label: str) -> dict[str, object]:
    """Run the real Task 154-164 services for a READY session."""
    sid = _seed_full_session(label)
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit = _healthy_pkg162(
            db, sid
        )
    diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
    pkg162 = _pkg162(
        admission, package, request_audit, proposal_result, proposal_audit, diagnostics
    )
    verdict163 = _certify(pkg162)
    assert verdict163["slice_status"] == "READY"
    audit164 = _audit164(pkg162, verdict163)
    assert audit164["slice_audit_status"] == "CONSISTENT"
    return {
        "session_id": sid,
        "pkg162": pkg162,
        "slice163": verdict163,
        "audit164": audit164,
    }


def _produce_upstream_unavailable(label: str) -> dict[str, object]:
    """Run the real Task 154-164 services for genuinely missing material.

    The diagnostics result is produced by the real Task 161 service from
    genuinely absent downstream material, so the Task 162-164 records are
    a schema-valid UNAVAILABLE business state (not a blocking one).
    """
    sid = _seed_full_session(label)
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
    # A validated BLOCKED admission is a blocking state; here the material
    # itself is genuinely absent instead.
    diagnostics = _diagnose(None, None, None, None)
    assert diagnostics["diagnostics_status"] == "NO_MATERIAL"
    pkg162 = _pkg162(admission, None, None, None, None, diagnostics)
    verdict163 = _certify(pkg162)
    assert verdict163["slice_status"] == "UNAVAILABLE"
    audit164 = _audit164(pkg162, verdict163)
    assert audit164["slice_audit_status"] == "CONSISTENT"
    return {
        "session_id": sid,
        "pkg162": pkg162,
        "slice163": verdict163,
        "audit164": audit164,
    }


# ---------------------------------------------------------------------------
# Composition helpers: real Task 165-188 boundaries
# ---------------------------------------------------------------------------


def _validate(model: type[BaseModel], value: object) -> object:
    """Validate a real service result through its strict contract."""
    return model.model_validate(value).model_dump()


def _compose_full_chain(upstream: dict[str, object]) -> dict[str, object]:
    """Run the real Task 165-188 services in dependency order.

    ``upstream`` carries the real Task 162/163/164 dictionaries produced by
    the actual Task 154-164 services. Every later boundary is a real service
    call over the real outputs of the previous one.
    """
    from rop.schemas.reasoning_run_stage_7_audit_package import (
        ReasoningRunStage7AuditPackageRead as _AuditPackageRead,
    )
    from rop.schemas.reasoning_run_stage_7_vertical_slice import (
        ReasoningRunStage7VerticalSliceRead,
    )
    from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
        ReasoningRunStage7VerticalSliceAuditRead,
    )

    # Task 165 — evidence bundle over the real Task 162/163/164 records.
    bundle165 = ReasoningRunStage7EvidenceBundleService.assemble(
        pkg162=_AuditPackageRead.model_validate(upstream["pkg162"]),
        slice163=ReasoningRunStage7VerticalSliceRead.model_validate(
            upstream["slice163"]
        ),
        audit164=ReasoningRunStage7VerticalSliceAuditRead.model_validate(
            upstream["audit164"]
        ),
    )

    # Task 166 — independent bundle audit.
    audit166_dict = ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=bundle165)
    audit166 = _A166.model_validate(audit166_dict)

    # Task 167 — bundle-audit consistency.
    consistency167_dict = (
        ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
            bundle=bundle165, audit=audit166
        )
    )
    consistency167 = _C167.model_validate(consistency167_dict)

    # Task 168 — evidence package over the real Task 162-167 records.
    package168 = ReasoningRunStage7EvidencePackageService.assemble(
        pkg162=_AuditPackageRead.model_validate(upstream["pkg162"]),
        slice163=ReasoningRunStage7VerticalSliceRead.model_validate(
            upstream["slice163"]
        ),
        audit164=ReasoningRunStage7VerticalSliceAuditRead.model_validate(
            upstream["audit164"]
        ),
        bundle165=_B165.model_validate(bundle165),
        audit166=audit166,
        consistency167=consistency167,
    )

    # Task 169 — independent package audit.
    audit169 = ReasoningRunStage7EvidencePackageAuditService.audit(
        package=_PKG168.model_validate(package168),
        pkg162=_AuditPackageRead.model_validate(upstream["pkg162"]),
        slice163=ReasoningRunStage7VerticalSliceRead.model_validate(
            upstream["slice163"]
        ),
        audit164=ReasoningRunStage7VerticalSliceAuditRead.model_validate(
            upstream["audit164"]
        ),
        bundle165=_B165.model_validate(bundle165),
        audit166=audit166,
        consistency167=consistency167,
    )

    # Task 170 — package-audit consistency.
    consistency170_dict = (
        ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
            package=_PKG168.model_validate(package168),
            audit=_A169.model_validate(audit169),
        )
    )
    consistency170 = _C170.model_validate(consistency170_dict)

    # Task 171 — final evidence attestation over the real package/audit.
    attestation171 = ReasoningRunStage7FinalEvidenceAttestationService.attest(
        package=_PKG168.model_validate(package168),
        audit=_A169.model_validate(audit169),
        consistency=consistency170,
    )

    # Task 172 — independent final-attestation audit.
    audit172 = ReasoningRunStage7FinalAttestationAuditService.audit(
        package=_PKG168.model_validate(package168),
        audit=_A169.model_validate(audit169),
        consistency=consistency170,
        attestation=_AT171.model_validate(attestation171),
    )

    # Task 173 — final-attestation consistency.
    consistency173 = ReasoningRunStage7FinalAttestationConsistencyService.verify(
        attestation=_AT171.model_validate(attestation171),
        audit=_AT172.model_validate(audit172),
    )

    # Step 174 onward: reuse the downstream boundaries verified on main.
    projection174 = ReasoningRunStage7ReleaseReadinessProjectionService.project(
        attestation=_AT171.model_validate(attestation171),
        audit=_AT172.model_validate(audit172),
        consistency=_AT173.model_validate(consistency173),
    )
    audit175 = ReasoningRunStage7ReleaseReadinessAuditService.audit(
        attestation=_AT171.model_validate(attestation171),
        audit=_AT172.model_validate(audit172),
        consistency=_AT173.model_validate(consistency173),
        projection=_P174.model_validate(projection174),
    )
    consistency176 = ReasoningRunStage7ReleaseReadinessAuditConsistencyService.verify(
        projection=_P174.model_validate(projection174),
        audit=_A175.model_validate(audit175),
    )
    bundle177 = ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
        projection174=_P174.model_validate(projection174),
        audit175=_A175.model_validate(audit175),
        consistency176=_C176.model_validate(consistency176),
    )
    audit178 = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
        projection174=_P174.model_validate(projection174),
        audit175=_A175.model_validate(audit175),
        consistency176=_C176.model_validate(consistency176),
        bundle=_B177.model_validate(bundle177),
    )
    consistency179 = (
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService.verify(
            bundle=_B177.model_validate(bundle177),
            audit=_A178.model_validate(audit178),
        )
    )
    attestation180 = ReasoningRunStage7ReleaseReadinessFinalAttestationService.attest(
        bundle=_B177.model_validate(bundle177),
        audit=_A178.model_validate(audit178),
        consistency=_C179.model_validate(consistency179),
    )
    audit181 = ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService.audit(
        bundle=_B177.model_validate(bundle177),
        audit=_A178.model_validate(audit178),
        consistency=_C179.model_validate(consistency179),
        attestation=_A180.model_validate(attestation180),
    )
    consistency182 = (
        ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService.verify(
            attestation=_A180.model_validate(attestation180),
            audit=_A181.model_validate(audit181),
        )
    )
    projection183 = ReasoningRunStage7FinalReleaseGateProjectionService.project(
        attestation=_A180.model_validate(attestation180),
        audit=_A181.model_validate(audit181),
        consistency=_C182.model_validate(consistency182),
    )
    audit184 = ReasoningRunStage7FinalReleaseGateAuditService.audit(
        attestation=_A180.model_validate(attestation180),
        audit=_A181.model_validate(audit181),
        consistency=_C182.model_validate(consistency182),
        projection=_P183.model_validate(projection183),
    )
    consistency185 = ReasoningRunStage7FinalReleaseGateAuditConsistencyService.verify(
        projection=_P183.model_validate(projection183),
        audit=_A184.model_validate(audit184),
    )
    package186 = ReasoningRunStage7ReleaseHandoffEvidencePackageService.assemble(
        projection=_P183.model_validate(projection183),
        audit=_A184.model_validate(audit184),
        consistency=_C185.model_validate(consistency185),
    )
    audit187 = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
        projection=_P183.model_validate(projection183),
        audit=_A184.model_validate(audit184),
        consistency=_C185.model_validate(consistency185),
        package=_P186.model_validate(package186),
    )
    consistency188 = (
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService.verify(
            package=_P186.model_validate(package186),
            audit=_A187.model_validate(audit187),
        )
    )
    return {
        "session_id": upstream["session_id"],
        "bundle165": _validate(_B165, bundle165),
        "audit166": _validate(_A166, audit166),
        "consistency167": _validate(_C167, consistency167),
        "package168": _validate(_PKG168, package168),
        "audit169": _validate(_A169, audit169),
        "consistency170": _validate(_C170, consistency170),
        "attestation171": _validate(_AT171, attestation171),
        "audit172": _validate(_AT172, audit172),
        "consistency173": _validate(_AT173, consistency173),
        "projection174": _validate(_P174, projection174),
        "audit175": _validate(_A175, audit175),
        "consistency176": _validate(_C176, consistency176),
        "bundle177": _validate(_B177, bundle177),
        "audit178": _validate(_A178, audit178),
        "consistency179": _validate(_C179, consistency179),
        "attestation180": _validate(_A180, attestation180),
        "audit181": _validate(_A181, audit181),
        "consistency182": _validate(_C182, consistency182),
        "projection183": _validate(_P183, projection183),
        "audit184": _validate(_A184, audit184),
        "consistency185": _validate(_C185, consistency185),
        "package186": _validate(_P186, package186),
        "audit187": _validate(_A187, audit187),
        "consistency188": _validate(_C188, consistency188),
    }


def _upstream_block(status: str):
    """Produce Task 162-164 records honoring the resolved upstream status."""
    if status == "READY":
        return _produce_upstream_ready("Task 191 READY")
    return _produce_upstream_unavailable("Task 191 UNAVAILABLE")


def test_full_chain_ready_path_reaches_consistent_handoff():
    """The real Task 154-188 services reach a consistent READY handoff."""
    chain = _compose_full_chain(_upstream_block("READY"))

    # Task 165-167 boundaries on the real bundle.
    assert chain["bundle165"]["bundle_status"] == "READY"
    assert chain["audit166"]["bundle_audit_status"] == "CONSISTENT"
    assert chain["consistency167"]["consistency_status"] == "CONSISTENT"

    # Task 168-170 on the real package.
    assert chain["package168"]["package_status"] == "READY"
    assert chain["audit169"]["package_audit_status"] == "CONSISTENT"
    assert chain["consistency170"]["consistency_status"] == "CONSISTENT"

    # Task 171-173 real attestation boundaries.
    assert chain["attestation171"]["attestation_status"] == "CERTIFIED"
    assert chain["audit172"]["attestation_audit_status"] == "CONSISTENT"
    assert chain["consistency173"]["consistency_status"] == "CONSISTENT"

    # Task 174-179 release-readiness boundaries.
    assert chain["projection174"]["readiness_status"] == "READY"
    assert chain["audit175"]["readiness_audit_status"] == "CONSISTENT"
    assert chain["consistency176"]["consistency_status"] == "CONSISTENT"
    assert chain["bundle177"]["bundle_status"] == "READY"
    assert chain["audit178"]["bundle_audit_status"] == "CONSISTENT"
    assert chain["consistency179"]["consistency_status"] == "CONSISTENT"

    # Task 180-182 final-attestation boundaries.
    assert chain["attestation180"]["attestation_status"] == "CERTIFIED"
    assert chain["audit181"]["attestation_audit_status"] == "CONSISTENT"
    assert chain["consistency182"]["attestation_consistency_status"] == "CONSISTENT"

    # Task 183-185 gate boundaries.
    assert chain["projection183"]["gate_status"] == "READY"
    assert chain["audit184"]["gate_audit_status"] == "CONSISTENT"
    assert chain["consistency185"]["gate_consistency_status"] == "CONSISTENT"

    # Task 186-188 handoff boundaries.
    assert chain["package186"]["package_status"] == "READY"
    assert chain["audit187"]["package_audit_status"] == "CONSISTENT"
    assert chain["consistency188"]["consistency_status"] == "CONSISTENT"


def test_full_chain_ready_session_id_is_preserved_through_handoff():
    """The real session identity flows through every boundary unchecked."""
    chain = _compose_full_chain(_upstream_block("READY"))
    for boundary in (
        "bundle165",
        "audit166",
        "consistency167",
        "package168",
        "audit169",
        "consistency170",
        "attestation171",
        "audit172",
        "consistency173",
        "projection174",
        "bundle177",
        "attestation180",
        "projection183",
        "package186",
        "consistency188",
    ):
        assert chain[boundary]["session_id"] == chain["session_id"]


def test_full_chain_ready_composition_is_deterministic():
    """Running the whole composition twice on the same upstream is stable."""
    upstream = _upstream_block("READY")
    first = _compose_full_chain(upstream)
    second = _compose_full_chain(upstream)
    for boundary in (
        "bundle165",
        "audit166",
        "consistency167",
        "package168",
        "audit169",
        "consistency170",
        "attestation171",
        "audit172",
        "consistency173",
        "projection174",
        "audit175",
        "consistency176",
        "bundle177",
        "audit178",
        "consistency179",
        "attestation180",
        "audit181",
        "consistency182",
        "projection183",
        "audit184",
        "consistency185",
        "package186",
        "audit187",
        "consistency188",
    ):
        assert first[boundary] == second[boundary]


# ---------------------------------------------------------------------------
# Task 192: genuine BLOCKED and UNAVAILABLE propagation over real services
# ---------------------------------------------------------------------------


def _blocked_upstream() -> dict[str, object]:
    """Genuine Task 162-164 records produced from a real BLOCKED admission.

    The real Task 154 admission service is given a non-certified Stage 6
    verdict (the test-only certification stub reports ``NO_MATERIAL``), so
    the BLOCKED admission is the service's own decision. The downstream
    material is genuinely absent, the Task 161 diagnostics are produced by
    the real service, and the Task 162-164 records are built by the real
    services. No finished record is edited after the fact.
    """
    sid = _seed_full_session("Task 192 blocked upstream")
    with TestingSessionLocal() as db:
        admission = ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("NO_MATERIAL")
        ).evaluate(db, UUID(sid))
    assert admission["admission_status"] == "BLOCKED"
    assert admission["admitted"] is False
    assert admission["stage_6_certification_status"] == "NO_MATERIAL"
    assert admission["stage_6_certification_consistent"] is True
    assert admission["findings"] == ["STAGE_6_CERTIFICATION_NOT_CERTIFIED:NO_MATERIAL"]
    validated_admission = ReasoningRunStage7AdmissionRead.model_validate(admission)
    assert validated_admission.model_dump() == admission

    diagnostics = _diagnose(None, None, None, None)
    assert diagnostics["diagnostics_status"] == "NO_MATERIAL"
    pkg162 = _pkg162(admission, None, None, None, None, diagnostics)
    assert pkg162["admission_status"] == "BLOCKED"
    verdict163 = _certify(pkg162)
    assert verdict163["slice_status"] == "BLOCKED"
    audit164 = _audit164(pkg162, verdict163)
    return {
        "session_id": sid,
        "pkg162": pkg162,
        "slice163": verdict163,
        "audit164": audit164,
    }


# Every business-status boundary from Task 165 through Task 188.
_BUSINESS_BOUNDARIES = (
    ("bundle165", "bundle_status"),
    ("package168", "package_status"),
    ("attestation171", "attestation_status"),
    ("projection174", "readiness_status"),
    ("bundle177", "bundle_status"),
    ("attestation180", "attestation_status"),
    ("projection183", "gate_status"),
    ("package186", "package_status"),
)

# Every audit/consistency boundary: (boundary, status field, published/expected
# field suffix or None when the contract does not publish that pair).
_VERIFICATION_BOUNDARIES = (
    ("audit166", "bundle_audit_status", "bundle_status"),
    ("consistency167", "consistency_status", None),
    ("audit169", "package_audit_status", "package_status"),
    ("consistency170", "consistency_status", None),
    ("audit172", "attestation_audit_status", "attestation_status"),
    ("consistency173", "consistency_status", None),
    ("audit175", "readiness_audit_status", "readiness_status"),
    ("consistency176", "consistency_status", None),
    ("audit178", "bundle_audit_status", "bundle_status"),
    ("consistency179", "consistency_status", None),
    ("audit181", "attestation_audit_status", "attestation_status"),
    ("consistency182", "attestation_consistency_status", "attestation_status"),
    ("audit184", "gate_audit_status", "gate_status"),
    ("consistency185", "gate_consistency_status", "gate_status"),
    ("audit187", "package_audit_status", "package_status"),
    ("consistency188", "consistency_status", None),
)


def _assert_status_propagates(chain: dict[str, object], status: str) -> None:
    """Assert one business status and its verified audits at every boundary.

    The business result must equal ``status`` at each Task 165-188 business
    boundary. Every audit and consistency record must verify that exact
    published status (CONSISTENT, with published == expected == ``status``
    wherever the contract exposes the pair), and the status must never
    become READY anywhere in the chain.
    """
    for boundary, field in _BUSINESS_BOUNDARIES:
        assert chain[boundary][field] == status, (boundary, field)

    for boundary, field, pair in _VERIFICATION_BOUNDARIES:
        record = chain[boundary]
        assert record[field] == "CONSISTENT", (boundary, field)
        assert record["available"] is True, boundary
        assert record["consistent"] is True, boundary
        assert record["finding_count"] == 0, boundary
        if pair is not None:
            assert record[f"published_{pair}"] == status, boundary
            assert record[f"expected_{pair}"] == status, boundary

    # The final-attestation boundaries expose availability separately from
    # the verification of their audit records.
    for boundary in ("attestation171", "attestation180"):
        assert chain[boundary]["available"] is (status != "UNAVAILABLE"), boundary

    # Upstream context carried into the package/projection boundaries.
    assert chain["bundle165"]["slice_status"] == status
    assert chain["bundle165"]["slice_audit_status"] == "CONSISTENT"
    assert chain["package168"]["t163_slice_status"] == status
    assert chain["package168"]["t165_bundle_status"] == status
    assert chain["package168"]["t167_consistency_status"] == "CONSISTENT"
    assert chain["attestation171"]["package_status"] == status
    assert chain["attestation180"]["bundle_status"] == status
    assert chain["package186"]["t183_gate_status"] == status
    assert chain["package186"]["t185_gate_consistency_status"] == "CONSISTENT"

    # The status can never be promoted to READY at any point in the chain.
    for boundary, record in chain.items():
        if boundary == "session_id":
            continue
        for key, value in record.items():
            assert value != "READY", (boundary, key)


def test_blocked_business_state_propagates_with_consistent_audits():
    """A genuine BLOCKED admission stays BLOCKED through the whole chain."""
    upstream = _blocked_upstream()
    # The real Task 163/164 records agree on the genuinely blocked upstream.
    assert upstream["pkg162"]["admission_status"] == "BLOCKED"
    assert upstream["slice163"]["slice_status"] == "BLOCKED"
    assert upstream["audit164"]["slice_audit_status"] == "CONSISTENT"
    assert upstream["audit164"]["published_slice_status"] == "BLOCKED"
    assert upstream["audit164"]["expected_slice_status"] == "BLOCKED"

    chain = _compose_full_chain(upstream)
    _assert_status_propagates(chain, "BLOCKED")
    assert chain["bundle165"]["admission_status"] == "BLOCKED"
    assert chain["package168"]["t162_admission_status"] == "BLOCKED"
    assert chain["session_id"] == upstream["session_id"]


def test_unavailable_business_state_fails_closed_to_handoff():
    """Genuinely unavailable upstream evidence stays UNAVAILABLE, not READY."""
    upstream = _produce_upstream_unavailable("Task 192 fail closed")
    chain = _compose_full_chain(upstream)
    _assert_status_propagates(chain, "UNAVAILABLE")
    # UNAVAILABLE is an admitted session with genuinely absent material; it is
    # neither promoted to READY nor converted into a BLOCKED state, while its
    # audit records remain verifiable as CONSISTENT.
    assert chain["bundle165"]["admission_status"] == "ADMITTED"
    assert chain["package168"]["t162_admission_status"] == "ADMITTED"
    assert chain["package186"]["package_status"] not in {"READY", "BLOCKED"}
    assert chain["consistency188"]["consistency_status"] == "CONSISTENT"
    assert chain["consistency188"]["available"] is True
    assert chain["session_id"] == upstream["session_id"]


# ---------------------------------------------------------------------------
# Task 193: contradiction precedence through independent audit boundaries
# ---------------------------------------------------------------------------


def _audit_task_169_package(
    upstream: dict[str, object],
    chain: dict[str, object],
    package: object,
) -> dict[str, object]:
    """Audit a published Task 168 package against the chain's real inputs."""
    from rop.schemas.reasoning_run_stage_7_audit_package import (
        ReasoningRunStage7AuditPackageRead,
    )
    from rop.schemas.reasoning_run_stage_7_vertical_slice import (
        ReasoningRunStage7VerticalSliceRead,
    )
    from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
        ReasoningRunStage7VerticalSliceAuditRead,
    )

    return ReasoningRunStage7EvidencePackageAuditService.audit(
        package=package,
        pkg162=ReasoningRunStage7AuditPackageRead.model_validate(upstream["pkg162"]),
        slice163=ReasoningRunStage7VerticalSliceRead.model_validate(
            upstream["slice163"]
        ),
        audit164=ReasoningRunStage7VerticalSliceAuditRead.model_validate(
            upstream["audit164"]
        ),
        bundle165=_B165.model_validate(chain["bundle165"]),
        audit166=_A166.model_validate(chain["audit166"]),
        consistency167=_C167.model_validate(chain["consistency167"]),
    )


def _compose_gate_handoff_from_projection(
    chain: dict[str, object],
    projection: object,
) -> dict[str, object]:
    """Re-run real Tasks 184-188 against a supplied published Task 183 record."""
    attestation = _A180.model_validate(chain["attestation180"])
    audit181 = _A181.model_validate(chain["audit181"])
    consistency182 = _C182.model_validate(chain["consistency182"])

    audit184 = _A184.model_validate(
        ReasoningRunStage7FinalReleaseGateAuditService.audit(
            attestation=attestation,
            audit=audit181,
            consistency=consistency182,
            projection=projection,
        )
    )
    consistency185 = _C185.model_validate(
        ReasoningRunStage7FinalReleaseGateAuditConsistencyService.verify(
            projection=projection,
            audit=audit184,
        )
    )
    package186 = _P186.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageService.assemble(
            projection=projection,
            audit=audit184,
            consistency=consistency185,
        )
    )
    audit187 = _A187.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
            projection=projection,
            audit=audit184,
            consistency=consistency185,
            package=package186,
        )
    )
    consistency188 = _C188.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService.verify(
            package=package186,
            audit=audit187,
        )
    )
    return {
        "audit184": audit184,
        "consistency185": consistency185,
        "package186": package186,
        "audit187": audit187,
        "consistency188": consistency188,
    }


def test_unavailable_published_gate_status_does_not_hide_readable_contradiction():
    """Task 184-188 retain proof that an UNAVAILABLE claim contradicts READY inputs."""
    upstream = _produce_upstream_ready("Task 193 unavailable-status contradiction")
    chain = _compose_full_chain(upstream)
    projection = _P183.model_validate(chain["projection183"])
    assert projection.gate_status == "READY"

    # Simulate a post-publication status corruption. All independently
    # produced Task 180-182 evidence remains genuine and bound to this session.
    projection.gate_status = "UNAVAILABLE"
    result = _compose_gate_handoff_from_projection(chain, projection)

    audit184 = result["audit184"]
    assert audit184.gate_audit_status == "INCONSISTENT"
    assert audit184.published_gate_status == "UNAVAILABLE"
    assert audit184.expected_gate_status == "READY"
    assert "GATE_STATUS_MISMATCH" in audit184.findings

    consistency185 = result["consistency185"]
    assert consistency185.gate_consistency_status == "INCONSISTENT"
    assert "EXPECTED_STATUS_CONTRADICTION" in consistency185.findings

    # The aggregate cannot erase the contradiction just because the published
    # gate status says UNAVAILABLE.
    audit187 = result["audit187"]
    assert audit187.package_audit_status == "INCONSISTENT"
    assert "T184_AUDIT_INCONSISTENT" in audit187.findings
    assert "T185_CONSISTENCY_INCONSISTENT" in audit187.findings

    consistency188 = result["consistency188"]
    assert consistency188.consistency_status == "INCONSISTENT"
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency188.findings
    assert "AUDIT_INCONSISTENT" in consistency188.findings


def test_task_169_detects_published_package_status_vs_independent_expectation():
    """A forged Task 168 status is INCONSISTENT, not an unavailable audit."""
    upstream = _produce_upstream_ready("Task 193 Task 168 status mismatch")
    chain = _compose_full_chain(upstream)
    package = _PKG168.model_validate(chain["package168"])
    package.package_status = "BLOCKED"

    audit = _A169.model_validate(_audit_task_169_package(upstream, chain, package))
    assert audit.package_audit_status == "INCONSISTENT"
    assert audit.published_package_status == "BLOCKED"
    assert audit.expected_package_status == "READY"
    assert "PACKAGE_STATUS_MISMATCH" in audit.findings


def test_task_170_preserves_a_bound_audit_of_inconsistent_package_evidence():
    """A same-session audit can correctly report package-content inconsistency."""
    upstream = _produce_upstream_ready("Task 193 Task 170 bound audit")
    chain = _compose_full_chain(upstream)
    package = _PKG168.model_validate(chain["package168"])

    # Corrupt one published copy of upstream provenance without changing the
    # independently produced Task 162 source value.
    package.t162_audit_source = "FORGED_TASK_162_SOURCE"
    audit = _A169.model_validate(_audit_task_169_package(upstream, chain, package))

    assert audit.package_audit_status == "INCONSISTENT"
    assert audit.session_id == package.session_id
    assert audit.published_package_status == "READY"
    assert audit.expected_package_status == "READY"
    assert "T162_AUDIT_SOURCE_MISMATCH" in audit.findings

    consistency = _C170.model_validate(
        ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
            package=package,
            audit=audit,
        )
    )
    assert consistency.consistency_status == "INCONSISTENT"
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency.findings
    assert "AUDIT_UNAVAILABLE" not in consistency.findings


def test_unreadable_handoff_audit_remains_unavailable_without_invented_conflict():
    """Unreadable audit inputs cannot prove a contradiction or a successful binding."""
    chain = _compose_full_chain(
        _produce_upstream_ready("Task 193 unreadable Task 187 evidence")
    )
    projection = _P183.model_validate(chain["projection183"])
    consistency185 = _C185.model_validate(chain["consistency185"])
    package = _P186.model_validate(chain["package186"])

    audit187_payload = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
        projection=projection,
        audit=object(),
        consistency=consistency185,
        package=package,
    )
    audit187 = _A187.model_validate(audit187_payload)
    assert audit187.package_audit_status == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in audit187.findings

    consistency188 = _C188.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService.verify(
            package=package,
            audit=audit187,
        )
    )
    assert consistency188.consistency_status == "UNAVAILABLE"
    assert consistency188.findings == ["AUDIT_UNAVAILABLE"]


def test_valid_handoff_audit_attached_to_another_package_is_inconsistent():
    """A valid audit cannot be reused to certify a different session's package."""
    first = _compose_full_chain(
        _produce_upstream_ready("Task 193 original audited package")
    )
    second = _compose_full_chain(
        _produce_upstream_ready("Task 193 detached package")
    )
    audit = _A187.model_validate(first["audit187"])
    different_package = _P186.model_validate(second["package186"])
    assert audit.package_audit_status == "CONSISTENT"
    assert audit.session_id != different_package.session_id

    consistency = _C188.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService.verify(
            package=different_package,
            audit=audit,
        )
    )
    assert consistency.consistency_status == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency.findings
    assert "AUDIT_UNAVAILABLE" not in consistency.findings


def test_task_188_preserves_bound_inconsistent_handoff_audit():
    """A readable, same-package status contradiction stays INCONSISTENT downstream."""
    chain = _compose_full_chain(
        _produce_upstream_ready("Task 193 Task 188 inconsistent audit")
    )
    projection = _P183.model_validate(chain["projection183"])
    audit184 = _A184.model_validate(chain["audit184"])
    consistency185 = _C185.model_validate(chain["consistency185"])
    package = _P186.model_validate(chain["package186"])
    assert package.package_status == "READY"

    # The audit receives the exact package and child evidence; only the
    # published package status is corrupted after construction.
    package.package_status = "BLOCKED"
    audit187 = _A187.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
            projection=projection,
            audit=audit184,
            consistency=consistency185,
            package=package,
        )
    )
    assert audit187.package_audit_status == "INCONSISTENT"
    assert audit187.session_id == package.session_id
    assert audit187.published_package_status == "BLOCKED"
    assert audit187.expected_package_status == "READY"

    consistency188 = _C188.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService.verify(
            package=package,
            audit=audit187,
        )
    )
    assert consistency188.consistency_status == "INCONSISTENT"
    assert "EXPECTED_STATUS_CONTRADICTION" in consistency188.findings
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency188.findings
    assert "AUDIT_UNAVAILABLE" not in consistency188.findings

