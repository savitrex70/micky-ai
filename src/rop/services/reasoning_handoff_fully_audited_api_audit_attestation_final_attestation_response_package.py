"""Task 093: fully audited final-attestation response package service.

Binds canonical Task 087 final-attestation API response to the Task 088
consistency audit into a deterministic package. Pure composition boundary;
never accesses database, never performs HTTP calls, never calls external
models, never mutates inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService,  # noqa: E501
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093 = "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_TASK_093"  # noqa: E501  # noqa: E501

_PACKAGE_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "response",
    "response_consistency",
    "package_source",
    "package_fingerprint",
    "audited_package_fingerprint",
)

_PACKAGE_BOOLEAN_FIELDS = ("available", "package_consistent")


def _coerce_session_id(value: Any) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except (ValueError, TypeError):
            return None
    return None


def _deep_normalize_session_ids(value: Any) -> Any:
    """Return deep copy with every 'session_id' string coerced to UUID."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, val in value.items():
            if key == "session_id" and isinstance(val, str):
                try:
                    result[key] = UUID(val)
                    continue
                except (ValueError, TypeError):
                    pass
            result[key] = _deep_normalize_session_ids(val)
        return result
    if isinstance(value, list):
        return [_deep_normalize_session_ids(item) for item in value]
    return value


def _canonicalize(value: Any) -> Any:
    """Return deterministic JSON-safe form."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(k): _canonicalize(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _compute_package_fingerprint(package_core: Mapping[str, Any]) -> str:
    """SHA-256 of canonical package core."""
    payload = json.dumps(
        _canonicalize(package_core),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expected_package_fingerprint(package: Mapping[str, Any]) -> str:
    """Recompute the exact Task 093 package fingerprint for a package."""
    sid = package.get("session_id")
    if isinstance(sid, UUID):
        sid_str = str(sid)
    elif isinstance(sid, str):
        sid_str = sid
    else:
        sid_str = str(sid) if sid is not None else ""
    core = {
        "session_id": sid_str,
        "response": _canonicalize(package.get("response")),
        "response_consistency": _canonicalize(package.get("response_consistency")),
    }
    return _compute_package_fingerprint(core)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError(  # noqa: E501
    Exception
):
    """Task 093: final-attestation response package contract violation."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService:  # noqa: E501
    """Task 093: pure final-attestation response package service."""

    def __init__(
        self,
        *,
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService  # noqa: E501
            | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService  # noqa: E501
            | None
        ) = None,
    ) -> None:
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService()  # noqa: E501
        )
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService()  # noqa: E501
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Return the Task 093 response package for a session.

        Obtains the Task 087 final-attestation response exactly once (via
        its own Task 087 orchestrator, never via HTTP), then produces the
        Task 088 consistency audit of that exact response, then packages
        them. Any contract error from those services is allowed to
        propagate unchanged -- this layer does not catch, translate, or
        repair it.
        """
        response_087 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_service.build_for_session(  # noqa: E501
            db, session_id
        )
        response_consistency_088 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency_service.build(  # noqa: E501
            response=response_087
        )
        return self.build(
            session_id=session_id,
            response=response_087,
            response_consistency=response_consistency_088,
        )

    def build(
        self,
        *,
        session_id: Any = None,
        response: Mapping[str, Any] | None = None,
        response_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the response package. Pure; never mutates inputs."""
        if response is None or not isinstance(response, Mapping):
            raise _ContractError(
                "RESPONSE_MISMATCH",
                "response is required and must be a mapping",
            )
        if response_consistency is None or not isinstance(
            response_consistency, Mapping
        ):
            raise _ContractError(
                "RESPONSE_CONSISTENCY_MISMATCH",
                "response_consistency is required and must be a mapping",
            )

        if session_id is not None:
            sid = _coerce_session_id(session_id)
            if sid is None:
                raise _ContractError(
                    "SESSION_ID_INVALID",
                    f"session_id is not a UUID: {type(session_id).__name__}",
                )
        else:
            sid = _coerce_session_id(response.get("session_id"))
            if sid is None:
                raise _ContractError(
                    "SESSION_ID_INVALID",
                    "response.session_id is not a valid UUID",
                )

        resp_sid = _coerce_session_id(response.get("session_id"))
        if resp_sid != sid:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "response.session_id does not match supplied session_id",
            )

        if not response_consistency.get("session_consistent", False):
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "response_consistency reports session is not consistent",
            )

        resp_source = response.get("response_source")
        if (
            resp_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087  # noqa: E501
        ):
            raise _ContractError(
                "RESPONSE_SOURCE_MISMATCH",
                f"response_source is invalid: {resp_source!r}",
            )

        cons_source = response_consistency.get("response_consistency_source")
        if (
            cons_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088  # noqa: E501
        ):
            raise _ContractError(
                "RESPONSE_CONSISTENCY_SOURCE_MISMATCH",
                f"response_consistency_source is invalid: {cons_source!r}",
            )

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService._validate_result(  # noqa: E501
                _deep_normalize_session_ids(response)
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_MISMATCH",
                f"Task 087 response contract failed: {exc}",
            ) from exc

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService._validate_result(  # noqa: E501
                dict(response_consistency)
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_CONSISTENCY_MISMATCH",
                f"Task 088 consistency contract failed: {exc}",
            ) from exc

        # The Task 087 envelope relationship (response_consistent derived
        # from the Task 086 audit) is re-validated via the nested Task 087
        # validator above -- never trusted -- and the package verdict is
        # the AND of both nested verified flags, preserving any
        # legitimately reported defect instead of promoting it.
        package_consistent = bool(
            response.get("response_consistent", False)
            and response_consistency.get("response_consistent", False)
        )

        package_core = {
            "session_id": str(sid),
            "response": _canonicalize(response),
            "response_consistency": _canonicalize(response_consistency),
        }
        try:
            package_fingerprint = _compute_package_fingerprint(package_core)
        except Exception as exc:
            raise _ContractError(
                "PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                f"could not compute package fingerprint: {exc}",
            ) from exc

        result: dict[str, Any] = {
            "available": True,
            "package_consistent": package_consistent,
            "session_id": sid,
            "response": response,
            "response_consistency": response_consistency,
            "package_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093,  # noqa: E501
            "package_fingerprint": package_fingerprint,
            "audited_package_fingerprint": package_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        """Validate Task 093 package contract."""
        for field in _PACKAGE_REQUIRED_FIELDS:
            if field not in result:
                raise _ContractError("MISSING_PACKAGE_FIELD", f"result has no {field}")
        for field in _PACKAGE_BOOLEAN_FIELDS:
            if not isinstance(result[field], bool):
                raise _ContractError(
                    f"{field.upper()}_TYPE",
                    f"{field} is not boolean: {result[field]!r}",
                )
        if result["available"] is not True:
            raise _ContractError("RESULT_UNAVAILABLE", "available is not True")
        if not isinstance(result["session_id"], UUID):
            raise _ContractError(
                "SESSION_ID_INVALID",
                f"session_id is not a UUID: {type(result['session_id']).__name__}",
            )
        if not isinstance(result["response"], Mapping):
            raise _ContractError(
                "RESPONSE_MISMATCH",
                "response is not a mapping",
            )
        if not isinstance(result["response_consistency"], Mapping):
            raise _ContractError(
                "RESPONSE_CONSISTENCY_MISMATCH",
                "response_consistency is not a mapping",
            )
        if (
            result["package_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093  # noqa: E501
        ):
            raise _ContractError(
                "PACKAGE_SOURCE_MISMATCH",
                f"package_source mismatch: {result['package_source']!r}",
            )

        fp = result.get("package_fingerprint")
        if not isinstance(fp, str) or not re.fullmatch(r"^[0-9a-f]{64}$", fp):
            raise _ContractError(
                "PACKAGE_FINGERPRINT_FORMAT",
                f"package_fingerprint is not 64-char hex: {fp!r}",
            )

        audited_fp = result.get("audited_package_fingerprint")
        if not isinstance(audited_fp, str) or not re.fullmatch(
            r"^[0-9a-f]{64}$", audited_fp
        ):
            raise _ContractError(
                "AUDITED_PACKAGE_FINGERPRINT_FORMAT",
                "audited_package_fingerprint is not 64-char lowercase "
                f"hex: {audited_fp!r}",
            )

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService._validate_result(  # noqa: E501
                _deep_normalize_session_ids(result["response"])
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_MISMATCH",
                f"nested Task 087 response failed: {exc}",
            ) from exc

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService._validate_result(  # noqa: E501
                dict(result["response_consistency"])
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_CONSISTENCY_MISMATCH",
                f"nested Task 088 consistency failed: {exc}",
            ) from exc

        resp_sid = _coerce_session_id(result["response"].get("session_id"))
        if resp_sid != result["session_id"]:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "response session_id != package session_id",
            )
        if result["response_consistency"].get("session_consistent") is not True:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "response_consistency reports session is not consistent",
            )

        expected_package_consistent = bool(
            result["response"].get("response_consistent", False)
            and result["response_consistency"].get("response_consistent", False)
        )
        if result["package_consistent"] != expected_package_consistent:
            raise _ContractError(
                "PACKAGE_CONSISTENT_MISMATCH",
                "package_consistent does not match the nested response values",
            )

        try:
            recomputed = _expected_package_fingerprint(result)
        except Exception as exc:
            raise _ContractError(
                "PACKAGE_FINGERPRINT_COMPUTE_FAILED",
                f"could not recompute package fingerprint: {exc}",
            ) from exc
        if result["package_fingerprint"] != recomputed:
            raise _ContractError(
                "PACKAGE_FINGERPRINT_MISMATCH",
                "package_fingerprint does not match contents",
            )

        if result["audited_package_fingerprint"] != result["package_fingerprint"]:
            raise _ContractError(
                "AUDITED_PACKAGE_FINGERPRINT_MISMATCH",
                "audited_package_fingerprint does not equal package_fingerprint",
            )
