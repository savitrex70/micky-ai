"""Task 191: real Task 162-188 evidence chain integration (READY path).

Genuine Task 162-164 records are produced by the real upstream services
(in-memory database, stubbed Stage 6 certification and a test-only fake
provider are the only substitutes at external boundaries). The real Task
165-188 services are then composed externally, in dependency order, by
``tests.stage7_chain_support``; in particular Tasks 171-173 are produced by
their own services rather than seeded. No evidence result is fabricated.
"""

from __future__ import annotations

import os
import re
from unittest.mock import patch

import pytest
from pydantic import BaseModel

os.environ.setdefault("ROP_APP_NAME", "test")
os.environ.setdefault("ROP_ENVIRONMENT", "testing")
os.environ.setdefault("ROP_LOG_LEVEL", "INFO")
os.environ.setdefault(
    "ROP_DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test"
)

from rop.database import get_db  # noqa: E402
from rop.main import app  # noqa: E402
from rop.services.reasoning_run_stage_7_evidence_bundle import (  # noqa: E402
    ReasoningRunStage7EvidenceBundleService,
)
from rop.services.reasoning_run_stage_7_evidence_bundle_audit import (  # noqa: E402
    ReasoningRunStage7EvidenceBundleAuditService,
)
from rop.services.reasoning_run_stage_7_evidence_bundle_audit_consistency import (  # noqa: E402,E501
    ReasoningRunStage7EvidenceBundleAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_evidence_package import (  # noqa: E402
    ReasoningRunStage7EvidencePackageService,
)
from rop.services.reasoning_run_stage_7_evidence_package_audit import (  # noqa: E402
    ReasoningRunStage7EvidencePackageAuditService,
)
from rop.services.reasoning_run_stage_7_evidence_package_audit_consistency import (  # noqa: E402,E501
    ReasoningRunStage7EvidencePackageAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_final_attestation_audit import (  # noqa: E402
    ReasoningRunStage7FinalAttestationAuditService,
)
from rop.services.reasoning_run_stage_7_final_attestation_consistency import (  # noqa: E402,E501
    ReasoningRunStage7FinalAttestationConsistencyService,
)
from rop.services.reasoning_run_stage_7_final_evidence_attestation import (  # noqa: E402
    ReasoningRunStage7FinalEvidenceAttestationService,
)
from rop.services.reasoning_run_stage_7_final_release_gate_audit import (  # noqa: E402
    ReasoningRunStage7FinalReleaseGateAuditService,
)
from rop.services.reasoning_run_stage_7_final_release_gate_audit_consistency import (  # noqa: E402,E501
    ReasoningRunStage7FinalReleaseGateAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_final_release_gate_projection import (  # noqa: E402,E501
    ReasoningRunStage7FinalReleaseGateProjectionService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseHandoffEvidencePackageService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package_audit import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService,
)
from rop.services.reasoning_run_stage_7_release_handoff_evidence_package_audit_consistency import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_audit import (  # noqa: E402
    ReasoningRunStage7ReleaseReadinessAuditService,
)
from rop.services.reasoning_run_stage_7_release_readiness_audit_consistency import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseReadinessAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseReadinessEvidenceBundleService,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService,
)
from rop.services.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_final_attestation import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationService,
)
from rop.services.reasoning_run_stage_7_release_readiness_final_attestation_audit import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService,
)
from rop.services.reasoning_run_stage_7_release_readiness_final_attestation_consistency import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService,
)
from rop.services.reasoning_run_stage_7_release_readiness_projection import (  # noqa: E402,E501
    ReasoningRunStage7ReleaseReadinessProjectionService,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (  # noqa: E402
    ReasoningRunStage7VerticalSliceService,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (  # noqa: E402
    ReasoningRunStage7VerticalSliceAuditService,
)
from tests.stage7_chain_support import (  # noqa: E402
    compose_evidence_chain,
    compose_full_chain,
    compose_release_chain,
    reset_db,
)

# Every real service entry point, in dependency order: (task, class, method).
_SERVICE_CALLS = (
    ("163", ReasoningRunStage7VerticalSliceService, "certify"),
    ("164", ReasoningRunStage7VerticalSliceAuditService, "audit"),
    ("165", ReasoningRunStage7EvidenceBundleService, "assemble"),
    ("166", ReasoningRunStage7EvidenceBundleAuditService, "audit"),
    ("167", ReasoningRunStage7EvidenceBundleAuditConsistencyService, "verify"),
    ("168", ReasoningRunStage7EvidencePackageService, "assemble"),
    ("169", ReasoningRunStage7EvidencePackageAuditService, "audit"),
    ("170", ReasoningRunStage7EvidencePackageAuditConsistencyService, "verify"),
    ("171", ReasoningRunStage7FinalEvidenceAttestationService, "attest"),
    ("172", ReasoningRunStage7FinalAttestationAuditService, "audit"),
    ("173", ReasoningRunStage7FinalAttestationConsistencyService, "verify"),
    ("174", ReasoningRunStage7ReleaseReadinessProjectionService, "project"),
    ("175", ReasoningRunStage7ReleaseReadinessAuditService, "audit"),
    ("176", ReasoningRunStage7ReleaseReadinessAuditConsistencyService, "verify"),
    ("177", ReasoningRunStage7ReleaseReadinessEvidenceBundleService, "assemble"),
    ("178", ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService, "audit"),
    (
        "179",
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService,
        "verify",
    ),
    ("180", ReasoningRunStage7ReleaseReadinessFinalAttestationService, "attest"),
    ("181", ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService, "audit"),
    (
        "182",
        ReasoningRunStage7ReleaseReadinessFinalAttestationConsistencyService,
        "verify",
    ),
    ("183", ReasoningRunStage7FinalReleaseGateProjectionService, "project"),
    ("184", ReasoningRunStage7FinalReleaseGateAuditService, "audit"),
    ("185", ReasoningRunStage7FinalReleaseGateAuditConsistencyService, "verify"),
    ("186", ReasoningRunStage7ReleaseHandoffEvidencePackageService, "assemble"),
    ("187", ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService, "audit"),
    (
        "188",
        ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService,
        "verify",
    ),
)

# The attribute holding each record's own canonical source identifier.
_SOURCE_FIELD = {
    "162": "audit_source",
    "163": "certification_source",
    "164": "audit_source",
    "165": "bundle_source",
    "166": "audit_source",
    "167": "consistency_source",
    "168": "package_source",
    "169": "audit_source",
    "170": "consistency_source",
    "171": "attestation_source",
    "172": "audit_source",
    "173": "consistency_source",
    "174": "projection_source",
    "175": "audit_source",
    "176": "consistency_source",
    "177": "bundle_source",
    "178": "audit_source",
    "179": "consistency_source",
    "180": "attestation_source",
    "181": "audit_source",
    "182": "consistency_source",
    "183": "projection_source",
    "184": "audit_source",
    "185": "consistency_source",
    "186": "package_source",
    "187": "audit_source",
    "188": "consistency_source",
}

_TASKS = tuple(_SOURCE_FIELD)


@pytest.fixture(autouse=True, scope="module")
def _restore_db_override():
    """Leave the shared app's database override as other modules expect it."""
    prior = app.dependency_overrides.get(get_db)
    yield
    if prior is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = prior


@pytest.fixture(scope="module")
def ready_chain() -> dict[str, BaseModel]:
    reset_db()
    return compose_full_chain("READY", "Task 191 genuine READY chain")


def _dumps(chain: dict[str, BaseModel]) -> dict[str, dict]:
    return {task: record.model_dump() for task, record in chain.items()}


def test_every_real_service_is_invoked_in_dependency_order() -> None:
    """Task 163-188 outputs are produced by their own services, not seeded."""
    reset_db()
    calls: list[str] = []
    patches = []
    for task, service, method in _SERVICE_CALLS:
        original = getattr(service, method)

        def _spy(*args, _task=task, _original=original, **kwargs):
            calls.append(_task)
            return _original(*args, **kwargs)

        patches.append(patch.object(service, method, _spy))
    for item in patches:
        item.start()
    try:
        chain = compose_full_chain("READY", "Task 191 service invocation")
    finally:
        for item in patches:
            item.stop()
    assert calls == [task for task, _, _ in _SERVICE_CALLS]
    assert set(chain) == set(_TASKS)


def test_ready_path_inputs_are_genuine_task_162_to_164_evidence(ready_chain) -> None:
    pkg162, slice163, audit164 = (
        ready_chain["162"],
        ready_chain["163"],
        ready_chain["164"],
    )
    assert pkg162.admission_status == "ADMITTED"
    assert pkg162.request_audit_status == "CONSISTENT"
    assert pkg162.proposal_audit_status == "CONSISTENT"
    assert pkg162.diagnostics_status == "HEALTHY"
    assert pkg162.provider_name == "fake-provider"
    assert pkg162.model_name == "fake-model"
    assert re.fullmatch(r"[0-9a-f]{64}", pkg162.request_fingerprint or "")
    assert pkg162.findings == []
    assert slice163.slice_status == "READY"
    assert audit164.slice_audit_status == "CONSISTENT"
    assert audit164.published_slice_status == "READY"
    assert audit164.expected_slice_status == "READY"


def test_task_165_to_167_bundle_audit_and_consistency(ready_chain) -> None:
    bundle, audit, consistency = (ready_chain[t] for t in ("165", "166", "167"))
    assert bundle.bundle_status == "READY"
    assert audit.bundle_audit_status == "CONSISTENT"
    assert audit.published_bundle_status == "READY"
    assert audit.expected_bundle_status == "READY"
    assert consistency.consistency_status == "CONSISTENT"


def test_task_168_to_170_package_audit_and_consistency(ready_chain) -> None:
    package, audit, consistency = (ready_chain[t] for t in ("168", "169", "170"))
    assert package.package_status == "READY"
    assert package.t165_bundle_status == "READY"
    assert package.t166_bundle_audit_status == "CONSISTENT"
    assert package.t167_consistency_status == "CONSISTENT"
    assert audit.package_audit_status == "CONSISTENT"
    assert audit.published_package_status == "READY"
    assert audit.expected_package_status == "READY"
    assert consistency.consistency_status == "CONSISTENT"


def test_task_171_to_173_are_produced_by_their_services(ready_chain) -> None:
    attestation, audit, consistency = (ready_chain[t] for t in ("171", "172", "173"))
    assert attestation.attestation_status == "CERTIFIED"
    assert attestation.certified is True
    assert attestation.blocked is False
    assert attestation.package_status == "READY"
    assert attestation.package_audit_status == "CONSISTENT"
    assert attestation.consistency_status == "CONSISTENT"
    assert audit.attestation_audit_status == "CONSISTENT"
    assert audit.published_attestation_status == "CERTIFIED"
    assert audit.expected_attestation_status == "CERTIFIED"
    assert consistency.consistency_status == "CONSISTENT"


def test_task_174_to_188_release_readiness_and_handoff(ready_chain) -> None:
    c = ready_chain
    assert c["174"].readiness_status == "READY"
    assert c["175"].readiness_audit_status == "CONSISTENT"
    assert c["176"].consistency_status == "CONSISTENT"
    assert c["177"].bundle_status == "READY"
    assert c["178"].bundle_audit_status == "CONSISTENT"
    assert c["179"].consistency_status == "CONSISTENT"
    assert c["180"].attestation_status == "CERTIFIED"
    assert c["181"].attestation_audit_status == "CONSISTENT"
    assert c["182"].attestation_consistency_status == "CONSISTENT"
    assert c["183"].gate_status == "READY"
    assert c["184"].gate_audit_status == "CONSISTENT"
    assert c["185"].gate_consistency_status == "CONSISTENT"
    assert c["186"].package_status == "READY"
    assert c["187"].package_audit_status == "CONSISTENT"
    assert c["187"].published_package_status == "READY"
    assert c["187"].expected_package_status == "READY"
    assert c["188"].consistency_status == "CONSISTENT"
    assert c["188"].available is True
    assert c["188"].consistent is True


@pytest.mark.parametrize("task", _TASKS)
def test_each_stage_is_finding_free_and_canonically_sourced(ready_chain, task) -> None:
    record = ready_chain[task]
    assert record.findings == []
    assert record.finding_count == 0
    source = getattr(record, _SOURCE_FIELD[task])
    assert source.endswith(f"_TASK_{task}")
    for flag in ("available", "consistent"):
        if hasattr(record, flag):
            assert getattr(record, flag) is True


@pytest.mark.parametrize("task", _TASKS)
def test_session_identity_is_preserved_through_every_stage(ready_chain, task) -> None:
    expected = ready_chain["162"].session_id
    assert expected
    assert ready_chain[task].session_id == expected


def test_request_fingerprint_and_attribution_are_preserved_verbatim(
    ready_chain,
) -> None:
    pkg162, bundle165 = ready_chain["162"], ready_chain["165"]
    assert bundle165.request_fingerprint == pkg162.request_fingerprint
    assert bundle165.provider_name == pkg162.provider_name == "fake-provider"
    assert bundle165.model_name == pkg162.model_name == "fake-model"
    assert bundle165.t162_audit_source == pkg162.audit_source


def test_downstream_chain_is_deterministic_and_read_only(ready_chain) -> None:
    """Re-running Tasks 165-188 over the same genuine inputs changes nothing."""
    inputs = {task: ready_chain[task] for task in ("162", "163", "164")}
    before = _dumps(inputs)
    rerun = dict(inputs)
    rerun.update(compose_evidence_chain(inputs["162"], inputs["163"], inputs["164"]))
    rerun.update(compose_release_chain(rerun["171"], rerun["172"], rerun["173"]))
    assert _dumps(rerun) == _dumps(ready_chain)
    assert _dumps(inputs) == before
