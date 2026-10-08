"""Task 164: Stage 7 vertical-slice consistency audit tests.

Independent deterministic audit of a published Task 163 vertical-slice
verdict against the Task 162 audit package it claims to certify. The
genuine material is produced once, up front, with the real Task 154-163
services and a test-only fake provider; the audit itself is then
exercised purely on the published mappings. The audit is read-only,
deterministic, session-isolated, and provider-neutral: it never calls
Task 162, Task 163, any lower-level Stage 7 service, or a provider, and
it never recomputes a fingerprint.
"""

from __future__ import annotations

import ast
import copy
import json
from collections.abc import Callable, Generator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
    ReasoningRunStage7VerticalSliceAuditRead,
)
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
)
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionService,
)
from rop.services.reasoning_run_stage_7_audit_package import (
    REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
    ReasoningRunStage7AuditPackageService,
)
from rop.services.reasoning_run_stage_7_diagnostics import (
    ReasoningRunStage7DiagnosticsService,
)
from rop.services.reasoning_run_stage_7_dispatch import (
    ReasoningRunStage7DispatchService,
)
from rop.services.reasoning_run_stage_7_proposal import (
    ReasoningRunStage7ProposalService,
)
from rop.services.reasoning_run_stage_7_proposal_audit import (
    ReasoningRunStage7ProposalAuditService,
)
from rop.services.reasoning_run_stage_7_request import (
    ReasoningRunStage7RequestService,
)
from rop.services.reasoning_run_stage_7_request_audit import (
    ReasoningRunStage7RequestAuditService,
)
from rop.services.reasoning_run_stage_7_result import (
    ReasoningRunStage7ResultService,
)
from rop.services.reasoning_run_stage_7_vertical_slice import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
    ReasoningRunStage7VerticalSliceService,
)
from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
    REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
    ReasoningRunStage7VerticalSliceAuditService,
)

AUDIT_KEYS = {
    "session_id",
    "slice_audit_status",
    "available",
    "consistent",
    "published_slice_status",
    "expected_slice_status",
    "finding_count",
    "findings",
    "audit_source",
}

_CONCRETE_PROVIDER_TOKENS = ("ollama", "openai", "gemini", "anthropic", "claude")
_PROHIBITED_SOURCE_TOKENS = (
    *_CONCRETE_PROVIDER_TOKENS,
    "httpx",
    "aiohttp",
    "urllib3",
    "requests",
    "os.environ",
    "getenv",
    "api_key",
    "socket",
    "entry_points",
)

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def override_get_db() -> Generator[Session, None, None]:
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


class _CertificationStub:
    """Returns one coherent Stage 6 verdict for the real admission path."""

    def __init__(self, status: str = "CERTIFIED") -> None:
        self._status = status
        self.calls: list[UUID] = []

    def certify(self, db: Session, session_id: UUID) -> dict[str, object]:
        self.calls.append(session_id)
        certified = self._status == "CERTIFIED"
        return {
            "requested_session_id": str(session_id),
            "certification_status": self._status,
            "certified": certified,
            "release_ready": certified,
        }


class _FakeProvider:
    """Deterministic test-only provider. No network, no model, no state."""

    def __init__(self) -> None:
        self.provider_name = "fake-provider"
        self.model_name = "fake-model"
        self.response: object = LLMReasoningProviderResponse(
            provider="fake-provider",
            model="fake-model",
            text='{"candidate_assessments": []}',
        )
        self.calls: list[object] = []

    def generate_reasoning(self, request: object) -> object:
        self.calls.append(request)
        return self.response


class _FailingProvider:
    """Test-only provider that raises one canonical failure."""

    def __init__(self, error: Exception) -> None:
        self.provider_name = "failing-provider"
        self.model_name = "failing-model"
        self.error = error
        self.calls: list[object] = []

    def generate_reasoning(self, request: object) -> object:
        self.calls.append(request)
        raise self.error


@pytest.fixture(autouse=True)
def _reset_db() -> Generator[None, None, None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    app.dependency_overrides[get_db] = override_get_db
    yield


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "stage-7-vertical-slice-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full_session(user_input: str) -> str:
    sid = _create_session(user_input)
    r = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert r.status_code == 201
    g = client.post(f"/sessions/{sid}/generate-candidates")
    assert g.status_code == 201
    e = client.post(f"/sessions/{sid}/evaluate-evidence")
    assert e.status_code == 200
    return sid


def _admission(db: Session, sid: str) -> dict:
    service = ReasoningRunStage7AdmissionService(
        certification_service=_CertificationStub("CERTIFIED")
    )
    admission = service.evaluate(db, UUID(sid))
    assert admission["admission_status"] == "ADMITTED"
    return admission


def _context(db: Session, sid: str) -> dict:
    context = ReasoningContextService().build_for_session(db, UUID(sid))
    assert context["available"] is True
    return context


def _build_package(db: Session, sid: str) -> dict:
    service = ReasoningRunStage7RequestService(
        admission_service=ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("CERTIFIED")
        )
    )
    package = service.build(db, UUID(sid))
    assert package["request_status"] == "PACKAGED"
    return package


def _audit_request(db: Session, package: object) -> dict:
    service = ReasoningRunStage7RequestAuditService(
        admission_service=ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("CERTIFIED")
        )
    )
    return service.audit(db, package)


def _valid_model_output(context: dict, explanation: str = "") -> str:
    text = explanation or "insufficient evidence to decide"
    assessments = [
        {
            "candidate_id": str(candidate.id),
            "assessment": "UNCLEAR",
            "supporting_evidence_ids": [],
            "contradicting_evidence_ids": [],
            "unresolved_information_ids": [],
            "explanation": text,
            "uncertainty_flags": ["insufficient_evidence"],
        }
        for candidate in context["candidate_state"]
    ]
    return json.dumps({"candidate_assessments": assessments})


def _response(text: str) -> LLMReasoningProviderResponse:
    return LLMReasoningProviderResponse(
        provider="fake-provider", model="fake-model", text=text
    )


def _healthy_material(
    db: Session, sid: str, text_builder: Callable[[dict], str] | None = None
) -> tuple[dict, dict, dict, dict, dict, object]:
    context = _context(db, sid)
    provider = _FakeProvider()
    text = (
        _valid_model_output(context) if text_builder is None else text_builder(context)
    )
    provider.response = _response(text)
    package = _build_package(db, sid)
    request_audit = _audit_request(db, package)
    assert request_audit["request_audit_status"] == "CONSISTENT"
    dispatch = ReasoningRunStage7DispatchService(provider=provider).dispatch(
        request=package, request_audit=request_audit
    )
    assert dispatch["dispatch_status"] == "DISPATCHED"
    proposal_result = ReasoningRunStage7ProposalService().build(
        dispatch_result=dispatch, context=context
    )
    assert proposal_result["proposal_status"] == "VALIDATED"
    proposal_audit = ReasoningRunStage7ProposalAuditService.audit(
        proposal_result=proposal_result, context=context
    )
    assert proposal_audit["proposal_audit_status"] == "CONSISTENT"
    return package, request_audit, proposal_result, proposal_audit, context, provider


def _outage_material(db: Session, sid: str) -> tuple[dict, dict, dict, dict]:
    context = _context(db, sid)
    provider = _FailingProvider(
        LLMReasoningProviderError("connection to model host failed")
    )
    package = _build_package(db, sid)
    request_audit = _audit_request(db, package)
    dispatch = ReasoningRunStage7DispatchService(provider=provider).dispatch(
        request=package, request_audit=request_audit
    )
    assert dispatch["dispatch_status"] == "UNAVAILABLE"
    assert dispatch["outcome"] == "MODEL_UNAVAILABLE"
    proposal_result = ReasoningRunStage7ProposalService().build(
        dispatch_result=dispatch, context=context
    )
    assert proposal_result["proposal_status"] == "MODEL_UNAVAILABLE"
    proposal_audit = ReasoningRunStage7ProposalAuditService.audit(
        proposal_result=proposal_result, context=context
    )
    assert proposal_audit["proposal_audit_status"] == "UNAVAILABLE"
    return package, request_audit, proposal_result, proposal_audit


def _model_failure_material(
    db: Session, sid: str, error: Exception
) -> tuple[dict, dict, dict, dict]:
    context = _context(db, sid)
    provider = _FailingProvider(error)
    package = _build_package(db, sid)
    request_audit = _audit_request(db, package)
    dispatch = ReasoningRunStage7DispatchService(provider=provider).dispatch(
        request=package, request_audit=request_audit
    )
    proposal_result = ReasoningRunStage7ProposalService().build(
        dispatch_result=dispatch, context=context
    )
    proposal_audit = ReasoningRunStage7ProposalAuditService.audit(
        proposal_result=proposal_result, context=context
    )
    return package, request_audit, proposal_result, proposal_audit


def _diagnose(
    package: object = None,
    request_audit: object = None,
    proposal_result: object = None,
    proposal_audit: object = None,
) -> dict:
    return ReasoningRunStage7DiagnosticsService.diagnose(
        request_package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
    )


def _package(
    admission: object = None,
    package: object = None,
    request_audit: object = None,
    proposal_result: object = None,
    proposal_audit: object = None,
    diagnostics: object = None,
) -> dict:
    return ReasoningRunStage7AuditPackageService.build(
        admission_result=admission,
        request_package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
        diagnostics_result=diagnostics,
    )


def _table_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f"SELECT COUNT(*) FROM {table.name}")
            ).scalar_one()
            for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
        }


# ---------------------------------------------------------------------------
# Genuine material and audit helpers
# ---------------------------------------------------------------------------


def _certify(package: object = None) -> dict:
    """Genuine Task 163 verdict (test-only; the audit never calls this)."""
    return ReasoningRunStage7VerticalSliceService.certify(audit_package=package)


def _audit(package: object = None, verdict: object = None) -> dict:
    return ReasoningRunStage7VerticalSliceAuditService.audit(
        audit_package=package, vertical_slice=verdict
    )


def _healthy_package(db: Session, sid: str) -> dict:
    package, request_audit, proposal_result, proposal_audit, _, _ = _healthy_material(
        db, sid
    )
    return _package(
        admission=_admission(db, sid),
        package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
        diagnostics=_diagnose(package, request_audit, proposal_result, proposal_audit),
    )


def _blocked_package(db: Session, sid: str) -> dict:
    admission = _admission(db, sid)
    package, request_audit, proposal_result, proposal_audit = _outage_material(db, sid)
    return _package(
        admission=admission,
        package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
        diagnostics=_diagnose(package, request_audit, proposal_result, proposal_audit),
    )


def _genuine_ready(label: str) -> tuple[str, dict, dict]:
    sid = _seed_full_session(label)
    with TestingSessionLocal() as db:
        package = _healthy_package(db, sid)
    verdict = _certify(package)
    assert verdict["slice_status"] == "READY"
    return sid, package, verdict


def _genuine_blocked(label: str) -> tuple[str, dict, dict]:
    sid = _seed_full_session(label)
    with TestingSessionLocal() as db:
        package = _blocked_package(db, sid)
    verdict = _certify(package)
    assert verdict["slice_status"] == "BLOCKED"
    assert verdict["findings"]
    return sid, package, verdict


def _with(mapping: dict, **changes: object) -> dict:
    return {**copy.deepcopy(mapping), **changes}


def _assert_inconsistent(result: dict, *codes: str) -> None:
    assert result["slice_audit_status"] == "INCONSISTENT"
    assert result["available"] is True
    assert result["consistent"] is False
    assert set(codes) <= set(result["findings"])
    assert result["finding_count"] == len(result["findings"])
    assert set(result) == AUDIT_KEYS


def _assert_unavailable(result: dict, *prefixes: str) -> None:
    assert result["slice_audit_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["consistent"] is False
    assert result["session_id"] == ""
    assert result["published_slice_status"] is None
    assert result["expected_slice_status"] is None
    assert len(result["findings"]) == len(prefixes)
    for finding, prefix in zip(result["findings"], prefixes, strict=True):
        assert finding.startswith(prefix)
    assert result["finding_count"] == len(result["findings"])
    assert set(result) == AUDIT_KEYS


# Each case leaves the Task 162 contract satisfied but removes one item the
# READY gate requires.
_READY_GATE_FAILURES = [
    ("admission blocked", {"admission_status": "BLOCKED"}),
    ("admission unavailable", {"admission_status": "UNAVAILABLE"}),
    ("admission absent", {"admission_status": None}),
    ("diagnostics degraded", {"diagnostics_status": "DEGRADED"}),
    ("diagnostics unhealthy", {"diagnostics_status": "UNHEALTHY"}),
    ("diagnostics no material", {"diagnostics_status": "NO_MATERIAL"}),
    ("request audit inconsistent", {"request_audit_status": "INCONSISTENT"}),
    ("request audit unavailable", {"request_audit_status": "UNAVAILABLE"}),
    ("request audit absent", {"request_audit_status": None}),
    ("proposal audit inconsistent", {"proposal_audit_status": "INCONSISTENT"}),
    ("proposal audit unavailable", {"proposal_audit_status": "UNAVAILABLE"}),
    ("proposal audit absent", {"proposal_audit_status": None}),
    ("empty session", {"session_id": ""}),
    ("blank session", {"session_id": "   "}),
    ("no attribution", {"provider_name": None, "model_name": None}),
    ("blank provider", {"provider_name": ""}),
    ("blank model", {"model_name": " "}),
    ("open finding", {"findings": ["SOME_FINDING"], "finding_count": 1}),
    ("fingerprint absent", {"request_fingerprint": None}),
    ("fingerprint empty", {"request_fingerprint": ""}),
    ("fingerprint short", {"request_fingerprint": "a" * 63}),
    ("fingerprint long", {"request_fingerprint": "a" * 65}),
    ("fingerprint non-hex", {"request_fingerprint": "g" * 64}),
    ("fingerprint uppercase", {"request_fingerprint": "A" * 64}),
    ("fingerprint newline", {"request_fingerprint": ("a" * 64) + "\n"}),
    ("foreign audit source", {"audit_source": "FORGED_SOURCE"}),
]


# ---------------------------------------------------------------------------
# 1. A genuine verdict is consistent, in every state
# ---------------------------------------------------------------------------


def test_genuine_ready_verdict_is_consistent() -> None:
    sid, package, verdict = _genuine_ready("Task 164 genuine ready")

    result = _audit(package, verdict)

    assert result["slice_audit_status"] == "CONSISTENT"
    assert result["available"] is True
    assert result["consistent"] is True
    assert result["session_id"] == sid
    assert result["published_slice_status"] == "READY"
    assert result["expected_slice_status"] == "READY"
    assert result["finding_count"] == 0
    assert result["findings"] == []
    assert result["audit_source"] == (
        REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164
    )
    assert set(result) == AUDIT_KEYS


def test_genuine_blocked_verdict_is_consistent() -> None:
    sid, package, verdict = _genuine_blocked("Task 164 genuine blocked")

    result = _audit(package, verdict)

    assert result["slice_audit_status"] == "CONSISTENT"
    assert result["session_id"] == sid
    assert result["published_slice_status"] == "BLOCKED"
    assert result["expected_slice_status"] == "BLOCKED"
    assert result["findings"] == []


def test_genuine_unavailable_verdicts_are_consistent() -> None:
    """A faithful UNAVAILABLE verdict is not an inconsistency."""
    _, healthy, _ = _genuine_ready("Task 164 genuine unavailable")
    empty = _package()
    for package in (
        _with(healthy, request_fingerprint=None),
        _with(healthy, diagnostics_status="DEGRADED"),
        empty,
    ):
        verdict = _certify(package)
        assert verdict["slice_status"] == "UNAVAILABLE"

        result = _audit(package, verdict)

        assert result["slice_audit_status"] == "CONSISTENT", package
        assert result["published_slice_status"] == "UNAVAILABLE"
        assert result["expected_slice_status"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    ("label", "changes"), _READY_GATE_FAILURES, ids=[c[0] for c in _READY_GATE_FAILURES]
)
def test_audit_accepts_every_genuine_task_163_verdict(
    label: str, changes: dict
) -> None:
    """The independent expectation agrees with the real Task 163 gate."""
    _, healthy, _ = _genuine_ready("Task 164 agreement with Task 163")
    package = _with(healthy, **changes)
    ReasoningRunStage7AuditPackageRead.model_validate(package)
    verdict = _certify(package)
    assert verdict["slice_status"] != "READY", label

    result = _audit(package, verdict)

    assert result["slice_audit_status"] == "CONSISTENT", label
    assert result["findings"] == [], label


# ---------------------------------------------------------------------------
# 2-8. Field bindings
# ---------------------------------------------------------------------------


def test_session_mismatch_is_inconsistent() -> None:
    sid, package, verdict = _genuine_ready("Task 164 session mismatch")
    other = str(uuid4())
    assert other != sid

    result = _audit(package, _with(verdict, session_id=other))

    _assert_inconsistent(result, "SESSION_ID_MISMATCH")
    assert result["findings"] == ["SESSION_ID_MISMATCH"]
    assert result["session_id"] == ""
    assert other not in json.dumps(result)


def test_admission_mismatch_is_inconsistent() -> None:
    _, package, verdict = _genuine_blocked("Task 164 admission mismatch")
    assert verdict["admission_status"] == "ADMITTED"

    result = _audit(package, _with(verdict, admission_status="UNAVAILABLE"))

    _assert_inconsistent(result, "ADMISSION_STATUS_MISMATCH")
    assert result["findings"] == ["ADMISSION_STATUS_MISMATCH"]


def test_diagnostics_mismatch_is_inconsistent() -> None:
    _, package, verdict = _genuine_blocked("Task 164 diagnostics mismatch")
    assert verdict["diagnostics_status"] == "UNHEALTHY"

    result = _audit(package, _with(verdict, diagnostics_status="DEGRADED"))

    _assert_inconsistent(result, "DIAGNOSTICS_STATUS_MISMATCH")
    assert result["findings"] == ["DIAGNOSTICS_STATUS_MISMATCH"]


def test_provider_mismatch_is_inconsistent() -> None:
    _, package, verdict = _genuine_ready("Task 164 provider mismatch")

    result = _audit(package, _with(verdict, provider_name="other-provider"))

    _assert_inconsistent(result, "PROVIDER_NAME_MISMATCH")
    assert result["findings"] == ["PROVIDER_NAME_MISMATCH"]
    assert "other-provider" not in json.dumps(result)


def test_model_mismatch_is_inconsistent() -> None:
    _, package, verdict = _genuine_ready("Task 164 model mismatch")

    result = _audit(package, _with(verdict, model_name="other-model"))

    _assert_inconsistent(result, "MODEL_NAME_MISMATCH")
    assert result["findings"] == ["MODEL_NAME_MISMATCH"]


def test_attribution_is_compared_verbatim() -> None:
    """No normalization: case and whitespace differences are mismatches."""
    _, package, verdict = _genuine_ready("Task 164 verbatim attribution")

    upper = _audit(package, _with(verdict, provider_name="FAKE-PROVIDER"))
    padded = _audit(package, _with(verdict, model_name=" fake-model"))

    _assert_inconsistent(upper, "PROVIDER_NAME_MISMATCH")
    _assert_inconsistent(padded, "MODEL_NAME_MISMATCH")


def test_attribution_on_unavailable_verdict_is_inconsistent() -> None:
    """UNAVAILABLE must carry no attribution, whatever the package holds."""
    _, healthy, _ = _genuine_ready("Task 164 unavailable attribution")
    package = _with(healthy, request_fingerprint=None)
    verdict = _certify(package)
    assert verdict["provider_name"] is None

    leaked = _with(verdict, provider_name="fake-provider", model_name="fake-model")
    result = _audit(package, leaked)

    _assert_inconsistent(result, "PROVIDER_NAME_MISMATCH", "MODEL_NAME_MISMATCH")


def test_findings_mismatch_is_inconsistent() -> None:
    _, package, verdict = _genuine_blocked("Task 164 findings mismatch")
    assert verdict["findings"]

    dropped = _audit(package, _with(verdict, findings=[], finding_count=0))
    swapped = _audit(
        package,
        _with(
            verdict, findings=sorted(["ZZ_FORGED_FINDING", *verdict["findings"][1:]])
        ),
    )

    _assert_inconsistent(dropped, "FINDINGS_MISMATCH", "FINDING_COUNT_MISMATCH")
    # Same count, different content: only the findings disagree.
    assert swapped["findings"] == ["FINDINGS_MISMATCH"]
    assert swapped["slice_audit_status"] == "INCONSISTENT"


def test_finding_count_mismatch_is_inconsistent() -> None:
    _, package, verdict = _genuine_blocked("Task 164 count mismatch")

    extra = _with(
        verdict,
        findings=sorted([*verdict["findings"], "ZZ_EXTRA"]),
        finding_count=len(verdict["findings"]) + 1,
    )
    result = _audit(package, extra)

    _assert_inconsistent(result, "FINDING_COUNT_MISMATCH", "FINDINGS_MISMATCH")


def test_count_incoherent_with_own_findings_is_unavailable() -> None:
    """A count that contradicts the verdict's own findings is malformed."""
    _, package, verdict = _genuine_blocked("Task 164 incoherent count")

    result = _audit(package, _with(verdict, finding_count=len(verdict["findings"]) + 1))

    _assert_unavailable(result, "TASK_163_RESULT_INVALID:")


def test_findings_are_never_repaired() -> None:
    """Unsorted or duplicated published findings are rejected, not laundered."""
    _, package, verdict = _genuine_blocked("Task 164 findings not repaired")
    findings = verdict["findings"]

    for tampered in (
        _with(
            verdict, findings=[*findings, findings[0]], finding_count=len(findings) + 1
        ),
        _with(
            verdict,
            findings=list(reversed(findings + ["ZZ_LAST"])),
            finding_count=len(findings) + 1,
        ),
    ):
        _assert_unavailable(_audit(package, tampered), "TASK_163_RESULT_INVALID:")


# ---------------------------------------------------------------------------
# 9-13. Status consistency
# ---------------------------------------------------------------------------


def test_ready_without_request_fingerprint_is_inconsistent() -> None:
    _, healthy, ready = _genuine_ready("Task 164 ready without fingerprint")
    package = _with(healthy, request_fingerprint=None)
    ReasoningRunStage7AuditPackageRead.model_validate(package)

    result = _audit(package, ready)

    _assert_inconsistent(result, "READY_EVIDENCE_MISMATCH", "SLICE_STATUS_MISMATCH")
    assert result["published_slice_status"] == "READY"
    assert result["expected_slice_status"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    "fingerprint",
    ["", "a" * 63, "a" * 65, "g" * 64, "A" * 64, ("a" * 63) + "F", ("a" * 64) + "\n"],
)
def test_ready_with_malformed_fingerprint_is_inconsistent(fingerprint: str) -> None:
    _, healthy, ready = _genuine_ready("Task 164 ready malformed fingerprint")
    package = _with(healthy, request_fingerprint=fingerprint)
    ReasoningRunStage7AuditPackageRead.model_validate(package)

    result = _audit(package, ready)

    _assert_inconsistent(result, "READY_EVIDENCE_MISMATCH")
    assert result["expected_slice_status"] == "UNAVAILABLE"


def test_fingerprint_is_checked_for_shape_never_recomputed() -> None:
    """A different canonical-shaped value is still the published value."""
    _, healthy, ready = _genuine_ready("Task 164 fingerprint shape only")
    other = "0123456789abcdef" * 4
    assert other != healthy["request_fingerprint"]

    result = _audit(_with(healthy, request_fingerprint=other), ready)

    assert result["slice_audit_status"] == "CONSISTENT"


def test_ready_with_noncanonical_audit_source_is_inconsistent() -> None:
    _, healthy, ready = _genuine_ready("Task 164 ready forged package source")
    package = _with(healthy, audit_source="FORGED_SOURCE")
    ReasoningRunStage7AuditPackageRead.model_validate(package)
    assert healthy["audit_source"] == (
        REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162
    )

    result = _audit(package, ready)

    _assert_inconsistent(result, "READY_EVIDENCE_MISMATCH", "SLICE_STATUS_MISMATCH")
    assert "FORGED_SOURCE" not in json.dumps(result)


@pytest.mark.parametrize(
    ("label", "changes"), _READY_GATE_FAILURES, ids=[c[0] for c in _READY_GATE_FAILURES]
)
def test_ready_verdict_requires_every_gate_condition(label: str, changes: dict) -> None:
    _, healthy, ready = _genuine_ready("Task 164 ready gate")
    package = _with(healthy, **changes)
    ReasoningRunStage7AuditPackageRead.model_validate(package)

    result = _audit(package, ready)

    _assert_inconsistent(result, "READY_EVIDENCE_MISMATCH", "SLICE_STATUS_MISMATCH")
    assert result["published_slice_status"] == "READY", label
    assert result["expected_slice_status"] in {"BLOCKED", "UNAVAILABLE"}, label


def test_blocked_without_a_blocking_condition_is_inconsistent() -> None:
    _, healthy, ready = _genuine_ready("Task 164 blocked without condition")
    invented = _with(ready, slice_status="BLOCKED")
    ReasoningRunStage7VerticalSliceRead.model_validate(invented)

    result = _audit(healthy, invented)

    _assert_inconsistent(result, "BLOCKED_EVIDENCE_MISMATCH", "SLICE_STATUS_MISMATCH")
    assert result["published_slice_status"] == "BLOCKED"
    assert result["expected_slice_status"] == "READY"


@pytest.mark.parametrize(
    "condition",
    [
        {"admission_status": "BLOCKED"},
        {"diagnostics_status": "UNHEALTHY"},
        {"request_audit_status": "INCONSISTENT"},
        {"proposal_audit_status": "INCONSISTENT"},
    ],
)
def test_each_blocking_condition_supports_a_blocked_verdict(condition: dict) -> None:
    _, healthy, ready = _genuine_ready("Task 164 blocking conditions")
    package = _with(healthy, **condition)
    verdict = _certify(package)
    assert verdict["slice_status"] == "BLOCKED"

    consistent = _audit(package, verdict)
    certified_anyway = _audit(package, ready)
    withheld = _audit(package, _with(verdict, slice_status="UNAVAILABLE"))

    assert consistent["slice_audit_status"] == "CONSISTENT"
    assert consistent["expected_slice_status"] == "BLOCKED"
    # The genuine READY verdict of the unblocked package cannot stand for it.
    _assert_inconsistent(
        certified_anyway, "READY_EVIDENCE_MISMATCH", "SLICE_STATUS_MISMATCH"
    )
    assert certified_anyway["expected_slice_status"] == "BLOCKED"
    # A refusal re-labelled as UNAVAILABLE no longer reflects the blocker.
    _assert_inconsistent(withheld, "UNAVAILABLE_EVIDENCE_MISMATCH")


def test_unavailable_verdict_for_a_ready_package_is_inconsistent() -> None:
    """Withholding a certification the package fully supports is a defect."""
    _, healthy, ready = _genuine_ready("Task 164 withheld certification")
    withheld = {
        **ready,
        "slice_status": "UNAVAILABLE",
        "provider_name": None,
        "model_name": None,
    }
    ReasoningRunStage7VerticalSliceRead.model_validate(withheld)

    result = _audit(healthy, withheld)

    _assert_inconsistent(
        result, "UNAVAILABLE_EVIDENCE_MISMATCH", "SLICE_STATUS_MISMATCH"
    )
    assert result["published_slice_status"] == "UNAVAILABLE"
    assert result["expected_slice_status"] == "READY"


# ---------------------------------------------------------------------------
# 14-17. Unreadable material is UNAVAILABLE, never compared
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("material", [None, [], (), "text", 7, object()])
def test_missing_or_non_mapping_package_is_unavailable(material: object) -> None:
    _, _, verdict = _genuine_ready("Task 164 missing package")

    result = _audit(material, verdict)

    _assert_unavailable(result, "TASK_162_PACKAGE_MISSING")
    assert result["findings"] == ["TASK_162_PACKAGE_MISSING"]


@pytest.mark.parametrize("material", [None, [], (), "text", 7, object()])
def test_missing_or_non_mapping_verdict_is_unavailable(material: object) -> None:
    _, package, _ = _genuine_ready("Task 164 missing verdict")

    result = _audit(package, material)

    _assert_unavailable(result, "TASK_163_RESULT_MISSING")


def test_both_inputs_missing_reports_both_markers_sorted() -> None:
    result = _audit()

    _assert_unavailable(result, "TASK_162_PACKAGE_MISSING", "TASK_163_RESULT_MISSING")


def test_malformed_package_is_unavailable() -> None:
    _, package, verdict = _genuine_ready("Task 164 malformed package")

    for field in sorted(package):
        truncated = {k: v for k, v in package.items() if k != field}
        result = _audit(truncated, verdict)
        _assert_unavailable(result, "TASK_162_PACKAGE_INVALID:")
        assert result["findings"][0].endswith(f"{field}:missing"), field

    incoherent = _with(package, finding_count=3)
    _assert_unavailable(_audit(incoherent, verdict), "TASK_162_PACKAGE_INVALID:")
    wrong_type = _with(package, diagnostics_status="SHINY")
    _assert_unavailable(_audit(wrong_type, verdict), "TASK_162_PACKAGE_INVALID:")


def test_malformed_verdict_is_unavailable() -> None:
    _, package, verdict = _genuine_ready("Task 164 malformed verdict")

    for field in sorted(verdict):
        truncated = {k: v for k, v in verdict.items() if k != field}
        result = _audit(package, truncated)
        _assert_unavailable(result, "TASK_163_RESULT_INVALID:")
        assert result["findings"][0].endswith(f"{field}:missing"), field

    # READY with no attribution violates the Task 163 contract itself.
    incoherent = _with(verdict, provider_name=None, model_name=None)
    _assert_unavailable(_audit(package, incoherent), "TASK_163_RESULT_INVALID:")
    unknown_status = _with(verdict, slice_status="CERTIFIED")
    _assert_unavailable(_audit(package, unknown_status), "TASK_163_RESULT_INVALID:")


def test_malformed_inputs_report_both_contracts() -> None:
    result = _audit({"session_id": "x"}, {"session_id": "x"})

    _assert_unavailable(result, "TASK_162_PACKAGE_INVALID:", "TASK_163_RESULT_INVALID:")


def test_extra_fields_are_rejected_through_the_child_schemas() -> None:
    _, package, verdict = _genuine_ready("Task 164 extra fields")
    package_extra = _with(package, unexpected_field="x")
    verdict_extra = _with(verdict, unexpected_field="x")
    with pytest.raises(ValidationError):
        ReasoningRunStage7AuditPackageRead.model_validate(package_extra)
    with pytest.raises(ValidationError):
        ReasoningRunStage7VerticalSliceRead.model_validate(verdict_extra)

    package_result = _audit(package_extra, verdict)
    verdict_result = _audit(package, verdict_extra)

    _assert_unavailable(package_result, "TASK_162_PACKAGE_INVALID:")
    assert package_result["findings"] == [
        "TASK_162_PACKAGE_INVALID:unexpected_field:extra_forbidden"
    ]
    _assert_unavailable(verdict_result, "TASK_163_RESULT_INVALID:")
    assert verdict_result["findings"] == [
        "TASK_163_RESULT_INVALID:unexpected_field:extra_forbidden"
    ]


def test_forged_package_of_legal_looking_strings_is_not_evidence() -> None:
    """A hand-written mapping cannot stand in for the Task 162 package."""
    _, _, verdict = _genuine_ready("Task 164 forged package")
    forged = {
        "session_id": verdict["session_id"],
        "admission_status": "ADMITTED",
        "diagnostics_status": "HEALTHY",
        "request_audit_status": "CONSISTENT",
        "proposal_audit_status": "CONSISTENT",
        "provider_name": "fake-provider",
        "model_name": "fake-model",
        "finding_count": 0,
        "findings": [],
        "audit_source": REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
    }

    result = _audit(forged, verdict)

    _assert_unavailable(result, "TASK_162_PACKAGE_INVALID:")


# ---------------------------------------------------------------------------
# 18. Certification source
# ---------------------------------------------------------------------------


def test_forged_task_163_certification_source_is_inconsistent() -> None:
    _, package, verdict = _genuine_ready("Task 164 forged certification source")
    assert verdict["certification_source"] == (
        REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163
    )
    forged = _with(verdict, certification_source="FORGED_TASK_163_SOURCE")
    ReasoningRunStage7VerticalSliceRead.model_validate(forged)

    result = _audit(package, forged)

    _assert_inconsistent(result, "TASK_163_SOURCE_MISMATCH")
    assert result["findings"] == ["TASK_163_SOURCE_MISMATCH"]
    assert "FORGED_TASK_163_SOURCE" not in json.dumps(result)


# ---------------------------------------------------------------------------
# 19-20. Determinism and no mutation
# ---------------------------------------------------------------------------


def test_repeated_audits_are_identical() -> None:
    _, package, verdict = _genuine_ready("Task 164 determinism")
    inconsistent_verdict = _with(verdict, session_id=str(uuid4()), model_name="other")

    for pair in ((package, verdict), (package, inconsistent_verdict), (None, None)):
        first = _audit(*pair)
        second = _audit(*pair)
        assert first == second
        assert json.dumps(first, sort_keys=False) == json.dumps(second, sort_keys=False)


def test_result_is_independent_of_input_key_order() -> None:
    _, package, verdict = _genuine_ready("Task 164 key order")
    tampered = _with(
        verdict, provider_name="x", model_name="y", session_id=str(uuid4())
    )

    def reordered(mapping: dict) -> dict:
        return {key: mapping[key] for key in sorted(mapping, reverse=True)}

    assert _audit(package, tampered) == _audit(reordered(package), reordered(tampered))
    assert _audit(package, verdict) == _audit(reordered(package), reordered(verdict))


def test_findings_are_sorted_and_deduplicated() -> None:
    _, healthy, ready = _genuine_ready("Task 164 finding order")
    package = _with(healthy, request_fingerprint=None)
    tampered = _with(ready, session_id=str(uuid4()), provider_name="p", model_name="m")

    result = _audit(package, tampered)

    assert result["findings"] == sorted(set(result["findings"]))
    assert len(result["findings"]) >= 4


def test_audit_never_mutates_its_inputs() -> None:
    _, package, verdict = _genuine_ready("Task 164 immutability")
    tampered = _with(verdict, provider_name="other-provider")
    package_before = copy.deepcopy(package)
    verdict_before = copy.deepcopy(verdict)
    tampered_before = copy.deepcopy(tampered)

    _audit(package, verdict)
    _audit(package, tampered)
    _audit({**package, "x": 1}, {**verdict, "y": 2})

    assert package == package_before
    assert verdict == verdict_before
    assert tampered == tampered_before


# ---------------------------------------------------------------------------
# 21-23. Independence: no lower-level service, no provider, no raw text
# ---------------------------------------------------------------------------


def _forbid_every_service(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_service(*args: object, **kwargs: object) -> None:
        raise AssertionError("service invoked while auditing")

    def _no_write(*args: object, **kwargs: object) -> None:
        raise AssertionError("write attempted while auditing")

    monkeypatch.setattr(ReasoningRunStage7AdmissionService, "evaluate", _no_service)
    monkeypatch.setattr(ReasoningRunStage7RequestService, "build", _no_service)
    monkeypatch.setattr(ReasoningRunStage7RequestAuditService, "audit", _no_service)
    monkeypatch.setattr(ReasoningRunStage7DispatchService, "dispatch", _no_service)
    monkeypatch.setattr(ReasoningRunStage7ProposalService, "build", _no_service)
    monkeypatch.setattr(ReasoningRunStage7ProposalAuditService, "audit", _no_service)
    monkeypatch.setattr(ReasoningRunStage7ResultService, "build", _no_service)
    monkeypatch.setattr(ReasoningRunStage7DiagnosticsService, "diagnose", _no_service)
    monkeypatch.setattr(ReasoningRunStage7AuditPackageService, "build", _no_service)
    monkeypatch.setattr(ReasoningRunStage7VerticalSliceService, "certify", _no_service)
    monkeypatch.setattr(ReasoningContextService, "build_for_session", _no_service)
    monkeypatch.setattr(Session, "add", _no_write)
    monkeypatch.setattr(Session, "merge", _no_write)
    monkeypatch.setattr(Session, "delete", _no_write)
    monkeypatch.setattr(Session, "commit", _no_write)


def test_audit_never_invokes_lower_level_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tasks 162 and 163 and every service behind them are made to raise."""
    _, package, verdict = _genuine_ready("Task 164 no service invocation")
    _, blocked_package, blocked_verdict = _genuine_blocked("Task 164 no service b")
    tampered = _with(verdict, session_id=str(uuid4()))
    counts_before = _table_counts()
    _forbid_every_service(monkeypatch)

    consistent = _audit(package, verdict)
    blocked = _audit(blocked_package, blocked_verdict)
    inconsistent = _audit(package, tampered)
    unavailable = _audit(None, None)

    assert consistent["slice_audit_status"] == "CONSISTENT"
    assert blocked["slice_audit_status"] == "CONSISTENT"
    assert inconsistent["slice_audit_status"] == "INCONSISTENT"
    assert unavailable["slice_audit_status"] == "UNAVAILABLE"
    assert _table_counts() == counts_before


def test_audit_does_not_rerun_task_163_to_compare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verdict Task 163 would never produce is judged on the package alone."""
    _, package, verdict = _genuine_ready("Task 164 independent expectation")
    invented = _with(verdict, slice_status="BLOCKED")

    def _lying_certify(*args: object, **kwargs: object) -> dict:
        return invented

    monkeypatch.setattr(
        ReasoningRunStage7VerticalSliceService, "certify", _lying_certify
    )

    result = _audit(package, invented)

    # If the audit re-ran Task 163 it would have compared invented with itself.
    _assert_inconsistent(result, "BLOCKED_EVIDENCE_MISMATCH")


def test_no_provider_is_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _seed_full_session("Task 164 no provider invocation")
    with TestingSessionLocal() as db:
        admission = _admission(db, sid)
        package, request_audit, proposal_result, proposal_audit, _, provider = (
            _healthy_material(db, sid)
        )
        diagnostics = _diagnose(package, request_audit, proposal_result, proposal_audit)
        audit_package = _package(
            admission=admission,
            package=package,
            request_audit=request_audit,
            proposal_result=proposal_result,
            proposal_audit=proposal_audit,
            diagnostics=diagnostics,
        )
    verdict = _certify(audit_package)
    assert len(provider.calls) == 1

    def _no_generate(*args: object, **kwargs: object) -> None:
        raise AssertionError("provider invoked while auditing a slice")

    monkeypatch.setattr(_FakeProvider, "generate_reasoning", _no_generate)
    result = _audit(audit_package, verdict)

    assert result["slice_audit_status"] == "CONSISTENT"
    assert len(provider.calls) == 1


def test_raw_provider_text_is_never_included() -> None:
    raw_text = "RAW-PROVIDER-TEXT-MUST-NOT-LEAK"
    _, package, verdict = _genuine_ready("Task 164 raw text")

    for result in (
        _audit(package, verdict),
        _audit(_with(package, raw_provider_text=raw_text), verdict),
        _audit(package, _with(verdict, raw_provider_text=raw_text)),
        _audit(package, _with(verdict, provider_name=raw_text)),
        _audit(_with(package, findings=[raw_text], finding_count=1), verdict),
    ):
        dumped = json.dumps(result)
        assert raw_text not in dumped
        assert "fake-provider" not in dumped
        assert "fake-model" not in dumped
        assert set(result) == AUDIT_KEYS
        assert "raw" not in " ".join(result)


# ---------------------------------------------------------------------------
# 24. Session isolation
# ---------------------------------------------------------------------------


def test_session_isolation() -> None:
    sid_a = _seed_full_session("Task 164 isolation A")
    sid_b = _seed_full_session("Task 164 isolation B")
    with TestingSessionLocal() as db:
        package_a = _healthy_package(db, sid_a)
        package_b = _healthy_package(db, sid_b)
    verdict_a = _certify(package_a)
    verdict_b = _certify(package_b)
    assert sid_a != sid_b
    assert verdict_a["session_id"] == sid_a
    assert verdict_b["session_id"] == sid_b

    assert _audit(package_a, verdict_a)["session_id"] == sid_a
    assert _audit(package_b, verdict_b)["session_id"] == sid_b
    for package, verdict in ((package_a, verdict_b), (package_b, verdict_a)):
        crossed = _audit(package, verdict)
        _assert_inconsistent(crossed, "SESSION_ID_MISMATCH")
        assert crossed["session_id"] == ""
        assert crossed["findings"] == ["SESSION_ID_MISMATCH"]


# ---------------------------------------------------------------------------
# Contract, signature, and source hygiene
# ---------------------------------------------------------------------------


def test_audit_schema_is_strict() -> None:
    assert ReasoningRunStage7VerticalSliceAuditRead.model_config["extra"] == "forbid"
    assert ReasoningRunStage7VerticalSliceAuditRead.model_config["from_attributes"]
    assert set(ReasoningRunStage7VerticalSliceAuditRead.model_fields) == AUDIT_KEYS

    _, package, verdict = _genuine_ready("Task 164 schema strict")
    result = _audit(package, verdict)
    ReasoningRunStage7VerticalSliceAuditRead.model_validate(result)
    with pytest.raises(ValidationError):
        ReasoningRunStage7VerticalSliceAuditRead.model_validate(
            {**result, "unexpected_field": "x"}
        )


def test_audit_schema_rejects_incoherent_states() -> None:
    _, package, verdict = _genuine_ready("Task 164 schema coherence")
    consistent = _audit(package, verdict)
    inconsistent = _audit(package, _with(verdict, session_id=str(uuid4())))
    unavailable = _audit(None, None)

    bad_states = [
        {**consistent, "available": False},
        {**consistent, "consistent": False},
        {**consistent, "finding_count": 1},
        {**consistent, "findings": ["X"], "finding_count": 1},
        {**consistent, "expected_slice_status": "BLOCKED"},
        {**consistent, "published_slice_status": None},
        {**inconsistent, "findings": [], "finding_count": 0},
        {**inconsistent, "consistent": True},
        {**inconsistent, "expected_slice_status": None},
        {**inconsistent, "findings": ["B", "A"], "finding_count": 2},
        {**inconsistent, "findings": ["A", "A"], "finding_count": 2},
        {**unavailable, "available": True},
        {**unavailable, "published_slice_status": "READY"},
        {**unavailable, "expected_slice_status": "READY"},
        {**unavailable, "session_id": "s"},
        {**unavailable, "findings": [], "finding_count": 0},
        {**consistent, "slice_audit_status": "CERTIFIED"},
    ]
    for state in bad_states:
        with pytest.raises(ValidationError):
            ReasoningRunStage7VerticalSliceAuditRead.model_validate(state)


def test_audit_service_accepts_only_package_and_verdict() -> None:
    import inspect

    parameters = inspect.signature(
        ReasoningRunStage7VerticalSliceAuditService.audit
    ).parameters
    assert set(parameters) == {"audit_package", "vertical_slice"}
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters.values())
    for name in ("db", "session", "session_id", "provider", "context"):
        assert name not in parameters


def test_audit_modules_import_only_published_contracts() -> None:
    """Static check: no lower-level Stage 7 service, context builder, or DB."""
    root = Path(__file__).resolve().parents[1]
    service_path = (
        root
        / "src"
        / "rop"
        / "services"
        / "reasoning_run_stage_7_vertical_slice_audit.py"
    )
    tree = ast.parse(service_path.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    rop_imports = {name for name in imported if name.startswith("rop.")}

    assert rop_imports == {
        "rop.schemas.reasoning_run_stage_7_audit_package",
        "rop.schemas.reasoning_run_stage_7_vertical_slice",
        "rop.schemas.reasoning_run_stage_7_vertical_slice_audit",
        "rop.services.reasoning_run_stage_7_audit_package",
        "rop.services.reasoning_run_stage_7_vertical_slice",
    }
    # Only the two published source constants cross the service boundary.
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        in {
            "rop.services.reasoning_run_stage_7_audit_package",
            "rop.services.reasoning_run_stage_7_vertical_slice",
        }
        for alias in node.names
    }
    assert imported_names == {
        "REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162",
        "REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163",
    }


def test_audit_never_recomputes_a_fingerprint() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (
        root
        / "src"
        / "rop"
        / "services"
        / "reasoning_run_stage_7_vertical_slice_audit.py"
    ).read_text(encoding="utf-8")
    for token in ("compute_fingerprint", "hashlib", "sha256", "hexdigest"):
        assert token not in source, token


def test_audit_module_source_is_clean() -> None:
    root = Path(__file__).resolve().parents[1]
    modules = (
        root
        / "src"
        / "rop"
        / "services"
        / "reasoning_run_stage_7_vertical_slice_audit.py",
        root
        / "src"
        / "rop"
        / "schemas"
        / "reasoning_run_stage_7_vertical_slice_audit.py",
    )
    for module_path in modules:
        lowered = module_path.read_text(encoding="utf-8").lower()
        for token in _PROHIBITED_SOURCE_TOKENS:
            assert token not in lowered, f"{module_path.name}: {token}"
    for module_path in sorted((root / "src" / "rop").rglob("*.py")):
        name = module_path.stem.lower()
        for token in _CONCRETE_PROVIDER_TOKENS:
            assert token not in name, f"{module_path}: {token}"
