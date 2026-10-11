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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionRead,
)
from rop.schemas.reasoning_run_stage_7_entry import ReasoningRunStage7EntryRead

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
from rop.services.reasoning_run_stage_6_certification import (
    ReasoningRunStage6CertificationContractError,
)
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
from rop.services.reasoning_run_stage_7_entry import ReasoningRunStage7EntryService
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


class _UnreadableCertification:
    """Reports an unreadable Stage 6 boundary without fabricating a verdict."""

    def __init__(self) -> None:
        self.calls: list[UUID] = []

    def certify(self, db: Session, session_id: UUID) -> dict[str, object]:
        self.calls.append(session_id)
        raise ReasoningRunStage6CertificationContractError(
            "GATE_UNREADABLE", "test-only Stage 6 boundary outage"
        )


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


def _healthy_pkg162(
    db: Session, sid: str, *, provider_explanation: str = ""
) -> tuple[dict, dict, dict, dict]:
    """Produce the real Task 162 audit package plus Request/Proposal audits."""
    context = _context(db, sid)
    provider = _FakeProvider(
        _valid_model_output(context, explanation=provider_explanation)
    )
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


def _produce_upstream_ready(
    label: str, *, provider_explanation: str = ""
) -> dict[str, object]:
    """Run the real Task 154-164 services for a READY session."""
    sid = _seed_full_session(label)
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit = _healthy_pkg162(
            db, sid, provider_explanation=provider_explanation
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
    assert "EXPECTED_STATUS_MISMATCH" in consistency185.findings

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
    """Unreadable audit evidence cannot prove a conflict or successful binding."""
    chain = _compose_full_chain(
        _produce_upstream_ready("Task 193 unreadable Task 187 evidence")
    )
    projection = _P183.model_validate(chain["projection183"])
    consistency185 = _C185.model_validate(chain["consistency185"])
    package = _P186.model_validate(chain["package186"])

    audit187_payload = (
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
            projection=projection,
            audit=object(),
            consistency=consistency185,
            package=package,
        )
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
    second = _compose_full_chain(_produce_upstream_ready("Task 193 detached package"))
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


# ---------------------------------------------------------------------------
# Task 194: session identity and fingerprint binding
# ---------------------------------------------------------------------------


def test_ready_chain_preserves_one_session_and_canonical_fingerprint_verbatim():
    """Every session echo agrees and fingerprint copies remain byte-for-byte equal."""
    upstream = _produce_upstream_ready("Task 194 identity and fingerprint")
    chain = _compose_full_chain(upstream)
    session_id = upstream["session_id"]
    fingerprint = upstream["pkg162"]["request_fingerprint"]

    assert session_id
    assert isinstance(fingerprint, str)
    assert len(fingerprint) == 64
    assert all(character in "0123456789abcdef" for character in fingerprint)

    for boundary in ("pkg162", "slice163", "audit164"):
        assert upstream[boundary]["session_id"] == session_id

    for boundary, record in chain.items():
        if boundary != "session_id":
            assert record["session_id"] == session_id, boundary

    assert chain["bundle165"]["request_fingerprint"] == fingerprint
    assert chain["audit166"]["audited_bundle"]["request_fingerprint"] == fingerprint
    assert chain["package168"]["t162_request_fingerprint"] == fingerprint
    assert (
        chain["package168"]["t165_bundle_evidence"]["request_fingerprint"]
        == fingerprint
    )
    assert (
        chain["package168"]["t166_audited_bundle"]["request_fingerprint"] == fingerprint
    )


def _bundle165_from_upstream(upstream: dict[str, object]) -> dict[str, object]:
    """Run the real Task 165 service over the supplied Task 162-164 records."""
    from rop.schemas.reasoning_run_stage_7_audit_package import (
        ReasoningRunStage7AuditPackageRead,
    )
    from rop.schemas.reasoning_run_stage_7_vertical_slice import (
        ReasoningRunStage7VerticalSliceRead,
    )
    from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
        ReasoningRunStage7VerticalSliceAuditRead,
    )

    return ReasoningRunStage7EvidenceBundleService.assemble(
        pkg162=ReasoningRunStage7AuditPackageRead.model_validate(upstream["pkg162"]),
        slice163=ReasoningRunStage7VerticalSliceRead.model_validate(
            upstream["slice163"]
        ),
        audit164=ReasoningRunStage7VerticalSliceAuditRead.model_validate(
            upstream["audit164"]
        ),
    )


def _assert_identity_failure_halts_chain(upstream: dict[str, object]) -> None:
    """An untrusted upstream identity can never reach a published handoff.

    Task 165 publishes UNAVAILABLE with no session identity, and the real
    Task 175 audit contract then refuses to certify a record without an
    identity, so the composition halts before any READY handoff exists.
    """
    from rop.services.reasoning_run_stage_7_release_readiness_audit import (
        ReasoningRunStage7ReleaseReadinessAuditContractError,
    )

    bundle165 = _B165.model_validate(_bundle165_from_upstream(upstream))
    assert bundle165.bundle_status == "UNAVAILABLE"
    assert bundle165.session_id == ""

    with pytest.raises(
        ReasoningRunStage7ReleaseReadinessAuditContractError,
        match="CONSISTENT requires a session identity",
    ) as excinfo:
        _compose_full_chain(upstream)
    assert excinfo.value.invariant == "RELEASE_READINESS_AUDIT_RESULT_INVALID"


def test_mismatched_upstream_session_is_not_recovered_by_later_boundaries():
    """A detached Task 163 identity fails closed and never reaches a handoff."""
    upstream = _produce_upstream_ready("Task 194 detached upstream session")
    upstream["slice163"]["session_id"] = "detached-session-194"

    _assert_identity_failure_halts_chain(upstream)

    bundle165 = _bundle165_from_upstream(upstream)
    assert "detached-session-194" not in {
        value for value in bundle165.values() if isinstance(value, str)
    }


def test_empty_upstream_audit_identity_is_not_restored_downstream():
    """A genuine UNAVAILABLE Task 164 audit carries no session identity."""
    from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
        ReasoningRunStage7VerticalSliceAuditRead,
    )

    upstream = _produce_upstream_ready("Task 194 empty audit identity")
    unavailable_audit = ReasoningRunStage7VerticalSliceAuditService.audit()
    validated_audit = ReasoningRunStage7VerticalSliceAuditRead.model_validate(
        unavailable_audit
    )
    assert validated_audit.slice_audit_status == "UNAVAILABLE"
    assert validated_audit.session_id == ""
    upstream["audit164"] = validated_audit.model_dump()

    _assert_identity_failure_halts_chain(upstream)


def test_detached_task_184_audit_identity_stays_untrusted_through_task_188():
    """Later boundaries cannot repair a gate audit detached from its projection."""
    chain = _compose_full_chain(
        _produce_upstream_ready("Task 194 detached downstream audit")
    )
    projection = _P183.model_validate(chain["projection183"])
    audit184 = _A184.model_validate(chain["audit184"])
    assert audit184.gate_audit_status == "CONSISTENT"
    audit184.session_id = "detached-gate-audit-194"

    consistency185 = _C185.model_validate(
        ReasoningRunStage7FinalReleaseGateAuditConsistencyService.verify(
            projection=projection,
            audit=audit184,
        )
    )
    assert consistency185.gate_consistency_status == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency185.findings

    package186 = _P186.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageService.assemble(
            projection=projection,
            audit=audit184,
            consistency=consistency185,
        )
    )
    assert package186.package_status == "UNAVAILABLE"
    assert package186.session_id == ""

    audit187 = _A187.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
            projection=projection,
            audit=audit184,
            consistency=consistency185,
            package=package186,
        )
    )
    assert audit187.package_audit_status == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in audit187.findings

    consistency188 = _C188.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService.verify(
            package=package186,
            audit=audit187,
        )
    )
    assert consistency188.consistency_status == "INCONSISTENT"
    assert consistency188.session_id == ""
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency188.findings


def test_task_167_fingerprint_snapshot_mismatch_cannot_produce_ready_package():
    """A different canonical fingerprint is detected, not recomputed or repaired."""
    from rop.schemas.reasoning_run_stage_7_audit_package import (
        ReasoningRunStage7AuditPackageRead,
    )
    from rop.schemas.reasoning_run_stage_7_vertical_slice import (
        ReasoningRunStage7VerticalSliceRead,
    )
    from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
        ReasoningRunStage7VerticalSliceAuditRead,
    )

    upstream = _produce_upstream_ready("Task 194 fingerprint snapshot mismatch")
    chain = _compose_full_chain(upstream)
    original_fingerprint = upstream["pkg162"]["request_fingerprint"]
    bundle = _B165.model_validate(chain["bundle165"])
    audit = _A166.model_validate(chain["audit166"])
    replacement = "b" * 64 if original_fingerprint != "b" * 64 else "c" * 64
    bundle.request_fingerprint = replacement

    consistency167 = _C167.model_validate(
        ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
            bundle=bundle,
            audit=audit,
        )
    )
    assert consistency167.consistency_status == "INCONSISTENT"
    assert "BUNDLE_SNAPSHOT_MISMATCH" in consistency167.findings

    package168 = _PKG168.model_validate(
        ReasoningRunStage7EvidencePackageService.assemble(
            pkg162=ReasoningRunStage7AuditPackageRead.model_validate(
                upstream["pkg162"]
            ),
            slice163=ReasoningRunStage7VerticalSliceRead.model_validate(
                upstream["slice163"]
            ),
            audit164=ReasoningRunStage7VerticalSliceAuditRead.model_validate(
                upstream["audit164"]
            ),
            bundle165=bundle,
            audit166=audit,
            consistency167=consistency167,
        )
    )
    assert package168.package_status == "UNAVAILABLE"
    assert package168.t162_request_fingerprint == original_fingerprint
    assert package168.t165_bundle_evidence.request_fingerprint == replacement
    assert "T165_T162_EVIDENCE_MISMATCH" in package168.findings


def test_malformed_request_fingerprint_cannot_publish_ready_task_165_bundle():
    """Task 165 withholds a malformed fingerprint and fails closed."""
    from rop.schemas.reasoning_run_stage_7_audit_package import (
        ReasoningRunStage7AuditPackageRead,
    )
    from rop.schemas.reasoning_run_stage_7_vertical_slice import (
        ReasoningRunStage7VerticalSliceRead,
    )
    from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
        ReasoningRunStage7VerticalSliceAuditRead,
    )

    upstream = _produce_upstream_ready("Task 194 malformed fingerprint")
    package162 = ReasoningRunStage7AuditPackageRead.model_validate(upstream["pkg162"])
    package162.request_fingerprint = "not-a-canonical-fingerprint"

    bundle = ReasoningRunStage7EvidenceBundleService.assemble(
        pkg162=package162,
        slice163=ReasoningRunStage7VerticalSliceRead.model_validate(
            upstream["slice163"]
        ),
        audit164=ReasoningRunStage7VerticalSliceAuditRead.model_validate(
            upstream["audit164"]
        ),
    )
    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert bundle["request_fingerprint"] is None
    assert "REQUEST_FINGERPRINT_MISSING_OR_MALFORMED" in bundle["bundle_findings"]


# ---------------------------------------------------------------------------
# Task 195: provider attribution and provenance binding
# ---------------------------------------------------------------------------


def test_ready_chain_preserves_provider_attribution_and_canonical_sources():
    """Provider identity and source provenance remain bound through Task 188."""
    upstream = _produce_upstream_ready("Task 195 provenance and attribution")
    chain = _compose_full_chain(upstream)
    provider = upstream["pkg162"]["provider_name"]
    model = upstream["pkg162"]["model_name"]

    assert provider
    assert model
    assert upstream["slice163"]["provider_name"] == provider
    assert upstream["slice163"]["model_name"] == model
    assert chain["bundle165"]["provider_name"] == provider
    assert chain["bundle165"]["model_name"] == model
    assert chain["audit166"]["audited_bundle"]["provider_name"] == provider
    assert chain["audit166"]["audited_bundle"]["model_name"] == model

    package168 = chain["package168"]
    assert package168["t162_provider_name"] == provider
    assert package168["t162_model_name"] == model
    assert package168["t163_provider_name"] == provider
    assert package168["t163_model_name"] == model
    assert package168["t165_bundle_evidence"]["provider_name"] == provider
    assert package168["t165_bundle_evidence"]["model_name"] == model
    assert package168["t166_audited_bundle"]["provider_name"] == provider
    assert package168["t166_audited_bundle"]["model_name"] == model

    canonical_sources = (
        (
            "Task 162",
            upstream["pkg162"],
            "audit_source",
            "REASONING_RUN_STAGE_7_AUDIT_PACKAGE_TASK_162",
        ),
        (
            "Task 163",
            upstream["slice163"],
            "certification_source",
            "REASONING_RUN_STAGE_7_VERTICAL_SLICE_TASK_163",
        ),
        (
            "Task 164",
            upstream["audit164"],
            "audit_source",
            "REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_TASK_164",
        ),
        (
            "Task 165",
            chain["bundle165"],
            "bundle_source",
            "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_TASK_165",
        ),
        (
            "Task 166",
            chain["audit166"],
            "audit_source",
            "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_TASK_166",
        ),
        (
            "Task 167",
            chain["consistency167"],
            "consistency_source",
            "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_TASK_167",
        ),
        (
            "Task 168",
            package168,
            "package_source",
            "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_TASK_168",
        ),
        (
            "Task 169",
            chain["audit169"],
            "audit_source",
            "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_TASK_169",
        ),
        (
            "Task 170",
            chain["consistency170"],
            "consistency_source",
            "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_TASK_170",
        ),
        (
            "Task 171",
            chain["attestation171"],
            "attestation_source",
            "REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_TASK_171",
        ),
        (
            "Task 172",
            chain["audit172"],
            "audit_source",
            "REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_TASK_172",
        ),
        (
            "Task 173",
            chain["consistency173"],
            "consistency_source",
            "REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_TASK_173",
        ),
        (
            "Task 174",
            chain["projection174"],
            "projection_source",
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_TASK_174",
        ),
        (
            "Task 175",
            chain["audit175"],
            "audit_source",
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_TASK_175",
        ),
        (
            "Task 176",
            chain["consistency176"],
            "consistency_source",
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_TASK_176",
        ),
        (
            "Task 177",
            chain["bundle177"],
            "bundle_source",
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_TASK_177",
        ),
        (
            "Task 178",
            chain["audit178"],
            "audit_source",
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_TASK_178",
        ),
        (
            "Task 179",
            chain["consistency179"],
            "consistency_source",
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_TASK_179",
        ),
        (
            "Task 180",
            chain["attestation180"],
            "attestation_source",
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_TASK_180",
        ),
        (
            "Task 181",
            chain["audit181"],
            "audit_source",
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_TASK_181",
        ),
        (
            "Task 182",
            chain["consistency182"],
            "consistency_source",
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_CONSISTENCY_TASK_182",
        ),
        (
            "Task 183",
            chain["projection183"],
            "projection_source",
            "REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_TASK_183",
        ),
        (
            "Task 184",
            chain["audit184"],
            "audit_source",
            "REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_TASK_184",
        ),
        (
            "Task 185",
            chain["consistency185"],
            "consistency_source",
            "REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_TASK_185",
        ),
        (
            "Task 186",
            chain["package186"],
            "package_source",
            "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_TASK_186",
        ),
        (
            "Task 187",
            chain["audit187"],
            "audit_source",
            "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_TASK_187",
        ),
        (
            "Task 188",
            chain["consistency188"],
            "consistency_source",
            "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_TASK_188",
        ),
    )
    for label, record, field, expected in canonical_sources:
        assert record[field] == expected, (label, field)

    # The aggregate is a verbatim evidence envelope for every child source.
    for field, expected in (
        ("t162_audit_source", upstream["pkg162"]["audit_source"]),
        ("t163_certification_source", upstream["slice163"]["certification_source"]),
        ("t164_audit_source", upstream["audit164"]["audit_source"]),
        ("t165_bundle_source", chain["bundle165"]["bundle_source"]),
        ("t166_audit_source", chain["audit166"]["audit_source"]),
        ("t167_consistency_source", chain["consistency167"]["consistency_source"]),
    ):
        assert package168[field] == expected, field
    assert (
        package168["t165_bundle_evidence"]["bundle_source"]
        == chain["bundle165"]["bundle_source"]
    )
    assert (
        package168["t166_audited_bundle"]["bundle_source"]
        == chain["bundle165"]["bundle_source"]
    )
    assert chain["package186"]["t183_projection_source"] == (
        chain["projection183"]["projection_source"]
    )
    assert chain["package186"]["t184_audit_source"] == chain["audit184"]["audit_source"]
    assert chain["package186"]["t185_consistency_source"] == (
        chain["consistency185"]["consistency_source"]
    )


def test_task_168_fails_closed_on_task_162_163_provider_model_mismatch():
    """Different child attributions remain visible and cannot produce READY."""
    upstream = _produce_upstream_ready("Task 195 conflicting provider attribution")
    expected_provider = upstream["pkg162"]["provider_name"]
    expected_model = upstream["pkg162"]["model_name"]
    upstream["slice163"]["provider_name"] = "substituted-provider-195"
    upstream["slice163"]["model_name"] = "substituted-model-195"

    chain = _compose_full_chain(upstream)
    package = chain["package168"]

    assert package["t162_provider_name"] == expected_provider
    assert package["t162_model_name"] == expected_model
    assert package["t163_provider_name"] == "substituted-provider-195"
    assert package["t163_model_name"] == "substituted-model-195"
    assert package["package_status"] == "UNAVAILABLE"
    assert "T162_T163_ATTRIBUTION_MISMATCH" in package["findings"]
    assert chain["audit169"]["package_audit_status"] == "CONSISTENT"
    assert chain["consistency170"]["consistency_status"] == "CONSISTENT"

    # The discrepancy remains in the evidence and the handoff cannot promote it.
    assert chain["package186"]["package_status"] == "UNAVAILABLE"
    assert chain["audit187"]["package_audit_status"] == "CONSISTENT"
    assert chain["consistency188"]["consistency_status"] == "CONSISTENT"


def test_noncanonical_task_162_source_is_preserved_and_fails_closed_end_to_end():
    """The real chain reports a forged child source without silently repairing it."""
    upstream = _produce_upstream_ready("Task 195 forged Task 162 source")
    forged_source = "FORGED_TASK_162_SOURCE_195"
    upstream["pkg162"]["audit_source"] = forged_source

    chain = _compose_full_chain(upstream)
    bundle = chain["bundle165"]
    package = chain["package168"]

    assert bundle["bundle_status"] == "UNAVAILABLE"
    assert bundle["t162_audit_source"] == forged_source
    assert "T162_AUDIT_SOURCE_NOT_CANONICAL" in bundle["bundle_findings"]

    assert package["package_status"] == "UNAVAILABLE"
    assert package["t162_audit_source"] == forged_source
    assert "T162_SOURCE_MISMATCH" in package["findings"]
    assert chain["package186"]["package_status"] == "UNAVAILABLE"
    assert chain["consistency188"]["consistency_status"] == "CONSISTENT"


# ---------------------------------------------------------------------------
# Task 196: Task 183-185 source integrity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    (
        "boundary",
        "source_field",
        "package_source_field",
        "valid_field",
        "invalid_finding",
    ),
    [
        (
            "projection183",
            "projection_source",
            "t183_projection_source",
            "t183_valid",
            "T183_EVIDENCE_INVALID",
        ),
        (
            "audit184",
            "audit_source",
            "t184_audit_source",
            "t184_valid",
            "T184_EVIDENCE_INVALID",
        ),
        (
            "consistency185",
            "consistency_source",
            "t185_consistency_source",
            "t185_valid",
            "T185_EVIDENCE_INVALID",
        ),
    ],
)
def test_task_183_185_source_forgery_fails_closed_through_task_188(
    boundary: str,
    source_field: str,
    package_source_field: str,
    valid_field: str,
    invalid_finding: str,
):
    """Forged gate-child provenance is preserved, audited, and never trusted."""
    chain = _compose_full_chain(
        _produce_upstream_ready(f"Task 196 forged {boundary} source")
    )
    projection = _P183.model_validate(chain["projection183"])
    audit = _A184.model_validate(chain["audit184"])
    consistency = _C185.model_validate(chain["consistency185"])

    child_by_boundary = {
        "projection183": projection,
        "audit184": audit,
        "consistency185": consistency,
    }
    forged_source = f"FORGED_{source_field.upper()}_TASK_196"
    setattr(child_by_boundary[boundary], source_field, forged_source)

    package = _P186.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageService.assemble(
            projection=projection,
            audit=audit,
            consistency=consistency,
        )
    )
    assert package.package_status == "UNAVAILABLE"
    assert getattr(package, package_source_field) == forged_source
    assert getattr(package, valid_field) is False
    assert "CHILD_SOURCE_MISMATCH" in package.findings
    assert invalid_finding in package.findings

    audit187 = _A187.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
            projection=projection,
            audit=audit,
            consistency=consistency,
            package=package,
        )
    )
    assert audit187.published_package_status == "UNAVAILABLE"
    assert audit187.expected_package_status == "UNAVAILABLE"
    assert audit187.package_audit_status == "INCONSISTENT"
    assert "CHILD_SOURCE_INVALID" in audit187.findings

    consistency188 = _C188.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService.verify(
            package=package,
            audit=audit187,
        )
    )
    assert consistency188.consistency_status == "INCONSISTENT"
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency188.findings
    assert "AUDIT_INCONSISTENT" in consistency188.findings


# ---------------------------------------------------------------------------
# Task 197: blocked source-forgery precedence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    (
        "boundary",
        "source_field",
        "package_source_field",
        "valid_field",
        "invalid_finding",
    ),
    [
        (
            "projection183",
            "projection_source",
            "t183_projection_source",
            "t183_valid",
            "T183_EVIDENCE_INVALID",
        ),
        (
            "audit184",
            "audit_source",
            "t184_audit_source",
            "t184_valid",
            "T184_EVIDENCE_INVALID",
        ),
        (
            "consistency185",
            "consistency_source",
            "t185_consistency_source",
            "t185_valid",
            "T185_EVIDENCE_INVALID",
        ),
    ],
)
def test_task_183_185_forged_sources_do_not_hide_explicit_blocking_evidence(
    boundary: str,
    source_field: str,
    package_source_field: str,
    valid_field: str,
    invalid_finding: str,
):
    """A forged source cannot erase a BLOCKED gate or validate its handoff."""
    chain = _compose_full_chain(_blocked_upstream())
    projection = _P183.model_validate(chain["projection183"])
    audit = _A184.model_validate(chain["audit184"])
    consistency = _C185.model_validate(chain["consistency185"])

    child_by_boundary = {
        "projection183": projection,
        "audit184": audit,
        "consistency185": consistency,
    }
    forged_source = f"FORGED_{source_field.upper()}_TASK_197"
    setattr(child_by_boundary[boundary], source_field, forged_source)

    package = _P186.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageService.assemble(
            projection=projection,
            audit=audit,
            consistency=consistency,
        )
    )
    assert package.package_status == "BLOCKED"
    assert package.t183_gate_status == "BLOCKED"
    assert package.t184_published_gate_status == "BLOCKED"
    assert package.t185_expected_gate_status == "BLOCKED"
    assert getattr(package, package_source_field) == forged_source
    assert getattr(package, valid_field) is False
    assert "CHILD_SOURCE_MISMATCH" in package.findings
    assert invalid_finding in package.findings
    assert "EXPLICIT_BLOCKING_GATE_EVIDENCE" in package.findings

    audit187 = _A187.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
            projection=projection,
            audit=audit,
            consistency=consistency,
            package=package,
        )
    )
    assert audit187.published_package_status == "BLOCKED"
    assert audit187.expected_package_status == "BLOCKED"
    assert audit187.package_audit_status == "INCONSISTENT"
    assert "CHILD_SOURCE_INVALID" in audit187.findings

    consistency188 = _C188.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService.verify(
            package=package,
            audit=audit187,
        )
    )
    assert consistency188.consistency_status == "INCONSISTENT"
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency188.findings
    assert "AUDIT_INCONSISTENT" in consistency188.findings



# ---------------------------------------------------------------------------
# Task 198: provider isolation and evidence privacy
# ---------------------------------------------------------------------------


def test_task_198_downstream_chain_is_provider_and_database_write_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tasks 165-188 consume published evidence without provider or DB access."""
    upstream = _produce_upstream_ready("Task 198 provider isolation")

    def reject_provider_dispatch(*args: object, **kwargs: object) -> None:
        pytest.fail("downstream evidence chain must not invoke provider dispatch")

    monkeypatch.setattr(
        ReasoningRunStage7DispatchService, "dispatch", reject_provider_dispatch
    )

    statements: list[str] = []

    def record_statement(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        chain = _compose_full_chain(upstream)
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert statements == []
    assert chain["bundle165"]["bundle_status"] == "READY"
    assert chain["package186"]["package_status"] == "READY"
    assert chain["consistency188"]["consistency_status"] == "CONSISTENT"


def test_task_198_raw_request_and_provider_payloads_are_not_published() -> None:
    """Raw request/provider material stays out of all published evidence records."""
    raw_request_sentinel = "RAW_REQUEST_PAYLOAD_SENTINEL_TASK198"
    raw_provider_sentinel = "RAW_PROVIDER_RESPONSE_SENTINEL_TASK198"
    upstream = _produce_upstream_ready(
        raw_request_sentinel,
        provider_explanation=raw_provider_sentinel,
    )

    # The provider and request boundary ran through the real upstream services;
    # only validated Task 162-164 published records enter the downstream chain.
    chain = _compose_full_chain(upstream)
    published_json = json.dumps(chain, sort_keys=True)

    assert raw_request_sentinel not in published_json
    assert raw_provider_sentinel not in published_json

    # Privacy filtering must not discard the canonical provider attribution.
    assert chain["bundle165"]["provider_name"] == upstream["slice163"]["provider_name"]
    assert chain["bundle165"]["model_name"] == upstream["slice163"]["model_name"]
    assert (
        chain["package168"]["t162_provider_name"]
        == upstream["pkg162"]["provider_name"]
    )
    assert (
        chain["package168"]["t162_model_name"] == upstream["pkg162"]["model_name"]
    )


def test_task_198_malformed_evidence_diagnostics_do_not_echo_untrusted_values() -> None:
    """Malformed evidence fails closed with structural findings, never raw input."""
    raw_value = "RAW_PROVIDER_RESPONSE_OBJECT_SENTINEL_TASK198"
    result = ReasoningRunStage7EvidenceBundleAuditService.audit(
        bundle={
            "session_id": raw_value,
            "raw_provider_response": raw_value,
        }
    )

    assert result["bundle_audit_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["consistent"] is False
    assert result["session_id"] == ""
    assert result["published_bundle_status"] is None
    assert result["expected_bundle_status"] is None
    assert result["audited_bundle"] is None
    assert result["findings"] == sorted(set(result["findings"]))
    assert raw_value not in json.dumps(result, sort_keys=True)



# ---------------------------------------------------------------------------
# Task 200: whole Stage 7 integration from entry through handoff
# ---------------------------------------------------------------------------


def _task200_entry(session_id: str, certification_service) -> dict[str, object]:
    """Invoke the real Task 153 entry boundary for the same session."""
    with TestingSessionLocal() as db:
        result = ReasoningRunStage7EntryService(
            certification_service=certification_service
        ).evaluate(db, UUID(session_id))
    return ReasoningRunStage7EntryRead.model_validate(result).model_dump()


def _task200_upstream(
    session_id: str,
    certification_service,
    *,
    provider_explanation: str = "",
) -> dict[str, object]:
    """Invoke the real Tasks 154-164 after the real Task 153 entry boundary.

    Only Stage 6 certification and the explicit provider response are test
    doubles. A blocked or unavailable request still passes through the real
    request, request-audit, dispatch, proposal, proposal-audit, diagnostics,
    aggregation, certification, and consistency services; the dispatch gate
    must prevent provider contact when the request was not packaged.
    """
    session_uuid = UUID(session_id)
    with TestingSessionLocal() as db:
        admission = ReasoningRunStage7AdmissionService(
            certification_service=certification_service
        ).evaluate(db, session_uuid)
        request = ReasoningRunStage7RequestService(
            admission_service=ReasoningRunStage7AdmissionService(
                certification_service=certification_service
            )
        ).build(db, session_uuid)
        request_audit = ReasoningRunStage7RequestAuditService(
            admission_service=ReasoningRunStage7AdmissionService(
                certification_service=certification_service
            )
        ).audit(db, request)
        context = ReasoningContextService().build_for_session(db, session_uuid)

        provider_text = (
            _valid_model_output(context, explanation=provider_explanation)
            if admission["admission_status"] == "ADMITTED"
            and request["request_status"] == "PACKAGED"
            else "{}"
        )
        provider = _FakeProvider(provider_text)
        dispatch = ReasoningRunStage7DispatchService(provider=provider).dispatch(
            request=request,
            request_audit=request_audit,
        )
        proposal = ReasoningRunStage7ProposalService().build(
            dispatch_result=dispatch,
            context=context,
        )
        proposal_audit = ReasoningRunStage7ProposalAuditService.audit(
            proposal_result=proposal,
            context=context,
        )

    diagnostics = _diagnose(request, request_audit, proposal, proposal_audit)
    package162 = _pkg162(
        admission,
        request,
        request_audit,
        proposal,
        proposal_audit,
        diagnostics,
    )
    verdict163 = _certify(package162)
    audit164 = _audit164(package162, verdict163)
    return {
        "session_id": session_id,
        "admission": admission,
        "request": request,
        "request_audit": request_audit,
        "dispatch": dispatch,
        "proposal": proposal,
        "proposal_audit": proposal_audit,
        "diagnostics": diagnostics,
        "pkg162": package162,
        "slice163": verdict163,
        "audit164": audit164,
        "test_provider_calls": len(provider.calls),
    }


def _task200_run_full_path(
    label: str,
    certification_service,
    *,
    provider_explanation: str = "",
) -> tuple[str, dict[str, object], dict[str, object], dict[str, object]]:
    """Run Task 153, Tasks 154-164, then the established Tasks 165-188 helper."""
    session_id = _seed_full_session(label)
    entry = _task200_entry(session_id, certification_service)
    upstream = _task200_upstream(
        session_id,
        certification_service,
        provider_explanation=provider_explanation,
    )
    chain = _compose_full_chain(upstream)
    return session_id, entry, upstream, chain


def test_task_200_full_valid_path_runs_from_entry_through_consistent_handoff():
    """The real Task 153-188 service sequence reaches a READY handoff."""
    _, entry, upstream, chain = _task200_run_full_path(
        "Task 200 whole-path READY",
        _CertificationStub("CERTIFIED"),
    )

    assert entry["stage_7_status"] == "READY"
    assert entry["finding_count"] == 0
    assert upstream["admission"]["admission_status"] == "ADMITTED"
    assert upstream["request"]["request_status"] == "PACKAGED"
    assert upstream["dispatch"]["dispatch_status"] == "DISPATCHED"
    assert upstream["proposal"]["proposal_status"] == "VALIDATED"
    assert upstream["proposal_audit"]["proposal_audit_status"] == "CONSISTENT"
    assert upstream["diagnostics"]["diagnostics_status"] == "HEALTHY"

    for boundary, field in _BUSINESS_BOUNDARIES:
        assert chain[boundary][field] == "READY", (boundary, field)
    for boundary, field, _ in _VERIFICATION_BOUNDARIES:
        assert chain[boundary][field] == "CONSISTENT", (boundary, field)
    assert chain["package186"]["package_status"] == "READY"
    assert chain["audit187"]["package_audit_status"] == "CONSISTENT"
    assert chain["consistency188"]["consistency_status"] == "CONSISTENT"


def test_task_200_blocked_path_uses_real_services_and_stays_blocked():
    """A genuine NO_MATERIAL admission cannot be promoted by downstream audits."""
    session_id = _create_session("Task 200 empty deterministic chain")
    certification = _CertificationStub("NO_MATERIAL")
    entry = _task200_entry(session_id, certification)
    upstream = _task200_upstream(session_id, certification)
    chain = _compose_full_chain(upstream)

    assert entry["stage_7_status"] == "READY"
    assert upstream["admission"]["admission_status"] == "BLOCKED"
    assert upstream["request"]["request_status"] == "BLOCKED"
    assert upstream["dispatch"]["dispatch_status"] == "BLOCKED"
    assert upstream["test_provider_calls"] == 0
    assert upstream["pkg162"]["provider_name"] is None
    assert upstream["pkg162"]["model_name"] is None
    _assert_status_propagates(chain, "BLOCKED")
    assert chain["package186"]["package_status"] == "BLOCKED"
    assert chain["consistency188"]["consistency_status"] == "CONSISTENT"


def test_task_200_unreadable_certification_fails_closed_through_handoff():
    """An unreadable Stage 6 result creates no attribution or READY claim."""
    session_id = _seed_full_session("Task 200 unreadable certification")
    certification = _UnreadableCertification()
    entry = _task200_entry(session_id, certification)
    upstream = _task200_upstream(session_id, certification)
    chain = _compose_full_chain(upstream)

    assert entry["stage_7_status"] == "UNAVAILABLE"
    assert entry["boundary_available"] is True
    assert upstream["admission"]["admission_status"] == "UNAVAILABLE"
    assert upstream["admission"]["stage_6_certification_status"] == "UNAVAILABLE"
    assert upstream["admission"]["admitted"] is False
    assert upstream["request"]["request_status"] == "UNAVAILABLE"
    assert upstream["test_provider_calls"] == 0
    assert upstream["pkg162"]["request_fingerprint"] is None
    assert upstream["pkg162"]["provider_name"] is None
    assert upstream["pkg162"]["model_name"] is None
    assert upstream["slice163"]["slice_status"] == "UNAVAILABLE"
    _assert_status_propagates(chain, "UNAVAILABLE")
    assert chain["package186"]["package_status"] == "UNAVAILABLE"
    assert chain["consistency188"]["consistency_status"] == "CONSISTENT"


def test_task_200_readable_gate_contradiction_remains_inconsistent_through_188():
    """A published contradiction is never laundered into an unavailable audit."""
    _, entry, upstream, chain = _task200_run_full_path(
        "Task 200 readable contradiction",
        _CertificationStub("CERTIFIED"),
    )
    assert entry["stage_7_status"] == "READY"
    assert chain["projection183"]["gate_status"] == "READY"

    projection = _P183.model_validate(chain["projection183"])
    projection.gate_status = "UNAVAILABLE"
    result = _compose_gate_handoff_from_projection(chain, projection)

    assert result["audit184"]["gate_audit_status"] == "INCONSISTENT"
    assert "GATE_STATUS_MISMATCH" in result["audit184"]["findings"]
    assert result["consistency185"]["gate_consistency_status"] == "INCONSISTENT"
    assert "EXPECTED_STATUS_MISMATCH" in result["consistency185"]["findings"]
    assert result["audit187"]["package_audit_status"] == "INCONSISTENT"
    assert "T184_AUDIT_INCONSISTENT" in result["audit187"]["findings"]
    assert "T185_CONSISTENCY_INCONSISTENT" in result["audit187"]["findings"]
    assert result["consistency188"]["consistency_status"] == "INCONSISTENT"
    assert "AUDIT_UNAVAILABLE" not in result["consistency188"]["findings"]


def test_task_200_detached_gate_audit_identity_remains_untrusted_through_188():
    """A detached published Task 184 audit is not repaired by Tasks 185-188."""
    _, entry, upstream, chain = _task200_run_full_path(
        "Task 200 detached gate audit",
        _CertificationStub("CERTIFIED"),
    )
    assert entry["stage_7_status"] == "READY"
    projection = _P183.model_validate(chain["projection183"])
    audit184 = _A184.model_validate(chain["audit184"])
    audit184.session_id = "detached-task-200-audit-session"

    consistency185 = _C185.model_validate(
        ReasoningRunStage7FinalReleaseGateAuditConsistencyService.verify(
            projection=projection,
            audit=audit184,
        )
    )
    assert consistency185.gate_consistency_status == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency185.findings

    package186 = _P186.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageService.assemble(
            projection=projection,
            audit=audit184,
            consistency=consistency185,
        )
    )
    assert package186.package_status == "UNAVAILABLE"
    assert package186.session_id == ""

    audit187 = _A187.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
            projection=projection,
            audit=audit184,
            consistency=consistency185,
            package=package186,
        )
    )
    assert audit187.package_audit_status == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in audit187.findings

    consistency188 = _C188.model_validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService.verify(
            package=package186,
            audit=audit187,
        )
    )
    assert consistency188.consistency_status == "INCONSISTENT"
    assert consistency188.session_id == ""
    assert "AUDIT_STATUS_NOT_CONSISTENT" in consistency188.findings
    assert "AUDIT_UNAVAILABLE" not in consistency188.findings
