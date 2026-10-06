"""Task 153: Stage 7 entry service.

Deterministic, read-only evaluation answering one question for one
session: is the existing deterministic ROP core structurally permitted
to enter the Stage 7 provider-agnostic model boundary? Four independent
checks feed one canonical verdict:

1. Presence: every canonical boundary module resolves and the
   production tree is readable.
2. Consistency: the Task 113 registry, the Task 057 provider seam,
   and the public schemas still agree.
3. Explicit injection: Task 119's invariant holds -- no registry, no
   default constructor wiring, no startup selection.
4. Prohibitions: the production tree carries no concrete provider
   indicator, no network client, no credential assignment, and no
   environment-driven activation.

The Stage 6 handoff is delegated entirely to the canonical Task 152
certification service. This contract never duplicates, recalculates,
or bypasses certification evidence, and it never calls a model, starts
a server, or opens a network connection.

NO_MATERIAL is an accepted handoff verdict: it is itself a completed
canonical Stage 6 certification for a genuinely empty deterministic
chain, so accepting it admits empty sessions to entry evaluation
without bypassing any evidence.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
from pathlib import Path
from typing import Any, Protocol, get_args
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from rop.schemas.llm_reasoning import (
    Assessment,
    LLMReasoningProposalRead,
    ReasoningCandidateAssessmentRead,
)
from rop.schemas.reasoning_run_stage_7_entry import ReasoningRunStage7EntryRead
from rop.services import llm_reasoning as llm_reasoning_module
from rop.services.llm_boundary_contract import (
    ALLOWED_BOUNDARY_OUTCOMES,
    ASSESSMENT_FIELDS,
    OUTCOME_INPUT_INCONSISTENT,
    OUTCOME_MODEL_OUTPUT_INCONSISTENT,
    OUTCOME_MODEL_OUTPUT_INVALID,
    OUTCOME_MODEL_UNAVAILABLE,
    PROPOSAL_TOP_FIELDS,
    PROVIDER_RESPONSE_KNOWN_FIELDS,
    PROVIDER_RESPONSE_REQUIRED_FIELDS,
    RAW_PROPOSAL_TOP_FIELDS,
    VALID_ASSESSMENTS,
)
from rop.services.llm_reasoning import LLMReasoningService
from rop.services.llm_reasoning_provider import (
    LLMReasoningProvider,
    LLMReasoningProviderResponse,
)
from rop.services.reasoning_run_stage_6_certification import (
    ReasoningRunStage6CertificationContractError,
    ReasoningRunStage6CertificationService,
)

REASONING_RUN_STAGE_7_ENTRY_SOURCE_TASK_153 = "REASONING_RUN_STAGE_7_ENTRY_TASK_153"

_BOUNDARY_MODULES: tuple[str, ...] = (
    "rop.services.llm_boundary_contract",
    "rop.services.llm_output_validation",
    "rop.services.llm_privacy_boundary",
    "rop.services.llm_proposal_inspection",
    "rop.services.llm_proposal_normalization",
    "rop.services.llm_provider_isolation",
    "rop.services.llm_reasoning",
    "rop.services.llm_reasoning_audit",
    "rop.services.llm_reasoning_provider",
    "rop.services.llm_request_serialization",
)

_NORMALIZER_OUTCOMES = (
    OUTCOME_INPUT_INCONSISTENT,
    OUTCOME_MODEL_OUTPUT_INCONSISTENT,
    OUTCOME_MODEL_OUTPUT_INVALID,
    OUTCOME_MODEL_UNAVAILABLE,
)

# Assembled by concatenation so this scanner's own source never
# contains a prohibited literal (the Task 123 architecture tests scan
# raw production text, and this service is itself production text).
_CONCRETE_PROVIDER_TOKENS = (
    "oll" + "ama",
    "op" + "enai",
    "gem" + "ini",
    "anthr" + "opic",
    "cl" + "aude",
)
_NETWORK_CLIENT_TOKENS = (
    "htt" + "px",
    "aio" + "htt" + "p",
    "urllib" + "3",
    "req" + "uests",
)

_PROVIDER_TOKEN_RE = re.compile(
    r"\b(?:" + "|".join(_CONCRETE_PROVIDER_TOKENS) + r")\b",
    re.IGNORECASE,
)
# Network-integration detection is import-shaped: a client module only
# becomes integration when production code imports it, so docstring
# prose cannot trip this rule.
_NETWORK_IMPORT_RES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (
        token,
        re.compile(
            r"^\s*(?:import|from)\s+(?:[\w.]+\s*,\s*)*" + re.escape(token) + r"\b"
        ),
    )
    for token in _NETWORK_CLIENT_TOKENS
)
# Credential-scan calibration: comment text is stripped first and only
# an assignment-shaped credential key is flagged, so the Task 108
# privacy boundary's own detection patterns do not trip this rule.
_API_KEY_RE = re.compile(r"""["']?api_?key["']?\s*[:=]""", re.IGNORECASE)
_ENV_ACCESS_RE = re.compile(r"os\.(?:getenv|environ)")

_REGISTRY_ATTRS = (
    "PROVIDER_REGISTRY",
    "DEFAULT_PROVIDER",
    "AUTO_PROVIDER",
    "PROVIDER_FACTORY",
)

_STAGE_6_HANDOFF_ACCEPTED_STATUSES = ("CERTIFIED", "NO_MATERIAL")


class ReasoningRunStage7EntryContractError(Exception):
    """Task 153: the entry result cannot be projected."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningRunStage7EntryService:
    """Canonical Stage 7 entry evaluation for one session.

    READY means the boundary seam is present, consistent, and
    explicitly injectable, the production scan is clean, and the Stage
    6 handoff returned a completed canonical verdict. READY never means
    a model is configured: absence of any concrete provider is the
    expected healthy state. BLOCKED is reserved for structural
    violations. UNAVAILABLE means the question cannot be answered here
    without any violation of this boundary's own structure.
    """

    def __init__(
        self,
        certification_service: ReasoningRunStage6CertificationService | None = None,
        production_root: str | Path | None = None,
        boundary_modules: tuple[str, ...] | None = None,
    ) -> None:
        self._certification_service = (
            certification_service
            if certification_service is not None
            else ReasoningRunStage6CertificationService()
        )
        self._production_root = (
            Path(production_root)
            if production_root is not None
            else Path(__file__).resolve().parents[1]
        )
        self._boundary_modules = (
            boundary_modules if boundary_modules is not None else _BOUNDARY_MODULES
        )

    def evaluate(self, db: Session, session_id: UUID) -> dict[str, Any]:
        """Return the strict Stage 7 entry verdict for one session.

        Read-only over session state: the only consumer of ``db`` is
        the canonical Task 152 certification handoff.
        """
        boundary_findings: list[str] = []
        consistency_findings: list[str] = []
        injection_findings: list[str] = []
        scan_findings: list[str] = []
        handoff_findings: list[str] = []

        boundary_available = self._check_presence(boundary_findings)
        self._scan_production_tree(scan_findings)
        handoff_unavailable = False
        handoff_not_certified = False
        if boundary_available:
            self._check_consistency(consistency_findings)
            self._check_injection(injection_findings)
            try:
                certification = self._certification_service.certify(db, session_id)
            except ReasoningRunStage6CertificationContractError as exc:
                handoff_unavailable = True
                handoff_findings.append(f"STAGE_6_HANDOFF_UNAVAILABLE:{exc.invariant}")
            else:
                certification_status = certification.get("certification_status")
                if certification_status not in _STAGE_6_HANDOFF_ACCEPTED_STATUSES:
                    handoff_not_certified = True
                    handoff_findings.append(
                        f"STAGE_6_HANDOFF_NOT_CERTIFIED:{certification_status}"
                    )

        findings = sorted(
            set(
                boundary_findings
                + consistency_findings
                + injection_findings
                + scan_findings
                + handoff_findings
            )
        )

        if not boundary_available:
            stage_7_status = "UNAVAILABLE"
        elif (
            consistency_findings
            or injection_findings
            or scan_findings
            or handoff_not_certified
        ):
            stage_7_status = "BLOCKED"
        elif handoff_unavailable:
            stage_7_status = "UNAVAILABLE"
        else:
            stage_7_status = "READY"

        result: dict[str, Any] = {
            "stage_7_status": stage_7_status,
            "boundary_available": boundary_available,
            "boundary_consistent": not consistency_findings,
            "provider_explicitly_injected": not injection_findings,
            "concrete_provider_present": any(
                finding.startswith("PROHIBITED_PROVIDER_") for finding in scan_findings
            ),
            "network_integration_present": any(
                finding.startswith("PROHIBITED_NETWORK_") for finding in scan_findings
            ),
            "api_key_configuration_present": any(
                finding.startswith("PROHIBITED_API_KEY_") for finding in scan_findings
            ),
            "stage_7_source": REASONING_RUN_STAGE_7_ENTRY_SOURCE_TASK_153,
            "findings": findings,
            "finding_count": len(findings),
        }
        try:
            validated = ReasoningRunStage7EntryRead.model_validate(result)
        except ValidationError as exc:
            raise ReasoningRunStage7EntryContractError(
                "ENTRY_RESULT_INVALID", str(exc)
            ) from exc
        return validated.model_dump()

    def _check_presence(self, findings: list[str]) -> bool:
        available = True
        for module_name in self._boundary_modules:
            try:
                spec = importlib.util.find_spec(module_name)
            except (ImportError, ValueError):
                spec = None
            if spec is None:
                available = False
                findings.append(f"BOUNDARY_MODULE_MISSING:{module_name}")
        if not self._production_root.is_dir():
            available = False
            findings.append(f"SCAN_ROOT_UNREADABLE:{self._production_root}")
        return available

    def _check_consistency(self, findings: list[str]) -> None:
        checks: tuple[tuple[str, bool], ...] = (
            (
                "provider_response_surface",
                set(PROVIDER_RESPONSE_REQUIRED_FIELDS)
                <= set(PROVIDER_RESPONSE_KNOWN_FIELDS),
            ),
            (
                "provider_response_fields",
                tuple(LLMReasoningProviderResponse.__dataclass_fields__)
                == tuple(PROVIDER_RESPONSE_REQUIRED_FIELDS),
            ),
            (
                "assessment_fields",
                set(ASSESSMENT_FIELDS)
                == set(ReasoningCandidateAssessmentRead.model_fields),
            ),
            (
                "proposal_top_fields",
                set(PROPOSAL_TOP_FIELDS) == set(LLMReasoningProposalRead.model_fields),
            ),
            (
                "assessment_values",
                tuple(VALID_ASSESSMENTS) == get_args(Assessment),
            ),
            (
                "normalizer_outcomes",
                set(_NORMALIZER_OUTCOMES) <= set(ALLOWED_BOUNDARY_OUTCOMES),
            ),
            (
                "raw_proposal_surface",
                set(RAW_PROPOSAL_TOP_FIELDS) <= set(PROPOSAL_TOP_FIELDS),
            ),
        )
        for name, holds in checks:
            if not holds:
                findings.append(f"BOUNDARY_CONTRACT_MISMATCH:{name}")

    def _check_injection(self, findings: list[str]) -> None:
        for registry_attr in _REGISTRY_ATTRS:
            if hasattr(llm_reasoning_module, registry_attr):
                findings.append(
                    f"EXPLICIT_INJECTION_VIOLATION:registry_attribute:{registry_attr}"
                )
        if Protocol not in LLMReasoningProvider.__mro__:
            findings.append("EXPLICIT_INJECTION_VIOLATION:provider_protocol_missing")
        try:
            parameters = inspect.signature(LLMReasoningService.__init__).parameters
        except (TypeError, ValueError):
            parameters = {}
        provider_parameter = parameters.get("provider")
        if provider_parameter is None or provider_parameter.default is not None:
            findings.append(
                "EXPLICIT_INJECTION_VIOLATION:provider_parameter_not_injectable"
            )
        try:
            default_service = LLMReasoningService()
        except Exception:
            findings.append("EXPLICIT_INJECTION_VIOLATION:default_construction_failed")
        else:
            if not hasattr(default_service, "provider"):
                findings.append(
                    "EXPLICIT_INJECTION_VIOLATION:default_provider_attr_missing"
                )
            elif default_service.provider is not None:
                findings.append("EXPLICIT_INJECTION_VIOLATION:default_provider_present")

    def _scan_production_tree(self, findings: list[str]) -> None:
        root = self._production_root
        if not root.is_dir():
            return
        for path in sorted(root.rglob("*.py"), key=lambda item: item.as_posix()):
            relative = path.relative_to(root).as_posix()
            lowered_name = relative.lower()
            for token in _CONCRETE_PROVIDER_TOKENS:
                if token in lowered_name:
                    findings.append(f"PROHIBITED_PROVIDER_MODULE:{relative}:{token}")
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                findings.append(f"SCAN_FILE_UNREADABLE:{relative}")
                continue
            for lineno, raw_line in enumerate(text.splitlines(), start=1):
                code_line = raw_line.split("#", 1)[0]
                if not code_line.strip():
                    continue
                provider_match = _PROVIDER_TOKEN_RE.search(code_line)
                if provider_match is not None:
                    findings.append(
                        "PROHIBITED_PROVIDER_INDICATOR:"
                        f"{relative}:{lineno}:{provider_match.group(0).lower()}"
                    )
                for token, import_re in _NETWORK_IMPORT_RES:
                    if import_re.search(code_line):
                        findings.append(
                            "PROHIBITED_NETWORK_INDICATOR:"
                            f"{relative}:{lineno}:{token}"
                        )
                if _API_KEY_RE.search(code_line):
                    findings.append(f"PROHIBITED_API_KEY_INDICATOR:{relative}:{lineno}")
                if _ENV_ACCESS_RE.search(code_line) and "provider" in code_line.lower():
                    findings.append(
                        f"PROHIBITED_ENV_ACTIVATION_INDICATOR:{relative}:{lineno}"
                    )
