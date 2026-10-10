"""Task 181: Stage 7 release-readiness final-attestation audit tests.

Comprehensive tests for the independent audit of the Task 180
release-readiness final attestation. The tests compose Tasks 174-180
externally; the audit service never invokes them itself.
"""

from __future__ import annotations

import copy
import inspect
import os
from uuid import uuid4

import pytest
from pydantic import ValidationError

# Set environment for imports
os.environ.setdefault("ROP_APP_NAME", "test")
os.environ.setdefault("ROP_ENVIRONMENT", "testing")
os.environ.setdefault("ROP_LOG_LEVEL", "INFO")
os.environ.setdefault(
    "ROP_DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test"
)

from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    ReasoningRunStage7ReleaseReadinessAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit_consistency import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176,
    ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178,
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit_consistency import (  # noqa: E501
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation import (
    ReasoningRunStage7ReleaseReadinessFinalAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_final_attestation_audit import (  # noqa: E501
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181,
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    ReasoningRunStage7ReleaseReadinessProjectionRead,
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

T181_SOURCE = (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_181
)
AUDIT_SOURCE = (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178
)

# Short aliases for long Task 179/180 contract identifiers.
_C179_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead
_C179 = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService
_A180_READ = ReasoningRunStage7ReleaseReadinessFinalAttestationRead

# ---------------------------------------------------------------------------
# Fixtures: externally composed Task 174-180 chains
# ---------------------------------------------------------------------------


def _chain(status: str):
    """Build a schema-valid Task 174-177 chain for the requested status."""
    session_id = str(uuid4())

    attestation_status = {
        "READY": "CERTIFIED",
        "BLOCKED": "BLOCKED",
        "UNAVAILABLE": "UNAVAILABLE",
    }[status]
    finding = {
        "READY": None,
        "BLOCKED": "BLOCKING_EVIDENCE",
        "UNAVAILABLE": "INSUFFICIENT_EVIDENCE",
    }[status]

    projection = ReasoningRunStage7ReleaseReadinessProjectionRead(
        session_id=session_id,
        readiness_status=status,
        attestation_status=attestation_status,
        attestation_audit_status="CONSISTENT",
        consistency_status="CONSISTENT",
        finding_count=1 if finding else 0,
        findings=[finding] if finding else [],
        projection_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    )

    audit175 = ReasoningRunStage7ReleaseReadinessAuditRead(
        session_id=session_id,
        readiness_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_readiness_status=status,
        expected_readiness_status=status,
        finding_count=0,
        findings=[],
        audit_source=REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    )

    consistency176 = ReasoningRunStage7ReleaseReadinessAuditConsistencyRead(
        session_id=session_id,
        consistency_status="CONSISTENT",
        available=True,
        consistent=True,
        finding_count=0,
        findings=[],
        consistency_source=(
            REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
        ),
    )

    bundle = ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(
        ReasoningRunStage7ReleaseReadinessEvidenceBundleService.assemble(
            projection174=projection,
            audit175=audit175,
            consistency176=consistency176,
        )
    )
    return {
        "projection": projection,
        "audit": audit175,
        "consistency": consistency176,
        "bundle": bundle,
        "session_id": session_id,
    }


def _bundle_audit(chain) -> ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead:
    """Run the real Task 178 service externally over the chain's evidence."""
    return ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead.model_validate(
        ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService.audit(
            projection174=chain["projection"],
            audit175=chain["audit"],
            consistency176=chain["consistency"],
            bundle=chain["bundle"],
        )
    )


def _consistency(chain, audit) -> _C179_READ:
    """Run the real Task 179 service externally over bundle and audit."""
    return _C179_READ.model_validate(_C179.verify(bundle=chain["bundle"], audit=audit))


def _attestation(
    bundle, audit, consistency
) -> ReasoningRunStage7ReleaseReadinessFinalAttestationRead:
    """Run the real Task 180 service externally over bundle/audit/consistency."""
    return _A180_READ.model_validate(
        ReasoningRunStage7ReleaseReadinessFinalAttestationService.attest(
            bundle=bundle, audit=audit, consistency=consistency
        )
    )


def _full_chain(status: str) -> dict:
    """Externally compose Tasks 174-180 for the requested readiness status."""
    chain = _chain(status)
    audit178 = _bundle_audit(chain)
    consistency179 = _consistency(chain, audit178)
    attestation180 = _attestation(chain["bundle"], audit178, consistency179)
    chain["audit178"] = audit178
    chain["consistency179"] = consistency179
    chain["attestation180"] = attestation180
    return chain


def _audit181(chain, attestation=None) -> dict:
    return ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService.audit(
        bundle=chain["bundle"],
        audit=chain["audit178"],
        consistency=chain["consistency179"],
        attestation=attestation or chain["attestation180"],
    )


@pytest.fixture
def ready_chain() -> dict:
    return _full_chain("READY")


@pytest.fixture
def blocked_chain() -> dict:
    return _full_chain("BLOCKED")


@pytest.fixture
def unavailable_chain() -> dict:
    return _full_chain("UNAVAILABLE")


# ---------------------------------------------------------------------------
# Audit verdicts for all three readiness states
# ---------------------------------------------------------------------------


def test_ready_chain_attestation_is_consistent(ready_chain) -> None:
    result = _audit181(ready_chain)
    assert result["attestation_audit_status"] == "CONSISTENT"
    assert result["available"] is True
    assert result["consistent"] is True
    assert result["published_attestation_status"] == "CERTIFIED"
    assert result["expected_attestation_status"] == "CERTIFIED"
    assert result["finding_count"] == 0
    assert result["findings"] == []
    assert result["session_id"] == ready_chain["session_id"]
    assert result["audit_source"] == T181_SOURCE


def test_blocked_chain_attestation_is_consistent(blocked_chain) -> None:
    result = _audit181(blocked_chain)
    assert result["attestation_audit_status"] == "CONSISTENT"
    assert result["published_attestation_status"] == "BLOCKED"
    assert result["expected_attestation_status"] == "BLOCKED"
    assert result["findings"] == []


def test_unavailable_chain_attestation_is_consistent(unavailable_chain) -> None:
    """A faithfully published UNAVAILABLE attestation is not a contradiction."""
    result = _audit181(unavailable_chain)
    assert result["attestation_audit_status"] == "CONSISTENT"
    assert result["published_attestation_status"] == "UNAVAILABLE"
    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert result["findings"] == []


def test_result_validates_against_strict_schema(ready_chain) -> None:
    ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead.model_validate(
        _audit181(ready_chain)
    )


# ---------------------------------------------------------------------------
# Forged published claims are detected
# ---------------------------------------------------------------------------


def test_forged_certified_over_unavailable_chain(ready_chain) -> None:
    """A CERTIFIED claim over UNAVAILABLE evidence is a proven forgery."""
    forged = _full_chain("UNAVAILABLE")
    payload = copy.deepcopy(forged["attestation180"].model_dump())
    payload["attestation_status"] = "CERTIFIED"
    payload["certified"] = True
    payload["available"] = True
    result = _audit181(forged, attestation=payload)
    assert result["attestation_audit_status"] == "INCONSISTENT"
    assert result["published_attestation_status"] == "CERTIFIED"
    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert "ATTESTATION_STATUS_MISMATCH" in result["findings"]
    assert "ATTESTATION_INVALID" in result["findings"]


def test_forged_blocked_over_ready_chain(ready_chain) -> None:
    """A BLOCKED claim over READY evidence is a proven forgery."""
    payload = copy.deepcopy(ready_chain["attestation180"].model_dump())
    payload["attestation_status"] = "BLOCKED"
    payload["blocked"] = True
    payload["certified"] = False
    result = _audit181(ready_chain, attestation=payload)
    assert result["attestation_audit_status"] == "INCONSISTENT"
    assert result["published_attestation_status"] == "BLOCKED"
    assert result["expected_attestation_status"] == "CERTIFIED"
    assert "ATTESTATION_STATUS_MISMATCH" in result["findings"]


def test_forged_certified_over_garbage_attestation(ready_chain) -> None:
    """A readable claim on an unreadable record can never be verified."""
    result = _audit181(ready_chain, attestation={"attestation_status": "CERTIFIED"})
    assert result["attestation_audit_status"] == "INCONSISTENT"
    assert result["published_attestation_status"] == "CERTIFIED"
    assert result["findings"] == ["ATTESTATION_INVALID"]


def test_forged_blocked_over_garbage_attestation(ready_chain) -> None:
    """A readable BLOCKED claim contradicting READY evidence is detected."""
    result = _audit181(ready_chain, attestation={"attestation_status": "BLOCKED"})
    assert result["attestation_audit_status"] == "INCONSISTENT"
    assert result["published_attestation_status"] == "BLOCKED"
    assert result["expected_attestation_status"] == "CERTIFIED"
    assert "ATTESTATION_INVALID" in result["findings"]
    assert "ATTESTATION_STATUS_MISMATCH" in result["findings"]


def test_forged_echo_fields_detected(ready_chain) -> None:
    payload = copy.deepcopy(ready_chain["attestation180"].model_dump())
    payload["bundle_audit_status"] = "INCONSISTENT"
    result = _audit181(ready_chain, attestation=payload)
    assert result["attestation_audit_status"] == "INCONSISTENT"
    assert "ATTESTATION_INVALID" in result["findings"]


def test_forged_finding_list_detected(ready_chain) -> None:
    payload = copy.deepcopy(ready_chain["attestation180"].model_dump())
    payload["finding_count"] = 5
    payload["findings"] = ["A", "B", "C", "D", "E"]
    result = _audit181(ready_chain, attestation=payload)
    assert result["attestation_audit_status"] == "INCONSISTENT"
    assert "ATTESTATION_INVALID" in result["findings"]


def test_forged_session_detected(ready_chain) -> None:
    payload = copy.deepcopy(ready_chain["attestation180"].model_dump())
    payload["session_id"] = str(uuid4())
    result = _audit181(ready_chain, attestation=payload)
    assert result["attestation_audit_status"] == "INCONSISTENT"
    assert "SESSION_BINDING_MISMATCH" in result["findings"]


# ---------------------------------------------------------------------------
# Unknown published status is never a fabricated claim
# ---------------------------------------------------------------------------


def test_unknown_published_status_is_unavailable(ready_chain) -> None:
    result = _audit181(ready_chain, attestation={"attestation_status": "GARBAGE"})
    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["published_attestation_status"] is None
    assert result["expected_attestation_status"] == "CERTIFIED"
    assert result["findings"] == ["ATTESTATION_INVALID"]


# ---------------------------------------------------------------------------
# Unavailable upstream evidence is insufficiency, not contradiction
# ---------------------------------------------------------------------------


def test_unavailable_children_not_treated_as_blocking(ready_chain) -> None:
    """An UNAVAILABLE child audit is insufficiency, never blocking."""
    audit178 = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id="",
        bundle_audit_status="UNAVAILABLE",
        available=False,
        consistent=False,
        published_bundle_status="UNAVAILABLE",
        expected_bundle_status="UNAVAILABLE",
        finding_count=1,
        findings=["EVIDENCE_INPUT_INVALID"],
        audit_source=AUDIT_SOURCE,
    )
    consistency179 = _consistency(ready_chain, audit178)
    attestation180 = _attestation(ready_chain["bundle"], audit178, consistency179)
    assert consistency179.consistency_status == "UNAVAILABLE"
    result = ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService.audit(
        bundle=ready_chain["bundle"],
        audit=audit178,
        consistency=consistency179,
        attestation=attestation180,
    )
    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert result["attestation_audit_status"] == "CONSISTENT"
    assert result["published_attestation_status"] == "UNAVAILABLE"


def test_upstream_unreadable_preserves_published_status(ready_chain) -> None:
    """Malformed upstream evidence never overwrites a readable claim."""
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.bundle_source = "FORGED_SOURCE"
    result = ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService.audit(
        bundle=bundle,
        audit=ready_chain["audit178"],
        consistency=ready_chain["consistency179"],
        attestation=ready_chain["attestation180"],
    )
    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["published_attestation_status"] == "CERTIFIED"
    assert result["expected_attestation_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in result["findings"]


# ---------------------------------------------------------------------------
# Wrong input types
# ---------------------------------------------------------------------------


def test_wrong_type_attestation_returns_unavailable(ready_chain) -> None:
    result = _audit181(ready_chain, attestation="not an attestation")
    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["published_attestation_status"] is None
    assert result["findings"] == ["ATTESTATION_INVALID"]


def test_wrong_type_bundle_returns_unavailable(ready_chain) -> None:
    result = ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService.audit(
        bundle="not a bundle",
        audit=ready_chain["audit178"],
        consistency=ready_chain["consistency179"],
        attestation=ready_chain["attestation180"],
    )
    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in result["findings"]


@pytest.mark.parametrize("bad_value", [None, 7, []])
def test_rejects_mutated_identity_types(ready_chain, bad_value) -> None:
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.session_id = bad_value
    result = ReasoningRunStage7ReleaseReadinessFinalAttestationAuditService.audit(
        bundle=bundle,
        audit=ready_chain["audit178"],
        consistency=ready_chain["consistency179"],
        attestation=ready_chain["attestation180"],
    )
    assert result["attestation_audit_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def _schema_kwargs(**overrides) -> dict:
    payload = {
        "session_id": "s",
        "attestation_audit_status": "CONSISTENT",
        "available": True,
        "consistent": True,
        "published_attestation_status": "CERTIFIED",
        "expected_attestation_status": "CERTIFIED",
        "finding_count": 0,
        "findings": [],
        "audit_source": T181_SOURCE,
    }
    payload.update(overrides)
    return payload


def test_schema_rejects_extra_fields() -> None:
    payload = _schema_kwargs()
    payload["extra"] = "forbidden"
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead.model_validate(
            payload
        )


def test_schema_rejects_incoherent_flags() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead(
            **_schema_kwargs(available=False)
        )


def test_schema_rejects_consistent_with_status_mismatch() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead(
            **_schema_kwargs(expected_attestation_status="BLOCKED")
        )


def test_schema_rejects_consistent_with_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead(
            **_schema_kwargs(finding_count=1, findings=["X"])
        )


def test_schema_rejects_inconsistent_without_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead(
            **_schema_kwargs(
                attestation_audit_status="INCONSISTENT",
                consistent=False,
            )
        )


def test_schema_rejects_unavailable_without_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead(
            **_schema_kwargs(
                attestation_audit_status="UNAVAILABLE",
                available=False,
                consistent=False,
            )
        )


def test_schema_rejects_unknown_status_without_invalid_finding() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead(
            **_schema_kwargs(
                attestation_audit_status="UNAVAILABLE",
                available=False,
                consistent=False,
                published_attestation_status=None,
                finding_count=1,
                findings=["OTHER"],
            )
        )


def test_schema_rejects_unknown_status_with_consistent_audit() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead(
            **_schema_kwargs(published_attestation_status=None)
        )


def test_schema_rejects_forged_source() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationAuditRead(
            **_schema_kwargs(audit_source="FORGED")
        )


# ---------------------------------------------------------------------------
# Immutability, determinism, architecture
# ---------------------------------------------------------------------------


def test_service_does_not_mutate_inputs(ready_chain) -> None:
    before = {
        "bundle": ready_chain["bundle"].model_dump(),
        "audit": ready_chain["audit178"].model_dump(),
        "consistency": ready_chain["consistency179"].model_dump(),
        "attestation": ready_chain["attestation180"].model_dump(),
    }
    _audit181(ready_chain)
    assert ready_chain["bundle"].model_dump() == before["bundle"]
    assert ready_chain["audit178"].model_dump() == before["audit"]
    assert ready_chain["consistency179"].model_dump() == before["consistency"]
    assert ready_chain["attestation180"].model_dump() == before["attestation"]


def test_service_is_deterministic(ready_chain) -> None:
    assert _audit181(ready_chain) == _audit181(ready_chain)


def test_service_has_no_provider_or_runtime_access() -> None:
    """Architecture: audit source contains no provider/network/DB access."""
    import rop.services.reasoning_run_stage_7_release_readiness_final_attestation_audit as module  # noqa: E501

    source = inspect.getsource(module)
    for token in (
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "api_key",
        "httpx",
        "sqlite",
        "postgres",
        "socket",
        "requests",
        "import os",
        "subprocess",
    ):
        assert token not in source.lower(), token


def test_service_module_calls_no_child_services() -> None:
    import rop.services.reasoning_run_stage_7_release_readiness_final_attestation_audit as module  # noqa: E501

    source = inspect.getsource(module)
    assert "Service.attest(" not in source
    assert "Service.assemble" not in source
    assert "Service.verify(" not in source


# ---------------------------------------------------------------------------
# Source constant test
# ---------------------------------------------------------------------------


def test_source_constant_is_correct() -> None:
    assert T181_SOURCE == (
        "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_AUDIT_TASK_181"
    )
