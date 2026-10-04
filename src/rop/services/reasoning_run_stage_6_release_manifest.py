"""Task 150: canonical Stage 6 release package manifest service.

Read-only metadata/index boundary over the eight canonical Stage 6
surfaces (Tasks 142-149). Reports each surface's current state in
stable canonical order and derives one package verdict; creates no
validation or readiness algorithm of its own. Reuses the existing
canonical services; reimplements no receipt, provenance, replay,
inspection, diagnostics, gate, audit, readiness, or evidence logic.
No reasoning execution, no replay engine invocation, no persistence,
no provider/model calls. The Task 140 ``original_result`` is request
material, never persisted, so it is never reconstructed here; its
``NOT_PERSISTED`` provenance is not an issue code and never drives
this manifest.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_6_release_manifest import (
    ReasoningRunStage6ReleaseManifestRead,
)
from rop.services.reasoning_run_diagnostics import (
    ReasoningRunDiagnosticsContractError,
    ReasoningRunDiagnosticsService,
)
from rop.services.reasoning_run_inspection import (
    ReasoningRunInspectionContractError,
    ReasoningRunInspectionService,
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
from rop.services.reasoning_run_stage_6_readiness import (
    ReasoningRunStage6ReadinessContractError,
    ReasoningRunStage6ReadinessService,
)
from rop.services.reasoning_run_stage_6_readiness_consistency_audit import (
    ReasoningRunStage6ReadinessConsistencyAuditContractError,
    ReasoningRunStage6ReadinessConsistencyAuditService,
)

REASONING_RUN_STAGE_6_RELEASE_MANIFEST_SOURCE_TASK_150 = (
    "REASONING_RUN_STAGE_6_RELEASE_MANIFEST_TASK_150"
)

COMPONENT_INSPECTION_TASK_142 = "REASONING_RUN_INSPECTION_TASK_142"
COMPONENT_DIAGNOSTICS_TASK_143 = "REASONING_RUN_DIAGNOSTICS_TASK_143"
COMPONENT_GATE_TASK_144 = "REASONING_RUN_STAGE_6_GATE_TASK_144"
COMPONENT_GATE_AUDIT_TASK_145 = "REASONING_RUN_STAGE_6_GATE_CONSISTENCY_AUDIT_TASK_145"
COMPONENT_READINESS_TASK_146 = "REASONING_RUN_STAGE_6_READINESS_TASK_146"
COMPONENT_READINESS_AUDIT_TASK_147 = (
    "REASONING_RUN_STAGE_6_READINESS_CONSISTENCY_AUDIT_TASK_147"
)
COMPONENT_EVIDENCE_TASK_148 = "REASONING_RUN_STAGE_6_EVIDENCE_TASK_148"
COMPONENT_EVIDENCE_AUDIT_TASK_149 = (
    "REASONING_RUN_STAGE_6_EVIDENCE_CONSISTENCY_AUDIT_TASK_149"
)


class ReasoningRunStage6ReleaseManifestContractError(Exception):
    """Task 150: the release manifest cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage6ReleaseManifestService:
    """Deterministic read-only Stage 6 release package manifest."""

    def __init__(
        self,
        inspection_service: ReasoningRunInspectionService | None = None,
        diagnostics_service: ReasoningRunDiagnosticsService | None = None,
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
    ) -> None:
        self.inspection_service = inspection_service or ReasoningRunInspectionService()
        self.diagnostics_service = (
            diagnostics_service or ReasoningRunDiagnosticsService()
        )
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

    def manifest(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Index the canonical Stage 6 surfaces for one exact session.

        Delegates to the existing Task 142-149 services. Read-only: no
        writes, no execution, no replay, no provider/model calls.
        ``release_ready`` is true exactly when every required invariant
        holds; a lower-level canonical inconsistency is never
        overridden.
        """
        try:
            inspection = self.inspection_service.inspect(db, session_id)
        except ReasoningRunInspectionContractError as exc:
            raise ReasoningRunStage6ReleaseManifestContractError(
                "INSPECTION_UNREADABLE",
                "persisted inspection material cannot be projected onto "
                "the canonical inspection schema",
            ) from exc
        try:
            diagnostics = self.diagnostics_service.diagnose(db, session_id)
        except ReasoningRunDiagnosticsContractError as exc:
            raise ReasoningRunStage6ReleaseManifestContractError(
                "DIAGNOSTICS_UNREADABLE",
                "persisted diagnostics material cannot be projected onto "
                "the canonical diagnostics schema",
            ) from exc
        try:
            gate = self.gate_service.evaluate(db, session_id)
        except ReasoningRunStage6GateContractError as exc:
            raise ReasoningRunStage6ReleaseManifestContractError(
                "GATE_UNREADABLE",
                "persisted gate material cannot be projected onto the "
                "canonical gate schema",
            ) from exc
        try:
            gate_audit = self.gate_audit_service.audit(db, session_id)
        except ReasoningRunStage6GateConsistencyAuditContractError as exc:
            raise ReasoningRunStage6ReleaseManifestContractError(
                "GATE_AUDIT_UNREADABLE",
                "persisted gate audit material cannot be projected onto "
                "the canonical audit schema",
            ) from exc
        try:
            readiness = self.readiness_service.report(db, session_id)
        except ReasoningRunStage6ReadinessContractError as exc:
            raise ReasoningRunStage6ReleaseManifestContractError(
                "READINESS_UNREADABLE",
                "persisted readiness material cannot be projected onto "
                "the canonical readiness schema",
            ) from exc
        try:
            readiness_audit = self.readiness_audit_service.audit(db, session_id)
        except ReasoningRunStage6ReadinessConsistencyAuditContractError as exc:
            raise ReasoningRunStage6ReleaseManifestContractError(
                "READINESS_AUDIT_UNREADABLE",
                "persisted readiness audit material cannot be projected "
                "onto the canonical audit schema",
            ) from exc
        try:
            evidence = self.evidence_service.bundle(db, session_id)
        except ReasoningRunStage6EvidenceContractError as exc:
            raise ReasoningRunStage6ReleaseManifestContractError(
                "EVIDENCE_UNREADABLE",
                "persisted evidence material cannot be projected onto "
                "the canonical evidence schema",
            ) from exc
        try:
            evidence_audit = self.evidence_audit_service.audit(db, session_id)
        except ReasoningRunStage6EvidenceConsistencyAuditContractError as exc:
            raise ReasoningRunStage6ReleaseManifestContractError(
                "EVIDENCE_AUDIT_UNREADABLE",
                "persisted evidence audit material cannot be projected "
                "onto the canonical audit schema",
            ) from exc

        components = self._components(
            inspection,
            diagnostics,
            gate,
            gate_audit,
            readiness,
            readiness_audit,
            evidence,
            evidence_audit,
        )
        manifest_status = self._manifest_status(
            gate,
            gate_audit,
            readiness,
            readiness_audit,
            evidence,
            evidence_audit,
        )
        findings = sorted(set(evidence["findings"]) | set(evidence_audit["findings"]))

        manifest = {
            "requested_session_id": str(session_id),
            "manifest_status": manifest_status,
            "release_ready": manifest_status == "READY",
            "finding_count": len(findings),
            "findings": findings,
            "components": components,
            "manifest_source": (REASONING_RUN_STAGE_6_RELEASE_MANIFEST_SOURCE_TASK_150),
        }
        try:
            validated = ReasoningRunStage6ReleaseManifestRead.model_validate(manifest)
        except ValidationError as exc:
            raise ReasoningRunStage6ReleaseManifestContractError(
                "MANIFEST_UNPROJECTABLE",
                "release manifest cannot be projected onto the canonical "
                "manifest schema",
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _components(
        inspection: dict[str, Any],
        diagnostics: dict[str, Any],
        gate: dict[str, Any],
        gate_audit: dict[str, Any],
        readiness: dict[str, Any],
        readiness_audit: dict[str, Any],
        evidence: dict[str, Any],
        evidence_audit: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build the eight canonical component entries in stable order."""
        return [
            {
                "component_id": COMPONENT_INSPECTION_TASK_142,
                "component_kind": "inspection",
                "status": inspection["overall_status"],
                "consistent": True,
                "available": True,
            },
            {
                "component_id": COMPONENT_DIAGNOSTICS_TASK_143,
                "component_kind": "diagnostics",
                "status": diagnostics["inspection_status"],
                "consistent": True,
                "available": True,
            },
            {
                "component_id": COMPONENT_GATE_TASK_144,
                "component_kind": "gate",
                "status": gate["gate_status"],
                "consistent": True,
                "available": True,
            },
            {
                "component_id": COMPONENT_GATE_AUDIT_TASK_145,
                "component_kind": "gate_consistency_audit",
                "status": gate_audit["actual_gate_status"],
                "consistent": gate_audit["gate_consistent"],
                "available": gate_audit["available"],
            },
            {
                "component_id": COMPONENT_READINESS_TASK_146,
                "component_kind": "readiness",
                "status": readiness["readiness_status"],
                "consistent": True,
                "available": True,
            },
            {
                "component_id": COMPONENT_READINESS_AUDIT_TASK_147,
                "component_kind": "readiness_consistency_audit",
                "status": readiness_audit["actual_readiness_status"],
                "consistent": readiness_audit["readiness_consistent"],
                "available": readiness_audit["available"],
            },
            {
                "component_id": COMPONENT_EVIDENCE_TASK_148,
                "component_kind": "evidence",
                "status": evidence["stage_6_status"],
                "consistent": True,
                "available": evidence["evidence_available"],
            },
            {
                "component_id": COMPONENT_EVIDENCE_AUDIT_TASK_149,
                "component_kind": "evidence_consistency_audit",
                "status": evidence_audit["actual_evidence_status"],
                "consistent": evidence_audit["evidence_consistent"],
                "available": evidence_audit["available"],
            },
        ]

    @staticmethod
    def _manifest_status(
        gate: dict[str, Any],
        gate_audit: dict[str, Any],
        readiness: dict[str, Any],
        readiness_audit: dict[str, Any],
        evidence: dict[str, Any],
        evidence_audit: dict[str, Any],
    ) -> str:
        """Derive the package verdict without overriding lower levels.

        Contradiction outranks missing evidence; evidence gaps never
        become tampering. READY requires every invariant: READY gate,
        consistent gate audit, READY readiness, consistent readiness
        audit, available consistent evidence. Anything unrecognized
        never silently passes as READY.
        """
        gate_status = gate["gate_status"]
        readiness_status = readiness["readiness_status"]
        evidence_status = evidence["stage_6_status"]
        if gate_status == "NO_MATERIAL":
            return "NO_MATERIAL"
        if (
            gate_status == "BLOCKED"
            or readiness_status == "BLOCKED"
            or evidence_status == "BLOCKED"
            or not gate_audit["gate_consistent"]
            or not readiness_audit["readiness_consistent"]
            or not evidence_audit["evidence_consistent"]
        ):
            return "BLOCKED"
        if (
            gate_status == "UNVERIFIABLE"
            or readiness_status == "UNVERIFIABLE"
            or evidence_status == "UNVERIFIABLE"
        ):
            return "UNVERIFIABLE"
        if (
            gate_status == "READY"
            and readiness_status == "READY"
            and evidence_status == "READY"
            and gate_audit["gate_consistent"]
            and readiness_audit["readiness_consistent"]
            and evidence_audit["evidence_consistent"]
            and evidence["evidence_available"]
            and evidence["release_ready"]
        ):
            return "READY"
        return "BLOCKED"
