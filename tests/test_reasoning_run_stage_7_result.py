"""Task 160: Stage 7 unified reasoning result boundary tests.

Covers the single provider-neutral result surface that combines the
Task 155 request package, the Task 156 request audit, the Task 158
validated proposal, and the Task 159 proposal audit. The boundary is
presentation only: the canonical child verdicts decide the aggregate
status with deterministic precedence (UNAVAILABLE -> INCONSISTENT ->
MODEL_UNAVAILABLE -> READY), raw provider text and the raw provider
response object never appear in the projection, and the service is
read-only and provider-free over the four material mappings.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
from collections.abc import Generator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_run_stage_7_result import (
    ReasoningRunStage7ResultRead,
)
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
)
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionService,
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
    REASONING_RUN_STAGE_7_RESULT_SOURCE_TASK_160,
    ReasoningRunStage7ResultService,
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

RESULT_KEYS = {
    "session_id",
    "request_fingerprint",
    "request_status",
    "proposal_status",
    "request_consistent",
    "proposal_consistent",
    "provider_name",
    "model_name",
    "result_status",
    "finding_count",
    "findings",
    "source",
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
            "metadata": {"source": "stage-7-result-test"},
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
    db: Session, sid: str, explanation: str = ""
) -> tuple[dict, dict, dict, dict, dict, object]:
    context = _context(db, sid)
    provider = _FakeProvider()
    provider.response = _response(_valid_model_output(context, explanation))
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


def _combine(
    package: object = None,
    request_audit: object = None,
    proposal_result: object = None,
    proposal_audit: object = None,
) -> dict:
    return ReasoningRunStage7ResultService.build(
        request_package=package,
        request_audit=request_audit,
        proposal_result=proposal_result,
        proposal_audit=proposal_audit,
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
# Happy path: reconciled material yields the READY aggregate
# ---------------------------------------------------------------------------


def test_healthy_result_is_ready() -> None:
    sid = _seed_full_session("Task 160 healthy result")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, provider = (
            _healthy_material(db, sid)
        )
        result = _combine(package, request_audit, proposal_result, proposal_audit)

    assert set(result) == RESULT_KEYS
    assert result["result_status"] == "READY"
    assert result["session_id"] == sid
    assert result["request_fingerprint"] == package["context_fingerprint"]
    assert result["request_status"] == "PACKAGED"
    assert result["proposal_status"] == "VALIDATED"
    assert result["request_consistent"] is True
    assert result["proposal_consistent"] is True
    assert result["provider_name"] == "fake-provider"
    assert result["model_name"] == "fake-model"
    assert result["finding_count"] == 0
    assert result["findings"] == []
    assert result["source"] == REASONING_RUN_STAGE_7_RESULT_SOURCE_TASK_160
    assert len(provider.calls) == 1


# ---------------------------------------------------------------------------
# INCONSISTENT: request or proposal integrity failure
# ---------------------------------------------------------------------------


def test_request_inconsistency_is_inconsistent() -> None:
    sid = _seed_full_session("Task 160 request inconsistency")
    with TestingSessionLocal() as db:
        package, _, proposal_result, proposal_audit, _, _ = _healthy_material(db, sid)
        forged_package = {**copy.deepcopy(package), "context_fingerprint": "0" * 64}
        inconsistent_audit = _audit_request(db, forged_package)
        assert inconsistent_audit["request_audit_status"] == "INCONSISTENT"
        result = _combine(package, inconsistent_audit, proposal_result, proposal_audit)

    assert result["result_status"] == "INCONSISTENT"
    assert result["request_consistent"] is False
    assert result["proposal_consistent"] is True
    assert "FINGERPRINT_MISMATCH" in result["findings"]
    assert result["request_status"] == "PACKAGED"
    assert result["proposal_status"] == "VALIDATED"


def test_proposal_inconsistency_is_inconsistent() -> None:
    sid = _seed_full_session("Task 160 proposal inconsistency")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, _, context, _ = _healthy_material(
            db, sid
        )
        corrupted = copy.deepcopy(proposal_result)
        corrupted["proposal"]["provider"] = ""
        inconsistent_audit = ReasoningRunStage7ProposalAuditService.audit(
            proposal_result=corrupted, context=context
        )
        assert inconsistent_audit["proposal_audit_status"] == "INCONSISTENT"
        result = _combine(package, request_audit, proposal_result, inconsistent_audit)

    assert result["result_status"] == "INCONSISTENT"
    assert result["request_consistent"] is True
    assert result["proposal_consistent"] is False
    assert "empty_provider" in result["findings"]


def test_proposal_fingerprint_mismatch_is_inconsistent() -> None:
    sid = _seed_full_session("Task 160 proposal fingerprint mismatch")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )
        forged = {**copy.deepcopy(proposal_result), "context_fingerprint": "0" * 64}
        result = _combine(package, request_audit, forged, proposal_audit)

    assert result["result_status"] == "INCONSISTENT"
    assert result["proposal_consistent"] is False
    assert "FINGERPRINT_MISMATCH" in result["findings"]


# ---------------------------------------------------------------------------
# MODEL_UNAVAILABLE: canonical Task 057 provider failure, reused verbatim
# ---------------------------------------------------------------------------


def test_provider_unavailable_result() -> None:
    sid = _seed_full_session("Task 160 provider unavailable")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit = _outage_material(
            db, sid
        )
        result = _combine(package, request_audit, proposal_result, proposal_audit)

    assert result["result_status"] == "MODEL_UNAVAILABLE"
    assert result["proposal_status"] == "MODEL_UNAVAILABLE"
    assert result["request_status"] == "PACKAGED"
    assert result["session_id"] == sid
    assert result["request_consistent"] is True
    assert result["proposal_consistent"] is False
    assert result["provider_name"] is None
    assert result["model_name"] is None
    assert "PROPOSAL_NOT_VALIDATED:MODEL_UNAVAILABLE" in result["findings"]


def test_model_output_failure_folds_to_inconsistent() -> None:
    cases = (
        (ValueError("invalid json output"), "MODEL_OUTPUT_INVALID"),
        (ValueError("unknown candidate reference"), "MODEL_OUTPUT_INCONSISTENT"),
    )
    sid = _seed_full_session("Task 160 model output failures")
    with TestingSessionLocal() as db:
        for error, expected in cases:
            package, request_audit, proposal_result, proposal_audit = (
                _model_failure_material(db, sid, error)
            )
            assert proposal_result["proposal_status"] == expected
            result = _combine(package, request_audit, proposal_result, proposal_audit)
            assert result["result_status"] == "INCONSISTENT"
            assert result["proposal_status"] == expected
            assert result["request_consistent"] is True
            assert result["proposal_consistent"] is False
            assert f"PROPOSAL_NOT_VALIDATED:{expected}" in result["findings"]


# ---------------------------------------------------------------------------
# UNAVAILABLE: missing required result material, no consistency claim
# ---------------------------------------------------------------------------


def test_missing_result_material_is_unavailable() -> None:
    sid = _seed_full_session("Task 160 missing material")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )

        empty = _combine()
        missing_package = _combine(None, request_audit, proposal_result, proposal_audit)
        missing_audit = _combine(package, None, proposal_result, proposal_audit)
        missing_proposal = _combine(package, request_audit, None, proposal_audit)
        missing_proposal_audit = _combine(package, request_audit, proposal_result, None)
        blocked_package = _combine(
            {**copy.deepcopy(package), "request_status": "BLOCKED"},
            request_audit,
            proposal_result,
            proposal_audit,
        )
        unavailable_proposal = _combine(
            package,
            request_audit,
            {
                **copy.deepcopy(proposal_result),
                "proposal_status": "UNAVAILABLE",
                "available": False,
                "proposal": None,
                "context_fingerprint": None,
                "provider": None,
                "model": None,
            },
            None,
        )

    for result in (
        empty,
        missing_package,
        missing_audit,
        missing_proposal,
        missing_proposal_audit,
        blocked_package,
        unavailable_proposal,
    ):
        assert result["result_status"] == "UNAVAILABLE"
        assert result["request_consistent"] is False
        assert result["proposal_consistent"] is False
        assert result["provider_name"] is None
        assert result["model_name"] is None

    assert empty["findings"] == [
        "PROPOSAL_RESULT_MISSING",
        "REQUEST_AUDIT_MISSING",
        "REQUEST_PACKAGE_MISSING",
    ]
    assert empty["session_id"] == ""
    assert empty["request_fingerprint"] is None
    assert missing_package["findings"] == ["REQUEST_PACKAGE_MISSING"]
    assert missing_audit["findings"] == ["REQUEST_AUDIT_MISSING"]
    assert missing_proposal["findings"] == ["PROPOSAL_RESULT_MISSING"]
    assert missing_proposal_audit["findings"] == ["PROPOSAL_AUDIT_MISSING"]
    assert blocked_package["findings"] == ["REQUEST_NOT_PACKAGED:BLOCKED"]
    assert blocked_package["request_status"] == "UNAVAILABLE"
    assert unavailable_proposal["findings"] == ["PROPOSAL_UNAVAILABLE"]


# ---------------------------------------------------------------------------
# Raw provider surface never escapes
# ---------------------------------------------------------------------------


def test_raw_provider_text_is_not_exposed() -> None:
    marker = "RAW-LLM-TEXT-MARKER-160"
    sid = _seed_full_session("Task 160 raw text not exposed")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid, explanation=marker)
        )
        result = _combine(package, request_audit, proposal_result, proposal_audit)

    assert result["result_status"] == "READY"
    serialized = json.dumps(result)
    assert marker not in serialized
    assert "provider_response" not in serialized
    assert "candidate_assessments" not in serialized
    assert '"text"' not in serialized


# ---------------------------------------------------------------------------
# Exact session isolation
# ---------------------------------------------------------------------------


def test_session_isolation_is_exact() -> None:
    sid_a = _seed_full_session("Task 160 isolation A")
    sid_b = _seed_full_session("Task 160 isolation B")
    with TestingSessionLocal() as db:
        package_a, audit_a, proposal_a, proposal_audit_a, _, _ = _healthy_material(
            db, sid_a
        )
        package_b, audit_b, proposal_b, proposal_audit_b, _, _ = _healthy_material(
            db, sid_b
        )

        result_a = _combine(package_a, audit_a, proposal_a, proposal_audit_a)
        result_b = _combine(package_b, audit_b, proposal_b, proposal_audit_b)
        crossed = _combine(package_a, audit_b, proposal_b, proposal_audit_b)
        reverse = _combine(package_b, audit_b, proposal_a, proposal_audit_a)

    assert result_a["result_status"] == "READY"
    assert result_a["session_id"] == sid_a
    assert result_b["result_status"] == "READY"
    assert result_b["session_id"] == sid_b

    assert crossed["result_status"] == "INCONSISTENT"
    assert crossed["session_id"] == sid_a
    assert "SESSION_MISMATCH" in crossed["findings"]

    assert reverse["result_status"] == "INCONSISTENT"
    assert reverse["session_id"] == sid_b
    assert "SESSION_MISMATCH" in reverse["findings"]


# ---------------------------------------------------------------------------
# Determinism and read-only behavior
# ---------------------------------------------------------------------------


def test_result_is_deterministic() -> None:
    sid = _seed_full_session("Task 160 deterministic")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )
        first = _combine(package, request_audit, proposal_result, proposal_audit)
        second = _combine(package, request_audit, proposal_result, proposal_audit)
        outage = _outage_material(db, sid)
        third = _combine(*outage)
        fourth = _combine(*outage)

    assert first == second
    assert third == fourth
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_result_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _seed_full_session("Task 160 read only")
    with TestingSessionLocal() as db:
        package, request_audit, proposal_result, proposal_audit, _, _ = (
            _healthy_material(db, sid)
        )

    def _no_write(*args: object, **kwargs: object) -> None:
        raise AssertionError("write attempted")

    def _no_rebuild(*args: object, **kwargs: object) -> None:
        raise AssertionError("material service invoked while projecting")

    monkeypatch.setattr(Session, "add", _no_write)
    monkeypatch.setattr(Session, "merge", _no_write)
    monkeypatch.setattr(Session, "delete", _no_write)
    monkeypatch.setattr(Session, "commit", _no_write)
    monkeypatch.setattr(ReasoningRunStage7RequestService, "build", _no_rebuild)
    monkeypatch.setattr(ReasoningRunStage7RequestAuditService, "audit", _no_rebuild)
    monkeypatch.setattr(ReasoningRunStage7DispatchService, "dispatch", _no_rebuild)
    monkeypatch.setattr(ReasoningRunStage7ProposalService, "build", _no_rebuild)
    monkeypatch.setattr(ReasoningRunStage7ProposalAuditService, "audit", _no_rebuild)

    counts_before = _table_counts()
    result = _combine(package, request_audit, proposal_result, proposal_audit)
    counts_after = _table_counts()

    assert result["result_status"] == "READY"
    assert counts_after == counts_before


# ---------------------------------------------------------------------------
# Strict schema
# ---------------------------------------------------------------------------


def _ready_payload() -> dict:
    return {
        "session_id": "0b8b1f9a-3f1e-4a1c-9c2f-9a5a1f9a3f1e",
        "request_fingerprint": "a" * 64,
        "request_status": "PACKAGED",
        "proposal_status": "VALIDATED",
        "request_consistent": True,
        "proposal_consistent": True,
        "provider_name": "fake-provider",
        "model_name": "fake-model",
        "result_status": "READY",
        "finding_count": 0,
        "findings": [],
        "source": REASONING_RUN_STAGE_7_RESULT_SOURCE_TASK_160,
    }


def test_result_schema_is_strict() -> None:
    valid = ReasoningRunStage7ResultRead.model_validate(_ready_payload())
    assert valid.result_status == "READY"

    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {**_ready_payload(), "raw_text": "smuggled"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {**_ready_payload(), "result_status": "WEIRD"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {**_ready_payload(), "request_consistent": False}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {**_ready_payload(), "provider_name": None}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {**_ready_payload(), "model_name": None}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {**_ready_payload(), "session_id": ""}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {**_ready_payload(), "finding_count": 3}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {**_ready_payload(), "findings": ["b", "a"], "finding_count": 2}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {**_ready_payload(), "findings": ["a", "a"], "finding_count": 2}
        )

    inconsistent = ReasoningRunStage7ResultRead.model_validate(
        {
            **_ready_payload(),
            "result_status": "INCONSISTENT",
            "request_consistent": False,
            "findings": ["FINGERPRINT_MISMATCH"],
            "finding_count": 1,
        }
    )
    assert inconsistent.result_status == "INCONSISTENT"

    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {**_ready_payload(), "result_status": "INCONSISTENT"}
        )

    model_unavailable = ReasoningRunStage7ResultRead.model_validate(
        {
            **_ready_payload(),
            "result_status": "MODEL_UNAVAILABLE",
            "proposal_status": "MODEL_UNAVAILABLE",
            "proposal_consistent": False,
            "provider_name": None,
            "model_name": None,
        }
    )
    assert model_unavailable.result_status == "MODEL_UNAVAILABLE"

    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {
                **_ready_payload(),
                "result_status": "MODEL_UNAVAILABLE",
                "proposal_status": "MODEL_UNAVAILABLE",
                "proposal_consistent": False,
                "provider_name": None,
                "model_name": None,
                "request_consistent": False,
            }
        )

    unavailable = ReasoningRunStage7ResultRead.model_validate(
        {
            **_ready_payload(),
            "result_status": "UNAVAILABLE",
            "request_status": "UNAVAILABLE",
            "proposal_status": "UNAVAILABLE",
            "request_consistent": False,
            "proposal_consistent": False,
            "provider_name": None,
            "model_name": None,
            "session_id": "",
            "request_fingerprint": None,
            "findings": ["REQUEST_PACKAGE_MISSING"],
            "finding_count": 1,
        }
    )
    assert unavailable.result_status == "UNAVAILABLE"

    with pytest.raises(ValidationError):
        ReasoningRunStage7ResultRead.model_validate(
            {
                **_ready_payload(),
                "result_status": "UNAVAILABLE",
                "proposal_status": "UNAVAILABLE",
                "provider_name": None,
                "model_name": None,
            }
        )


# ---------------------------------------------------------------------------
# Boundary shape: material-only, provider-free, source-clean
# ---------------------------------------------------------------------------


def test_result_service_accepts_only_material() -> None:
    signature = inspect.signature(ReasoningRunStage7ResultService.build)
    parameters = signature.parameters
    assert set(parameters) == {
        "request_package",
        "request_audit",
        "proposal_result",
        "proposal_audit",
    }
    for parameter in parameters.values():
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    import rop.services.reasoning_run_stage_7_result as service_module

    for name in dir(service_module):
        if name.startswith("PROVIDER_"):
            raise AssertionError(f"provider-specific module attribute: {name}")


def test_no_concrete_provider_module_present() -> None:
    services_dir = Path(__file__).resolve().parents[1] / "src" / "rop" / "services"
    schemas_dir = Path(__file__).resolve().parents[1] / "src" / "rop" / "schemas"
    for directory in (services_dir, schemas_dir):
        for path in directory.glob("*stage_7*"):
            lowered = path.stem.lower()
            for token in _CONCRETE_PROVIDER_TOKENS:
                assert token not in lowered, path.name


def test_result_module_source_is_clean() -> None:
    root = Path(__file__).resolve().parents[1]
    modules = (
        root / "src" / "rop" / "services" / "reasoning_run_stage_7_result.py",
        root / "src" / "rop" / "schemas" / "reasoning_run_stage_7_result.py",
    )
    for module_path in modules:
        source = module_path.read_text(encoding="utf-8")
        lowered = source.lower()
        for token in _PROHIBITED_SOURCE_TOKENS:
            assert token not in lowered, f"{module_path.name}: {token}"
        spec = importlib.util.spec_from_file_location(
            f"source_scan_{module_path.stem}", module_path
        )
        assert spec is not None
