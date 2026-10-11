"""Shared composition support for Stage 7 full-chain integration tests.

Produces genuine Task 162-164 material with the real Task 154-164 services
(an in-memory database, a stubbed Stage 6 certification and a test-only fake
provider are the only substitutes at external boundaries), then composes the
real, already-published Task 165-188 services externally, in dependency
order. No evidence service is stubbed, no intermediate result is seeded, no
fingerprint is recomputed, and no real provider or network is involved.

Only this composition layer calls one evidence service after another; the
services themselves remain independent.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import BaseModel
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
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    ReasoningRunStage7EvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package import (
    ReasoningRunStage7EvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit import (
    ReasoningRunStage7EvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit_consistency import (
    ReasoningRunStage7EvidencePackageAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_attestation_audit import (
    ReasoningRunStage7FinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_attestation_consistency import (
    ReasoningRunStage7FinalAttestationConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_evidence_attestation import (
    ReasoningRunStage7FinalEvidenceAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_audit import (
    ReasoningRunStage7FinalReleaseGateAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_audit_consistency import (
    ReasoningRunStage7FinalReleaseGateAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_projection import (
    ReasoningRunStage7FinalReleaseGateProjectionRead,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit import (
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (
    ReasoningRunStage7ReleaseReadinessAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit_consistency import (
    ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation import (
    ReasoningRunStage7ReleaseReadinessFinalAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_audit import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    ReasoningRunStage7ReleaseReadinessProjectionRead,
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
from rop.services.reasoning_run_stage_7_request import (
    ReasoningRunStage7RequestService,
)
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
# In-memory database and client (the only persistence involved is the
# upstream Task 154-162 test database that produces genuine Task 162 input).
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


client = TestClient(app)


def reset_db() -> None:
    """Recreate the in-memory schema and route the app to it."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    app.dependency_overrides[get_db] = override_get_db


class CertificationStub:
    """One coherent Stage 6 verdict for the real admission path (external)."""

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


class FakeProvider:
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


class FailingProvider:
    """Test-only provider that raises one canonical failure."""

    def __init__(self, error: Exception) -> None:
        self.provider_name = "failing-provider"
        self.model_name = "failing-model"
        self.error = error
        self.calls: list[object] = []

    def generate_reasoning(self, request: object) -> object:
        self.calls.append(request)
        raise self.error


# ---------------------------------------------------------------------------
# Genuine Task 154-164 production
# ---------------------------------------------------------------------------


def create_seeded_session(label: str) -> str:
    created = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": label,
            "current_stage": "initial",
            "metadata": {"source": "stage-7-full-chain-integration"},
        },
    )
    assert created.status_code == 201
    sid = str(created.json()["id"])
    observation = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert observation.status_code == 201
    assert client.post(f"/sessions/{sid}/generate-candidates").status_code == 201
    assert client.post(f"/sessions/{sid}/evaluate-evidence").status_code == 200
    return sid


def _admission_service() -> ReasoningRunStage7AdmissionService:
    return ReasoningRunStage7AdmissionService(certification_service=CertificationStub())


def _valid_model_output(context: dict[str, Any]) -> str:
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


def _build_pkg162(db: Session, sid: str, provider: Any) -> dict[str, Any]:
    """Run the real Task 154-162 services and return the Task 162 package."""
    context = ReasoningContextService().build_for_session(db, UUID(sid))
    assert context["available"] is True
    if isinstance(provider, FakeProvider):
        provider.response = LLMReasoningProviderResponse(
            provider="fake-provider",
            model="fake-model",
            text=_valid_model_output(context),
        )
    admission = _admission_service().evaluate(db, UUID(sid))
    assert admission["admission_status"] == "ADMITTED"
    request_package = ReasoningRunStage7RequestService(
        admission_service=_admission_service()
    ).build(db, UUID(sid))
    assert request_package["request_status"] == "PACKAGED"
    request_audit = ReasoningRunStage7RequestAuditService(
        admission_service=_admission_service()
    ).audit(db, request_package)
    dispatch = ReasoningRunStage7DispatchService(provider=provider).dispatch(
        request=request_package, request_audit=request_audit
    )
    proposal_result = ReasoningRunStage7ProposalService().build(
        dispatch_result=dispatch, context=context
    )
    proposal_audit = ReasoningRunStage7ProposalAuditService.audit(
        proposal_result=proposal_result, context=context
    )
    diagnostics = ReasoningRunStage7DiagnosticsService.diagnose(
        request_package=request_package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
    )
    return ReasoningRunStage7AuditPackageService.build(
        admission_result=admission,
        request_package=request_package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
        diagnostics_result=diagnostics,
    )


def produce_stage_inputs(scenario: str, label: str) -> dict[str, BaseModel]:
    """Genuine, validated Task 162, 163 and 164 records for one scenario.

    ``READY``: a healthy, fully audited interaction. ``BLOCKED``: a provider
    outage, which Task 163 certifies as a blocked slice.
    """
    sid = create_seeded_session(label)
    provider: Any
    if scenario == "READY":
        provider = FakeProvider()
    elif scenario == "BLOCKED":
        provider = FailingProvider(
            LLMReasoningProviderError("connection to model host failed")
        )
    else:  # pragma: no cover - guards against a typo in a test
        raise ValueError(f"unsupported scenario: {scenario}")
    with TestingSessionLocal() as db:
        pkg162 = _build_pkg162(db, sid, provider)
    slice163 = ReasoningRunStage7VerticalSliceService.certify(audit_package=pkg162)
    audit164 = ReasoningRunStage7VerticalSliceAuditService.audit(
        audit_package=pkg162, vertical_slice=slice163
    )
    return {
        "162": ReasoningRunStage7AuditPackageRead.model_validate(pkg162),
        "163": ReasoningRunStage7VerticalSliceRead.model_validate(slice163),
        "164": ReasoningRunStage7VerticalSliceAuditRead.model_validate(audit164),
    }


# ---------------------------------------------------------------------------
# External composition of the real Task 165-188 services
# ---------------------------------------------------------------------------


def _validate(model: type[BaseModel], value: dict[str, Any]) -> Any:
    return model.model_validate(value)


def compose_evidence_chain(
    pkg162: ReasoningRunStage7AuditPackageRead,
    slice163: ReasoningRunStage7VerticalSliceRead,
    audit164: ReasoningRunStage7VerticalSliceAuditRead,
) -> dict[str, BaseModel]:
    """Run the real Task 165-173 services over validated Task 162-164 records."""
    bundle165 = _validate(
        ReasoningRunStage7EvidenceBundleRead,
        ReasoningRunStage7EvidenceBundleService.assemble(
            pkg162=pkg162, slice163=slice163, audit164=audit164
        ),
    )
    audit166 = _validate(
        ReasoningRunStage7EvidenceBundleAuditRead,
        ReasoningRunStage7EvidenceBundleAuditService.audit(bundle=bundle165),
    )
    consistency167 = _validate(
        ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
        ReasoningRunStage7EvidenceBundleAuditConsistencyService.verify(
            bundle=bundle165, audit=audit166
        ),
    )
    package168 = _validate(
        ReasoningRunStage7EvidencePackageRead,
        ReasoningRunStage7EvidencePackageService.assemble(
            pkg162=pkg162,
            slice163=slice163,
            audit164=audit164,
            bundle165=bundle165,
            audit166=audit166,
            consistency167=consistency167,
        ),
    )
    audit169 = _validate(
        ReasoningRunStage7EvidencePackageAuditRead,
        ReasoningRunStage7EvidencePackageAuditService.audit(
            package=package168,
            pkg162=pkg162,
            slice163=slice163,
            audit164=audit164,
            bundle165=bundle165,
            audit166=audit166,
            consistency167=consistency167,
        ),
    )
    consistency170 = _validate(
        ReasoningRunStage7EvidencePackageAuditConsistencyRead,
        ReasoningRunStage7EvidencePackageAuditConsistencyService.verify(
            package=package168, audit=audit169
        ),
    )
    attestation171 = _validate(
        ReasoningRunStage7FinalEvidenceAttestationRead,
        ReasoningRunStage7FinalEvidenceAttestationService.attest(
            package=package168, audit=audit169, consistency=consistency170
        ),
    )
    audit172 = _validate(
        ReasoningRunStage7FinalAttestationAuditRead,
        ReasoningRunStage7FinalAttestationAuditService.audit(
            package=package168,
            audit=audit169,
            consistency=consistency170,
            attestation=attestation171,
        ),
    )
    consistency173 = _validate(
        ReasoningRunStage7FinalAttestationConsistencyRead,
        ReasoningRunStage7FinalAttestationConsistencyService.verify(
            attestation=attestation171, audit=audit172
        ),
    )
    return {
        "165": bundle165,
        "166": audit166,
        "167": consistency167,
        "168": package168,
        "169": audit169,
        "170": consistency170,
        "171": attestation171,
        "172": audit172,
        "173": consistency173,
    }


def compose_release_chain(
    attestation171: ReasoningRunStage7FinalEvidenceAttestationRead,
    audit172: ReasoningRunStage7FinalAttestationAuditRead,
    consistency173: ReasoningRunStage7FinalAttestationConsistencyRead,
) -> dict[str, BaseModel]:
    """Run the real Task 174-188 services over the Task 171-173 records."""
    projection174 = _validate(
        ReasoningRunStage7ReleaseReadinessProjectionRead,
        ReasoningRunStage7ReleaseReadinessProjectionService.project(
            attestation=attestation171, audit=audit172, consistency=consistency173
        ),
    )
    audit175 = _validate(
        ReasoningRunStage7ReleaseReadinessAuditRead,
        ReasoningRunStage7ReleaseReadinessAuditService.audit(
            attestation=attestation171,
            audit=audit172,
            consistency=consistency173,
            projection=projection174,
        ),
    )
    consistency176 = _validate(
        ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
        ReasoningRunStage7ReleaseReadinessAuditConsistencyService.verify(
            projection=projection174, audit=audit175
        ),
    )
    bundle177 = _validate(
        ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
        ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
            projection174=projection174,
            audit175=audit175,
            consistency176=consistency176,
        ),
    )
    audit178 = _validate(
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
            projection174=projection174,
            audit175=audit175,
            consistency176=consistency176,
            bundle=bundle177,
        ),
    )
    consistency179 = _validate(
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead,
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService.verify(
            bundle=bundle177, audit=audit178
        ),
    )
    attestation180 = _validate(
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead,
        ReasoningRunStage7ReleaseReadinessFinalAttestationService.attest(
            bundle=bundle177, audit=audit178, consistency=consistency179
        ),
    )
    audit181 = _validate(
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead,
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService.audit(
            bundle=bundle177,
            audit=audit178,
            consistency=consistency179,
            attestation=attestation180,
        ),
    )
    consistency182 = _validate(
        ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyRead,
        ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService.verify(
            attestation=attestation180, audit=audit181
        ),
    )
    projection183 = _validate(
        ReasoningRunStage7FinalReleaseGateProjectionRead,
        ReasoningRunStage7FinalReleaseGateProjectionService.project(
            attestation=attestation180, audit=audit181, consistency=consistency182
        ),
    )
    audit184 = _validate(
        ReasoningRunStage7FinalReleaseGateAuditRead,
        ReasoningRunStage7FinalReleaseGateAuditService.audit(
            attestation=attestation180,
            audit=audit181,
            consistency=consistency182,
            projection=projection183,
        ),
    )
    consistency185 = _validate(
        ReasoningRunStage7FinalReleaseGateAuditConsistencyRead,
        ReasoningRunStage7FinalReleaseGateAuditConsistencyService.verify(
            projection=projection183, audit=audit184
        ),
    )
    package186 = _validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageRead,
        ReasoningRunStage7ReleaseHandoffEvidencePackageService.assemble(
            projection=projection183, audit=audit184, consistency=consistency185
        ),
    )
    audit187 = _validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead,
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService.audit(
            projection=projection183,
            audit=audit184,
            consistency=consistency185,
            package=package186,
        ),
    )
    consistency188 = _validate(
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead,
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService.verify(
            package=package186, audit=audit187
        ),
    )
    return {
        "174": projection174,
        "175": audit175,
        "176": consistency176,
        "177": bundle177,
        "178": audit178,
        "179": consistency179,
        "180": attestation180,
        "181": audit181,
        "182": consistency182,
        "183": projection183,
        "184": audit184,
        "185": consistency185,
        "186": package186,
        "187": audit187,
        "188": consistency188,
    }


def compose_full_chain(scenario: str = "READY", label: str = "full chain") -> dict:
    """Genuine Task 162-164 inputs, then the real Task 165-188 services.

    Returns a mapping keyed by task number string ("162" ... "188").
    """
    chain: dict[str, BaseModel] = dict(produce_stage_inputs(scenario, label))
    chain.update(
        compose_evidence_chain(chain["162"], chain["163"], chain["164"])  # type: ignore[arg-type]
    )
    chain.update(
        compose_release_chain(chain["171"], chain["172"], chain["173"])  # type: ignore[arg-type]
    )
    return chain
