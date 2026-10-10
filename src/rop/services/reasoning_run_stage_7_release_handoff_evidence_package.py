"""Task 186: read-only assembly of release-handoff evidence."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

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
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package import (
    REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186,
    ReasoningRunStage7ReleaseHandoffEvidencePackageRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186",
    "ReasoningRunStage7ReleaseHandoffEvidencePackageContractError",
    "ReasoningRunStage7ReleaseHandoffEvidencePackageService",
]

_PROJECTION = ReasoningRunStage7FinalReleaseGateProjectionRead
_AUDIT = ReasoningRunStage7FinalReleaseGateAuditRead
_CONSISTENCY = ReasoningRunStage7FinalReleaseGateAuditConsistencyRead
_GATE_STATUSES = {"READY", "BLOCKED", "UNAVAILABLE"}
_AUDIT_STATUSES = {"CONSISTENT", "INCONSISTENT", "UNAVAILABLE"}
_ATTESTATION_STATUSES = {"CERTIFIED", "BLOCKED", "UNAVAILABLE"}
_T185_SOURCE = (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185
)


class ReasoningRunStage7ReleaseHandoffEvidencePackageContractError(Exception):
    """Task 186: the assembled release-handoff package violates its contract."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def _read_child(value: Any, model_type: type) -> tuple[dict[str, Any], bool]:
    """Take an independent snapshot and check it against its published contract."""
    if not isinstance(value, model_type):
        return {}, False
    try:
        payload = deepcopy(value.__dict__)
        model_type.model_validate(payload, strict=True)
    except (AttributeError, TypeError, ValidationError):
        try:
            payload = deepcopy(value.__dict__)
        except (AttributeError, TypeError):
            return {}, False
        return payload if isinstance(payload, dict) else {}, False
    return payload, True


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return value if type(value) is str else ""


def _status(payload: dict[str, Any], key: str, allowed: set[str]) -> str | None:
    value = payload.get(key)
    return value if type(value) is str and value in allowed else None


def _optional_bool(payload: dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    return value if type(value) is bool else None


def _findings(payload: dict[str, Any]) -> tuple[list[str], bool]:
    value = payload.get("findings")
    if type(value) is not list or not all(type(item) is str for item in value):
        return [], False
    return list(value), True


class ReasoningRunStage7ReleaseHandoffEvidencePackageService:
    """Deterministic, provider-neutral, read-only handoff package assembler."""

    @staticmethod
    def assemble(
        *,
        projection: _PROJECTION,
        audit: _AUDIT,
        consistency: _CONSISTENCY,
    ) -> dict[str, Any]:
        """Assemble already-published Task 183/184/185 read evidence.

        READY is limited to a canonical, finding-free gate and correctly
        bound, finding-free audit and consistency records. BLOCKED requires
        an explicit readable BLOCKED gate status. Otherwise the package is
        UNAVAILABLE, including when the child audit itself is UNAVAILABLE.
        No upstream service, provider, database, or network is used.
        """
        projection_data, projection_valid = _read_child(projection, _PROJECTION)
        audit_data, audit_valid = _read_child(audit, _AUDIT)
        consistency_data, consistency_valid = _read_child(consistency, _CONSISTENCY)

        projection_findings, projection_findings_valid = _findings(projection_data)
        audit_findings, audit_findings_valid = _findings(audit_data)
        consistency_findings, consistency_findings_valid = _findings(consistency_data)
        projection_count = len(projection_findings)
        audit_count = len(audit_findings)
        consistency_count = len(consistency_findings)

        projection_valid = (
            projection_valid
            and projection_findings_valid
            and type(projection_data.get("finding_count")) is int
            and projection_data["finding_count"] == projection_count
        )
        audit_valid = (
            audit_valid
            and audit_findings_valid
            and type(audit_data.get("finding_count")) is int
            and audit_data["finding_count"] == audit_count
        )
        consistency_valid = (
            consistency_valid
            and consistency_findings_valid
            and type(consistency_data.get("finding_count")) is int
            and consistency_data["finding_count"] == consistency_count
        )

        t183_status = _status(projection_data, "gate_status", _GATE_STATUSES)
        t183_attestation_status = _status(
            projection_data, "attestation_status", _ATTESTATION_STATUSES
        )
        t183_attestation_audit_status = _status(
            projection_data, "attestation_audit_status", _AUDIT_STATUSES
        )
        t183_consistency_status = _status(
            projection_data, "consistency_status", _AUDIT_STATUSES
        )
        t184_status = _status(audit_data, "gate_audit_status", _AUDIT_STATUSES)
        t185_status = _status(
            consistency_data, "gate_consistency_status", _AUDIT_STATUSES
        )
        t184_published = _status(audit_data, "published_gate_status", _GATE_STATUSES)
        t184_expected = _status(audit_data, "expected_gate_status", _GATE_STATUSES)
        t185_published = _status(
            consistency_data, "published_gate_status", _GATE_STATUSES
        )
        t185_expected = _status(
            consistency_data, "expected_gate_status", _GATE_STATUSES
        )

        sources_match = (
            _text(projection_data, "projection_source")
            == REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183
            and _text(audit_data, "audit_source")
            == REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184
            and _text(consistency_data, "consistency_source") == _T185_SOURCE
        )
        child_ids = (
            _text(projection_data, "session_id"),
            _text(audit_data, "session_id"),
            _text(consistency_data, "session_id"),
        )
        identity_matches = bool(child_ids[0]) and child_ids.count(child_ids[0]) == 3
        if identity_matches:
            session_id = child_ids[0]
        else:
            session_id = ""

        audit_binding_matches = (
            t184_status == "CONSISTENT"
            and _optional_bool(audit_data, "available") is True
            and _optional_bool(audit_data, "consistent") is True
            and t184_published == t183_status
            and t184_expected == t183_status
            and child_ids[0] == child_ids[1]
            and not audit_findings
        )
        consistency_binding_matches = (
            t185_status == "CONSISTENT"
            and _optional_bool(consistency_data, "available") is True
            and _optional_bool(consistency_data, "consistent") is True
            and t185_published == t183_status
            and t185_expected == t183_status
            and child_ids[0] == child_ids[2]
            and not consistency_findings
        )
        ready = (
            projection_valid
            and audit_valid
            and consistency_valid
            and sources_match
            and identity_matches
            and t183_status == "READY"
            and not projection_findings
            and audit_binding_matches
            and consistency_binding_matches
        )
        explicit_blocking = (
            (projection_valid and t183_status == "BLOCKED")
            or (audit_valid and "BLOCKED" in {t184_published, t184_expected})
            or (consistency_valid and "BLOCKED" in {t185_published, t185_expected})
        )

        findings: set[str] = (
            set(projection_findings) | set(audit_findings) | set(consistency_findings)
        )
        if not projection_valid:
            findings.add("T183_EVIDENCE_INVALID")
        if not audit_valid:
            findings.add("T184_EVIDENCE_INVALID")
        if not consistency_valid:
            findings.add("T185_EVIDENCE_INVALID")
        if not sources_match:
            findings.add("CHILD_SOURCE_MISMATCH")
        if not identity_matches:
            findings.add("CHILD_SESSION_MISMATCH")
        if t184_status == "UNAVAILABLE":
            findings.add("T184_AUDIT_UNAVAILABLE")
        elif not audit_binding_matches:
            findings.add("T184_AUDIT_NOT_BOUND")
        if t185_status == "UNAVAILABLE":
            findings.add("T185_CONSISTENCY_UNAVAILABLE")
        elif not consistency_binding_matches:
            findings.add("T185_CONSISTENCY_NOT_BOUND")
        if explicit_blocking:
            findings.add("EXPLICIT_BLOCKING_GATE_EVIDENCE")

        package_status = (
            "BLOCKED" if explicit_blocking else ("READY" if ready else "UNAVAILABLE")
        )
        if package_status == "READY":
            findings.clear()
        elif not findings:
            findings.add("HANDOFF_EVIDENCE_UNAVAILABLE")

        result = {
            "session_id": session_id,
            "t183_session_id": child_ids[0],
            "t183_gate_status": t183_status,
            "t183_attestation_status": t183_attestation_status,
            "t183_attestation_audit_status": t183_attestation_audit_status,
            "t183_consistency_status": t183_consistency_status,
            "t183_finding_count": projection_count,
            "t183_findings": projection_findings,
            "t183_projection_source": _text(projection_data, "projection_source"),
            "t183_valid": projection_valid,
            "t184_session_id": child_ids[1],
            "t184_gate_audit_status": t184_status,
            "t184_available": _optional_bool(audit_data, "available"),
            "t184_consistent": _optional_bool(audit_data, "consistent"),
            "t184_published_gate_status": t184_published,
            "t184_expected_gate_status": t184_expected,
            "t184_finding_count": audit_count,
            "t184_findings": audit_findings,
            "t184_audit_source": _text(audit_data, "audit_source"),
            "t184_valid": audit_valid,
            "t185_session_id": child_ids[2],
            "t185_gate_consistency_status": t185_status,
            "t185_available": _optional_bool(consistency_data, "available"),
            "t185_consistent": _optional_bool(consistency_data, "consistent"),
            "t185_published_gate_status": t185_published,
            "t185_expected_gate_status": t185_expected,
            "t185_finding_count": consistency_count,
            "t185_findings": consistency_findings,
            "t185_consistency_source": _text(consistency_data, "consistency_source"),
            "t185_valid": consistency_valid,
            "package_status": package_status,
            "finding_count": len(findings),
            "findings": sorted(findings),
            "package_source": (
                REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186
            ),
        }
        return ReasoningRunStage7ReleaseHandoffEvidencePackageService._project(result)

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        try:
            return ReasoningRunStage7ReleaseHandoffEvidencePackageRead.model_validate(
                result
            ).model_dump()
        except ValidationError as exc:
            raise ReasoningRunStage7ReleaseHandoffEvidencePackageContractError(
                "RELEASE_HANDOFF_PACKAGE_INVALID", str(exc)
            ) from exc
