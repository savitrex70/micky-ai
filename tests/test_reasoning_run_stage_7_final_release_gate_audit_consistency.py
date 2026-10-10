"""Focused tests for Task 185 final release-gate audit consistency."""

from __future__ import annotations

import copy
import inspect
from importlib import import_module

import pytest
from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_final_release_gate_audit import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    ReasoningRunStage7FinalReleaseGateAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_audit_consistency import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185,
    ReasoningRunStage7FinalReleaseGateAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_release_gate_projection import (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183,
    ReasoningRunStage7FinalReleaseGateProjectionRead,
)
from rop.services.reasoning_run_stage_7_final_release_gate_audit_consistency import (
    ReasoningRunStage7FinalReleaseGateAuditConsistencyService,
)

_SERVICE = ReasoningRunStage7FinalReleaseGateAuditConsistencyService
_SESSION = "session-185"
_UNSET = object()


def _projection(
    status: str = "READY", session_id: str = _SESSION
) -> ReasoningRunStage7FinalReleaseGateProjectionRead:
    findings = {
        "READY": [],
        "BLOCKED": ["BLOCKING_EVIDENCE"],
        "UNAVAILABLE": ["GATE_EVIDENCE_UNAVAILABLE"],
    }[status]
    return ReasoningRunStage7FinalReleaseGateProjectionRead(
        session_id=session_id,
        gate_status=status,
        attestation_status={
            "READY": "CERTIFIED",
            "BLOCKED": "BLOCKED",
            "UNAVAILABLE": "UNAVAILABLE",
        }[status],
        attestation_audit_status={
            "READY": "CONSISTENT",
            "BLOCKED": "INCONSISTENT",
            "UNAVAILABLE": "UNAVAILABLE",
        }[status],
        consistency_status={
            "READY": "CONSISTENT",
            "BLOCKED": "CONSISTENT",
            "UNAVAILABLE": "UNAVAILABLE",
        }[status],
        finding_count=len(findings),
        findings=findings,
        projection_source=(
            REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
        ),
    )


def _audit(
    status: str = "READY",
    verdict: str = "CONSISTENT",
    *,
    published_status: str | None | object = _UNSET,
    expected_status: str | None = None,
    session_id: str | None = None,
) -> ReasoningRunStage7FinalReleaseGateAuditRead:
    published = status if published_status is _UNSET else published_status
    expected = status if expected_status is None else expected_status
    findings = (
        ["AUDIT_CONTRADICTION"]
        if verdict == "INCONSISTENT"
        else (["AUDIT_UNAVAILABLE"] if verdict == "UNAVAILABLE" else [])
    )
    if published is None:
        findings.append("PROJECTION_INVALID")
    return ReasoningRunStage7FinalReleaseGateAuditRead(
        session_id=("" if verdict == "UNAVAILABLE" else (session_id or _SESSION)),
        gate_audit_status=verdict,
        available=verdict != "UNAVAILABLE",
        consistent=verdict == "CONSISTENT",
        published_gate_status=published,
        expected_gate_status=expected,
        finding_count=len(findings),
        findings=sorted(findings),
        audit_source=REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    )


def _verify(projection: object = _UNSET, audit: object = _UNSET) -> dict[str, object]:
    return _SERVICE.verify(
        projection=_projection() if projection is _UNSET else projection,
        audit=_audit() if audit is _UNSET else audit,
    )


def test_schema_enforces_source_verdict_and_findings_contract() -> None:
    payload = {
        "session_id": _SESSION,
        "gate_consistency_status": "CONSISTENT",
        "available": True,
        "consistent": True,
        "published_gate_status": "READY",
        "expected_gate_status": "READY",
        "finding_count": 0,
        "findings": [],
        "consistency_source": (
            REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185
        ),
    }
    assert ReasoningRunStage7FinalReleaseGateAuditConsistencyRead(**payload)
    with pytest.raises(ValidationError):
        ReasoningRunStage7FinalReleaseGateAuditConsistencyRead(
            **payload, extra_field=True
        )
    invalid = dict(payload, consistency_source="FORGED")
    with pytest.raises(ValidationError, match="canonical Task 185 source"):
        ReasoningRunStage7FinalReleaseGateAuditConsistencyRead(**invalid)
    invalid = dict(payload, consistent=False)
    with pytest.raises(ValidationError, match="consistent must equal"):
        ReasoningRunStage7FinalReleaseGateAuditConsistencyRead(**invalid)
    invalid = dict(payload, findings=["Z", "A"], finding_count=2)
    with pytest.raises(ValidationError, match="findings must be sorted"):
        ReasoningRunStage7FinalReleaseGateAuditConsistencyRead(**invalid)


@pytest.mark.parametrize(
    ("status", "verdict"),
    [("READY", "READY"), ("BLOCKED", "BLOCKED"), ("UNAVAILABLE", "UNAVAILABLE")],
)
def test_matching_projection_and_available_audit_are_consistent(
    status: str, verdict: str
) -> None:
    result = _verify(_projection(status), _audit(verdict))
    assert result["gate_consistency_status"] == "CONSISTENT"
    assert result["available"] is True
    assert result["consistent"] is True
    assert result["published_gate_status"] == status
    assert result["expected_gate_status"] == status
    assert result["session_id"] == _SESSION
    assert result["finding_count"] == 0
    assert result["findings"] == []


def test_audit_unavailable_does_not_mismatch_on_blank_identity() -> None:
    unavailable = _audit("READY", "UNAVAILABLE")
    result = _verify(_projection(), unavailable)
    assert result["gate_consistency_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert "AUDIT_UNAVAILABLE" in result["findings"]
    assert "SESSION_MISMATCH" not in result["findings"]


def test_readable_status_conflict_remains_inconsistent_with_unavailable_audit() -> None:
    unavailable = _audit(
        "READY",
        "UNAVAILABLE",
        published_status="READY",
        expected_status="BLOCKED",
    )
    result = _verify(_projection("READY"), unavailable)
    assert result["gate_consistency_status"] == "INCONSISTENT"
    assert result["session_id"] == _SESSION
    assert {
        "EXPECTED_STATUS_MISMATCH",
        "AUDIT_STATUS_MISMATCH",
        "AUDIT_UNAVAILABLE",
    }.issubset(result["findings"])


def test_detects_status_and_session_conflicts() -> None:
    result = _verify(
        _projection("BLOCKED"),
        _audit("READY", session_id="other-session"),
    )
    assert result["gate_consistency_status"] == "INCONSISTENT"
    assert {
        "PUBLISHED_STATUS_MISMATCH",
        "EXPECTED_STATUS_MISMATCH",
        "SESSION_MISMATCH",
    }.issubset(result["findings"])


def test_audit_unavailable_with_no_readable_contradiction_is_unavailable() -> None:
    audit = _audit(
        "READY",
        "UNAVAILABLE",
        published_status=None,
        expected_status="READY",
    )
    result = _verify(_projection("READY"), audit)
    assert result["gate_consistency_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert result["published_gate_status"] == "READY"
    assert result["findings"] == ["AUDIT_UNAVAILABLE"]


@pytest.mark.parametrize("kind", ["projection", "audit"])
def test_revalidates_semantically_mutated_inputs(kind: str) -> None:
    projection = _projection()
    audit = _audit()
    if kind == "projection":
        projection.finding_count = 1
    else:
        audit.available = False
    result = _verify(projection, audit)
    assert result["gate_consistency_status"] == "INCONSISTENT"
    assert f"{kind.upper()}_INVARIANT_INVALID" in result["findings"]


def test_mutated_field_with_wrong_type_is_unavailable() -> None:
    projection = _projection()
    projection.gate_status = "UNKNOWN"
    result = _verify(projection, _audit())
    assert result["gate_consistency_status"] == "UNAVAILABLE"
    assert result["session_id"] == ""
    assert result["published_gate_status"] is None
    assert "EVIDENCE_INPUT_INVALID" in result["findings"]
    assert "PROJECTION_INVALID" in result["findings"]


def test_noncanonical_source_is_a_readable_contradiction() -> None:
    projection = _projection()
    projection.projection_source = "FORGED"
    result = _verify(projection, _audit())
    assert result["gate_consistency_status"] == "INCONSISTENT"
    assert "PROJECTION_SOURCE_INVALID" in result["findings"]


@pytest.mark.parametrize("projection,audit", [(None, _audit()), (_projection(), None)])
def test_wrong_input_types_are_unavailable(projection: object, audit: object) -> None:
    result = _verify(projection, audit)
    assert result["gate_consistency_status"] == "UNAVAILABLE"
    assert "EVIDENCE_INPUT_INVALID" in result["findings"]


def test_inputs_are_immutable_and_results_are_deterministic() -> None:
    projection = _projection("UNAVAILABLE")
    audit = _audit("UNAVAILABLE")
    before = copy.deepcopy((projection.model_dump(), audit.model_dump()))
    first = _verify(projection, audit)
    second = _verify(projection, audit)
    assert first == second
    assert (projection.model_dump(), audit.model_dump()) == before
    assert first["findings"] == sorted(set(first["findings"]))
    assert first["finding_count"] == len(first["findings"])


def test_service_does_not_call_upstream_services_or_perform_io() -> None:
    module = import_module(
        "rop.services.reasoning_run_stage_7_final_release_gate_audit_consistency"
    )

    source = inspect.getsource(module).lower()
    for forbidden in (
        "rop.services.reasoning_run_stage_7_final_release_gate_audit.",
        "rop.services.reasoning_run_stage_7_final_release_gate_projection.",
        "sqlite",
        "postgres",
        "requests",
        "httpx",
        "socket",
        "subprocess",
        "import os",
        "open(",
    ):
        assert forbidden not in source, forbidden
