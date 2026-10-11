"""Task 178: Stage 7 release-readiness evidence bundle audit service.

Independent audit boundary over the already-published Task 177
release-readiness evidence bundle. The auditor independently derives the
expected bundle status from the supplied Task 174 projection, Task 175
audit, and Task 176 consistency record rather than trusting the published
bundle.

The auditor never calls Task 177, never calls Tasks 174-176 services,
never recomputes fingerprints, never executes a release, never invokes a
provider, and never accesses a database. Inputs are never mutated.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (
    ReasoningRunStage7ReleaseReadinessAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit_consistency import (
    ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177,
    ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_evidence_bundle_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178,
    ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)
from rop.services.reasoning_run_stage_7_release_readiness_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
)
from rop.services.reasoning_run_stage_7_release_readiness_audit_consistency import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176,
)
from rop.services.reasoning_run_stage_7_release_readiness_projection import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
)

__all__ = [
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178",
    "ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditContractError",
    "ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService",
]

# Module-level alias: the canonical read-model name exceeds the 88-column
# limit once prefixed by call-site indentation, so call sites reference this
# short alias instead.
_AUDIT_READ = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditRead


def _revalidate_or_recover_semantic_conflict(
    model_type: Any,
    value: Any,
) -> Any:
    """Revalidate fields while retaining readable semantic contradictions.

    Post-construction mutation leaves field values integers/strings/lists
    that are readable but jointly impossible under the strict contract.
    Recovery via ``model_construct`` restores a readable record so a real
    contradiction can still surface; it is deliberately applied only when
    the payload is readable enough to contradict anything (e.g. a status
    field carrying an unknown value is re-raised instead).
    """
    payload = value.model_dump()
    try:
        return model_type.model_validate(payload)
    except ValidationError as exc:
        # A missing unreadable field would poison model_construct (it has
        # no default), so re-raise instead of recovering: the record is not
        # readable enough to contradict anything.
        if any(error["type"] == "missing" for error in exc.errors()):
            raise
        if all(not error["loc"] for error in exc.errors()):
            # Value error: readable-but-impossible joint fields. Recover a
            # coherent-shaped record so contradictions can still surface.
            return model_type.model_construct(**payload)
        raise


class ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditContractError(Exception):
    """Task 178: the release-readiness bundle audit cannot be performed."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService:
    """Deterministic read-only audit of one release-readiness evidence bundle."""

    @staticmethod
    def audit(
        *,
        projection174: ReasoningRunStage7ReleaseReadinessProjectionRead,
        audit175: ReasoningRunStage7ReleaseReadinessAuditRead,
        consistency176: ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
        bundle: dict[str, Any] | ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
    ) -> dict[str, Any]:
        """Independently audit one already-published Task 177 bundle.

        ``CONSISTENT`` when the independently derived expected bundle
        status matches the published bundle. ``INCONSISTENT`` when the
        readable published evidence contradicts the derived result,
        including a forged READY or BLOCKED bundle whose underlying Task
        174-176 records disagree. ``UNAVAILABLE`` for missing or malformed
        Task 177 input and when the binding cannot be proven from the
        supplied evidence. No child service is invoked, no fingerprint is
        recomputed, and no database is written.
        """
        try:
            if not isinstance(
                projection174, ReasoningRunStage7ReleaseReadinessProjectionRead
            ):
                raise TypeError("projection174 has an unexpected model type")
            if not isinstance(audit175, ReasoningRunStage7ReleaseReadinessAuditRead):
                raise TypeError("audit175 has an unexpected model type")
            if not isinstance(
                consistency176,
                ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
            ):
                raise TypeError("consistency176 has an unexpected model type")
            projection174 = _revalidate_or_recover_semantic_conflict(
                ReasoningRunStage7ReleaseReadinessProjectionRead, projection174
            )
            audit175 = _revalidate_or_recover_semantic_conflict(
                ReasoningRunStage7ReleaseReadinessAuditRead, audit175
            )
            consistency176 = _revalidate_or_recover_semantic_conflict(
                ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
                consistency176,
            )
        except (AttributeError, TypeError, ValidationError):
            fallback = ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService
            return fallback._project(
                {
                    "session_id": "",
                    "bundle_audit_status": "UNAVAILABLE",
                    "available": False,
                    "consistent": False,
                    "published_bundle_status": "UNAVAILABLE",
                    "expected_bundle_status": "UNAVAILABLE",
                    "finding_count": 1,
                    "findings": ["EVIDENCE_INPUT_INVALID"],
                    "audit_source": (
                        REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178
                    ),
                }
            )

        findings: list[str] = []

        # Step A0 — Canonical sources for Tasks 174/175/176
        if (
            projection174.projection_source
            != REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174
        ):
            findings.append("PROJECTION_SOURCE_INVALID")
        if (
            audit175.audit_source
            != REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175
        ):
            findings.append("AUDIT_SOURCE_INVALID")
        if (
            consistency176.consistency_source
            != REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
        ):
            findings.append("CONSISTENCY_SOURCE_INVALID")

        # Step A — Independently derive the expected bundle status from the
        # supplied Task 174-176 records. BLOCKED takes precedence over
        # READY; anything else is UNAVAILABLE.
        blocked = (
            projection174.readiness_status == "BLOCKED"
            or projection174.attestation_status == "BLOCKED"
            or projection174.attestation_audit_status == "INCONSISTENT"
            or projection174.consistency_status == "INCONSISTENT"
            or audit175.readiness_audit_status == "INCONSISTENT"
            or consistency176.consistency_status == "INCONSISTENT"
        )
        ready = (
            not blocked
            and projection174.readiness_status == "READY"
            and projection174.attestation_status == "CERTIFIED"
            and projection174.attestation_audit_status == "CONSISTENT"
            and projection174.consistency_status == "CONSISTENT"
            and projection174.finding_count == 0
            and projection174.findings == []
            and audit175.readiness_audit_status == "CONSISTENT"
            and audit175.published_readiness_status == "READY"
            and audit175.expected_readiness_status == "READY"
            and audit175.finding_count == 0
            and audit175.findings == []
            and consistency176.consistency_status == "CONSISTENT"
            and consistency176.finding_count == 0
            and consistency176.findings == []
        )
        if blocked:
            expected_status = "BLOCKED"
        elif ready:
            expected_status = "READY"
        else:
            expected_status = "UNAVAILABLE"

        # Step B — Revalidate the published Task 177 bundle, including
        # objects mutated after Pydantic construction.
        raw_bundle: Any = None
        bundle_obj: ReasoningRunStage7ReleaseReadinessEvidenceBundleRead | None = None
        try:
            bundle_model = bundle
            if isinstance(bundle, ReasoningRunStage7ReleaseReadinessEvidenceBundleRead):
                raw_bundle = bundle.model_dump()
            elif isinstance(bundle, dict):
                raw_bundle = bundle
                bundle_model = (
                    ReasoningRunStage7ReleaseReadinessEvidenceBundleRead.model_validate(
                        raw_bundle
                    )
                )
            else:
                raise TypeError("bundle has an unexpected model type")
            bundle_obj = _revalidate_or_recover_semantic_conflict(
                ReasoningRunStage7ReleaseReadinessEvidenceBundleRead,
                bundle_model,
            )
        except (TypeError, ValidationError):
            bundle_obj = None
            findings.append("BUNDLE_INVALID")

        # Only a record that carries the canonical Task 177 source claims to
        # be a Task 177 bundle; a wrong source is a readable contradiction.
        if bundle_obj is not None and bundle_obj.bundle_source != (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177
        ):
            findings.append("BUNDLE_SOURCE_INVALID")

        if bundle_obj is None:
            # Read the claimed status only from an otherwise-readable dict.
            raw_status = (
                raw_bundle.get("bundle_status")
                if isinstance(raw_bundle, dict)
                else None
            )
            if raw_status in ("READY", "BLOCKED", "UNAVAILABLE"):
                published_status = raw_status
                if raw_status != expected_status:
                    findings.append("BUNDLE_STATUS_MISMATCH")
                findings = sorted(set(findings))
                audit_status = "INCONSISTENT"
            else:
                published_status = "UNAVAILABLE"
                findings = sorted(set(findings))
                audit_status = "UNAVAILABLE"
            result: dict[str, Any] = {
                "session_id": (
                    projection174.session_id
                    if audit_status != "UNAVAILABLE"
                    and len(
                        {
                            projection174.session_id,
                            audit175.session_id,
                            consistency176.session_id,
                        }
                    )
                    == 1
                    and projection174.session_id != ""
                    else ""
                ),
                "bundle_audit_status": audit_status,
                "available": audit_status != "UNAVAILABLE",
                "consistent": audit_status == "CONSISTENT",
                "published_bundle_status": published_status,
                "expected_bundle_status": expected_status,
                "finding_count": len(findings),
                "findings": findings,
                "audit_source": (
                    REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178
                ),
            }
            return (
                ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService._project(
                    result
                )
            )

        # Step C — Session binding. Three outcomes are kept distinct:
        # * proven: ALL THREE upstream session ids are non-empty, identical
        #   and equal to the bundle's non-empty session id;
        # * contradicted: the non-empty upstream identities disagree, the
        #   bundle's identity conflicts with them, the bundle omits its
        #   identity although upstream records establish one, or the bundle
        #   claims an identity that no upstream record supports;
        # * unavailable: nothing contradicts the bundle, but fewer than three
        #   upstream records establish the shared identity (including none at
        #   all with an empty bundle session). A blank identity from an
        #   unavailable or unbound record is insufficient evidence, never a
        #   proof and never by itself a mismatch.
        upstream_sessions = (
            projection174.session_id,
            audit175.session_id,
            consistency176.session_id,
        )
        identities = {sid for sid in upstream_sessions if sid != ""}
        binding_unavailable = False
        if identities:
            # Disagreeing identities, a conflicting bundle identity, or a
            # bundle that omits an identity upstream establishes.
            binding_error = identities != {bundle_obj.session_id}
            if not binding_error and "" in upstream_sessions:
                # Agreeing and echoed, but not established by all three.
                binding_unavailable = True
        elif bundle_obj.session_id != "":
            # The upstream records establish no identity, yet the bundle
            # claims one: an unsupported claim is a contradiction.
            binding_error = True
        else:
            binding_error = False
            binding_unavailable = True
        if binding_error:
            findings.append("SESSION_BINDING_MISMATCH")

        # Step D — Compare the expected vs published bundle status
        if expected_status != bundle_obj.bundle_status:
            findings.append("BUNDLE_STATUS_MISMATCH")

        # Step E — The bundle must echo its child statuses verbatim
        if bundle_obj.readiness_status != projection174.readiness_status:
            findings.append("PROJECTION_STATUS_ECHO_MISMATCH")
        if bundle_obj.readiness_audit_status != audit175.readiness_audit_status:
            findings.append("AUDIT_STATUS_ECHO_MISMATCH")
        if bundle_obj.audit_consistency_status != consistency176.consistency_status:
            findings.append("CONSISTENCY_STATUS_ECHO_MISMATCH")

        # Step F — Canonical-source echoes and internal coherence of the
        # published bundle
        if bundle_obj.projection_source != (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174
        ) or bundle_obj.audit_source != (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175
        ):
            findings.append("BUNDLE_SOURCE_ECHO_INVALID")
        if bundle_obj.consistency_source != (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176
        ):
            findings.append("BUNDLE_SOURCE_ECHO_INVALID")
        if (
            bundle_obj.finding_count != len(bundle_obj.findings)
            or len(set(bundle_obj.findings)) != len(bundle_obj.findings)
            or bundle_obj.findings != sorted(bundle_obj.findings)
        ):
            findings.append("BUNDLE_FINDINGS_COHERENCE_INVALID")
        if (
            bundle_obj.bundle_finding_count != len(bundle_obj.bundle_findings)
            or len(set(bundle_obj.bundle_findings)) != len(bundle_obj.bundle_findings)
            or bundle_obj.bundle_findings != sorted(bundle_obj.bundle_findings)
        ):
            findings.append("BUNDLE_FINDINGS_COHERENCE_INVALID")

        # Step G — Populate result dict. Demonstrated contradictions always
        # win and stay INCONSISTENT. Without any contradiction, a published
        # bundle was read successfully; its verdict follows the comparison.
        findings = sorted(set(findings))
        if findings:
            bundle_audit_status = "INCONSISTENT"
        elif binding_unavailable:
            # Nothing contradicts the bundle, but no shared session identity
            # can be proven, so the audit can never claim CONSISTENT.
            findings = ["SESSION_BINDING_UNAVAILABLE"]
            bundle_audit_status = "UNAVAILABLE"
        else:
            bundle_audit_status = "CONSISTENT"

        result = {
            "session_id": (
                bundle_obj.session_id if bundle_audit_status != "UNAVAILABLE" else ""
            ),
            "bundle_audit_status": bundle_audit_status,
            "available": bundle_audit_status != "UNAVAILABLE",
            "consistent": bundle_audit_status == "CONSISTENT",
            "published_bundle_status": bundle_obj.bundle_status,
            "expected_bundle_status": expected_status,
            "finding_count": len(findings),
            "findings": findings,
            "audit_source": (
                REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_178
            ),
        }
        return ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditService._project(
            result
        )

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the audit result through the strict contract."""
        try:
            validated = _AUDIT_READ.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7ReleaseReadinessEvidenceBundleAuditContractError(
                "RELEASE_READINESS_BUNDLE_AUDIT_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
