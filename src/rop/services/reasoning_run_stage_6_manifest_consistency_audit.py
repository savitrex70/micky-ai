"""Task 151: Stage 6 release package manifest consistency audit service.

Read-only audit of the Task 150 manifest against the canonical
upstream chain: Task 144 gate, Task 145 gate consistency, Task 146
readiness, Task 147 readiness consistency, Task 148 evidence, and
Task 149 evidence consistency (which themselves embed the Task 142
inspection and Task 143 diagnostics evidence). Verifies manifest
status, release-ready value, required component presence/order, and
per-component agreement with upstream outputs. Reuses the existing
manifest, gate, audit, readiness, and evidence services; reimplements
no receipt, fingerprint, snapshot, provenance, replay, inspection,
diagnostics, gate, readiness, evidence, or manifest validation logic.
No reasoning execution, no replay engine invocation, no persistence,
no provider/model calls. The Task 140 ``original_result`` is request
material, never persisted, so it is never reconstructed here; its
``NOT_PERSISTED`` provenance is not an issue code and never drives
this audit.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_6_manifest_consistency_audit import (
    ReasoningRunStage6ManifestConsistencyAuditRead,
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
from rop.services.reasoning_run_stage_6_release_manifest import (
    ReasoningRunStage6ReleaseManifestContractError,
    ReasoningRunStage6ReleaseManifestService,
)

REASONING_RUN_STAGE_6_MANIFEST_CONSISTENCY_AUDIT_SOURCE_TASK_151 = (
    "REASONING_RUN_STAGE_6_MANIFEST_CONSISTENCY_AUDIT_TASK_151"
)

REQUIRED_MANIFEST_COMPONENT_IDS = (
    "REASONING_RUN_INSPECTION_TASK_142",
    "REASONING_RUN_DIAGNOSTICS_TASK_143",
    "REASONING_RUN_STAGE_6_GATE_TASK_144",
    "REASONING_RUN_STAGE_6_GATE_CONSISTENCY_AUDIT_TASK_145",
    "REASONING_RUN_STAGE_6_READINESS_TASK_146",
    "REASONING_RUN_STAGE_6_READINESS_CONSISTENCY_AUDIT_TASK_147",
    "REASONING_RUN_STAGE_6_EVIDENCE_TASK_148",
    "REASONING_RUN_STAGE_6_EVIDENCE_CONSISTENCY_AUDIT_TASK_149",
)


class ReasoningRunStage6ManifestConsistencyAuditContractError(Exception):
    """Task 151: the manifest consistency audit cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage6ManifestConsistencyAuditService:
    """Deterministic read-only audit of the Task 150 release manifest."""

    def __init__(
        self,
        manifest_service: ReasoningRunStage6ReleaseManifestService | None = (None),
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
        self.manifest_service = (
            manifest_service or ReasoningRunStage6ReleaseManifestService()
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

    def audit(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Audit the published manifest against upstream evidence.

        Delegates to the existing Task 150/144/145/146/147/148/149
        services. Read-only: no writes, no execution, no replay, no
        provider/model calls. A manifest is never reported consistent
        and release-ready when any canonical upstream condition
        prevents readiness.
        """
        try:
            manifest = self.manifest_service.manifest(db, session_id)
        except ReasoningRunStage6ReleaseManifestContractError as exc:
            raise ReasoningRunStage6ManifestConsistencyAuditContractError(
                "MANIFEST_UNREADABLE",
                "persisted manifest material cannot be projected onto "
                "the canonical manifest schema",
            ) from exc
        try:
            gate = self.gate_service.evaluate(db, session_id)
        except ReasoningRunStage6GateContractError as exc:
            raise ReasoningRunStage6ManifestConsistencyAuditContractError(
                "GATE_UNREADABLE",
                "persisted gate material cannot be projected onto the "
                "canonical gate schema",
            ) from exc
        try:
            gate_audit = self.gate_audit_service.audit(db, session_id)
        except ReasoningRunStage6GateConsistencyAuditContractError as exc:
            raise ReasoningRunStage6ManifestConsistencyAuditContractError(
                "GATE_AUDIT_UNREADABLE",
                "persisted gate audit material cannot be projected onto "
                "the canonical audit schema",
            ) from exc
        try:
            readiness = self.readiness_service.report(db, session_id)
        except ReasoningRunStage6ReadinessContractError as exc:
            raise ReasoningRunStage6ManifestConsistencyAuditContractError(
                "READINESS_UNREADABLE",
                "persisted readiness material cannot be projected onto "
                "the canonical readiness schema",
            ) from exc
        try:
            readiness_audit = self.readiness_audit_service.audit(db, session_id)
        except ReasoningRunStage6ReadinessConsistencyAuditContractError as exc:
            raise ReasoningRunStage6ManifestConsistencyAuditContractError(
                "READINESS_AUDIT_UNREADABLE",
                "persisted readiness audit material cannot be projected "
                "onto the canonical audit schema",
            ) from exc
        try:
            evidence = self.evidence_service.bundle(db, session_id)
        except ReasoningRunStage6EvidenceContractError as exc:
            raise ReasoningRunStage6ManifestConsistencyAuditContractError(
                "EVIDENCE_UNREADABLE",
                "persisted evidence material cannot be projected onto "
                "the canonical evidence schema",
            ) from exc
        try:
            evidence_audit = self.evidence_audit_service.audit(db, session_id)
        except ReasoningRunStage6EvidenceConsistencyAuditContractError as exc:
            raise ReasoningRunStage6ManifestConsistencyAuditContractError(
                "EVIDENCE_AUDIT_UNREADABLE",
                "persisted evidence audit material cannot be projected "
                "onto the canonical audit schema",
            ) from exc

        upstream = {
            "gate": gate,
            "gate_audit": gate_audit,
            "readiness": readiness,
            "readiness_audit": readiness_audit,
            "evidence": evidence,
            "evidence_audit": evidence_audit,
        }
        actual = manifest["manifest_status"]
        expected = self._expected_status(upstream)
        expected_release_ready = expected == "READY"

        findings = list(manifest["findings"])
        if expected != actual:
            findings.append(
                "MANIFEST_STATUS_MISMATCH:" f"expected={expected},actual={actual}"
            )
        if manifest["release_ready"] != expected_release_ready:
            findings.append(
                "MANIFEST_RELEASE_READY_MISMATCH:"
                f"expected={expected_release_ready},"
                f"actual={manifest['release_ready']}"
            )
        findings.extend(self._component_findings(manifest["components"], upstream))
        findings = sorted(set(findings))

        consistent = (
            expected == actual
            and manifest["release_ready"] == expected_release_ready
            and not self._component_findings(manifest["components"], upstream)
        )

        audit = {
            "requested_session_id": str(session_id),
            "available": True,
            "manifest_status": actual,
            "expected_manifest_status": expected,
            "actual_manifest_status": actual,
            "manifest_consistent": consistent,
            "release_ready": manifest["release_ready"],
            "finding_count": len(findings),
            "findings": findings,
            "audit_source": (
                REASONING_RUN_STAGE_6_MANIFEST_CONSISTENCY_AUDIT_SOURCE_TASK_151
            ),
        }
        try:
            validated = ReasoningRunStage6ManifestConsistencyAuditRead.model_validate(
                audit
            )
        except ValidationError as exc:
            raise ReasoningRunStage6ManifestConsistencyAuditContractError(
                "AUDIT_UNPROJECTABLE",
                "manifest consistency audit cannot be projected onto the "
                "canonical audit schema",
            ) from exc
        return validated.model_dump()

    @staticmethod
    def _expected_status(upstream: dict[str, Any]) -> str:
        """Map canonical upstream outputs to the expected manifest state.

        Independent expectation over already computed verdicts:
        contradiction (or any disagreeing consistency audit) blocks, a
        pure evidence gap leaves the package unverifiable, and only a
        fully READY consistent chain is READY. The architectural
        ``original_result`` gap never appears here because it is not an
        issue code anywhere upstream. An unknown combination never
        silently passes as READY.
        """
        gate = upstream["gate"]
        gate_audit = upstream["gate_audit"]
        readiness = upstream["readiness"]
        readiness_audit = upstream["readiness_audit"]
        evidence = upstream["evidence"]
        evidence_audit = upstream["evidence_audit"]
        if gate["gate_status"] == "NO_MATERIAL":
            return "NO_MATERIAL"
        if (
            gate["gate_status"] == "BLOCKED"
            or readiness["readiness_status"] == "BLOCKED"
            or evidence["stage_6_status"] == "BLOCKED"
            or not gate_audit["gate_consistent"]
            or not readiness_audit["readiness_consistent"]
            or not evidence_audit["evidence_consistent"]
        ):
            return "BLOCKED"
        if (
            gate["gate_status"] == "UNVERIFIABLE"
            or readiness["readiness_status"] == "UNVERIFIABLE"
            or evidence["stage_6_status"] == "UNVERIFIABLE"
        ):
            return "UNVERIFIABLE"
        if (
            gate["gate_status"] == "READY"
            and readiness["readiness_status"] == "READY"
            and evidence["stage_6_status"] == "READY"
            and gate_audit["gate_consistent"]
            and readiness_audit["readiness_consistent"]
            and evidence_audit["evidence_consistent"]
            and evidence["evidence_available"]
            and evidence["release_ready"]
        ):
            return "READY"
        return "BLOCKED"

    @staticmethod
    def _component_findings(
        components: list[dict[str, Any]], upstream: dict[str, Any]
    ) -> list[str]:
        """Verify required component identity, order, and agreement."""
        findings: list[str] = []
        required = list(REQUIRED_MANIFEST_COMPONENT_IDS)
        required_set = set(required)
        present = [c["component_id"] for c in components]
        present_set = set(present)
        for required_id in required:
            if required_id not in present_set:
                findings.append(f"MANIFEST_COMPONENT_MISSING:{required_id}")
        if [cid for cid in present if cid in required_set] != [
            cid for cid in required if cid in present_set
        ]:
            findings.append("MANIFEST_COMPONENT_ORDER_MISMATCH")
        expected_statuses = {
            "REASONING_RUN_INSPECTION_TASK_142": upstream["gate"]["inspection_status"],
            "REASONING_RUN_DIAGNOSTICS_TASK_143": upstream["gate"]["inspection_status"],
            "REASONING_RUN_STAGE_6_GATE_TASK_144": upstream["gate"]["gate_status"],
            "REASONING_RUN_STAGE_6_GATE_CONSISTENCY_AUDIT_TASK_145": (
                upstream["gate_audit"]["actual_gate_status"]
            ),
            "REASONING_RUN_STAGE_6_READINESS_TASK_146": upstream["readiness"][
                "readiness_status"
            ],
            "REASONING_RUN_STAGE_6_READINESS_CONSISTENCY_AUDIT_TASK_147": (
                upstream["readiness_audit"]["actual_readiness_status"]
            ),
            "REASONING_RUN_STAGE_6_EVIDENCE_TASK_148": upstream["evidence"][
                "stage_6_status"
            ],
            "REASONING_RUN_STAGE_6_EVIDENCE_CONSISTENCY_AUDIT_TASK_149": (
                upstream["evidence_audit"]["actual_evidence_status"]
            ),
        }
        for component in components:
            cid = component["component_id"]
            if cid in expected_statuses and (
                component["status"] != expected_statuses[cid]
            ):
                findings.append(
                    "MANIFEST_COMPONENT_MISMATCH:"
                    f"{cid}:expected={expected_statuses[cid]},"
                    f"actual={component['status']}"
                )
        return findings
