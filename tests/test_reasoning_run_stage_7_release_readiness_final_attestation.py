"""Task 180: Stage 7 release-readiness final attestation tests.

Comprehensive tests for the final attestation over the Task 177
release-readiness evidence bundle, its Task 178 independent audit, and
the Task 179 bundle-audit consistency verdict. The tests compose Tasks
174-179 externally; the attestation service never invokes them itself.
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
    REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180,
    ReasoningRunStage7ReleaseReadinessFinalAttestationRead,
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

T180_SOURCE = REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_SOURCE_TASK_180
AUDIT_SOURCE = (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178
)

# Short aliases for the long Task 179 contract identifiers.
_C179_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead
_C179 = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyService

# ---------------------------------------------------------------------------
# Fixtures: externally composed Task 174-179 chains
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


def _consistency(
    chain, audit
) -> ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditConsistencyRead:
    """Run the real Task 179 service externally over bundle and audit."""
    return _C179_READ.model_validate(_C179.verify(bundle=chain["bundle"], audit=audit))


def _attest(bundle, audit, consistency) -> dict:
    return ReasoningRunStage7ReleaseReadinessFinalAttestationService.attest(
        bundle=bundle, audit=audit, consistency=consistency
    )


@pytest.fixture
def ready_chain() -> dict:
    return _chain("READY")


@pytest.fixture
def blocked_chain() -> dict:
    return _chain("BLOCKED")


@pytest.fixture
def unavailable_chain() -> dict:
    return _chain("UNAVAILABLE")


# ---------------------------------------------------------------------------
# Attestation verdicts for all three readiness states
# ---------------------------------------------------------------------------


def test_ready_chain_is_certified(ready_chain) -> None:
    audit = _bundle_audit(ready_chain)
    result = _attest(ready_chain["bundle"], audit, _consistency(ready_chain, audit))
    assert result["attestation_status"] == "CERTIFIED"
    assert result["certified"] is True
    assert result["blocked"] is False
    assert result["available"] is True
    assert result["session_id"] == ready_chain["session_id"]
    assert result["bundle_status"] == "READY"
    assert result["bundle_audit_status"] == "CONSISTENT"
    assert result["bundle_audit_consistency_status"] == "CONSISTENT"
    assert result["finding_count"] == 0
    assert result["findings"] == []
    assert result["attestation_source"] == T180_SOURCE


def test_blocked_chain_is_blocked(blocked_chain) -> None:
    audit = _bundle_audit(blocked_chain)
    result = _attest(blocked_chain["bundle"], audit, _consistency(blocked_chain, audit))
    assert result["attestation_status"] == "BLOCKED"
    assert result["blocked"] is True
    assert result["certified"] is False
    assert result["available"] is True
    assert "BUNDLE_BLOCKED" in result["findings"]
    assert result["bundle_status"] == "BLOCKED"


def test_unavailable_chain_is_unavailable(unavailable_chain) -> None:
    """A faithfully represented UNAVAILABLE readiness result stays UNAVAILABLE."""
    audit = _bundle_audit(unavailable_chain)
    result = _attest(
        unavailable_chain["bundle"], audit, _consistency(unavailable_chain, audit)
    )
    assert result["attestation_status"] == "UNAVAILABLE"
    assert result["certified"] is False
    assert result["blocked"] is False
    assert result["available"] is False
    assert "BUNDLE_UNAVAILABLE" in result["findings"]
    assert result["bundle_status"] == "UNAVAILABLE"
    assert result["bundle_audit_status"] == "CONSISTENT"
    assert result["bundle_audit_consistency_status"] == "CONSISTENT"


def test_result_validates_against_strict_schema(ready_chain) -> None:
    audit = _bundle_audit(ready_chain)
    result = _attest(ready_chain["bundle"], audit, _consistency(ready_chain, audit))
    ReasoningRunStage7ReleaseReadinessFinalAttestationRead.model_validate(result)


# ---------------------------------------------------------------------------
# Unavailable audit/consistency are insufficiency, not blocking
# ---------------------------------------------------------------------------


def test_unavailable_audit_is_unavailable_not_blocked(ready_chain) -> None:
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
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
    consistency = _consistency(ready_chain, audit)
    result = _attest(ready_chain["bundle"], audit, consistency)
    assert result["attestation_status"] == "UNAVAILABLE"
    assert result["blocked"] is False
    assert "AUDIT_UNAVAILABLE" in result["findings"]
    assert "CONSISTENCY_UNAVAILABLE" in result["findings"]
    assert "BUNDLE_AUDIT_SESSION_MISMATCH" not in result["findings"]


# ---------------------------------------------------------------------------
# Contradictions are never hidden; forged states are never certified
# ---------------------------------------------------------------------------


def test_detached_consistent_audit_is_not_certified(ready_chain) -> None:
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id=str(uuid4()),
        bundle_audit_status="CONSISTENT",
        available=True,
        consistent=True,
        published_bundle_status="READY",
        expected_bundle_status="READY",
        finding_count=0,
        findings=[],
        audit_source=AUDIT_SOURCE,
    )
    consistency = _consistency(ready_chain, audit)
    result = _attest(ready_chain["bundle"], audit, consistency)
    assert result["attestation_status"] != "CERTIFIED"
    assert "BUNDLE_AUDIT_SESSION_MISMATCH" in result["findings"]
    assert consistency.consistency_status == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency.findings


def test_inconsistent_audit_yields_blocked(ready_chain) -> None:
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id=ready_chain["session_id"],
        bundle_audit_status="INCONSISTENT",
        available=True,
        consistent=False,
        published_bundle_status="READY",
        expected_bundle_status="BLOCKED",
        finding_count=1,
        findings=["EXPECTED_STATUS_MISMATCH"],
        audit_source=AUDIT_SOURCE,
    )
    consistency = _consistency(ready_chain, audit)
    result = _attest(ready_chain["bundle"], audit, consistency)
    assert result["attestation_status"] == "BLOCKED"
    assert "AUDIT_INCONSISTENT" in result["findings"]
    assert "AUDIT_HAS_FINDINGS" in result["findings"]
    assert "EXPECTED_STATUS_MISMATCH" in result["findings"]
    assert consistency.consistency_status == "INCONSISTENT"
    assert "CONSISTENCY_INCONSISTENT" in result["findings"]


def test_status_echo_mismatch_is_not_certified(ready_chain) -> None:
    audit = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead(
        session_id=ready_chain["session_id"],
        bundle_audit_status="INCONSISTENT",
        available=True,
        consistent=False,
        published_bundle_status="BLOCKED",
        expected_bundle_status="BLOCKED",
        finding_count=1,
        findings=["BUNDLE_STATUS_MISMATCH"],
        audit_source=AUDIT_SOURCE,
    )
    result = _attest(ready_chain["bundle"], audit, _consistency(ready_chain, audit))
    assert result["attestation_status"] == "BLOCKED"
    assert "PUBLISHED_STATUS_MISMATCH" in result["findings"]
    assert "EXPECTED_STATUS_MISMATCH" in result["findings"]


# ---------------------------------------------------------------------------
# Malformed input, wrong types, forgery, mutation
# ---------------------------------------------------------------------------


def test_wrong_type_bundle_returns_unavailable(ready_chain) -> None:
    audit = _bundle_audit(ready_chain)
    result = _attest("not a bundle", audit, _consistency(ready_chain, audit))
    assert result["attestation_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]
    assert result["bundle_status"] is None
    assert result["bundle_audit_status"] is None
    assert result["bundle_audit_consistency_status"] is None
    assert result["session_id"] == ""


def test_wrong_type_audit_returns_unavailable(ready_chain) -> None:
    audit = _bundle_audit(ready_chain)
    result = _attest(ready_chain["bundle"], 42, _consistency(ready_chain, audit))
    assert result["attestation_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_wrong_type_consistency_returns_unavailable(ready_chain) -> None:
    audit = _bundle_audit(ready_chain)
    result = _attest(ready_chain["bundle"], audit, ["nope"])
    assert result["attestation_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_forged_bundle_source_detected(ready_chain) -> None:
    audit = _bundle_audit(ready_chain)
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.bundle_source = "FORGED_SOURCE"
    result = _attest(bundle, audit, _consistency(ready_chain, audit))
    assert result["attestation_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_mutated_bundle_status_detected(ready_chain) -> None:
    """A READY bundle forged to BLOCKED fails revalidation, never BLOCKED."""
    audit = _bundle_audit(ready_chain)
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.bundle_status = "BLOCKED"
    result = _attest(bundle, audit, _consistency(ready_chain, audit))
    assert result["attestation_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


def test_mutated_audit_session_detected(ready_chain) -> None:
    """A surviving session mutation is a demonstrable contradiction."""
    audit = copy.deepcopy(_bundle_audit(ready_chain))
    audit.session_id = str(uuid4())
    consistency = _consistency(ready_chain, audit)
    result = _attest(ready_chain["bundle"], audit, consistency)
    assert result["attestation_status"] == "BLOCKED"
    assert result["certified"] is False
    assert "BUNDLE_AUDIT_SESSION_MISMATCH" in result["findings"]
    assert consistency.consistency_status == "INCONSISTENT"
    assert "SESSION_MISMATCH" in consistency.findings


@pytest.mark.parametrize("bad_value", [None, 7, []])
def test_rejects_mutated_identity_types(ready_chain, bad_value) -> None:
    audit = _bundle_audit(ready_chain)
    bundle = copy.deepcopy(ready_chain["bundle"])
    bundle.session_id = bad_value
    result = _attest(bundle, audit, _consistency(ready_chain, audit))
    assert result["attestation_status"] == "UNAVAILABLE"
    assert result["findings"] == ["EVIDENCE_INPUT_INVALID"]


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


def _schema_kwargs(**overrides) -> dict:
    payload = {
        "session_id": "s",
        "attestation_status": "UNAVAILABLE",
        "certified": False,
        "blocked": False,
        "available": False,
        "bundle_status": "UNAVAILABLE",
        "bundle_audit_status": "CONSISTENT",
        "bundle_audit_consistency_status": "CONSISTENT",
        "finding_count": 1,
        "findings": ["BUNDLE_UNAVAILABLE"],
        "attestation_source": T180_SOURCE,
    }
    payload.update(overrides)
    return payload


def test_schema_rejects_extra_fields(ready_chain) -> None:
    audit = _bundle_audit(ready_chain)
    result = _attest(ready_chain["bundle"], audit, _consistency(ready_chain, audit))
    result["extra_field"] = "forbidden"
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead.model_validate(result)


def test_schema_rejects_incoherent_flags() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
            **_schema_kwargs(certified=True)
        )


def test_schema_rejects_certified_with_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
            **_schema_kwargs(
                attestation_status="CERTIFIED",
                certified=True,
                available=True,
                bundle_status="READY",
            )
        )


def test_schema_rejects_certified_without_session() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
            **_schema_kwargs(
                session_id="",
                attestation_status="CERTIFIED",
                certified=True,
                available=True,
                bundle_status="READY",
                finding_count=0,
                findings=[],
            )
        )


def test_schema_rejects_certified_over_unready_bundle() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
            **_schema_kwargs(
                attestation_status="CERTIFIED",
                certified=True,
                available=True,
                finding_count=0,
                findings=[],
            )
        )


def test_schema_rejects_blocked_without_blocking_evidence() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
            **_schema_kwargs(
                attestation_status="BLOCKED",
                blocked=True,
                available=True,
                bundle_status="READY",
                finding_count=1,
                findings=["X"],
            )
        )


def test_schema_rejects_blocked_without_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
            **_schema_kwargs(
                attestation_status="BLOCKED",
                blocked=True,
                available=True,
                bundle_status="BLOCKED",
                finding_count=0,
                findings=[],
            )
        )


def test_schema_rejects_unavailable_hiding_blocking_evidence() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
            **_schema_kwargs(bundle_status="BLOCKED")
        )


def test_schema_rejects_unavailable_without_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
            **_schema_kwargs(finding_count=0, findings=[])
        )


def test_schema_rejects_unsorted_findings() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
            **_schema_kwargs(finding_count=2, findings=["Z", "A"])
        )


def test_schema_rejects_forged_source() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7ReleaseReadinessFinalAttestationRead(
            **_schema_kwargs(attestation_source="FORGED")
        )


# ---------------------------------------------------------------------------
# Immutability, determinism, architecture
# ---------------------------------------------------------------------------


def test_service_does_not_mutate_inputs(ready_chain) -> None:
    audit = _bundle_audit(ready_chain)
    consistency = _consistency(ready_chain, audit)
    before = {
        "bundle": ready_chain["bundle"].model_dump(),
        "audit": audit.model_dump(),
        "consistency": consistency.model_dump(),
    }
    _attest(ready_chain["bundle"], audit, consistency)
    assert ready_chain["bundle"].model_dump() == before["bundle"]
    assert audit.model_dump() == before["audit"]
    assert consistency.model_dump() == before["consistency"]


def test_service_is_deterministic(ready_chain) -> None:
    audit = _bundle_audit(ready_chain)
    consistency = _consistency(ready_chain, audit)
    first = _attest(ready_chain["bundle"], audit, consistency)
    second = _attest(ready_chain["bundle"], audit, consistency)
    assert first == second


def test_service_has_no_provider_or_runtime_access() -> None:
    """Architecture: attestation source contains no provider/network/DB access."""
    import rop.services.reasoning_run_stage_7_release_readiness_final_attestation as module  # noqa: E501

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
    import rop.services.reasoning_run_stage_7_release_readiness_final_attestation as module  # noqa: E501

    source = inspect.getsource(module)
    assert "Service.assemble" not in source
    assert "Service.audit(" not in source
    assert "Service.verify(" not in source


# ---------------------------------------------------------------------------
# Source constant test
# ---------------------------------------------------------------------------


def test_source_constant_is_correct() -> None:
    assert T180_SOURCE == (
        "REASONING_RUN_STAGE_7_RELEASE_READINESS_FINAL_ATTESTATION_TASK_180"
    )
