"""Task 087: expose the Task 085/086 final-attestation bundle via a read-only API.

Delegation-only orchestration so the HTTP layer can expose the complete
Task 085 final attestation bundle and its Task 086 independent
consistency audit without duplicating the wiring of Tasks 079-086 and
without making an internal HTTP call. It calls, in order:

    1. Task 085 (via its own orchestrator, which itself obtains the Task
       083 final attestation package exactly once and derives the Task
       084 consistency audit of that exact package) to obtain the final
       attestation bundle the response represents
    2. Task 086 to independently audit that exact Task 085 bundle

No contract rule, validation, or semantic check owned by Tasks 079-086
is reimplemented here: every upstream contract error propagates
unchanged so the API layer can translate it into a generic internal
failure rather than silently downgrading a malformed or unavailable
upstream result into a successful final-attestation response.

A legitimate underlying defect (for example a Task 085 bundle that
correctly reports ``bundle_consistent = False``) is preserved unchanged
through every layer; this module never converts a truthfully reported
defect into a false success, and never mutates any nested input.

No decision, diagnosis, treatment, probability, utility, or confidence
semantics, and no external vendor or model dependency, appears in this
module. Strictly read-only: no database write, no transaction commit,
and no internal HTTP call is made anywhere in this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    _expected_bundle_fingerprint as _task085_expected_bundle_fingerprint,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService,  # noqa: E501
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087 = "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_TASK_087"  # noqa: E501

_RESPONSE_REQUIRED_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "final_attestation_bundle",
    "final_attestation_bundle_consistency",
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


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseContractError(  # noqa: E501
    Exception
):
    """Task 087: the final-attestation response could not be assembled."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseContractError  # noqa: E501


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService:  # noqa: E501
    """Task 087: delegation-only orchestration of Tasks 085-086.

    Exists so the API layer can expose the Task 085 final attestation
    bundle and its Task 086 independent consistency audit without
    duplicating Task 079-086 wiring. It does not duplicate any contract
    rule, validation, or semantic check, and never performs HTTP against
    its own process.
    """

    def __init__(
        self,
        *,
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService  # noqa: E501
            | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService  # noqa: E501
            | None
        ) = None,
    ) -> None:
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService()  # noqa: E501
        )
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService()  # noqa: E501
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Return the Task 085/086 final-attestation response for a session.

        Obtains the Task 085 final attestation bundle exactly once (via
        its own Task 085 orchestrator, never via HTTP), then produces
        the Task 086 consistency audit of that exact bundle. Any
        contract error from those services is allowed to propagate
        unchanged -- this layer does not catch, translate, or repair it.
        """
        bundle_085 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_service.build_for_session(  # noqa: E501
            db, session_id
        )
        bundle_consistency_086 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency_service.build(  # noqa: E501
            bundle=bundle_085
        )

        result: dict[str, Any] = {
            "available": True,
            "response_consistent": bool(
                bundle_consistency_086.get("bundle_consistent", False)
            ),
            "session_id": session_id,
            "final_attestation_bundle": bundle_085,
            "final_attestation_bundle_consistency": bundle_consistency_086,
            "response_source": (
                REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087  # noqa: E501
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
        if not isinstance(result["final_attestation_bundle"], Mapping):
            raise _ContractError(
                "FINAL_ATTESTATION_BUNDLE_MISMATCH",
                "final_attestation_bundle is not a mapping",
            )
        if not isinstance(result["final_attestation_bundle_consistency"], Mapping):
            raise _ContractError(
                "FINAL_ATTESTATION_BUNDLE_CONSISTENCY_MISMATCH",
                "final_attestation_bundle_consistency is not a mapping",
            )
        if (
            result["response_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087  # noqa: E501
        ):
            raise _ContractError(
                "RESPONSE_SOURCE_MISMATCH",
                "response_source is not the Task 087 identifier: "
                + repr(result["response_source"]),
            )

        bundle = result["final_attestation_bundle"]
        bundle_consistency = result["final_attestation_bundle_consistency"]

        # Nested Task 085 contract.
        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService._validate_result(  # noqa: E501
                bundle
            )
        except Exception as exc:
            raise _ContractError(
                "FINAL_ATTESTATION_BUNDLE_MISMATCH",
                "nested Task 085 bundle failed its own validator: " + str(exc),
            ) from exc

        # Nested Task 086 contract.
        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService._validate_result(  # noqa: E501
                dict(bundle_consistency), bundle=bundle
            )
        except Exception as exc:
            raise _ContractError(
                "FINAL_ATTESTATION_BUNDLE_CONSISTENCY_MISMATCH",
                "nested Task 086 audit failed its own validator: " + str(exc),
            ) from exc

        # Session identity: preserved throughout the entire chain.
        bundle_sid = _coerce_session_id(bundle.get("session_id"))
        if bundle_sid != result["session_id"]:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "final_attestation_bundle.session_id != response session_id",
            )
        if bundle_consistency.get("session_consistent") is not True:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "final_attestation_bundle_consistency reports session is not "
                "consistent",
            )

        # Sources -- fixed identifiers preserved for every nested artifact.
        if (
            bundle.get("bundle_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085  # noqa: E501
        ):
            raise _ContractError(
                "FINAL_ATTESTATION_BUNDLE_SOURCE_MISMATCH",
                "nested Task 085 bundle_source mismatch",
            )
        if (
            bundle_consistency.get("bundle_consistency_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086  # noqa: E501
        ):
            raise _ContractError(
                "FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
                "nested Task 086 bundle_consistency_source mismatch",
            )

        # Fingerprint provenance: Task 086 must bind to the exact Task
        # 085 bundle it audited -- never trust the declared fingerprint,
        # always recompute it from the Task 085 bundle definition.
        if bundle_consistency.get("bundle_fingerprint") != bundle.get(
            "bundle_fingerprint"
        ):
            raise _ContractError(
                "BUNDLE_FINGERPRINT_MISMATCH",
                "final_attestation_bundle_consistency.bundle_fingerprint does "
                "not match the final_attestation_bundle",
            )
        try:
            expected_fp = _task085_expected_bundle_fingerprint(bundle)
        except Exception as exc:
            raise _ContractError(
                "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                "could not recompute Task 085 bundle fingerprint: " + str(exc),
            ) from exc
        if bundle_consistency.get("bundle_fingerprint") != expected_fp:
            raise _ContractError(
                "BUNDLE_FINGERPRINT_MISMATCH",
                "final_attestation_bundle_consistency.bundle_fingerprint does "
                "not match the recomputed Task 085 bundle fingerprint",
            )
        if bundle_consistency.get("audited_bundle_fingerprint") != expected_fp:
            raise _ContractError(
                "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
                "final_attestation_bundle_consistency.audited_bundle_fingerprint "  # noqa: E501
                "does not match the recomputed Task 085 bundle fingerprint",
            )

        # Response relationship: never trust the declared flag, always
        # recompute it from the Task 086 audit's own bundle_consistent.
        expected_response_consistent = bool(
            bundle_consistency.get("bundle_consistent", False)
        )
        if result["response_consistent"] != expected_response_consistent:
            raise _ContractError(
                "RESPONSE_CONSISTENT_MISMATCH",
                "response_consistent does not match the Task 086 " "bundle_consistent",
            )
