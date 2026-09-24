"""Task 073: fully audited attestation package service.

Binds canonical Task 071 attestation to the Task 072 consistency audit into
a deterministic package. Pure composition boundary; never accesses database,
never performs HTTP calls, never calls external models, never mutates inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071,
    ReasoningHandoffFullyAuditedApiAuditAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072,
    ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService,
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073 = (
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_TASK_073"
)

_PACKAGE_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "attestation",
    "attestation_consistency",
    "package_source",
    "package_fingerprint",
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


class ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError(  # noqa: E501
    Exception
):
    """Task 073: attestation package contract violation."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationPackageContractError


class ReasoningHandoffFullyAuditedApiAuditAttestationPackageService:
    """Task 073: pure attestation package service."""

    def build(
        self,
        *,
        session_id: Any = None,
        attestation: Mapping[str, Any] | None = None,
        attestation_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the attestation package. Pure; never mutates inputs."""
        if attestation is None or not isinstance(attestation, Mapping):
            raise _ContractError(
                "ATTESTATION_MISMATCH",
                "attestation is required and must be a mapping",
            )
        if attestation_consistency is None or not isinstance(
            attestation_consistency, Mapping
        ):
            raise _ContractError(
                "ATTESTATION_CONSISTENCY_MISMATCH",
                "attestation_consistency is required and must be a mapping",
            )

        # Session ID resolution and validation
        if session_id is not None:
            sid = _coerce_session_id(session_id)
            if sid is None:
                raise _ContractError(
                    "SESSION_ID_INVALID",
                    f"session_id is not a UUID: {type(session_id).__name__}",
                )
        else:
            sid = _coerce_session_id(attestation.get("session_id"))
            if sid is None:
                raise _ContractError(
                    "SESSION_ID_INVALID",
                    "attestation.session_id is not a valid UUID",
                )

        att_sid = _coerce_session_id(attestation.get("session_id"))
        if att_sid != sid:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "attestation.session_id does not match supplied session_id",
            )

        if not attestation_consistency.get("session_consistent", False):
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "attestation_consistency reports session is not consistent",
            )

        # Source identifiers
        att_source = attestation.get("attestation_source")
        if (
            att_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071
        ):
            raise _ContractError(
                "ATTESTATION_SOURCE_MISMATCH",
                f"attestation_source is invalid: {att_source!r}",
            )

        cons_source = attestation_consistency.get("attestation_consistency_source")
        if (
            cons_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072  # noqa: E501
        ):
            raise _ContractError(
                "ATTESTATION_CONSISTENCY_SOURCE_MISMATCH",
                f"attestation_consistency_source is invalid: {cons_source!r}",
            )

        # Validate nested contracts
        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(  # noqa: E501
                _deep_normalize_session_ids(attestation)
            )
        except Exception as exc:
            raise _ContractError(
                "ATTESTATION_MISMATCH",
                f"Task 071 attestation contract failed: {exc}",
            ) from exc

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService._validate_result(  # noqa: E501
                dict(attestation_consistency)
            )
        except Exception as exc:
            raise _ContractError(
                "ATTESTATION_CONSISTENCY_MISMATCH",
                f"Task 072 attestation consistency contract failed: {exc}",
            ) from exc

        # Fingerprint binding: Task 072 audited fp must match attestation
        actual_att_fp = attestation.get("audited_attestation_fingerprint")
        cons_att_fp = attestation_consistency.get("audited_attestation_fingerprint")
        if cons_att_fp != actual_att_fp:
            raise _ContractError(
                "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH",
                "attestation_consistency audited_attestation_fingerprint does not match attestation",  # noqa: E501
            )

        # Consistency relationship
        package_consistent = bool(
            attestation.get("attestation_consistent", False)
            and attestation_consistency.get("attestation_consistent", False)
        )

        package_core = {
            "session_id": str(sid),
            "attestation": _canonicalize(attestation),
            "attestation_consistency": _canonicalize(attestation_consistency),
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
            "attestation": attestation,
            "attestation_consistency": attestation_consistency,
            "package_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073,  # noqa: E501
            "package_fingerprint": package_fingerprint,
            "audited_package_fingerprint": package_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        """Validate Task 073 package contract."""
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
        if not isinstance(result["attestation"], Mapping):
            raise _ContractError("ATTESTATION_MISMATCH", "attestation is not a mapping")
        if not isinstance(result["attestation_consistency"], Mapping):
            raise _ContractError(
                "ATTESTATION_CONSISTENCY_MISMATCH",
                "attestation_consistency is not a mapping",
            )
        if (
            result["package_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073  # noqa: E501
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

        # Validate nested contracts
        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationService._validate_result(  # noqa: E501
                _deep_normalize_session_ids(result["attestation"])
            )
        except Exception as exc:
            raise _ContractError(
                "ATTESTATION_MISMATCH",
                f"nested Task 071 attestation failed: {exc}",
            ) from exc

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyService._validate_result(  # noqa: E501
                dict(result["attestation_consistency"])
            )
        except Exception as exc:
            raise _ContractError(
                "ATTESTATION_CONSISTENCY_MISMATCH",
                f"nested Task 072 consistency failed: {exc}",
            ) from exc

        # Session binding
        att_sid = _coerce_session_id(result["attestation"].get("session_id"))
        if att_sid != result["session_id"]:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "attestation session_id != package session_id",
            )

        # Fingerprint binding
        if result["attestation_consistency"].get(
            "audited_attestation_fingerprint"
        ) != result["attestation"].get("audited_attestation_fingerprint"):
            raise _ContractError(
                "AUDITED_ATTESTATION_FINGERPRINT_MISMATCH",
                "audited_attestation_fingerprint mismatch",
            )

        # Recomputed package fingerprint
        core = {
            "session_id": str(result["session_id"]),
            "attestation": _canonicalize(result["attestation"]),
            "attestation_consistency": _canonicalize(result["attestation_consistency"]),
        }
        try:
            recomputed = _compute_package_fingerprint(core)
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
