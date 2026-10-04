"""Task 095: fully audited final attestation response bundle service.

Binds the Task 093 response package with the Task 094 consistency audit
into a deterministic bundle. Pure composition boundary; never accesses
database, never performs HTTP calls, never calls external models, never
mutates inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_094,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService,  # noqa: E501
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095 = "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_TASK_095"  # noqa: E501  # noqa: E501

_BUNDLE_REQUIRED_FIELDS = (
    "available",
    "bundle_consistent",
    "session_id",
    "response_package",
    "response_package_consistency",
    "bundle_source",
    "bundle_fingerprint",
    "audited_bundle_fingerprint",
)

_BUNDLE_BOOLEAN_FIELDS = ("available", "bundle_consistent")


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


def _compute_bundle_fingerprint(bundle_core: Mapping[str, Any]) -> str:
    """SHA-256 of canonical bundle core."""
    payload = json.dumps(
        _canonicalize(bundle_core),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expected_bundle_fingerprint(bundle: Mapping[str, Any]) -> str:
    """Recompute the exact Task 095 bundle fingerprint definition."""
    core = {
        "session_id": str(bundle["session_id"]),
        "response_package": _canonicalize(bundle["response_package"]),
        "response_package_consistency": _canonicalize(
            bundle["response_package_consistency"]
        ),
    }
    return _compute_bundle_fingerprint(core)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError(  # noqa: E501
    Exception
):
    """Task 095: response bundle contract violation."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService:  # noqa: E501
    """Task 095: pure final attestation response bundle service."""

    def __init__(
        self,
        *,
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService  # noqa: E501
            | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_consistency_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService  # noqa: E501
            | None
        ) = None,
    ) -> None:
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService()  # noqa: E501
        )
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_consistency_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_consistency_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService()  # noqa: E501
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Return the Task 095 response bundle for a session.

        Obtains the Task 093 response package exactly once through its
        own orchestrator, never via HTTP, then produces the Task 094
        consistency audit of that exact package, then bundles them. Any
        contract error from those services is allowed to propagate unchanged
        -- this layer does not catch, translate, or repair it.
        """
        package_093 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_service.build_for_session(  # noqa: E501
            db, session_id
        )
        package_consistency_094 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_consistency_service.build(  # noqa: E501
            package=package_093
        )
        return self.build(
            session_id=session_id,
            response_package=package_093,
            response_package_consistency=package_consistency_094,
        )

    def build(
        self,
        *,
        session_id: Any = None,
        response_package: Mapping[str, Any] | None = None,
        response_package_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the response bundle. Pure; never mutates inputs."""
        if response_package is None or not isinstance(response_package, Mapping):
            raise _ContractError(
                "RESPONSE_PACKAGE_MISMATCH",
                "response_package is required and must be a mapping",
            )
        if response_package_consistency is None or not isinstance(
            response_package_consistency, Mapping
        ):
            raise _ContractError(
                "RESPONSE_PACKAGE_CONSISTENCY_MISMATCH",
                "response_package_consistency is required and must be a mapping",
            )

        if session_id is not None:
            sid = _coerce_session_id(session_id)
            if sid is None:
                raise _ContractError(
                    "SESSION_ID_INVALID",
                    f"session_id is not a UUID: {type(session_id).__name__}",
                )
        else:
            sid = _coerce_session_id(response_package.get("session_id"))
            if sid is None:
                raise _ContractError(
                    "SESSION_ID_INVALID",
                    "response_package.session_id is not a valid UUID",
                )

        pkg_sid = _coerce_session_id(response_package.get("session_id"))
        if pkg_sid != sid:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "response_package.session_id does not match supplied session_id",
            )

        if not response_package_consistency.get("session_consistent", False):
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "response_package_consistency reports session is not consistent",
            )

        pkg_source = response_package.get("package_source")
        if (
            pkg_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093  # noqa: E501
        ):
            raise _ContractError(
                "RESPONSE_PACKAGE_SOURCE_MISMATCH",
                f"package_source is invalid: {pkg_source!r}",
            )

        cons_source = response_package_consistency.get("package_consistency_source")
        if (
            cons_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_094  # noqa: E501
        ):
            raise _ContractError(
                "RESPONSE_PACKAGE_CONSISTENCY_SOURCE_MISMATCH",
                f"package_consistency_source is invalid: {cons_source!r}",
            )

        pkg_fp = response_package.get("package_fingerprint")
        cons_fp = response_package_consistency.get("package_fingerprint")
        if isinstance(cons_fp, str) and isinstance(pkg_fp, str) and cons_fp != pkg_fp:
            raise _ContractError(
                "PACKAGE_FINGERPRINT_BINDING_MISMATCH",
                "consistency package_fingerprint does not equal package "
                "package_fingerprint",
            )

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService._validate_result(  # noqa: E501
                _deep_normalize_session_ids(response_package)
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_PACKAGE_MISMATCH",
                f"Task 093 package contract failed: {exc}",
            ) from exc

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService._validate_result(  # noqa: E501
                dict(response_package_consistency)
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_PACKAGE_CONSISTENCY_MISMATCH",
                f"Task 094 consistency contract failed: {exc}",
            ) from exc

        bundle_consistent = bool(
            response_package.get("package_consistent", False)
            and response_package_consistency.get("package_consistent", False)
        )

        bundle_core = {
            "session_id": str(sid),
            "response_package": _canonicalize(response_package),
            "response_package_consistency": _canonicalize(response_package_consistency),
        }
        try:
            bundle_fingerprint = _compute_bundle_fingerprint(bundle_core)
        except Exception as exc:
            raise _ContractError(
                "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                f"could not compute bundle fingerprint: {exc}",
            ) from exc

        result: dict[str, Any] = {
            "available": True,
            "bundle_consistent": bundle_consistent,
            "session_id": sid,
            "response_package": response_package,
            "response_package_consistency": response_package_consistency,
            "bundle_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095,  # noqa: E501
            "bundle_fingerprint": bundle_fingerprint,
            "audited_bundle_fingerprint": bundle_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        """Validate Task 095 bundle contract."""
        for field in _BUNDLE_REQUIRED_FIELDS:
            if field not in result:
                raise _ContractError("MISSING_BUNDLE_FIELD", f"result has no {field}")
        for field in _BUNDLE_BOOLEAN_FIELDS:
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
        if not isinstance(result["response_package"], Mapping):
            raise _ContractError(
                "RESPONSE_PACKAGE_MISMATCH",
                "response_package is not a mapping",
            )
        if not isinstance(result["response_package_consistency"], Mapping):
            raise _ContractError(
                "RESPONSE_PACKAGE_CONSISTENCY_MISMATCH",
                "response_package_consistency is not a mapping",
            )
        if (
            result["bundle_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095  # noqa: E501
        ):
            raise _ContractError(
                "BUNDLE_SOURCE_MISMATCH",
                f"bundle_source mismatch: {result['bundle_source']!r}",
            )

        fp = result.get("bundle_fingerprint")
        if not isinstance(fp, str) or not re.fullmatch(r"^[0-9a-f]{64}$", fp):
            raise _ContractError(
                "BUNDLE_FINGERPRINT_FORMAT",
                f"bundle_fingerprint is not 64-char hex: {fp!r}",
            )

        audited_fp = result.get("audited_bundle_fingerprint")
        if not isinstance(audited_fp, str) or not re.fullmatch(
            r"^[0-9a-f]{64}$", audited_fp
        ):
            raise _ContractError(
                "AUDITED_BUNDLE_FINGERPRINT_FORMAT",
                "audited_bundle_fingerprint is not 64-char lowercase "
                f"hex: {audited_fp!r}",
            )

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService._validate_result(  # noqa: E501
                _deep_normalize_session_ids(result["response_package"])
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_PACKAGE_MISMATCH",
                f"nested Task 093 package failed: {exc}",
            ) from exc

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService._validate_result(  # noqa: E501
                dict(result["response_package_consistency"])
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_PACKAGE_CONSISTENCY_MISMATCH",
                f"nested Task 094 consistency failed: {exc}",
            ) from exc

        pkg_sid = _coerce_session_id(result["response_package"].get("session_id"))
        if pkg_sid != result["session_id"]:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "response_package session_id != bundle session_id",
            )

        expected_bundle_consistent = bool(
            result["response_package"].get("package_consistent", False)
            and result["response_package_consistency"].get("package_consistent", False)
        )
        if result["bundle_consistent"] != expected_bundle_consistent:
            raise _ContractError(
                "BUNDLE_CONSISTENT_MISMATCH",
                "bundle_consistent does not match nested values",
            )

        try:
            recomputed = _expected_bundle_fingerprint(result)
        except Exception as exc:
            raise _ContractError(
                "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                f"could not recompute bundle fingerprint: {exc}",
            ) from exc
        if result["bundle_fingerprint"] != recomputed:
            raise _ContractError(
                "BUNDLE_FINGERPRINT_MISMATCH",
                "bundle_fingerprint does not match contents",
            )

        if result["audited_bundle_fingerprint"] != result["bundle_fingerprint"]:
            raise _ContractError(
                "AUDITED_BUNDLE_FINGERPRINT_MISMATCH",
                "audited_bundle_fingerprint does not equal bundle_fingerprint",
            )
