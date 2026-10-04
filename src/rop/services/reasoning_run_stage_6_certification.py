"""Task 152: final Stage 6 deterministic release certification service.

Thin final orchestration/certification boundary over the canonical
Stage 6 chain: Task 144 gate, Task 145 gate consistency, Task 146
readiness, Task 147 readiness consistency, Task 148 evidence, Task
149 evidence consistency, Task 150 manifest, and Task 151 manifest
consistency audit. Consumes their canonical results; duplicates none
of the Task 137-151 algorithms. No reasoning execution, no replay
engine invocation, no persistence, no provider/model calls, no Stage 7
code. The Task 140 ``original_result`` is request material, never
persisted, so it is never reconstructed here; its ``NOT_PERSISTED``
provenance is not an issue code and never blocks certification on its
own. Certification confirms the deterministic core only.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_6_certification import (
    ReasoningRunStage6CertificationRead,
)
from rop.services.reasoning_run_stage_6_evidence import (
    ReasoningRunStage6EvidenceContractError,
    ReasoningRunStage6EvidenceService,
)
from rop.services.reasoning_run_stage_6_evidence_consistency_audit import (
    ReasoningRunStage6EvidenceConsistencyAuditContractError,
    ReasoningRunStage6EvidenceConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_gate import (
    ReasoningRunStage6GateContractError,
    ReasoningRunStage6GateService,
)
from rop.services.reasoning_run_stage_6_gate_consistency_audit import (
    ReasoningRunStage6GateConsistencyAuditContractError,
    ReasoningRunStage6GateConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_manifest_consistency_audit import (
    ReasoningRunStage6ManifestConsistencyAuditContractError,
    ReasoningRunStage6ManifestConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_readiness import (
    ReasoningRunStage6ReadinessContractError,
    ReasoningRunStage6ReadinessService,
)
from rop.services.reasoning_run_stage_6_readiness_consistency_audit import (
    ReasoningRunStage6ReadinessConsistencyAuditContractError,
    ReasoningRunStage6ReadinessConsistencyAuditService,
)
from rop.services.reasoning_run_stage_6_release_manifest import (
    ReasoningRunStage6ReleaseManifestContractError,
    ReasoningRunStage6ReleaseManifestService,
)

REASONING_RUN_STAGE_6_CERTIFICATION_SOURCE_TASK_152 = (
    "REASONING_RUN_STAGE_6_CERTIFICATION_TASK_152"
)


class ReasoningRunStage6CertificationContractError(Exception):
    """Task 152: the certification result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage6CertificationService:
    """Deterministic read-only final Stage 6 release certification."""

    def __init__(
        self,
        gate_service: ReasoningRunStage6GateService | None = None,
        gate_audit_service: ReasoningRunStage6GateConsistencyAuditService | None = None,
        readiness_service: ReasoningRunStage6ReadinessService | None = None,
        readiness_audit_service: (
            ReasoningRunStage6ReadinessConsistencyAuditService | None
        ) = None,
        evidence_service: ReasoningRunStage6EvidenceService | None = None,
        evidence_audit_service: (
            ReasoningRunStage6EvidenceConsistencyAuditService | None
        ) = None,
        manifest_service: ReasoningRunStage6ReleaseManifestService | None = (None),
        manifest_audit_service: (
            ReasoningRunStage6ManifestConsistencyAuditService | None
        ) = None,
    ) -> None:
        self.gate_service = gate_service or ReasoningRunStage6GateService()
        self.gate_audit_service = (
            gate_audit_service or ReasoningRunStage6GateConsistencyAuditService()
        )
        self.readiness_service = (
            readiness_service or ReasoningRunStage6ReadinessService()
        )
        self.readiness_audit_service = (
            readiness_audit_service
            or ReasoningRunStage6ReadinessConsistencyAuditService()
        )
        self.evidence_service = evidence_service or ReasoningRunStage6EvidenceService()
        self.evidence_audit_service = (
            evidence_audit_service
            or ReasoningRunStage6EvidenceConsistencyAuditService()
        )
        self.manifest_service = (
            manifest_service or ReasoningRunStage6ReleaseManifestService()
        )
        self.manifest_audit_service = (
            manifest_audit_service
            or ReasoningRunStage6ManifestConsistencyAuditService()
        )

    def certify(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Certify the Stage 6 deterministic core for one exact session.

        Delegates to the existing Task 144-151 services. Read-only: no
        writes, no execution, no replay, no provider/model calls, no
        Stage 7. ``certified`` is true only when every invariant holds;
        no lower-level inconsistency is ever overridden.
        """
        try:
            gate = self.gate_service.evaluate(db, session_id)
        except ReasoningRunStage6GateContractError as exc:
            raise ReasoningRunStage6CertificationContractError(
                "GATE_UNREADABLE",
                "persisted gate material cannot be projected onto the "
                "canonical gate schema",
            ) from exc
        try:
            gate_audit = self.gate_audit_service.audit(db, session_id)
        except ReasoningRunStage6GateConsistencyAuditContractError as exc:
            raise ReasoningRunStage6CertificationContractError(
                "GATE_AUDIT_UNREADABLE",
                "persisted gate audit material cannot be projected onto "
                "the canonical audit schema",
            ) from exc
        try:
            readiness = self.readiness_service.report(db, session_id)
        except ReasoningRunStage6ReadinessContractError as exc:
            raise ReasoningRunStage6CertificationContractError(
                "READINESS_UNREADABLE",
                "persisted readiness material cannot be projected onto "
                "the canonical readiness schema",
            ) from exc
        try:
            readiness_audit = self.readiness_audit_service.audit(db, session_id)
        except ReasoningRunStage6ReadinessConsistencyAuditContractError as exc:
            raise ReasoningRunStage6CertificationContractError(
                "READINESS_AUDIT_UNREADABLE",
                "persisted readiness audit material cannot be projected "
                "onto the canonical audit schema",
            ) from exc
        try:
            evidence = self.evidence_service.bundle(db, session_id)
        except ReasoningRunStage6EvidenceContractError as exc:
            raise ReasoningRunStage6CertificationContractError(
                "EVIDENCE_UNREADABLE",
                "persisted evidence material cannot be projected onto "
                "the canonical evidence schema",
            ) from exc
        try:
            evidence_audit = self.evidence_audit_service.audit(db, session_id)
        except ReasoningRunStage6EvidenceConsistencyAuditContractError as exc:
            raise ReasoningRunStage6CertificationContractError(
                "EVIDENCE_AUDIT_UNREADABLE",
                "persisted evidence audit material cannot be projected "
                "onto the canonical audit schema",
            ) from exc
        try:
            manifest = self.manifest_service.manifest(db, session_id)
        except ReasoningRunStage6ReleaseManifestContractError as exc:
            raise ReasoningRunStage6CertificationContractError(
                "MANIFEST_UNREADABLE",
                "persisted manifest material cannot be projected onto "
                "the canonical manifest schema",
            ) from exc
        try:
            manifest_audit = self.manifest_audit_service.audit(db, session_id)
        except ReasoningRunStage6ManifestConsistencyAuditContractError as exc:
            raise ReasoningRunStage6CertificationContractError(
                "MANIFEST_AUDIT_UNREADABLE",
                "persisted manifest audit material cannot be projected "
                "onto the canonical audit schema",
            ) from exc

        gate_status = gate["gate_status"]
        gate_ready = gate["ready"]
        gate_consistent = gate_audit["gate_consistent"]
        readiness_status = readiness["readiness_status"]
        readiness_release_ready = readiness["release_ready"]
        readiness_consistent = readiness_audit["readiness_consistent"]
        evidence_status = evidence["stage_6_status"]
        evidence_release_ready = evidence["release_ready"]
        evidence_available = evidence["evidence_available"]
        evidence_consistent = evidence_audit["evidence_consistent"]
        manifest_status = manifest["manifest_status"]
        manifest_release_ready = manifest["release_ready"]
        manifest_consistent = manifest_audit["manifest_consistent"]
        manifest_components = manifest["components"]
        has_material = gate_status != "NO_MATERIAL"

        certification_status = self._certification_status(
            gate_status,
            gate_ready,
            gate_consistent,
            readiness_status,
            readiness_release_ready,
            readiness_consistent,
            evidence_status,
            evidence_release_ready,
            evidence_available,
            evidence_consistent,
            manifest_status,
            manifest_release_ready,
            manifest_consistent,
            manifest_components,
        )
        certified = certification_status == "CERTIFIED"

        findings = sorted(
            set(evidence["findings"])
            | set(manifest["findings"])
            | set(manifest_audit["findings"])
        )
        if has_material and not gate_ready == (gate_status == "READY"):
            findings = sorted(
                set(findings)
                | {"GATE_READY_INCOHERENT:" f"status={gate_status},ready={gate_ready}"}
            )
        if has_material and not readiness_release_ready == (
            readiness_status == "READY"
        ):
            findings = sorted(
                set(findings)
                | {
                    "READINESS_RELEASE_READY_INCOHERENT:"
                    f"status={readiness_status},"
                    f"release_ready={readiness_release_ready}"
                }
            )
        if has_material and not evidence_release_ready == (evidence_status == "READY"):
            findings = sorted(
                set(findings)
                | {
                    "EVIDENCE_RELEASE_READY_INCOHERENT:"
                    f"status={evidence_status},"
                    f"release_ready={evidence_release_ready}"
                }
            )
        if has_material and not manifest_release_ready == (manifest_status == "READY"):
            findings = sorted(
                set(findings)
                | {
                    "MANIFEST_RELEASE_READY_INCOHERENT:"
                    f"status={manifest_status},"
                    f"release_ready={manifest_release_ready}"
                }
            )
        if has_material and not evidence_available:
            findings = sorted(set(findings) | {"EVIDENCE_UNAVAILABLE"})
        for component in manifest_components if has_material else []:
            cid = component["component_id"]
            if not component["available"]:
                findings = sorted(
                    set(findings) | {f"MANIFEST_COMPONENT_NOT_AVAILABLE:{cid}"}
                )
            if not component["consistent"]:
                findings = sorted(
                    set(findings) | {f"MANIFEST_COMPONENT_INCONSISTENT:{cid}"}
                )

        certification = {
            "requested_session_id": str(session_id),
            "certification_status": certification_status,
            "certified": certified,
            "release_ready": certified,
            "gate_status": gate_status,
            "gate_consistent": gate_consistent,
            "readiness_status": readiness_status,
            "readiness_consistent": readiness_consistent,
            "evidence_status": evidence_status,
            "evidence_consistent": evidence_consistent,
            "manifest_status": manifest_status,
            "manifest_consistent": manifest_consistent,
            "finding_count": len(findings),
            "findings": findings,
            "certification_source": (
                REASONING_RUN_STAGE_6_CERTIFICATION_SOURCE_TASK_152
            ),
        }
        try:
            validated = ReasoningRunStage6CertificationRead.model_validate(
                certification
            )
        except ValidationError as exc:
            raise ReasoningRunStage6CertificationContractError(
                "CERTIFICATION_UNPROJECTABLE",
                "certification cannot be projected onto the canonical "
                "certification schema",
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _certification_status(
        gate_status: str,
        gate_ready: bool,
        gate_consistent: bool,
        readiness_status: str,
        readiness_release_ready: bool,
        readiness_consistent: bool,
        evidence_status: str,
        evidence_release_ready: bool,
        evidence_available: bool,
        evidence_consistent: bool,
        manifest_status: str,
        manifest_release_ready: bool,
        manifest_consistent: bool,
        manifest_components: list[dict[str, Any]],
    ) -> str:
        """Derive the certification verdict from canonical verdicts.

        Every status/boolean contradiction blocks: a READY surface
        whose boolean flag disagrees, an unavailable evidence bundle,
        an unavailable manifest component, or an inconsistent manifest
        component each independently prevents certification, as does
        any disagreeing consistency audit. Contradiction (or any
        disagreeing audit) blocks; a pure evidence gap without
        contradiction leaves the core unverifiable; certification
        requires every invariant. The architectural ``original_result``
        gap never appears here because it is not an issue code anywhere
        upstream. An unknown combination never silently passes as
        CERTIFIED.
        """
        components_coherent = all(
            component["available"] and component["consistent"]
            for component in manifest_components
        )
        if gate_status == "NO_MATERIAL":
            return "NO_MATERIAL"
        if (
            gate_status == "BLOCKED"
            or readiness_status == "BLOCKED"
            or evidence_status == "BLOCKED"
            or manifest_status == "BLOCKED"
            or not gate_consistent
            or not readiness_consistent
            or not evidence_consistent
            or not manifest_consistent
            or not gate_ready == (gate_status == "READY")
            or not readiness_release_ready == (readiness_status == "READY")
            or not evidence_release_ready == (evidence_status == "READY")
            or not manifest_release_ready == (manifest_status == "READY")
            or not evidence_available
            or not components_coherent
        ):
            return "BLOCKED"
        if (
            gate_status == "UNVERIFIABLE"
            or readiness_status == "UNVERIFIABLE"
            or evidence_status == "UNVERIFIABLE"
            or manifest_status == "UNVERIFIABLE"
        ):
            return "UNVERIFIABLE"
        if (
            gate_status == "READY"
            and gate_ready
            and readiness_status == "READY"
            and readiness_release_ready
            and evidence_status == "READY"
            and evidence_release_ready
            and evidence_available
            and manifest_status == "READY"
            and manifest_release_ready
            and gate_consistent
            and readiness_consistent
            and evidence_consistent
            and manifest_consistent
            and components_coherent
        ):
            return "CERTIFIED"
        return "BLOCKED"
