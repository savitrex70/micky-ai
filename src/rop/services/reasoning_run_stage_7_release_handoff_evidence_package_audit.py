"""Task 187: independent verification of the Task 186 handoff package."""

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
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit import (
    REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187,
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187",
    "ReasoningRunStage7ReleaseHandoffEvidencePackageAuditContractError",
    "ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService",
]

_PROJECTION = ReasoningRunStage7FinalReleaseGateProjectionRead
_AUDIT = ReasoningRunStage7FinalReleaseGateAuditRead
_CONSISTENCY = ReasoningRunStage7FinalReleaseGateAuditConsistencyRead
_PACKAGE = ReasoningRunStage7ReleaseHandoffEvidencePackageRead
_AUDIT_RESULT = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead
_GATE_STATUSES = {"READY", "BLOCKED", "UNAVAILABLE"}
_AUDIT_STATUSES = {"CONSISTENT", "INCONSISTENT", "UNAVAILABLE"}
_ATTESTATION_STATUSES = {"CERTIFIED", "BLOCKED", "UNAVAILABLE"}
_CHILD_MODELS = (_PROJECTION, _AUDIT, _CONSISTENCY)
_CHILD_SOURCES = (
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_PROJECTION_SOURCE_TASK_183,
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_SOURCE_TASK_184,
    REASONING_RUN_STAGE_7_FINAL_RELEASE_GATE_AUDIT_CONSISTENCY_SOURCE_TASK_185,
)


class ReasoningRunStage7ReleaseHandoffEvidencePackageAuditContractError(Exception):
    """Task 187 result violates its strict independent audit contract."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


def _snapshot_child(value: Any, model_type: type) -> tuple[dict[str, Any], bool, bool]:
    """Return an isolated child snapshot, validity, and structural readability."""
    if not isinstance(value, model_type):
        return {}, False, False
    try:
        payload = deepcopy(value.__dict__)
    except (AttributeError, TypeError, ValueError):
        return {}, False, False
    try:
        model_type.model_validate(payload, strict=True)
    except ValidationError as exc:
        # Root-level invariant failures retain readable values for auditing;
        # field-level/type failures are insufficient evidence.
        readable = all(not error["loc"] for error in exc.errors())
        return payload, False, readable
    return payload, True, True


def _text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    return value if type(value) is str else ""


def _status(payload: dict[str, Any], field: str, allowed: set[str]) -> str | None:
    value = payload.get(field)
    return value if type(value) is str and value in allowed else None


def _boolean(payload: dict[str, Any], field: str) -> bool | None:
    value = payload.get(field)
    return value if type(value) is bool else None


def _findings(payload: dict[str, Any]) -> tuple[list[str], bool]:
    value = payload.get("findings")
    if type(value) is not list or not all(type(item) is str for item in value):
        return [], False
    return list(value), True


def _package_evidence(
    projection: dict[str, Any],
    projection_valid: bool,
    audit: dict[str, Any],
    audit_valid: bool,
    consistency: dict[str, Any],
    consistency_valid: bool,
) -> dict[str, Any]:
    """Independently derive the complete Task 186 output from child records."""
    projection_findings, projection_findings_valid = _findings(projection)
    audit_findings, audit_findings_valid = _findings(audit)
    consistency_findings, consistency_findings_valid = _findings(consistency)
    projection_count = len(projection_findings)
    audit_count = len(audit_findings)
    consistency_count = len(consistency_findings)

    projection_valid = (
        projection_valid
        and projection_findings_valid
        and type(projection.get("finding_count")) is int
        and projection["finding_count"] == projection_count
    )
    audit_valid = (
        audit_valid
        and audit_findings_valid
        and type(audit.get("finding_count")) is int
        and audit["finding_count"] == audit_count
    )
    consistency_valid = (
        consistency_valid
        and consistency_findings_valid
        and type(consistency.get("finding_count")) is int
        and consistency["finding_count"] == consistency_count
    )

    t183_status = _status(projection, "gate_status", _GATE_STATUSES)
    t183_attestation = _status(projection, "attestation_status", _ATTESTATION_STATUSES)
    t183_audit_status = _status(projection, "attestation_audit_status", _AUDIT_STATUSES)
    t183_consistency_status = _status(projection, "consistency_status", _AUDIT_STATUSES)
    t184_status = _status(audit, "gate_audit_status", _AUDIT_STATUSES)
    t185_status = _status(consistency, "gate_consistency_status", _AUDIT_STATUSES)
    t184_published = _status(audit, "published_gate_status", _GATE_STATUSES)
    t184_expected = _status(audit, "expected_gate_status", _GATE_STATUSES)
    t185_published = _status(consistency, "published_gate_status", _GATE_STATUSES)
    t185_expected = _status(consistency, "expected_gate_status", _GATE_STATUSES)

    sources_match = (
        _text(projection, "projection_source") == _CHILD_SOURCES[0]
        and _text(audit, "audit_source") == _CHILD_SOURCES[1]
        and _text(consistency, "consistency_source") == _CHILD_SOURCES[2]
    )
    child_ids = (
        _text(projection, "session_id"),
        _text(audit, "session_id"),
        _text(consistency, "session_id"),
    )
    identity_matches = bool(child_ids[0]) and child_ids.count(child_ids[0]) == 3
    session_id = child_ids[0] if identity_matches else ""

    audit_binding_matches = (
        t184_status == "CONSISTENT"
        and _boolean(audit, "available") is True
        and _boolean(audit, "consistent") is True
        and t184_published == t183_status
        and t184_expected == t183_status
        and child_ids[0] == child_ids[1]
        and not audit_findings
    )
    consistency_binding_matches = (
        t185_status == "CONSISTENT"
        and _boolean(consistency, "available") is True
        and _boolean(consistency, "consistent") is True
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
    package_findings = (
        set(projection_findings) | set(audit_findings) | set(consistency_findings)
    )
    if not projection_valid:
        package_findings.add("T183_EVIDENCE_INVALID")
    if not audit_valid:
        package_findings.add("T184_EVIDENCE_INVALID")
    if not consistency_valid:
        package_findings.add("T185_EVIDENCE_INVALID")
    if not sources_match:
        package_findings.add("CHILD_SOURCE_MISMATCH")
    if not identity_matches:
        package_findings.add("CHILD_SESSION_MISMATCH")
    if t184_status == "UNAVAILABLE":
        package_findings.add("T184_AUDIT_UNAVAILABLE")
    elif not audit_binding_matches:
        package_findings.add("T184_AUDIT_NOT_BOUND")
    if t185_status == "UNAVAILABLE":
        package_findings.add("T185_CONSISTENCY_UNAVAILABLE")
    elif not consistency_binding_matches:
        package_findings.add("T185_CONSISTENCY_NOT_BOUND")
    if explicit_blocking:
        package_findings.add("EXPLICIT_BLOCKING_GATE_EVIDENCE")

    package_status = (
        "BLOCKED" if explicit_blocking else ("READY" if ready else "UNAVAILABLE")
    )
    if package_status == "READY":
        package_findings.clear()
    elif not package_findings:
        package_findings.add("HANDOFF_EVIDENCE_UNAVAILABLE")

    return {
        "session_id": session_id,
        "t183_session_id": child_ids[0],
        "t183_gate_status": t183_status,
        "t183_attestation_status": t183_attestation,
        "t183_attestation_audit_status": t183_audit_status,
        "t183_consistency_status": t183_consistency_status,
        "t183_finding_count": projection_count,
        "t183_findings": projection_findings,
        "t183_projection_source": _text(projection, "projection_source"),
        "t183_valid": projection_valid,
        "t184_session_id": child_ids[1],
        "t184_gate_audit_status": t184_status,
        "t184_available": _boolean(audit, "available"),
        "t184_consistent": _boolean(audit, "consistent"),
        "t184_published_gate_status": t184_published,
        "t184_expected_gate_status": t184_expected,
        "t184_finding_count": audit_count,
        "t184_findings": audit_findings,
        "t184_audit_source": _text(audit, "audit_source"),
        "t184_valid": audit_valid,
        "t185_session_id": child_ids[2],
        "t185_gate_consistency_status": t185_status,
        "t185_available": _boolean(consistency, "available"),
        "t185_consistent": _boolean(consistency, "consistent"),
        "t185_published_gate_status": t185_published,
        "t185_expected_gate_status": t185_expected,
        "t185_finding_count": consistency_count,
        "t185_findings": consistency_findings,
        "t185_consistency_source": _text(consistency, "consistency_source"),
        "t185_valid": consistency_valid,
        "package_status": package_status,
        "finding_count": len(package_findings),
        "findings": sorted(package_findings),
        "package_source": (
            REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186
        ),
    }


def _package_payload(value: Any) -> tuple[dict[str, Any], bool, bool]:
    """Read package values without trusting model_dump or mutable cached state."""
    if isinstance(value, _PACKAGE):
        try:
            payload = deepcopy(value.__dict__)
        except (AttributeError, TypeError, ValueError):
            return {}, False, False
    elif isinstance(value, dict):
        try:
            payload = deepcopy(value)
        except (TypeError, ValueError):
            return {}, False, False
    else:
        return {}, False, False
    try:
        _PACKAGE.model_validate(payload, strict=True)
    except ValidationError:
        return payload, False, True
    return payload, True, True


class ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService:
    """Pure audit of a Task 186 package against independent Task 183–185 inputs."""

    @staticmethod
    def audit(
        *,
        projection: _PROJECTION,
        audit: _AUDIT,
        consistency: _CONSISTENCY,
        package: dict[str, Any] | _PACKAGE,
    ) -> dict[str, Any]:
        """Derive package state independently and verify the published evidence."""
        service = ReasoningRunStage7ReleaseHandoffEvidencePackageAuditService
        projection_data, projection_valid, projection_readable = _snapshot_child(
            projection, _PROJECTION
        )
        audit_data, audit_valid, audit_readable = _snapshot_child(audit, _AUDIT)
        consistency_data, consistency_valid, consistency_readable = _snapshot_child(
            consistency, _CONSISTENCY
        )
        expected = _package_evidence(
            projection_data,
            projection_valid,
            audit_data,
            audit_valid,
            consistency_data,
            consistency_valid,
        )
        package_data, package_valid, package_readable = _package_payload(package)
        published = _status(package_data, "package_status", _GATE_STATUSES)
        expected_status = expected["package_status"]
        findings: set[str] = set()
        contradiction = False

        upstream_readable = (
            projection_readable and audit_readable and consistency_readable
        )
        upstream_valid = projection_valid and audit_valid and consistency_valid
        if not upstream_readable:
            findings.add("EVIDENCE_INPUT_INVALID")
        if not package_valid:
            findings.add("PACKAGE_INVALID")
        if published is None:
            findings.add("PACKAGE_INVALID")
        if published != expected_status:
            findings.add("PACKAGE_STATUS_MISMATCH")
            contradiction = published is not None

        # A package is an evidence envelope: every child field, validity flag,
        # finding and source must match the independent derivation.
        if package_readable:
            for field, expected_value in expected.items():
                if (
                    field not in package_data
                    or package_data.get(field) != expected_value
                ):
                    if field == "package_source":
                        findings.add("PACKAGE_SOURCE_INVALID")
                    elif field.startswith("t183_"):
                        findings.add("T183_EVIDENCE_MISMATCH")
                    elif field.startswith("t184_"):
                        findings.add("T184_EVIDENCE_MISMATCH")
                    elif field.startswith("t185_"):
                        findings.add("T185_EVIDENCE_MISMATCH")
                    elif field == "session_id":
                        findings.add("SESSION_BINDING_MISMATCH")
                    elif field == "package_status":
                        findings.add("PACKAGE_STATUS_MISMATCH")
                    else:
                        findings.add("PACKAGE_FINDINGS_MISMATCH")
                    if field != "package_status" or published is not None:
                        contradiction = True

        source_values = (
            projection_data.get("projection_source"),
            audit_data.get("audit_source"),
            consistency_data.get("consistency_source"),
        )
        if any(
            type(value) is str and value and value != canonical
            for value, canonical in zip(source_values, _CHILD_SOURCES, strict=True)
        ):
            findings.add("CHILD_SOURCE_INVALID")
            contradiction = True

        # A readable status echo conflict is independently contradictory,
        # including when another child is unavailable.
        t183_status = _status(projection_data, "gate_status", _GATE_STATUSES)
        t184_published = _status(audit_data, "published_gate_status", _GATE_STATUSES)
        t184_expected = _status(audit_data, "expected_gate_status", _GATE_STATUSES)
        t185_published = _status(
            consistency_data, "published_gate_status", _GATE_STATUSES
        )
        t185_expected = _status(
            consistency_data, "expected_gate_status", _GATE_STATUSES
        )
        if _status(audit_data, "gate_audit_status", _AUDIT_STATUSES) == "UNAVAILABLE":
            findings.add("T184_AUDIT_UNAVAILABLE")
        if (
            _status(consistency_data, "gate_consistency_status", _AUDIT_STATUSES)
            == "UNAVAILABLE"
        ):
            findings.add("T185_CONSISTENCY_UNAVAILABLE")
        for echoed in (t184_published, t184_expected, t185_published, t185_expected):
            if t183_status is not None and echoed is not None and echoed != t183_status:
                findings.add("CHILD_STATUS_MISMATCH")
                contradiction = True
        if (
            t184_published is not None
            and t184_expected is not None
            and t184_published != t184_expected
        ) or (
            t185_published is not None
            and t185_expected is not None
            and t185_published != t185_expected
        ):
            findings.add("CHILD_STATUS_MISMATCH")
            contradiction = True

        # Empty identities carried by a valid UNAVAILABLE child are unknown,
        # not evidence of a session mismatch.
        identities = [
            (projection_data, "session_id", None),
            (
                audit_data,
                "session_id",
                _status(audit_data, "gate_audit_status", _AUDIT_STATUSES),
            ),
            (
                consistency_data,
                "session_id",
                _status(consistency_data, "gate_consistency_status", _AUDIT_STATUSES),
            ),
        ]
        nonempty_ids = [
            _text(record, field)
            for record, field, child_status in identities
            if child_status != "UNAVAILABLE" and _text(record, field)
        ]
        if nonempty_ids and any(
            identity != nonempty_ids[0] for identity in nonempty_ids
        ):
            findings.add("SESSION_BINDING_MISMATCH")
            contradiction = True

        # Structurally valid, canonical evidence that explicitly reports a
        # contradiction cannot be masked by another unavailable child.
        if (
            audit_valid
            and _status(audit_data, "gate_audit_status", _AUDIT_STATUSES)
            == "INCONSISTENT"
        ):
            findings.add("T184_AUDIT_INCONSISTENT")
            contradiction = True
        if (
            consistency_valid
            and _status(consistency_data, "gate_consistency_status", _AUDIT_STATUSES)
            == "INCONSISTENT"
        ):
            findings.add("T185_CONSISTENCY_INCONSISTENT")
            contradiction = True

        if upstream_readable and not upstream_valid:
            findings.add("CHILD_INVARIANT_INVALID")
            contradiction = True

        findings_list = sorted(findings)
        unavailable_input = (
            not upstream_readable
            or not upstream_valid
            or any(
                _status(data, field, statuses) == "UNAVAILABLE"
                for data, field, statuses in (
                    (projection_data, "gate_status", _GATE_STATUSES),
                    (audit_data, "gate_audit_status", _AUDIT_STATUSES),
                    (consistency_data, "gate_consistency_status", _AUDIT_STATUSES),
                )
            )
        )
        if contradiction:
            status = "INCONSISTENT"
            session_id = _text(projection_data, "session_id")
        elif unavailable_input or not package_valid or published is None:
            status = "UNAVAILABLE"
            session_id = ""
            if not findings_list:
                findings_list = ["EVIDENCE_UNAVAILABLE"]
        else:
            status = "CONSISTENT"
            session_id = expected["session_id"]
            findings_list = []

        return service._project(
            {
                "session_id": session_id,
                "package_audit_status": status,
                "available": status != "UNAVAILABLE",
                "consistent": status == "CONSISTENT",
                "published_package_status": published,
                "expected_package_status": expected_status,
                "finding_count": len(set(findings_list)),
                "findings": sorted(set(findings_list)),
                "audit_source": (
                    REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187
                ),
            }
        )

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        try:
            return _AUDIT_RESULT.model_validate(result).model_dump()
        except ValidationError as exc:
            raise ReasoningRunStage7ReleaseHandoffEvidencePackageAuditContractError(
                "RELEASE_HANDOFF_PACKAGE_AUDIT_INVALID", str(exc)
            ) from exc
