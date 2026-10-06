"""Task 156: Stage 7 request provenance and integrity audit service.

Independent deterministic audit of the Task 155 request package. The
service never trusts the builder's flags: it re-reads the canonical
Task 154 admission verdict, rebuilds the canonical Task 055 context,
recomputes the canonical Task 104 serialization and fingerprint, and
compares each of those against the packaged claims. A supplied
fingerprint is only accepted when it matches a fresh recomputation; a
PACKAGED request additionally requires an available package state, a
canonical ADMITTED admission bound to the audited session whose Stage 6
certification is CERTIFIED and whose public invariants are coherent
(admitted matches the verdict, the Stage 6 record is consistent, and
release readiness matches certification); and the canonical context
must itself report itself available and consistent, otherwise the audit
fails closed as UNAVAILABLE.

Read-only: no persistence, no provider call, no network, and no
mutation of the audited package.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_7_request_audit import (
    ReasoningRunStage7RequestAuditRead,
)
from rop.services.llm_boundary_contract import PAYLOAD_FIELDS
from rop.services.llm_request_serialization import (
    compute_fingerprint,
    serialize_context,
    to_json_safe,
    validate_payload,
)
from rop.services.reasoning_context import (
    ReasoningContextContractError,
    ReasoningContextService,
)
from rop.services.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionContractError,
    ReasoningRunStage7AdmissionService,
)
from rop.services.reasoning_run_stage_7_request import (
    REASONING_RUN_STAGE_7_REQUEST_SOURCE_TASK_155,
)

REASONING_RUN_STAGE_7_REQUEST_AUDIT_SOURCE_TASK_156 = (
    "REASONING_RUN_STAGE_7_REQUEST_AUDIT_TASK_156"
)

_DIMENSION_NAMES = (
    "session_consistent",
    "admission_consistent",
    "certification_consistent",
    "source_consistent",
    "payload_consistent",
    "fingerprint_consistent",
)


class ReasoningRunStage7RequestAuditContractError(Exception):
    """Task 156: the request audit result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7RequestAuditService:
    """Deterministic read-only provenance audit for a request package."""

    def __init__(
        self,
        admission_service: ReasoningRunStage7AdmissionService | None = None,
        reasoning_context_service: ReasoningContextService | None = None,
    ) -> None:
        self._admission_service = (
            admission_service
            if admission_service is not None
            else ReasoningRunStage7AdmissionService()
        )
        self._context_service = (
            reasoning_context_service
            if reasoning_context_service is not None
            else ReasoningContextService()
        )

    def audit(self, db: Session, package: Mapping[str, Any] | None) -> dict[str, Any]:
        """Independently verify one Task 155 package against canonical state.

        Statuses: ``CONSISTENT`` (every dimension re-derived and
        matched, with no findings), ``INCONSISTENT`` (readable package
        with at least one mismatch and at least one finding),
        ``UNAVAILABLE`` (package material missing, a verification input
        unreadable, or readable canonical evidence that reports itself
        unavailable -- no dimension is certified). Findings are
        deterministic, sorted, and deduplicated.
        """
        findings: list[str] = []
        dimensions = {name: False for name in _DIMENSION_NAMES}
        unavailable = False

        if not isinstance(package, Mapping):
            findings.append("REQUEST_PACKAGE_MISSING")
            return self._finalize("UNAVAILABLE", dimensions, findings)

        request_status = package.get("request_status")
        if request_status != "PACKAGED":
            findings.append(f"REQUEST_NOT_PACKAGED:{request_status}")
            return self._finalize("UNAVAILABLE", dimensions, findings)

        raw_payload = package.get("payload")
        if not isinstance(raw_payload, Mapping):
            findings.append("REQUEST_PAYLOAD_MISSING")
            return self._finalize("UNAVAILABLE", dimensions, findings)
        payload = dict(raw_payload)

        fingerprint = package.get("context_fingerprint")
        if not isinstance(fingerprint, str):
            findings.append("FINGERPRINT_MISSING")
            return self._finalize("UNAVAILABLE", dimensions, findings)

        package_available = package.get("available")
        availability_ok = package_available is True
        if not availability_ok:
            findings.append(f"REQUEST_AVAILABILITY_MISMATCH:{package_available}")

        source = package.get("request_source")
        if source == REASONING_RUN_STAGE_7_REQUEST_SOURCE_TASK_155:
            dimensions["source_consistent"] = True
        else:
            findings.append(f"REQUEST_SOURCE_MISMATCH:{source}")

        session_id = package.get("session_id")
        session_uuid: UUID | None = None
        if isinstance(session_id, str):
            try:
                session_uuid = UUID(session_id)
            except (ValueError, TypeError):
                session_uuid = None
        if session_uuid is None:
            findings.append("SESSION_IDENTITY_MALFORMED")
        elif payload.get("session_id") != session_id:
            findings.append(f"SESSION_IDENTITY_MISMATCH:{payload.get('session_id')}")
        else:
            dimensions["session_consistent"] = True

        unexpected_fields = validate_payload(payload)
        missing_fields = sorted(set(PAYLOAD_FIELDS) - set(payload))
        for field in sorted(unexpected_fields):
            findings.append(f"PAYLOAD_UNEXPECTED_FIELD:{field}")
        for field in missing_fields:
            findings.append(f"PAYLOAD_MISSING_FIELD:{field}")
        payload_fields_ok = not unexpected_fields and not missing_fields

        fingerprint_ok = False
        try:
            recomputed_fingerprint = compute_fingerprint(payload)
        except (TypeError, ValueError):
            findings.append("PAYLOAD_NOT_SERIALIZABLE")
        else:
            fingerprint_ok = recomputed_fingerprint == fingerprint
            if not fingerprint_ok:
                findings.append("FINGERPRINT_MISMATCH")

        canonical_ok = False
        if session_uuid is not None and not unavailable:
            try:
                context = self._context_service.build_for_session(db, session_uuid)
            except ReasoningContextContractError as exc:
                findings.append(f"CONTEXT_UNREADABLE:{exc.invariant}")
                unavailable = True
            else:
                if (
                    not isinstance(context, Mapping)
                    or context.get("available") is not True
                    or context.get("context_consistent") is not True
                ):
                    findings.append("CONTEXT_UNAVAILABLE")
                    unavailable = True
                else:
                    canonical_ok = self._canonical_equal(
                        serialize_context(context), payload
                    )
                    if not canonical_ok:
                        findings.append("PAYLOAD_NOT_CANONICAL")
                    context_session = str(context.get("session_id"))
                    if context_session != session_id:
                        findings.append(f"SESSION_IDENTITY_MISMATCH:{context_session}")

        if session_uuid is not None and not unavailable:
            try:
                admission = self._admission_service.evaluate(db, session_uuid)
            except ReasoningRunStage7AdmissionContractError as exc:
                findings.append(f"ADMISSION_UNREADABLE:{exc.invariant}")
                unavailable = True
            else:
                recomputed_admission = admission.get("admission_status")
                recomputed_admitted = admission.get("admitted")
                recomputed_cert = admission.get("stage_6_certification_status")
                recomputed_release_ready = admission.get("stage_6_release_ready")
                recomputed_cert_consistent = admission.get(
                    "stage_6_certification_consistent"
                )
                admission_session = admission.get("requested_session_id")
                session_binding_ok = admission_session == str(session_uuid)
                recomputed_is_admitted = recomputed_admission == "ADMITTED"
                recomputed_is_certified = recomputed_cert == "CERTIFIED"
                admission_verdict_coherent = (
                    recomputed_admitted == recomputed_is_admitted
                )
                certification_coherent = recomputed_cert_consistent is True
                release_ready_coherent = (
                    recomputed_release_ready == recomputed_is_certified
                )
                if not session_binding_ok:
                    findings.append(
                        f"ADMISSION_SESSION_ID_MISMATCH:{admission_session}"
                    )
                if not admission_verdict_coherent:
                    findings.append("ADMISSION_VERDICT_INCOHERENT")
                if not certification_coherent:
                    findings.append("STAGE_6_CERTIFICATION_INCOHERENT")
                if not release_ready_coherent:
                    findings.append("STAGE_6_RELEASE_READY_INCOHERENT")
                echoed_admission = package.get("admission_status")
                if not recomputed_is_admitted:
                    findings.append(f"ADMISSION_NOT_ADMITTED:{recomputed_admission}")
                elif echoed_admission != "ADMITTED":
                    findings.append(f"ADMISSION_STATUS_MISMATCH:{echoed_admission}")
                if (
                    session_binding_ok
                    and admission_verdict_coherent
                    and certification_coherent
                    and release_ready_coherent
                    and recomputed_is_admitted
                    and recomputed_is_certified
                    and echoed_admission == "ADMITTED"
                ):
                    dimensions["admission_consistent"] = True
                echoed_cert = package.get("stage_6_certification_status")
                if echoed_cert != recomputed_cert:
                    findings.append(f"STAGE_6_CERTIFICATION_MISMATCH:{echoed_cert}")
                elif not recomputed_is_certified:
                    findings.append(
                        f"STAGE_6_CERTIFICATION_NOT_CERTIFIED:{recomputed_cert}"
                    )
                else:
                    dimensions["certification_consistent"] = True

        dimensions["payload_consistent"] = (
            payload_fields_ok and canonical_ok and availability_ok
        )
        dimensions["fingerprint_consistent"] = fingerprint_ok

        if unavailable:
            status = "UNAVAILABLE"
        elif all(dimensions.values()):
            status = "CONSISTENT"
        else:
            status = "INCONSISTENT"
        return self._finalize(status, dimensions, findings)

    @staticmethod
    def _canonical_equal(left: Any, right: Any) -> bool:
        try:
            left_text = json.dumps(
                to_json_safe(left), sort_keys=True, separators=(",", ":"), default=str
            )
            right_text = json.dumps(
                to_json_safe(right), sort_keys=True, separators=(",", ":"), default=str
            )
        except (TypeError, ValueError):
            return False
        return left_text == right_text

    @staticmethod
    def _finalize(
        status: str, dimensions: dict[str, bool], findings: list[str]
    ) -> dict[str, Any]:
        if status == "UNAVAILABLE":
            dimensions = {name: False for name in _DIMENSION_NAMES}
        normalized = sorted(set(findings))
        result: dict[str, Any] = {
            "request_audit_status": status,
            "available": status != "UNAVAILABLE",
            **dimensions,
            "finding_count": len(normalized),
            "findings": normalized,
            "audit_source": REASONING_RUN_STAGE_7_REQUEST_AUDIT_SOURCE_TASK_156,
        }
        try:
            validated = ReasoningRunStage7RequestAuditRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7RequestAuditContractError(
                "REQUEST_AUDIT_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
