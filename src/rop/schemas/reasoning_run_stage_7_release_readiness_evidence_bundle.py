"""Task 177: Stage 7 release-readiness evidence bundle contract.

Strict read-only aggregation of the already-published Task 174
release-readiness projection, Task 175 release-readiness audit, and Task 176
release-readiness audit-consistency verdict into one deterministic,
provider-neutral release-readiness evidence surface. The bundle answers:
what readiness did Task 174 project, did Task 175 independently confirm
its expected status, and did Task 176 bind the audit to the exact
projection?

The bundle is an evidence aggregation boundary, not a gate. It consumes
only already-published material from Tasks 174, 175, and 176 and never
redoes their reasoning: no readiness is re-derived, no fingerprint is
recomputed, no release is executed, and no provider is invoked.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177 = (
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_TASK_177"
)

# The complete set of structural finding codes Task 177 itself may publish in
# ``bundle_findings``: the session binding across the three inputs failed, or
# an input was missing or failed its own contract. Child findings (Tasks 174,
# 175, 176) are never copied into the aggregate.
REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_FINDING_CODES_TASK_177 = (
    frozenset({"EVIDENCE_INPUT_INVALID", "STAGE_7_SESSION_MISMATCH"})
)


class ReasoningRunStage7ReleaseReadinessEvidenceBundleRead(BaseModel):
    """Strict read model for one release-readiness evidence bundle.

    ``bundle_status`` is the single aggregate verdict: ``READY`` only when
    the Task 174 projection published ``READY``, the Task 175 audit is
    ``CONSISTENT`` over that same status, and the Task 176 consistency
    verdict is ``CONSISTENT`` over that same binding. ``BLOCKED`` when the
    bundle's published fields carry an approved blocking state.
    ``UNAVAILABLE`` for everything else. ``bundle_findings`` contains only
    Task 177 structural finding codes, never copies of child findings.
    ``session_id`` is the common session shared by the three inputs; it is
    empty when no binding is established. ``projection_evidence_valid``,
    ``audit_evidence_valid``, and ``consistency_evidence_valid`` state
    whether each child surface was present and passed its own contract:
    a ``False`` flag requires that surface to carry the canonical
    unavailable placeholder, so placeholder fields can never be mistaken
    for genuine child output.
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    # Identity
    session_id: str

    # Task 174 evidence (verbatim from the validated projection)
    readiness_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    attestation_status: Literal["CERTIFIED", "BLOCKED", "UNAVAILABLE"]
    attestation_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    consistency_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    finding_count: int
    findings: list[str]
    projection_source: str  # Task 174 projection_source value

    # Task 175 evidence (verbatim from the validated audit)
    readiness_audit_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    audit_available: bool
    audit_consistent: bool
    published_readiness_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    expected_readiness_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    audit_finding_count: int
    audit_findings: list[str]
    audit_source: str  # Task 175 audit_source value

    # Task 176 evidence (verbatim from the validated consistency verdict)
    audit_consistency_status: Literal["CONSISTENT", "INCONSISTENT", "UNAVAILABLE"]
    consistency_available: bool
    consistency_consistent: bool
    consistency_finding_count: int
    consistency_findings: list[str]
    consistency_source: str  # Task 176 consistency_source value

    # Aggregate
    bundle_status: Literal["READY", "BLOCKED", "UNAVAILABLE"]
    bundle_finding_count: int
    bundle_findings: list[str]
    bundle_source: str  # Task 177 source constant
    # Task 177 evidence-validity assessment: whether each child surface
    # was present and passed its own contract during assembly. False
    # exactly when that child's evidence was unavailable and its surface
    # carries the canonical unavailable placeholder below; a consumer
    # must never mistake placeholder fields for genuine child output.
    projection_evidence_valid: bool
    audit_evidence_valid: bool
    consistency_evidence_valid: bool

    @model_validator(mode="after")
    def _coherent_bundle(
        self,
    ) -> ReasoningRunStage7ReleaseReadinessEvidenceBundleRead:
        # Task 174 surface: finding_count == len(findings), sorted, deduplicated
        if self.finding_count != len(self.findings):
            raise ValueError("finding_count must equal len(findings)")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must not contain duplicates")
        if self.findings != sorted(self.findings):
            raise ValueError("findings must be sorted")
        # Task 175 surface: audit_finding_count == len(audit_findings)
        if self.audit_finding_count != len(self.audit_findings):
            raise ValueError("audit_finding_count must equal len(audit_findings)")
        if len(set(self.audit_findings)) != len(self.audit_findings):
            raise ValueError("audit_findings must not contain duplicates")
        if self.audit_findings != sorted(self.audit_findings):
            raise ValueError("audit_findings must be sorted")
        # Task 176 surface: coherence
        if self.consistency_finding_count != len(self.consistency_findings):
            raise ValueError(
                "consistency_finding_count must equal len(consistency_findings)"
            )
        if len(set(self.consistency_findings)) != len(self.consistency_findings):
            raise ValueError("consistency_findings must not contain duplicates")
        if self.consistency_findings != sorted(self.consistency_findings):
            raise ValueError("consistency_findings must be sorted")
        # Task 177 aggregate surface: coherence
        if self.bundle_finding_count != len(self.bundle_findings):
            raise ValueError("bundle_finding_count must equal len(bundle_findings)")
        if len(set(self.bundle_findings)) != len(self.bundle_findings):
            raise ValueError("bundle_findings must not contain duplicates")
        if self.bundle_findings != sorted(self.bundle_findings):
            raise ValueError("bundle_findings must be sorted")
        unapproved = set(self.bundle_findings) - (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_FINDING_CODES_TASK_177
        )
        if unapproved:
            raise ValueError(
                "bundle_findings contains unapproved Task 177 finding codes: "
                f"{sorted(unapproved)}"
            )
        if "STAGE_7_SESSION_MISMATCH" in self.bundle_findings and self.session_id != "":
            raise ValueError(
                "a session mismatch finding must not claim a shared session_id"
            )
        if self.consistency_available != (
            self.audit_consistency_status != "UNAVAILABLE"
        ):
            raise ValueError(
                "consistency_available must equal "
                "(audit_consistency_status != 'UNAVAILABLE')"
            )
        if self.consistency_consistent != (
            self.audit_consistency_status == "CONSISTENT"
        ):
            raise ValueError(
                "consistency_consistent must equal "
                "(audit_consistency_status == 'CONSISTENT')"
            )
        # audit_available must equal (readiness_audit_status != "UNAVAILABLE")
        if self.audit_available != (self.readiness_audit_status != "UNAVAILABLE"):
            raise ValueError(
                "audit_available must equal (readiness_audit_status != 'UNAVAILABLE')"
            )
        # audit_consistent must equal (readiness_audit_status == "CONSISTENT")
        if self.audit_consistent != (self.readiness_audit_status == "CONSISTENT"):
            raise ValueError(
                "audit_consistent must equal (readiness_audit_status == 'CONSISTENT')"
            )
        # Canonical sources
        if self.projection_source != (
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_TASK_174"
        ):
            raise ValueError("projection_source must be the canonical Task 174 source")
        if (
            self.audit_source
            != "REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_TASK_175"
        ):
            raise ValueError("audit_source must be the canonical Task 175 source")
        if self.consistency_source != (
            "REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_TASK_176"
        ):
            raise ValueError("consistency_source must be the canonical Task 176 source")
        if self.bundle_source != (
            REASONING_RUN_STAGE_7_RELEASE_READINESS_EVIDENCE_BUNDLE_SOURCE_TASK_177
        ):
            raise ValueError("bundle_source must be the canonical Task 177 source")
        # Precedence BLOCKED > READY > UNAVAILABLE, enforced in both
        # directions so no status can be forged over its own evidence.
        published_blocking = (
            self.readiness_status == "BLOCKED"
            or self.readiness_audit_status == "INCONSISTENT"
            or self.audit_consistency_status == "INCONSISTENT"
        )
        if self.bundle_status == "BLOCKED":
            if not published_blocking:
                raise ValueError("BLOCKED bundle requires a published blocking state")
        elif published_blocking:
            raise ValueError(
                "a published blocking state requires bundle_status BLOCKED"
            )
        elif self.bundle_status == "READY":
            if not self._ready_conditions_hold():
                raise ValueError("READY bundle requires complete READY evidence")
        elif self._ready_conditions_hold():
            raise ValueError(
                "UNAVAILABLE bundle must not withhold fully supported READY evidence"
            )
        # Evidence-validity coherence: an unavailable child surface is
        # honest only as the canonical placeholder, and a valid child
        # surface in an UNAVAILABLE state must carry its own diagnostic
        # findings, mirroring the child unavailable-state contracts.
        if not self.projection_evidence_valid:
            if not (
                self.readiness_status == "UNAVAILABLE"
                and self.attestation_status == "UNAVAILABLE"
                and self.attestation_audit_status == "UNAVAILABLE"
                and self.consistency_status == "UNAVAILABLE"
                and self.finding_count == 0
                and self.findings == []
            ):
                raise ValueError(
                    "an invalid projection surface must carry the canonical "
                    "unavailable placeholder"
                )
        elif self.readiness_status == "UNAVAILABLE" and self.finding_count == 0:
            raise ValueError("a valid unavailable projection surface requires findings")
        if not self.audit_evidence_valid:
            if not (
                self.readiness_audit_status == "UNAVAILABLE"
                and self.audit_available is False
                and self.audit_consistent is False
                and self.published_readiness_status == "UNAVAILABLE"
                and self.expected_readiness_status == "UNAVAILABLE"
                and self.audit_finding_count == 0
                and self.audit_findings == []
            ):
                raise ValueError(
                    "an invalid audit surface must carry the canonical "
                    "unavailable placeholder"
                )
        elif (
            self.readiness_audit_status == "UNAVAILABLE"
            and self.audit_finding_count == 0
        ):
            raise ValueError("a valid unavailable audit surface requires findings")
        if not self.consistency_evidence_valid:
            if not (
                self.audit_consistency_status == "UNAVAILABLE"
                and self.consistency_available is False
                and self.consistency_consistent is False
                and self.consistency_finding_count == 0
                and self.consistency_findings == []
            ):
                raise ValueError(
                    "an invalid consistency surface must carry the canonical "
                    "unavailable placeholder"
                )
        elif (
            self.audit_consistency_status == "UNAVAILABLE"
            and self.consistency_finding_count == 0
        ):
            raise ValueError(
                "a valid unavailable consistency surface requires findings"
            )
        return self

    def _ready_conditions_hold(self) -> bool:
        """Report whether the published evidence supports every READY condition.

        A READY bundle requires the Task 174 projection to publish READY,
        the Task 175 audit to be CONSISTENT over READY (same published and
        independently expected status), the Task 176 consistency verdict to
        be CONSISTENT, and every finding surface, including the Task 177
        aggregate findings, to be finding-free.
        """
        return (
            self.session_id != ""
            and self.bundle_finding_count == 0
            and self.bundle_findings == []
            and self.readiness_status == "READY"
            and self.attestation_status == "CERTIFIED"
            and self.attestation_audit_status == "CONSISTENT"
            and self.consistency_status == "CONSISTENT"
            and self.finding_count == 0
            and self.findings == []
            and self.readiness_audit_status == "CONSISTENT"
            and self.audit_available is True
            and self.audit_consistent is True
            and self.published_readiness_status == "READY"
            and self.expected_readiness_status == "READY"
            and self.audit_finding_count == 0
            and self.audit_findings == []
            and self.audit_consistency_status == "CONSISTENT"
            and self.consistency_available is True
            and self.consistency_consistent is True
            and self.consistency_finding_count == 0
            and self.consistency_findings == []
        )
