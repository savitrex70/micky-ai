"""Task 188: read-only consistency check for a release-handoff package audit."""

# ruff: noqa: I001

from __future__ import annotations

from copy import deepcopy
from functools import cache
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package import (
    REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186,
    ReasoningRunStage7ReleaseHandoffEvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit import (
    REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187,
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_handoff_evidence_package_audit_consistency import (  # noqa: E501
    REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_188,
    ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyRead as _ResultRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_188",
    "ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyContractError",
    "ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService",
]

_MISSING = object()
_SOURCE = REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_188  # noqa: E501


@cache
def _field_adapter(annotation: Any) -> TypeAdapter[Any]:
    return TypeAdapter(annotation)


def _snapshot(value: object, model_type: type[BaseModel]) -> dict[str, Any] | None:
    """Copy the stored model state without invoking providers or mutating inputs."""
    if not isinstance(value, model_type):
        return None
    try:
        payload = deepcopy(value.__dict__)
    except (AttributeError, RecursionError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _is_readable(payload: dict[str, Any] | None, model_type: type[BaseModel]) -> bool:
    """Check field presence and strict field types, excluding cross-field rules."""
    if payload is None:
        return False
    try:
        for name, info in model_type.model_fields.items():
            value = payload.get(name, _MISSING)
            if value is _MISSING:
                return False
            _field_adapter(info.annotation).validate_python(value, strict=True)
    except (TypeError, ValueError):
        return False
    return True


def _satisfies_contract(payload: dict[str, Any], model_type: type[BaseModel]) -> bool:
    """Revalidate a fresh snapshot because Pydantic models are mutable."""
    try:
        model_type.model_validate(payload, strict=True)
    except (TypeError, ValueError, ValidationError):
        return False
    return True


def _unavailable(findings: list[str]) -> dict[str, Any]:
    return _project(
        {
            "session_id": "",
            "consistency_status": "UNAVAILABLE",
            "available": False,
            "consistent": False,
            "finding_count": len(findings),
            "findings": sorted(set(findings)),
            "consistency_source": _SOURCE,
        }
    )


def _project(result: dict[str, Any]) -> dict[str, Any]:
    try:
        validated = _ResultRead.model_validate(result, strict=True)
    except ValidationError as exc:
        raise ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyContractError(  # noqa: E501
            "RELEASE_HANDOFF_PACKAGE_AUDIT_CONSISTENCY_INVALID", str(exc)
        ) from exc
    return validated.model_dump()


class ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyContractError(
    Exception
):
    """Task 188 result violates its strict consistency contract."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7ReleaseHandoffEvidencePackageAuditConsistencyService:
    """Pure deterministic consistency check for Task 186 and Task 187 evidence."""

    @staticmethod
    def verify(
        *,
        package: ReasoningRunStage7ReleaseHandoffEvidencePackageRead,
        audit: ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead,
    ) -> dict[str, Any]:
        """Verify the binding of the published package to its independent audit.

        Missing, mistyped, or malformed evidence and missing session binding
        produce ``UNAVAILABLE``. Readable contradictions produce
        ``INCONSISTENT``. A valid UNAVAILABLE package may still be consistently
        audited; a valid UNAVAILABLE audit cannot establish a comparison.
        """
        package_payload = _snapshot(
            package, ReasoningRunStage7ReleaseHandoffEvidencePackageRead
        )
        audit_payload = _snapshot(
            audit, ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead
        )
        package_readable = _is_readable(
            package_payload, ReasoningRunStage7ReleaseHandoffEvidencePackageRead
        )
        audit_readable = _is_readable(
            audit_payload, ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead
        )
        if not package_readable or not audit_readable:
            findings = {"PACKAGE_OR_AUDIT_INVALID"}
            if not package_readable:
                findings.add("PACKAGE_UNREADABLE")
            if not audit_readable:
                findings.add("AUDIT_UNREADABLE")
            return _unavailable(sorted(findings))

        assert package_payload is not None and audit_payload is not None
        package_contract_valid = _satisfies_contract(
            package_payload, ReasoningRunStage7ReleaseHandoffEvidencePackageRead
        )
        audit_contract_valid = _satisfies_contract(
            audit_payload, ReasoningRunStage7ReleaseHandoffEvidencePackageAuditRead
        )

        # A structurally sound unavailable audit verified nothing. Do not
        # confuse it with a successful audit of an UNAVAILABLE package.
        if (
            audit_contract_valid
            and audit_payload["package_audit_status"] == "UNAVAILABLE"
        ):
            return _unavailable(["AUDIT_UNAVAILABLE"])

        package_session_id = package_payload["session_id"]
        audit_session_id = audit_payload["session_id"]

        findings: set[str] = set()
        session_binding_available = bool(package_session_id and audit_session_id)
        if session_binding_available and package_session_id != audit_session_id:
            findings.add("SESSION_MISMATCH")
        elif not session_binding_available:
            findings.add("SESSION_BINDING_UNAVAILABLE")
        if (
            package_payload["package_source"]
            != REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_SOURCE_TASK_186
        ):
            findings.add("PACKAGE_SOURCE_MISMATCH")
        if (
            audit_payload["audit_source"]
            != REASONING_RUN_STAGE_7_RELEASE_HANDOFF_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_187  # noqa: E501
        ):
            findings.add("AUDIT_SOURCE_MISMATCH")

        package_status = package_payload["package_status"]
        if package_status != audit_payload["published_package_status"]:
            findings.add("PUBLISHED_STATUS_MISMATCH")
        if package_status != audit_payload["expected_package_status"]:
            findings.add("EXPECTED_STATUS_CONTRADICTION")
        if audit_payload["package_audit_status"] != "CONSISTENT":
            findings.add("AUDIT_STATUS_NOT_CONSISTENT")
        if (
            audit_payload["package_audit_status"] == "CONSISTENT"
            and audit_payload["findings"]
        ):
            findings.add("AUDIT_FINDINGS_MISMATCH")
        if not audit_payload["available"]:
            findings.add("AUDIT_UNAVAILABLE")
        if not audit_payload["consistent"]:
            findings.add("AUDIT_INCONSISTENT")
        if package_payload["finding_count"] != len(package_payload["findings"]):
            findings.add("FINDING_COUNT_MISMATCH")
        if audit_payload["finding_count"] != len(audit_payload["findings"]):
            findings.add("FINDING_COUNT_MISMATCH")
        if not package_contract_valid:
            findings.add("PACKAGE_CONTRACT_INVALID")
        if not audit_contract_valid:
            findings.add("AUDIT_CONTRACT_INVALID")

        ordered_findings = sorted(findings)
        contradiction_findings = {
            "SESSION_MISMATCH",
            "PACKAGE_SOURCE_MISMATCH",
            "AUDIT_SOURCE_MISMATCH",
            "PUBLISHED_STATUS_MISMATCH",
            "EXPECTED_STATUS_CONTRADICTION",
            "AUDIT_STATUS_NOT_CONSISTENT",
            "AUDIT_FINDINGS_MISMATCH",
            "AUDIT_INCONSISTENT",
        }
        contradiction = bool(findings & contradiction_findings)
        status = (
            "INCONSISTENT"
            if contradiction
            else ("UNAVAILABLE" if ordered_findings else "CONSISTENT")
        )
        if status == "UNAVAILABLE":
            return _unavailable(ordered_findings or ["EVIDENCE_UNAVAILABLE"])
        return _project(
            {
                "session_id": package_session_id if session_binding_available else "",
                "consistency_status": status,
                "available": True,
                "consistent": status == "CONSISTENT",
                "finding_count": len(ordered_findings),
                "findings": ordered_findings,
                "consistency_source": _SOURCE,
            }
        )
