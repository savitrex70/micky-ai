"""Task 099: expose the Task 097/098 final release attestation via a read-only API.

Delegation-only orchestration so the HTTP layer can expose the complete
Task 097 final release attestation and its Task 098 independent
consistency audit without duplicating the wiring of Tasks 055-098 and
without making an internal HTTP call. It calls, in order:

    1. Task 097 (via its own orchestrator, which itself obtains the Task
       095 response bundle exactly once and derives the Task 096
       consistency audit of that exact bundle) to obtain the final
       release attestation the response represents
    2. Task 098 to independently audit that exact Task 097 attestation

No contract rule, validation, or semantic check owned by Tasks 055-098
is reimplemented here: every upstream contract error propagates
unchanged so the API layer can translate it into a generic internal
failure rather than silently downgrading a malformed or unavailable
upstream result into a successful final-release-attestation response.

A legitimate underlying defect (for example a Task 097 attestation that
correctly reports ``final_attestation_consistent = False``) is preserved
unchanged through every layer; this module never converts a truthfully
reported defect into a false success, and never mutates any nested input.

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

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    _expected_final_fingerprint as _task097_expected_final_fingerprint,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService,  # noqa: E501
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099 = "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_TASK_099"  # noqa: E501

_RESPONSE_REQUIRED_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "final_release_attestation",
    "final_release_attestation_consistency",
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


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError(  # noqa: E501
    Exception
):
    """Task 099: the final release attestation response could not be assembled."""  # noqa: E501

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseContractError  # noqa: E501


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService:  # noqa: E501
    """Task 099: delegation-only orchestration of Tasks 097-098.

    Exists so the API layer can expose the Task 097 final release
    attestation and its Task 098 independent consistency audit without
    duplicating Task 055-098 wiring. It does not duplicate any contract
    rule, validation, or semantic check, and never performs HTTP against
    its own process.
    """

    def __init__(
        self,
        *,
        reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService  # noqa: E501
            | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService  # noqa: E501
            | None
        ) = None,
    ) -> None:
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService()  # noqa: E501
        )
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService()  # noqa: E501
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Return the Task 097/098 final release attestation response.

        Obtains the Task 097 final release attestation exactly once (via
        its own Task 097 orchestrator, never via HTTP), then produces
        the Task 098 consistency audit of that exact attestation. Any
        contract error from those services is allowed to propagate
        unchanged -- this layer does not catch, translate, or repair it.
        """
        attestation_097 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_service.build_for_session(  # noqa: E501
            db, session_id
        )
        attestation_consistency_098 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency_service.build(  # noqa: E501
            final_attestation=attestation_097
        )

        result: dict[str, Any] = {
            "available": True,
            "response_consistent": bool(
                attestation_consistency_098.get("final_attestation_consistent", False)
            ),
            "session_id": session_id,
            "final_release_attestation": attestation_097,
            "final_release_attestation_consistency": attestation_consistency_098,
            "response_source": (
                REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099  # noqa: E501
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
        if not isinstance(result["final_release_attestation"], Mapping):
            raise _ContractError(
                "FINAL_RELEASE_ATTESTATION_MISMATCH",
                "final_release_attestation is not a mapping",
            )
        if not isinstance(result["final_release_attestation_consistency"], Mapping):
            raise _ContractError(
                "FINAL_RELEASE_ATTESTATION_CONSISTENCY_MISMATCH",
                "final_release_attestation_consistency is not a mapping",
            )
        if (
            result["response_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099  # noqa: E501
        ):
            raise _ContractError(
                "RESPONSE_SOURCE_MISMATCH",
                "response_source is not the Task 099 identifier: "
                + repr(result["response_source"]),
            )

        attestation = result["final_release_attestation"]
        attestation_consistency = result["final_release_attestation_consistency"]

        # Nested Task 097 contract.
        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService._validate_result(  # noqa: E501
                attestation
            )
        except Exception as exc:
            raise _ContractError(
                "FINAL_RELEASE_ATTESTATION_MISMATCH",
                "nested Task 097 attestation failed its own validator: " + str(exc),
            ) from exc

        # Nested Task 098 contract, audited against the exact Task 097
        # attestation this response represents.
        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService._validate_result(  # noqa: E501
                dict(attestation_consistency), final_attestation=attestation
            )
        except Exception as exc:
            raise _ContractError(
                "FINAL_RELEASE_ATTESTATION_CONSISTENCY_MISMATCH",
                "nested Task 098 audit failed its own validator: " + str(exc),
            ) from exc

        # Session identity: preserved throughout the entire chain. Task
        # 098 carries no session_id field of its own, so binding is the
        # Task 097 attestation session plus the audit's session flag.
        attestation_sid = _coerce_session_id(attestation.get("session_id"))
        if attestation_sid != result["session_id"]:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "final_release_attestation.session_id != response session_id",
            )
        if attestation_consistency.get("session_consistent") is not True:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "final_release_attestation_consistency reports session is not "
                "consistent",
            )

        # Sources -- fixed identifiers preserved for every nested artifact.
        if (
            attestation.get("final_attestation_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097  # noqa: E501
        ):
            raise _ContractError(
                "FINAL_RELEASE_ATTESTATION_SOURCE_MISMATCH",
                "nested Task 097 final_attestation_source mismatch",
            )
        if (
            attestation_consistency.get("final_attestation_consistency_source")
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098  # noqa: E501
        ):
            raise _ContractError(
                "FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_MISMATCH",
                "nested Task 098 final_attestation_consistency_source mismatch",
            )

        # Fingerprint provenance: Task 098 must bind to the exact Task
        # 097 attestation it audited -- never trust the declared
        # fingerprints, always recompute them from the Task 097
        # attestation definition, with no fallback between fields.
        if attestation_consistency.get(
            "final_attestation_fingerprint"
        ) != attestation.get("final_attestation_fingerprint"):
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
                "final_release_attestation_consistency.final_attestation_fingerprint "  # noqa: E501
                "does not match the final_release_attestation",
            )
        try:
            expected_fp = _task097_expected_final_fingerprint(attestation)
        except Exception as exc:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                "could not recompute Task 097 attestation fingerprint: " + str(exc),
            ) from exc
        if attestation_consistency.get("final_attestation_fingerprint") != expected_fp:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
                "final_release_attestation_consistency.final_attestation_fingerprint "  # noqa: E501
                "does not match the recomputed Task 097 attestation fingerprint",
            )
        if (
            attestation_consistency.get("audited_final_attestation_fingerprint")
            != expected_fp
        ):
            raise _ContractError(
                "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
                "final_release_attestation_consistency.audited_final_attestation_fingerprint "  # noqa: E501
                "does not match the recomputed Task 097 attestation fingerprint",
            )

        # Response relationship: never trust the declared flag, always
        # recompute it from the Task 098 audit's own
        # final_attestation_consistent.
        expected_response_consistent = bool(
            attestation_consistency.get("final_attestation_consistent", False)
        )
        if result["response_consistent"] != expected_response_consistent:
            raise _ContractError(
                "RESPONSE_CONSISTENT_MISMATCH",
                "response_consistent does not match the Task 098 "
                "final_attestation_consistent",
            )
