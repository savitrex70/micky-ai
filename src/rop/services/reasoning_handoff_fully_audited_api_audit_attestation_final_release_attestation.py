"""Task 097: final release attestation over the Task 095 bundle and Task 096 audit.

Binds the Task 095 response bundle with the Task 096 consistency audit
into the terminal self-authenticating release attestation artifact. Pure
composition boundary; never accesses database, never performs HTTP calls,
never calls external models, never mutates inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501
    _expected_bundle_fingerprint as _task095_expected_bundle_fingerprint,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService,  # noqa: E501
)

REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097 = "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_TASK_097"  # noqa: E501

_FINAL_ATTESTATION_REQUIRED_FIELDS = (
    "available",
    "final_attestation_consistent",
    "session_id",
    "response_bundle",
    "response_bundle_consistency",
    "final_attestation_source",
    "final_attestation_fingerprint",
    "audited_final_attestation_fingerprint",
)

_FINAL_ATTESTATION_BOOLEAN_FIELDS = ("available", "final_attestation_consistent")


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


def _compute_final_attestation_fingerprint(final_core: Mapping[str, Any]) -> str:
    """SHA-256 of canonical final attestation core."""
    payload = json.dumps(
        _canonicalize(final_core),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expected_final_fingerprint(final: Mapping[str, Any]) -> str:
    """Recompute the exact Task 097 release attestation fingerprint."""
    core = {
        "session_id": str(final["session_id"]),
        "response_bundle": _canonicalize(final["response_bundle"]),
        "response_bundle_consistency": _canonicalize(
            final["response_bundle_consistency"]
        ),
    }
    return _compute_final_attestation_fingerprint(core)


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError(  # noqa: E501
    Exception
):
    """Task 097: final release attestation contract violation."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


_ContractError = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError  # noqa: E501


class ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService:  # noqa: E501
    """Task 097: pure final release attestation service."""

    def __init__(
        self,
        *,
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService  # noqa: E501
            | None
        ) = None,
        reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency_service: (  # noqa: E501
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService  # noqa: E501
            | None
        ) = None,
    ) -> None:
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService()  # noqa: E501
        )
        self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency_service = (  # noqa: E501
            reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency_service  # noqa: E501
            or ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService()  # noqa: E501
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Return the Task 097 final release attestation for a session.

        Obtains the Task 095 response bundle exactly once (via its own
        Task 095 orchestrator, never via HTTP), then produces the Task
        096 consistency audit of that exact bundle, then produces the
        final release attestation. Any contract error from those services
        is allowed to propagate unchanged -- this layer does not catch,
        translate, or repair it.
        """
        bundle_095 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_service.build_for_session(  # noqa: E501
            db, session_id
        )
        bundle_consistency_096 = self.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency_service.build(  # noqa: E501
            bundle=bundle_095
        )
        return self.build(
            session_id=session_id,
            response_bundle=bundle_095,
            response_bundle_consistency=bundle_consistency_096,
        )

    def build(
        self,
        *,
        session_id: Any = None,
        response_bundle: Mapping[str, Any] | None = None,
        response_bundle_consistency: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the final release attestation. Pure; never mutates inputs."""
        if response_bundle is None or not isinstance(response_bundle, Mapping):
            raise _ContractError(
                "RESPONSE_BUNDLE_MISMATCH",
                "response_bundle is required and must be a mapping",
            )
        if response_bundle_consistency is None or not isinstance(
            response_bundle_consistency, Mapping
        ):
            raise _ContractError(
                "RESPONSE_BUNDLE_CONSISTENCY_MISMATCH",
                "response_bundle_consistency is required and must be a mapping",
            )

        if session_id is not None:
            sid = _coerce_session_id(session_id)
            if sid is None:
                raise _ContractError(
                    "SESSION_ID_INVALID",
                    f"session_id is not a UUID: {type(session_id).__name__}",
                )
        else:
            sid = _coerce_session_id(response_bundle.get("session_id"))
            if sid is None:
                raise _ContractError(
                    "SESSION_ID_INVALID",
                    "response_bundle.session_id is not a valid UUID",
                )

        bundle_sid = _coerce_session_id(response_bundle.get("session_id"))
        if bundle_sid != sid:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "response_bundle.session_id does not match supplied session_id",
            )

        if not response_bundle_consistency.get("session_consistent", False):
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "response_bundle_consistency reports session is not consistent",
            )

        bundle_source = response_bundle.get("bundle_source")
        if (
            bundle_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095  # noqa: E501
        ):
            raise _ContractError(
                "RESPONSE_BUNDLE_SOURCE_MISMATCH",
                f"bundle_source is invalid: {bundle_source!r}",
            )

        cons_source = response_bundle_consistency.get("bundle_consistency_source")
        if (
            cons_source
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096  # noqa: E501
        ):
            raise _ContractError(
                "RESPONSE_BUNDLE_CONSISTENCY_SOURCE_MISMATCH",
                f"bundle_consistency_source is invalid: {cons_source!r}",
            )

        bundle_fp = response_bundle.get("bundle_fingerprint")
        cons_fp = response_bundle_consistency.get("bundle_fingerprint")
        if (
            isinstance(cons_fp, str)
            and isinstance(bundle_fp, str)
            and cons_fp != bundle_fp
        ):
            raise _ContractError(
                "BUNDLE_FINGERPRINT_BINDING_MISMATCH",
                "consistency bundle_fingerprint does not equal bundle "
                "bundle_fingerprint",
            )

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
                _deep_normalize_session_ids(response_bundle)
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_BUNDLE_MISMATCH",
                f"Task 095 bundle contract failed: {exc}",
            ) from exc

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService._validate_result(  # noqa: E501
                dict(response_bundle_consistency)
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_BUNDLE_CONSISTENCY_MISMATCH",
                f"Task 096 consistency contract failed: {exc}",
            ) from exc

        try:
            expected_bundle_fp = _task095_expected_bundle_fingerprint(response_bundle)
        except Exception as exc:
            raise _ContractError(
                "BUNDLE_FINGERPRINT_COMPUTE_FAILED",
                f"could not recompute Task 095 bundle fingerprint: {exc}",
            ) from exc
        if bundle_fp != expected_bundle_fp or cons_fp != expected_bundle_fp:
            raise _ContractError(
                "BUNDLE_FINGERPRINT_MISMATCH",
                "stored bundle fingerprints do not equal the recomputed "
                "Task 095 bundle fingerprint",
            )

        final_consistent = bool(
            response_bundle.get("bundle_consistent", False)
            and response_bundle_consistency.get("bundle_consistent", False)
        )

        final_core = {
            "session_id": str(sid),
            "response_bundle": _canonicalize(response_bundle),
            "response_bundle_consistency": _canonicalize(response_bundle_consistency),
        }
        try:
            final_fingerprint = _compute_final_attestation_fingerprint(final_core)
        except Exception as exc:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                f"could not compute final attestation fingerprint: {exc}",
            ) from exc

        result: dict[str, Any] = {
            "available": True,
            "final_attestation_consistent": final_consistent,
            "session_id": sid,
            "response_bundle": response_bundle,
            "response_bundle_consistency": response_bundle_consistency,
            "final_attestation_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097,  # noqa: E501
            "final_attestation_fingerprint": final_fingerprint,
            "audited_final_attestation_fingerprint": final_fingerprint,
        }
        self._validate_result(result)
        return result

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> None:
        """Validate Task 097 final release attestation contract."""
        for field in _FINAL_ATTESTATION_REQUIRED_FIELDS:
            if field not in result:
                raise _ContractError(
                    "MISSING_FINAL_ATTESTATION_FIELD", f"result has no {field}"
                )
        for field in _FINAL_ATTESTATION_BOOLEAN_FIELDS:
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
        if not isinstance(result["response_bundle"], Mapping):
            raise _ContractError(
                "RESPONSE_BUNDLE_MISMATCH",
                "response_bundle is not a mapping",
            )
        if not isinstance(result["response_bundle_consistency"], Mapping):
            raise _ContractError(
                "RESPONSE_BUNDLE_CONSISTENCY_MISMATCH",
                "response_bundle_consistency is not a mapping",
            )
        if (
            result["final_attestation_source"]
            != REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097  # noqa: E501
        ):
            raise _ContractError(
                "FINAL_ATTESTATION_SOURCE_MISMATCH",
                "final_attestation_source mismatch: "
                f"{result['final_attestation_source']!r}",
            )

        fp = result.get("final_attestation_fingerprint")
        if not isinstance(fp, str) or not re.fullmatch(r"^[0-9a-f]{64}$", fp):
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_FORMAT",
                f"final_attestation_fingerprint is not 64-char hex: {fp!r}",
            )

        audited_fp = result.get("audited_final_attestation_fingerprint")
        if not isinstance(audited_fp, str) or not re.fullmatch(
            r"^[0-9a-f]{64}$", audited_fp
        ):
            raise _ContractError(
                "AUDITED_FINAL_ATTESTATION_FINGERPRINT_FORMAT",
                "audited_final_attestation_fingerprint is not 64-char "
                f"lowercase hex: {audited_fp!r}",
            )

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
                _deep_normalize_session_ids(result["response_bundle"])
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_BUNDLE_MISMATCH",
                f"nested Task 095 bundle failed: {exc}",
            ) from exc

        try:
            ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService._validate_result(  # noqa: E501
                dict(result["response_bundle_consistency"])
            )
        except Exception as exc:
            raise _ContractError(
                "RESPONSE_BUNDLE_CONSISTENCY_MISMATCH",
                f"nested Task 096 consistency failed: {exc}",
            ) from exc

        bundle_sid = _coerce_session_id(result["response_bundle"].get("session_id"))
        if bundle_sid != result["session_id"]:
            raise _ContractError(
                "SESSION_ID_MISMATCH",
                "response_bundle session_id != final attestation session_id",
            )

        expected_final = bool(
            result["response_bundle"].get("bundle_consistent", False)
            and result["response_bundle_consistency"].get("bundle_consistent", False)
        )
        if result["final_attestation_consistent"] != expected_final:
            raise _ContractError(
                "FINAL_ATTESTATION_CONSISTENT_MISMATCH",
                "final_attestation_consistent does not match nested values",
            )

        try:
            recomputed = _expected_final_fingerprint(result)
        except Exception as exc:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_COMPUTE_FAILED",
                f"could not recompute final attestation fingerprint: {exc}",
            ) from exc
        if result["final_attestation_fingerprint"] != recomputed:
            raise _ContractError(
                "FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
                "final_attestation_fingerprint does not match contents",
            )

        if (
            result["audited_final_attestation_fingerprint"]
            != result["final_attestation_fingerprint"]
        ):
            raise _ContractError(
                "AUDITED_FINAL_ATTESTATION_FINGERPRINT_MISMATCH",
                "audited_final_attestation_fingerprint does not equal "
                "final_attestation_fingerprint",
            )
