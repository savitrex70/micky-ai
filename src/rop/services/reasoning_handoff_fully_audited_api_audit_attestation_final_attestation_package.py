"""Task 083: final attestation package service.

Binds the canonical Task 081 final attestation to the Task 082
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

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_SOURCE_TASK_081,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation import (  # noqa: E501
    _canonicalize as _task081_canonicalize,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation import (  # noqa: E501
    _compute_final_attestation_fingerprint as _task081_compute_final_attestation_fingerprint,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService,  # noqa: E501
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083 = "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_TASK_083"  # noqa: E501  # noqa: E501

_PACKAGE_REQUIRED_FIELDS = (
    "available",
    "package_consistent",
    "session_id",
    "final_attestation",
    "final_attestation_consistency",
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


def _expected_081_fingerprint(final_attestation: Mapping[str, Any]) -> str:
    """Recompute the exact Task 081 fingerprint using its own helpers."""
    sid = final_attestation.get("session_id")
    if isinstance(sid, UUID):
        sid_str = str(sid)
    elif isinstance(sid, str):
        sid_str = sid
    else:
        sid_str = str(sid) if sid is not None else ""
    core = {
        "session_id": sid_str,
        "response_bundle": _task081_canonicalize(
            final_attestation.get("response_bundle")
        ),
        "response_bundle_consistency": _task081_canonicalize(
            final_attestation.get("response_bundle_consistency")
        ),
    }
    return _task081_compute_final_attestation_fingerprint(core)


def _expected_package_fingerprint(package: Mapping[str, Any]) -> str:
    """Recompute the exact Task 083 package fingerprint for a package."""
    sid = package.get("session_id")
    if isinstance(sid, UUID):
        sid_str = str(sid)
    elif isinstance(sid, str):
        sid_str = sid
    else:
        sid_str = str(sid) if sid is not None else ""
    core = {
        "session_id": sid_str,
        "final_attestation": _canonicalize(package.get("final_attestation")),
        "final_attestation_consistency": _canonicalize(
            package.get("final_attestation_consistency")
        ),
    }
    return _compute_package_fingerprint(core)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError(  # noqa: E501
    Exception
):
    """Task 083: final attestation package contract violation."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageContractError  # noqa: E501


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService:
    """Task 083: pure final attestation package service."""

    def __init__(
        self,
        *,
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService  # noqa: E501
            | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService  # noqa: E501
            | None
        ) = None,
    ) -> None:
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService()  # noqa: E501
        )
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService()  # noqa: E501
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Return the Task 083 final attestation package for a session.

        Obtains the Task 081 final attestation exactly once (via its
        own Task 081 orchestrator, never via HTTP), then produces the
        Task 082 consistency audit of that exact attestation, then packages
        them. Any contract error from those services is allowed to
        propagate unchanged -- this layer does not catch, translate, or
        repair it.
        """
        final_081 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_service.build_for_session(  # noqa: E501
            db, session_id
        )
        consistency_082 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency_service.build(  # noqa: E501
            final_attestation=final_081
        )
        return self.build(
            session_id=session_id,
            final_attestation=final_081,
            final_attestation_consistency=consistency_082,
        )

    def build(
        self,
        *,
        session_id: Any = None,
        final_attestation: Mapping[str, Any] | None = None,
        final_attestation_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the final attestation package. Pure; never mutates inputs."""
        if final_attestation is None or not isinstance(final_attestation, Mapping):
            raise _ContractError(
                "FINAL_ATTESTATION_MISMATCH",
                "final_attestation is required and must be a mapping",
            )
        if final_attestation_consistency is None or not isinstance(
            final_attestation_consistency, Mapping
        ):
            raise _ContractError(
                "FINAL_ATTESTATION_CONSISTENCY_MISMATCH",
                "final_attestation_consistency is required and must be a mapping",  # noqa: E501
            )

        if session_id is not None:
            sid = _coerce_session_id(session_id)
            if sid is None:
                raise _ContractError(
                    "SESSION_ID_INVALID",
                    f"session_id is not a UUID: {type(session_id).__name__}",
                )
        else:
            sid = _coerce_session_id(final_attestation.get("session_id"))
            if sid is None:
                raise _ContractError(
                    "SESSION_ID_INVALID",
                    "final_attestation.session_id is not a valid UUID",
                )

        final_sid = _coerce_session_id(final_attestation.get("session_id"))
        if final_sid != sid:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "final_attestation.session_id does not match supplied session_id",  # noqa: E501
            )

        if not final_attestation_consistency.get("session_consistent", False):
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "final_attestation_consistency reports session is not consistent",  # noqa: E501
            )

        final_source = final_attestation.get("final_attestation_source")
        if (
            final_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_SOURCE_TASK_081  # noqa: E501
        ):
            raise _ContractError(
                "FINAL_ATTESTATION_SOURCE_MISMATCH",
                f"final_attestation_source is invalid: {final_source!r}",
            )

        cons_source = final_attestation_consistency.get(
            "final_attestation_consistency_source"
        )
        if (
            cons_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082  # noqa: E501
        ):
            raise _ContractError(
                "FINAL_ATTESTATION_CONSISTENCY_SOURCE_MISMATCH",
                f"final_attestation_consistency_source is invalid: {cons_source!r}",  # noqa: E501
            )

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService._validate_result(  # noqa: E501
                _deep_normalize_session_ids(final_attestation)
            )
        except Exception as exc:
            raise _ContractError(
                "FINAL_ATTESTATION_MISMATCH",
                f"Task 081 final attestation contract failed: {exc}",
            ) from exc

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService._validate_result(  # noqa: E501
                dict(final_attestation_consistency)
            )
        except Exception as exc:
            raise _ContractError(
                "FINAL_ATTESTATION_CONSISTENCY_MISMATCH",
                f"Task 082 consistency contract failed: {exc}",
            ) from exc

        try:
            expected_081 = _expected_081_fingerprint(final_attestation)
        except Exception as exc:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                f"could not recompute Task 081 fingerprint: {exc}",
            ) from exc
        cons_fp = final_attestation_consistency.get(
            "final_attestation_fingerprint"
        )  # noqa: E501
        cons_audited_fp = final_attestation_consistency.get(
            "audited_final_attestation_fingerprint"
        )
        if cons_fp != expected_081:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_BINDING_MISMATCH",
                "consistency final_attestation_fingerprint does not equal "
                "the recomputed Task 081 fingerprint",
            )
        if cons_audited_fp != expected_081:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_BINDING_MISMATCH",
                "consistency audited_final_attestation_fingerprint does not "
                "equal the recomputed Task 081 fingerprint",
            )

        package_consistent = bool(
            final_attestation_consistency.get(
                "final_attestation_consistent", False
            )  # noqa: E501
        )

        package_core = {
            "session_id": str(sid),
            "final_attestation": _canonicalize(final_attestation),
            "final_attestation_consistency": _canonicalize(
                final_attestation_consistency
            ),
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
            "final_attestation": final_attestation,
            "final_attestation_consistency": final_attestation_consistency,
            "package_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083,  # noqa: E501
            "package_fingerprint": package_fingerprint,
            "audited_package_fingerprint": package_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        """Validate Task 083 final attestation package contract."""
        for field in _PACKAGE_REQUIRED_FIELDS:
            if field not in result:
                raise _ContractError(
                    "MISSING_PACKAGE_FIELD", f"result has no {field}"
                )  # noqa: E501
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
                f"session_id is not a UUID: {type(result['session_id']).__name__}",  # noqa: E501
            )
        if not isinstance(result["final_attestation"], Mapping):
            raise _ContractError(
                "FINAL_ATTESTATION_MISMATCH",
                "final_attestation is not a mapping",
            )
        if not isinstance(result["final_attestation_consistency"], Mapping):
            raise _ContractError(
                "FINAL_ATTESTATION_CONSISTENCY_MISMATCH",
                "final_attestation_consistency is not a mapping",
            )
        if (
            result["package_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083  # noqa: E501
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
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService._validate_result(  # noqa: E501
                _deep_normalize_session_ids(result["final_attestation"])
            )
        except Exception as exc:
            raise _ContractError(
                "FINAL_ATTESTATION_MISMATCH",
                f"nested Task 081 final attestation failed: {exc}",
            ) from exc

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService._validate_result(  # noqa: E501
                dict(result["final_attestation_consistency"])
            )
        except Exception as exc:
            raise _ContractError(
                "FINAL_ATTESTATION_CONSISTENCY_MISMATCH",
                f"nested Task 082 consistency failed: {exc}",
            ) from exc

        final_sid = _coerce_session_id(result["final_attestation"].get("session_id"))
        if final_sid != result["session_id"]:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "final_attestation session_id != package session_id",
            )

        try:
            expected_081 = _expected_081_fingerprint(
                result["final_attestation"]
            )  # noqa: E501
        except Exception as exc:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                f"could not recompute Task 081 fingerprint: {exc}",
            ) from exc
        nested_cons = result["final_attestation_consistency"]
        if nested_cons.get("final_attestation_fingerprint") != expected_081:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_BINDING_MISMATCH",
                "nested consistency final_attestation_fingerprint does not "
                "equal the recomputed Task 081 fingerprint",
            )
        if (
            nested_cons.get("audited_final_attestation_fingerprint") != expected_081
        ):  # noqa: E501
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_BINDING_MISMATCH",
                "nested consistency audited_final_attestation_fingerprint "
                "does not equal the recomputed Task 081 fingerprint",
            )

        expected_package_consistent = bool(
            result["final_attestation_consistency"].get(
                "final_attestation_consistent", False
            )
        )
        if result["package_consistent"] != expected_package_consistent:
            raise _ContractError(
                "PACKAGE_CONSISTENT_MISMATCH",
                "package_consistent does not match the nested consistency value",  # noqa: E501
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
                "audited_package_fingerprint does not equal package_fingerprint",  # noqa: E501
            )
