"""Task 075: expose the Task 071-074 attestation layer via a read-only API.

Delegation-only orchestration so the HTTP layer can expose the complete
Task 073 attestation package and its Task 074 independent consistency
audit without duplicating the wiring of Tasks 059-074 and without making
an internal HTTP call. It calls, in order:

    1. Task 063 (via Task 065's own orchestrator) to obtain the audit
       bundle the ``/reasoning-handoff/fully-audited`` route returns
    2. Task 066 to audit that exact response body
    3. Task 067 to package that exact response body and that exact audit
    4. Task 068 to audit that exact Task 067 package
    5. Task 069 to bundle that exact Task 067 package and Task 068 audit
    6. Task 070 to audit that exact Task 069 bundle
    7. Task 071 to attest that exact Task 069 bundle and Task 070 audit
    8. Task 072 to audit that exact Task 071 attestation
    9. Task 073 to package that exact Task 071 attestation and Task 072
       audit
    10. Task 074 to independently audit that exact Task 073 package

No contract rule, validation, or semantic check owned by Tasks 059-074 is
reimplemented here: every upstream contract error propagates unchanged so
the API layer can translate it into a generic internal failure rather
than silently downgrading a malformed or unavailable upstream result into
a successful attestation response.

A legitimate underlying defect (for example a Task 069 bundle that
correctly reports ``bundle_consistent = False``) is preserved unchanged
through every layer; this module never converts a truthfully reported
defect into a false success, and never mutates any nested input.

No decision, diagnosis, treatment, probability, utility, or confidence
semantics, and no external vendor or model client dependency, appears in
this module. Strictly read-only: no database write, no transaction
commit, and no internal HTTP call is made anywhere in this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.schemas.reasoning_handoff_api_audit_bundle import (
    ReasoningHandoffApiAuditBundleRead,
)
from rop.services.reasoning_handoff_fully_audited_api import (
    ReasoningHandoffFullyAuditedApiService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071,
    ReasoningHandoffFullyAuditedApiAuditAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072,
    ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073,
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_bundle import (
    ReasoningHandoffFullyAuditedApiAuditBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_bundle_consistency import (
    ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_package import (
    ReasoningHandoffFullyAuditedApiAuditPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_package_consistency import (
    ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_consistency import (
    ReasoningHandoffFullyAuditedApiConsistencyService,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075 = (
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_TASK_075"
)

_EXPECTED_METHOD = "GET"
_EXPECTED_STATUS_CODE = 200

_RESPONSE_REQUIRED_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "attestation_package",
    "attestation_package_consistency",
    "response_source",
)

_RESPONSE_BOOLEAN_FIELDS = ("available", "response_consistent")


def _coerce_session_id(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except (ValueError, TypeError):
            return None
    return None


def _transport_body(response: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact JSON-safe Task 065 response representation.

    Produces precisely what the Task 065 endpoint transmits for its own
    ``ReasoningHandoffApiAuditBundleRead`` response model. This is a
    representation step only: the caller's mapping is never mutated, and
    a body that cannot be typed is passed through unchanged so upstream
    validators still report the defect rather than this helper hiding it.
    """
    try:
        typed = ReasoningHandoffApiAuditBundleRead.model_validate(dict(response))
        return typed.model_dump(mode="json")
    except Exception:
        return dict(response)


class ReasoningHandoffFullyAuditedApiAuditAttestationResponseContractError(Exception):
    """Task 075: the attestation response could not be assembled."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationResponseContractError


class ReasoningHandoffFullyAuditedApiAuditAttestationResponseService:
    """Task 075: delegation-only orchestration of Tasks 059-074.

    Exists so the API layer can expose the Task 073 attestation package
    and its Task 074 independent consistency audit without duplicating
    Task 059-074 wiring. It does not duplicate any contract rule,
    validation, or semantic check, and never performs HTTP against its
    own process.
    """

    def __init__(
        self,
        reasoning_handoff_fully_audited_api_service: (
            ReasoningHandoffFullyAuditedApiService | None
        ) = None,
        reasoning_handoff_fully_audited_api_consistency_service: (
            ReasoningHandoffFullyAuditedApiConsistencyService | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_package_service: (
            ReasoningHandoffFullyAuditedApiAuditPackageService | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_package_consistency_service: (
            ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_bundle_service: (
            ReasoningHandoffFullyAuditedApiAuditBundleService | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_bundle_consistency_service: (
            ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_attestation_service: (
            ReasoningHandoffFullyAuditedApiAuditAttestationService | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_attestation_consistency_service: (
            ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_attestation_package_service: (
            ReasoningHandoffFullyAuditedApiAuditAttestationPackageService | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_attestation_package_consistency_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService
            | None
        ) = None,
    ) -> None:
        self.reasoning_handoff_fully_audited_api_service = (
            reasoning_handoff_fully_audited_api_service
            or ReasoningHandoffFullyAuditedApiService()
        )
        self.reasoning_handoff_fully_audited_api_consistency_service = (
            reasoning_handoff_fully_audited_api_consistency_service
            or ReasoningHandoffFullyAuditedApiConsistencyService()
        )
        self.reasoning_handoff_fully_audited_api_audit_package_service = (
            reasoning_handoff_fully_audited_api_audit_package_service
            or ReasoningHandoffFullyAuditedApiAuditPackageService()
        )
        self.reasoning_handoff_fully_audited_api_audit_package_consistency_service = (
            reasoning_handoff_fully_audited_api_audit_package_consistency_service
            or ReasoningHandoffFullyAuditedApiAuditPackageConsistencyService()
        )
        self.reasoning_handoff_fully_audited_api_audit_bundle_service = (
            reasoning_handoff_fully_audited_api_audit_bundle_service
            or ReasoningHandoffFullyAuditedApiAuditBundleService()
        )
        self.reasoning_handoff_fully_audited_api_audit_bundle_consistency_service = (
            reasoning_handoff_fully_audited_api_audit_bundle_consistency_service
            or ReasoningHandoffFullyAuditedApiAuditBundleConsistencyService()
        )
        self.reasoning_handoff_fully_audited_api_audit_attestation_service = (
            reasoning_handoff_fully_audited_api_audit_attestation_service
            or ReasoningHandoffFullyAuditedApiAuditAttestationService()
        )
        self.reasoning_handoff_fully_audited_api_audit_attestation_consistency_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_consistency_service
            or ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService()
        )
        self.reasoning_handoff_fully_audited_api_audit_attestation_package_service = (
            reasoning_handoff_fully_audited_api_audit_attestation_package_service
            or ReasoningHandoffFullyAuditedApiAuditAttestationPackageService()
        )
        self.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_package_consistency_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService()  # noqa: E501
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Return the Task 073/074 attestation response for a session.

        Obtains the Task 063 bundle exactly once (via Task 065's own
        orchestrator, never via HTTP), represents it in its exact
        transport form, then derives Tasks 066 through 074 from that
        exact representation. Any contract error from those services is
        allowed to propagate unchanged -- this layer does not catch,
        translate, or repair it.
        """
        bundle_063 = self.reasoning_handoff_fully_audited_api_service.build_for_session(
            db, session_id
        )
        body = _transport_body(bundle_063)
        path = f"/sessions/{session_id}/reasoning-handoff/fully-audited"

        api_consistency = (
            self.reasoning_handoff_fully_audited_api_consistency_service.build(
                session_id=session_id,
                method=_EXPECTED_METHOD,
                path=path,
                status_code=_EXPECTED_STATUS_CODE,
                response_body=body,
            )
        )
        package_067 = self.reasoning_handoff_fully_audited_api_audit_package_service.build(  # noqa: E501
            session_id=session_id,
            method=_EXPECTED_METHOD,
            path=path,
            status_code=_EXPECTED_STATUS_CODE,
            response=body,
            api_consistency=api_consistency,
        )
        package_consistency_068 = self.reasoning_handoff_fully_audited_api_audit_package_consistency_service.build(  # noqa: E501
            package=package_067
        )
        bundle_069 = (
            self.reasoning_handoff_fully_audited_api_audit_bundle_service.build(
                session_id=session_id,
                api_audit_package=package_067,
                api_audit_package_consistency=package_consistency_068,
            )
        )
        bundle_consistency_070 = self.reasoning_handoff_fully_audited_api_audit_bundle_consistency_service.build(  # noqa: E501
            bundle=bundle_069
        )
        attestation_071 = self.reasoning_handoff_fully_audited_api_audit_attestation_service.build(  # noqa: E501
            session_id=session_id,
            api_audit_bundle=bundle_069,
            api_audit_bundle_consistency=bundle_consistency_070,
        )
        attestation_consistency_072 = self.reasoning_handoff_fully_audited_api_audit_attestation_consistency_service.build(  # noqa: E501
            attestation=attestation_071
        )
        attestation_package_073 = self.reasoning_handoff_fully_audited_api_audit_attestation_package_service.build(  # noqa: E501
            session_id=session_id,
            attestation=attestation_071,
            attestation_consistency=attestation_consistency_072,
        )
        attestation_package_consistency_074 = self.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency_service.build(  # noqa: E501
            package=attestation_package_073
        )

        result: dict[str, Any] = {
            "available": True,
            "response_consistent": bool(
                attestation_package_consistency_074.get("package_consistent", False)
            ),
            "session_id": session_id,
            "attestation_package": attestation_package_073,
            "attestation_package_consistency": attestation_package_consistency_074,
            "response_source": (
                REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075  # noqa: E501
            ),
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        for field in _RESPONSE_REQUIRED_FIELDS:
            if field not in result:
                raise _ContractError("MISSING_RESPONSE_FIELD", "result has no " + field)
        for field in _RESPONSE_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise _ContractError(
                    field.upper() + "_TYPE",
                    field + " is not boolean: " + repr(result[field]),
                )
        if result["available"] is not True:
            raise _ContractError("RESULT_UNAVAILABLE", "available is not True")
        if not isinstance(result["session_id"], UUID):
            raise _ContractError(
                "SESSION_ID_INVALID",
                "session_id is not a UUID: " + type(result["session_id"]).__name__,
            )
        if not isinstance(result["attestation_package"], Mapping):
            raise _ContractError(
                "ATTESTATION_PACKAGE_MISMATCH",
                "attestation_package is not a mapping",
            )
        if not isinstance(result["attestation_package_consistency"], Mapping):
            raise _ContractError(
                "ATTESTATION_PACKAGE_CONSISTENCY_MISMATCH",
                "attestation_package_consistency is not a mapping",
            )
        if (
            result["response_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075  # noqa: E501
        ):
            raise _ContractError(
                "RESPONSE_SOURCE_MISMATCH",
                "response_source is not the Task 075 identifier: "
                + repr(result["response_source"]),
            )

        package = result["attestation_package"]
        package_consistency = result["attestation_package_consistency"]

        # Nested Task 073 contract.
        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationPackageService._validate_result(  # noqa: E501
                package
            )
        except Exception as exc:
            raise _ContractError(
                "ATTESTATION_PACKAGE_MISMATCH",
                "nested Task 073 package failed its own validator: " + str(exc),
            ) from exc

        # Nested Task 074 contract.
        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService._validate_result(  # noqa: E501
                dict(package_consistency), package=package
            )
        except Exception as exc:
            raise _ContractError(
                "ATTESTATION_PACKAGE_CONSISTENCY_MISMATCH",
                "nested Task 074 audit failed its own validator: " + str(exc),
            ) from exc

        # Session identity: preserved throughout the entire chain.
        package_sid = _coerce_session_id(package.get("session_id"))
        if package_sid != result["session_id"]:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "attestation_package.session_id != response session_id",
            )

        # Sources -- fixed identifiers preserved for every nested artifact.
        attestation = package.get("attestation")
        if not isinstance(attestation, Mapping):
            raise _ContractError(
                "ATTESTATION_PACKAGE_MISMATCH",
                "attestation_package.attestation is not a mapping",
            )
        if (
            attestation.get("attestation_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071
        ):
            raise _ContractError(
                "ATTESTATION_SOURCE_MISMATCH",
                "nested Task 071 attestation_source mismatch",
            )
        attestation_consistency = package.get("attestation_consistency")
        if not isinstance(attestation_consistency, Mapping):
            raise _ContractError(
                "ATTESTATION_PACKAGE_MISMATCH",
                "attestation_package.attestation_consistency is not a mapping",
            )
        if (
            attestation_consistency.get("attestation_consistency_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072  # noqa: E501
        ):
            raise _ContractError(
                "ATTESTATION_CONSISTENCY_SOURCE_MISMATCH",
                "nested Task 072 attestation_consistency_source mismatch",
            )
        if (
            package.get("package_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073  # noqa: E501
        ):
            raise _ContractError(
                "ATTESTATION_PACKAGE_SOURCE_MISMATCH",
                "nested Task 073 package_source mismatch",
            )
        if (
            package_consistency.get("package_consistency_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074  # noqa: E501
        ):
            raise _ContractError(
                "ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
                "nested Task 074 package_consistency_source mismatch",
            )

        # Fingerprint provenance: Task 074 must bind to the exact Task
        # 073 package it audited -- never trust the declared fingerprint,
        # always recompute it from the Task 073 package definition.
        try:
            expected_fp = ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyService._package_fingerprint(  # noqa: E501
                package
            )
        except Exception as exc:
            raise _ContractError(
                "PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                "could not recompute Task 073 package fingerprint: " + str(exc),
            ) from exc
        if package_consistency.get("package_fingerprint") != expected_fp:
            raise _ContractError(
                "PACKAGE_FINGERPRINT_MISMATCH",
                "attestation_package_consistency.package_fingerprint does not "
                "match the attestation_package",
            )
        if package_consistency.get("audited_package_fingerprint") != expected_fp:
            raise _ContractError(
                "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
                "attestation_package_consistency.audited_package_fingerprint "
                "does not match the attestation_package",
            )

        # Response relationship: never trust the declared flag, always
        # recompute it from the Task 074 audit's own package_consistent.
        expected_response_consistent = bool(
            package_consistency.get("package_consistent", False)
        )
        if result["response_consistent"] != expected_response_consistent:
            raise _ContractError(
                "RESPONSE_CONSISTENT_MISMATCH",
                "response_consistent does not match the Task 074 " "package_consistent",
            )
