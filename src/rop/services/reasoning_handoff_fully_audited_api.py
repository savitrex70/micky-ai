"""Task 065: fully audited reasoning handoff API orchestration.

Delegation-only orchestration so the HTTP layer can expose the complete
Task 063 audit bundle without duplicating the wiring of Tasks 059-063
and without making internal HTTP calls. It calls, in order:

    1. Task 059 to obtain the Task 057 handoff response body
    2. Task 060 to audit that exact response body
    3. Task 061 to package the exact response body and that exact audit
    4. Task 062 to audit that exact Task 061 package
    5. Task 063 to bundle that exact package and that exact audit

The Task 059 response body is obtained exactly once and passed unchanged
into Task 060 and Task 061 -- a refactor that obtains a second body, or
rebuilds the handoff internally, is a defect this layer must not
introduce. No contract rule, validation, or semantic check is
reimplemented here: every upstream contract error propagates unchanged
so the API layer can translate it into a generic internal failure
rather than silently downgrading a malformed or unavailable upstream
result into a successful audited response.

Response representation
-----------------------
Before auditing, the Task 059 result is deterministically represented
in exactly the JSON-safe form the HTTP layer would transmit for its own
``ReasoningHandoffRead`` response model (``model_validate`` followed by
``model_dump(mode="json")``). The transport representation -- not the
in-memory object graph -- is what Tasks 060-063 audit, package, and
bundle. This keeps every downstream fingerprint provable by an
independent consumer that only holds the received JSON: UUIDs, datetimes,
and nested typed models are already in the canonical string form used by
the repository's fingerprint helpers, so a fingerprint recomputed from
the received body equals the fingerprint recorded at build time. The
normalization is a representation step only -- no field is added,
dropped, reordered, or reinterpreted, and the result is bit-for-bit the
JSON the Task 059 endpoint itself would return.

No decision, diagnosis, treatment, probability, utility, or confidence
semantics, and no external vendor or model client dependency, appears in
this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.schemas.reasoning_handoff import ReasoningHandoffRead
from rop.services.reasoning_handoff_api import ReasoningHandoffApiService
from rop.services.reasoning_handoff_api_audit_bundle import (
    ReasoningHandoffApiAuditBundleService,
)
from rop.services.reasoning_handoff_api_audit_package import (
    ReasoningHandoffApiAuditPackageService,
)
from rop.services.reasoning_handoff_api_audit_package_consistency import (
    ReasoningHandoffApiAuditPackageConsistencyService,
)
from rop.services.reasoning_handoff_api_consistency import (
    ReasoningHandoffApiConsistencyService,
)

_EXPECTED_METHOD = "GET"
_EXPECTED_STATUS_CODE = 200


def _transport_body(response: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact JSON-safe Task 059 response representation.

    Produces precisely what the Task 059 endpoint transmits for its own
    ``ReasoningHandoffRead`` response model. This is a representation
    step only: the caller's mapping is never mutated, and a body that
    cannot be typed is passed through unchanged so upstream validators
    still report the defect rather than this helper hiding it.
    """
    try:
        typed = ReasoningHandoffRead.model_validate(dict(response))
        return typed.model_dump(mode="json")
    except Exception:
        return dict(response)


class ReasoningHandoffFullyAuditedApiService:
    """Task 065: delegation-only orchestration of Tasks 059-063.

    Exists so the API layer can expose the Task 063 audit bundle without
    duplicating Task 059/060/061/062/063 wiring. It does not duplicate
    any contract rule, validation, or semantic check, and never performs
    HTTP against its own process.
    """

    def __init__(
        self,
        reasoning_handoff_api_service: ReasoningHandoffApiService | None = None,
        reasoning_handoff_api_consistency_service: (
            ReasoningHandoffApiConsistencyService | None
        ) = None,
        reasoning_handoff_api_audit_package_service: (
            ReasoningHandoffApiAuditPackageService | None
        ) = None,
        reasoning_handoff_api_audit_package_consistency_service: (
            ReasoningHandoffApiAuditPackageConsistencyService | None
        ) = None,
        reasoning_handoff_api_audit_bundle_service: (
            ReasoningHandoffApiAuditBundleService | None
        ) = None,
    ) -> None:
        self.reasoning_handoff_api_service = (
            reasoning_handoff_api_service or ReasoningHandoffApiService()
        )
        self.reasoning_handoff_api_consistency_service = (
            reasoning_handoff_api_consistency_service
            or ReasoningHandoffApiConsistencyService()
        )
        self.reasoning_handoff_api_audit_package_service = (
            reasoning_handoff_api_audit_package_service
            or ReasoningHandoffApiAuditPackageService()
        )
        self.reasoning_handoff_api_audit_package_consistency_service = (
            reasoning_handoff_api_audit_package_consistency_service
            or ReasoningHandoffApiAuditPackageConsistencyService()
        )
        self.reasoning_handoff_api_audit_bundle_service = (
            reasoning_handoff_api_audit_bundle_service
            or ReasoningHandoffApiAuditBundleService()
        )

    def build_for_session(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Return the Task 063 audit bundle for a session.

        Obtains the Task 059 response body exactly once, represents it in
        its exact transport form, then derives the Task 060 audit, the
        Task 061 package, the Task 062 audit, and the Task 063 bundle
        from that exact representation. Any contract error from those
        services is allowed to propagate unchanged -- this layer does not
        catch, translate, or repair it.
        """
        response = self.reasoning_handoff_api_service.build_for_session(db, session_id)
        body = _transport_body(response)
        path = f"/sessions/{session_id}/reasoning-handoff"

        api_consistency = self.reasoning_handoff_api_consistency_service.build(
            session_id=session_id,
            method=_EXPECTED_METHOD,
            path=path,
            status_code=_EXPECTED_STATUS_CODE,
            response_body=body,
        )
        package = self.reasoning_handoff_api_audit_package_service.build(
            session_id=session_id,
            method=_EXPECTED_METHOD,
            path=path,
            status_code=_EXPECTED_STATUS_CODE,
            response=body,
            api_consistency=api_consistency,
        )
        package_consistency = (
            self.reasoning_handoff_api_audit_package_consistency_service.build(
                package=package
            )
        )
        return self.reasoning_handoff_api_audit_bundle_service.build(
            session_id=session_id,
            api_audit_package=package,
            api_audit_package_consistency=package_consistency,
        )
