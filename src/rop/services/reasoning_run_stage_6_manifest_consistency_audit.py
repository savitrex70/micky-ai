"""Task 151: Stage 6 release package manifest consistency audit service.

Read-only audit of the Task 150 manifest against the canonical
upstream chain: Task 143 diagnostics, Task 144 gate, Task 145 gate
consistency, Task 146 readiness, Task 147 readiness consistency,
Task 148 evidence, and Task 149 evidence consistency (which
themselves embed the Task 142 inspection evidence). Verifies manifest
status, release-ready value, required component presence/order, and
per-component agreement with upstream outputs. Reuses the existing
manifest, diagnostics, gate, audit, readiness, and evidence services;
reimplements no receipt, fingerprint, snapshot, provenance, replay,
inspection, diagnostics, gate, readiness, evidence, or manifest
validation logic. No reasoning execution, no replay engine
invocation, no persistence, no provider/model calls. The Task 140
``original_result`` is request material, never persisted, so it is
never reconstructed here; its ``NOT_PERSISTED`` provenance is not an
issue code and never drives this audit.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.reasoning_run_stage_6_manifest_consistency_audit import (
    ReasoningRunStage6ManifestConsistencyAuditRead,
)
from rop.services.reasoning_run_diagnostics import (
    ReasoningRunDiagnosticsContractError,
    ReasoningRunDiagnosticsService,
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
        self.manifest_service = (
            manifest_service or ReasoningRunStage6ReleaseManifestService()
        )
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

    def audit(
        self,
        db: Session,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Audit the published manifest against upstream evidence.

        Delegates to the existing Task 150/143/144/145/146/147/148/149
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
            diagnostics = self.diagnostics_service.diagnose(db, session_id)
        except ReasoningRunDiagnosticsContractError as exc:
            raise ReasoningRunStage6ManifestConsistencyAuditContractError(
                "DIAGNOSTICS_UNREADABLE",
                "persisted diagnostics material cannot be projected onto "
                "the canonical diagnostics schema",
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
            "diagnostics": diagnostics,
            "readiness": readiness,
            "readiness_audit": readiness_audit,
            "evidence": evidence,
            "evidence_audit": evidence_audit,
        }
        actual = manifest["manifest_status"]
        expected = self._expected_status(upstream)
        expected_release_ready = expected == "READY"
        expected_components = self._expected_components(upstream)

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
        component_findings = self._component_findings(
            manifest["components"], expected_components
        )
        findings.extend(component_findings)
        findings = sorted(set(findings))

        consistent = (
            expected == actual
            and manifest["release_ready"] == expected_release_ready
            and not component_findings
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

        Independent expectation over already computed verdicts,
        mirroring the approved Task 150 contract exactly: a
        disagreeing consistency audit contradicts the package and
        outranks the missing-evidence classification, the boolean
        ready/release-ready flags must cohere with their owning status
        strings, diagnostics health participates in the verdict
        (UNHEALTHY blocks, DEGRADED leaves it unverifiable), a fully
        coherent empty chain is NO_MATERIAL, and only a fully READY
        consistent chain is READY. The architectural ``original_result``
        gap never appears here because it is not an issue code anywhere
        upstream. An unknown combination never silently passes as
        READY.
        """
        gate = upstream["gate"]
        gate_audit = upstream["gate_audit"]
        readiness = upstream["readiness"]
        readiness_audit = upstream["readiness_audit"]
        evidence = upstream["evidence"]
        evidence_audit = upstream["evidence_audit"]

        gate_status = gate["gate_status"]
        readiness_status = readiness["readiness_status"]
        evidence_status = evidence["stage_6_status"]

        gate_consistent = gate_audit["gate_consistent"]
        readiness_consistent = readiness_audit["readiness_consistent"]
        evidence_consistent = evidence_audit["evidence_consistent"]

        diagnostics_status = gate["diagnostics_status"]

        gate_ready_coherent = gate["ready"] == (gate_status == "READY")
        readiness_release_ready_coherent = readiness["release_ready"] == (
            readiness_status == "READY"
        )
        evidence_release_ready_coherent = evidence["release_ready"] == (
            evidence_status == "READY"
        )

        if not gate_consistent:
            return "BLOCKED"
        if not readiness_consistent:
            return "BLOCKED"
        if not evidence_consistent:
            return "BLOCKED"
        if gate_status == "BLOCKED":
            return "BLOCKED"
        if readiness_status == "BLOCKED":
            return "BLOCKED"
        if evidence_status == "BLOCKED":
            return "BLOCKED"
        if not gate_ready_coherent:
            return "BLOCKED"
        if not readiness_release_ready_coherent:
            return "BLOCKED"
        if not evidence_release_ready_coherent:
            return "BLOCKED"
        if diagnostics_status == "UNHEALTHY":
            return "BLOCKED"
        if (
            gate_status == "NO_MATERIAL"
            and readiness_status == "NO_MATERIAL"
            and evidence_status == "NO_MATERIAL"
        ):
            return "NO_MATERIAL"
        if (
            gate_status == "UNVERIFIABLE"
            or readiness_status == "UNVERIFIABLE"
            or evidence_status == "UNVERIFIABLE"
            or diagnostics_status == "DEGRADED"
        ):
            return "UNVERIFIABLE"
        if (
            gate_status == "READY"
            and gate_ready_coherent
            and gate_consistent
            and readiness_status == "READY"
            and readiness_release_ready_coherent
            and readiness_consistent
            and evidence_status == "READY"
            and evidence_release_ready_coherent
            and evidence["evidence_available"]
            and evidence_consistent
            and diagnostics_status == "HEALTHY"
        ):
            return "READY"
        return "BLOCKED"

    @staticmethod
    def _expected_components(upstream: dict[str, Any]) -> list[dict[str, Any]]:
        """Derive the expected manifest component entries from upstream.

        One explicit canonical mapping from each required component ID
        to its expected kind, status, availability, and consistency,
        recomputed from the canonical Task 143-149 outputs using the
        same construction rules as Task 150: report surfaces carry
        strict-schema coherence, verdict surfaces agree with their
        governing audits, the diagnostics entry carries the canonical
        Task 144 diagnostics-health derivation as its status and reads
        its availability from the canonical Task 143 response.
        """
        gate = upstream["gate"]
        gate_audit = upstream["gate_audit"]
        diagnostics = upstream["diagnostics"]
        readiness = upstream["readiness"]
        readiness_audit = upstream["readiness_audit"]
        evidence = upstream["evidence"]
        evidence_audit = upstream["evidence_audit"]
        return [
            {
                "component_id": "REASONING_RUN_INSPECTION_TASK_142",
                "component_kind": "inspection",
                "status": gate["inspection_status"],
                "consistent": True,
                "available": True,
            },
            {
                "component_id": "REASONING_RUN_DIAGNOSTICS_TASK_143",
                "component_kind": "diagnostics",
                "status": gate["diagnostics_status"],
                "consistent": True,
                "available": diagnostics["session_exists"],
            },
            {
                "component_id": "REASONING_RUN_STAGE_6_GATE_TASK_144",
                "component_kind": "gate",
                "status": gate["gate_status"],
                "consistent": gate_audit["gate_consistent"],
                "available": True,
            },
            {
                "component_id": (
                    "REASONING_RUN_STAGE_6_GATE_CONSISTENCY_AUDIT_TASK_145"
                ),
                "component_kind": "gate_consistency_audit",
                "status": gate_audit["actual_gate_status"],
                "consistent": gate_audit["gate_consistent"],
                "available": gate_audit["available"],
            },
            {
                "component_id": "REASONING_RUN_STAGE_6_READINESS_TASK_146",
                "component_kind": "readiness",
                "status": readiness["readiness_status"],
                "consistent": readiness_audit["readiness_consistent"],
                "available": True,
            },
            {
                "component_id": (
                    "REASONING_RUN_STAGE_6_READINESS_CONSISTENCY_AUDIT_TASK_147"
                ),
                "component_kind": "readiness_consistency_audit",
                "status": readiness_audit["actual_readiness_status"],
                "consistent": readiness_audit["readiness_consistent"],
                "available": readiness_audit["available"],
            },
            {
                "component_id": "REASONING_RUN_STAGE_6_EVIDENCE_TASK_148",
                "component_kind": "evidence",
                "status": evidence["stage_6_status"],
                "consistent": evidence_audit["evidence_consistent"],
                "available": evidence["evidence_available"],
            },
            {
                "component_id": (
                    "REASONING_RUN_STAGE_6_EVIDENCE_CONSISTENCY_AUDIT_TASK_149"
                ),
                "component_kind": "evidence_consistency_audit",
                "status": evidence_audit["actual_evidence_status"],
                "consistent": evidence_audit["evidence_consistent"],
                "available": evidence_audit["available"],
            },
        ]

    @staticmethod
    def _component_findings(
        components: list[dict[str, Any]], expected: list[dict[str, Any]]
    ) -> list[str]:
        """Verify component identity, kind, status, availability, order."""
        findings: list[str] = []
        required = list(REQUIRED_MANIFEST_COMPONENT_IDS)
        required_set = set(required)
        present = [c["component_id"] for c in components]
        present_set = set(present)
        for required_id in required:
            if required_id not in present_set:
                findings.append(f"MANIFEST_COMPONENT_MISSING:{required_id}")
        for cid in sorted(required_set):
            if present.count(cid) > 1:
                findings.append(f"MANIFEST_COMPONENT_DUPLICATE:{cid}")
        for cid in sorted(present_set - required_set):
            findings.append(f"MANIFEST_COMPONENT_UNEXPECTED:{cid}")
        if [cid for cid in present if cid in required_set] != [
            cid for cid in required if cid in present_set
        ]:
            findings.append("MANIFEST_COMPONENT_ORDER_MISMATCH")
        expected_by_id = {c["component_id"]: c for c in expected}
        seen: set[str] = set()
        for component in components:
            cid = component["component_id"]
            if cid not in expected_by_id or cid in seen:
                continue
            seen.add(cid)
            want = expected_by_id[cid]
            if component["component_kind"] != want["component_kind"]:
                findings.append(
                    "MANIFEST_COMPONENT_KIND_MISMATCH:"
                    f"{cid}:expected={want['component_kind']},"
                    f"actual={component['component_kind']}"
                )
            if component["status"] != want["status"]:
                findings.append(
                    "MANIFEST_COMPONENT_MISMATCH:"
                    f"{cid}:expected={want['status']},"
                    f"actual={component['status']}"
                )
            if component["available"] != want["available"]:
                findings.append(
                    "MANIFEST_COMPONENT_AVAILABLE_MISMATCH:"
                    f"{cid}:expected={want['available']},"
                    f"actual={component['available']}"
                )
            if component["consistent"] != want["consistent"]:
                findings.append(
                    "MANIFEST_COMPONENT_CONSISTENT_MISMATCH:"
                    f"{cid}:expected={want['consistent']},"
                    f"actual={component['consistent']}"
                )
        return findings
