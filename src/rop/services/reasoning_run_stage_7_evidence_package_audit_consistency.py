"""Task 170: Stage 7 evidence-package audit consistency service.

Independent consistency boundary between Task 168 Evidence Package and
Task 169 Evidence-Package Audit. The service verifies exact binding of
session identity, package status, package source, evidence presence,
findings, finding counts, published versus expected status, audit source,
and audit status.

Readable versus unreadable evidence
-----------------------------------
The service separates two very different ways an input can be wrong:

* **Unreadable** -- the input is not the expected model, an attribute is
  missing, a field has the wrong type, a status or identity value lies
  outside its permitted set, or a nested evidence object is malformed. The
  comparison cannot be evaluated safely, so the result is ``UNAVAILABLE``.
* **Readable but contradictory** -- every field can be read and compared, but
  the values contradict each other or fail their own contract (a forged
  source, a detached session, disagreeing statuses, wrong flags, a finding
  count that does not match its findings). The comparison continues and the
  result is ``INCONSISTENT`` with the specific findings, so a schema contract
  failure never hides *what* is wrong.

A structurally valid Task 169 audit whose own status is ``UNAVAILABLE`` is a
third, distinct case: the audit is readable and honest that it verified
nothing, so there is no audited package state to bind. The result is
``UNAVAILABLE`` with the single finding ``AUDIT_UNAVAILABLE`` -- never the
generic ``PACKAGE_OR_AUDIT_INVALID`` reserved for unreadable inputs.

The service never calls Task 168 or Task 169 services, never recomputes
fingerprints, never invokes a provider, and never accesses a database. It
only reads the already-published Pydantic objects.

Read-only and pure: no database session, no persistence, no provider
invocation, no network, no replay, no mutation.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from rop.schemas.reasoning_run_stage_7_evidence_package import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    ReasoningRunStage7EvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    ReasoningRunStage7EvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170,
    ReasoningRunStage7EvidencePackageAuditConsistencyRead,
)

__all__ = [
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170",
    "ReasoningRunStage7EvidencePackageAuditConsistencyContractError",
    "ReasoningRunStage7EvidencePackageAuditConsistencyService",
]

_MISSING = object()


@cache
def _field_adapter(annotation: Any) -> TypeAdapter[Any]:
    """Return the cached type adapter for one field annotation."""
    return TypeAdapter(annotation)


def _is_readable(value: object, model_type: type[BaseModel]) -> bool:
    """Report whether ``value`` can be read field by field as ``model_type``.

    Readability is deliberately narrower than the model's own contract. It
    asks only whether every declared field is present with a value of the
    declared type (including permitted status literals) and whether every
    nested evidence object is itself readable. Cross-field rules -- canonical
    sources, flag/status agreement, finding counts, aggregate coherence -- are
    *not* checked here: a value that is readable but breaks those rules is
    evidence to compare, not evidence that cannot be read.
    """
    if not isinstance(value, model_type):
        return False
    try:
        for name, info in model_type.model_fields.items():
            attribute = getattr(value, name, _MISSING)
            if attribute is _MISSING:
                return False
            _field_adapter(info.annotation).validate_python(attribute, strict=True)
            if isinstance(attribute, BaseModel) and not _is_readable(
                attribute, type(attribute)
            ):
                return False
    except (AttributeError, TypeError, ValueError):
        # ``ValidationError`` is a ``ValueError``.
        return False
    return True


def _satisfies_contract(value: BaseModel) -> bool:
    """Report whether a readable value still satisfies its full own contract.

    Models are not revalidated on assignment, so a package or audit mutated
    after construction can be perfectly readable yet no longer coherent.
    """
    try:
        type(value).model_validate(value.model_dump())
    except (AttributeError, TypeError, ValueError):
        return False
    return True


class ReasoningRunStage7EvidencePackageAuditConsistencyContractError(Exception):
    """Task 170: the package-audit consistency cannot be verified."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7EvidencePackageAuditConsistencyService:
    """Deterministic read-only consistency check for package-audit binding."""

    @staticmethod
    def verify(
        *,
        package: ReasoningRunStage7EvidencePackageRead,
        audit: ReasoningRunStage7EvidencePackageAuditRead,
    ) -> dict[str, Any]:
        """Verify exact binding between package and audit.

        ``CONSISTENT`` when the audit is canonically bound to the exact
        Task 168 package represented. ``INCONSISTENT`` when both inputs are
        readable but the audit is detached from, or contradicts, the package
        (or either input fails its own contract). ``UNAVAILABLE`` when an
        input is unreadable -- missing, the wrong model type, missing
        attributes, wrongly typed fields, or malformed nested evidence -- or
        when the Task 169 audit is itself a valid ``UNAVAILABLE`` audit that
        verified nothing.

        No child service is invoked, no fingerprint is recomputed, and no
        database is written.
        """
        service = ReasoningRunStage7EvidencePackageAuditConsistencyService

        # Step 1 — Readability. Only inputs that cannot be evaluated safely
        # are UNAVAILABLE; this gate never judges semantic consistency.
        package_unreadable = not _is_readable(
            package, ReasoningRunStage7EvidencePackageRead
        )
        audit_unreadable = not _is_readable(
            audit, ReasoningRunStage7EvidencePackageAuditRead
        )
        if package_unreadable or audit_unreadable:
            unreadable = {"PACKAGE_OR_AUDIT_INVALID"}
            if package_unreadable:
                unreadable.add("PACKAGE_UNREADABLE")
            if audit_unreadable:
                unreadable.add("AUDIT_UNREADABLE")
            return service._unavailable(sorted(unreadable))

        # Step 2 — Own-contract status of each readable input. A failure is a
        # finding to report alongside the comparison, never a reason to stop.
        package_contract_valid = _satisfies_contract(package)
        audit_contract_valid = _satisfies_contract(audit)

        # Step 3 — A structurally valid UNAVAILABLE audit verified nothing:
        # it names no session and no package status, so there is nothing to
        # bind. This is distinct from a malformed audit object.
        if audit_contract_valid and audit.package_audit_status == "UNAVAILABLE":
            return service._unavailable(["AUDIT_UNAVAILABLE"])

        findings: set[str] = set()

        # Step A — Session identity must match exactly
        if package.session_id != audit.session_id:
            findings.add("SESSION_MISMATCH")

        # Step B — Package source must be canonical Task 168 source
        if (
            package.package_source
            != REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168
        ):
            findings.add("PACKAGE_SOURCE_MISMATCH")

        # Step C — Audit source must be canonical Task 169 source
        if (
            audit.audit_source
            != REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169
        ):
            findings.add("AUDIT_SOURCE_MISMATCH")

        # Step D — Published package status must match audit's published status
        if package.package_status != audit.published_package_status:
            findings.add("PUBLISHED_STATUS_MISMATCH")

        # Step E — The audit independently derives the expected package
        # status; it must match the actual package status.
        if package.package_status != audit.expected_package_status:
            findings.add("EXPECTED_STATUS_CONTRADICTION")

        # Step F — Audit status must be CONSISTENT for the binding to be valid
        if audit.package_audit_status != "CONSISTENT":
            findings.add("AUDIT_STATUS_NOT_CONSISTENT")

        # Step G — Findings describe different layers: Task 168 carries
        # evidence findings; Task 169 carries findings about package
        # coherence. A Task 169 audit that claims consistency must be
        # finding-free, and every finding count must equal its findings.
        if audit.package_audit_status == "CONSISTENT" and audit.findings:
            findings.add("AUDIT_FINDINGS_MISMATCH")
        if package.finding_count != len(package.findings):
            findings.add("FINDING_COUNT_MISMATCH")
        if audit.finding_count != len(audit.findings):
            findings.add("FINDING_COUNT_MISMATCH")

        # Step H — Audit availability and consistency flags must align with
        # the published audit status.
        if not audit.available:
            findings.add("AUDIT_UNAVAILABLE")
        if not audit.consistent:
            findings.add("AUDIT_INCONSISTENT")

        # Step I — The package must name a session.
        if package.session_id == "":
            findings.add("PACKAGE_SESSION_EMPTY")

        # Step J — Own-contract failures stay visible next to the specific
        # findings above, so a mutated object can never read as CONSISTENT.
        if not package_contract_valid:
            findings.add("PACKAGE_CONTRACT_INVALID")
        if not audit_contract_valid:
            findings.add("AUDIT_CONTRACT_INVALID")

        # Step K — Populate result dict
        ordered = sorted(findings)
        consistency_status = "INCONSISTENT" if ordered else "CONSISTENT"
        result: dict[str, Any] = {
            "session_id": package.session_id,
            "consistency_status": consistency_status,
            "available": True,
            "consistent": consistency_status == "CONSISTENT",
            "finding_count": len(ordered),
            "findings": ordered,
            "consistency_source": (
                REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170
            ),
        }

        # Step L — Validate through schema, raise on contract error
        return service._project(result)

    @staticmethod
    def _unavailable(findings: list[str]) -> dict[str, Any]:
        """Build the schema-valid UNAVAILABLE result for the given findings."""
        return ReasoningRunStage7EvidencePackageAuditConsistencyService._project(
            {
                "session_id": "",
                "consistency_status": "UNAVAILABLE",
                "available": False,
                "consistent": False,
                "finding_count": len(findings),
                "findings": findings,
                "consistency_source": (
                    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170
                ),
            }
        )

    @staticmethod
    def _project(result: dict[str, Any]) -> dict[str, Any]:
        """Validate the consistency result through the strict contract."""
        try:
            validated = (
                ReasoningRunStage7EvidencePackageAuditConsistencyRead.model_validate(
                    result
                )
            )
        except ValidationError as exc:
            raise ReasoningRunStage7EvidencePackageAuditConsistencyContractError(
                "PACKAGE_AUDIT_CONSISTENCY_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()
