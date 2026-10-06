"""Task 157: Stage 7 explicit provider dispatch tests.

Covers the explicit dispatch seam over the generic LLMReasoningProvider
interface: an explicitly injected test-only fake provider receives one
defensive snapshot of the approved Task 155 request package, exactly
once, and only after the Task 156 audit is consistent. Provider
absence, canonical provider failure, malformed metadata, mutation of
the request snapshot, and hostile provider objects are all contained
by the canonical Task 057/107 taxonomy. No default provider, no
discovery, no registry, no environment or configuration activation, no
network, no concrete provider module.
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
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_run_stage_7_dispatch import (
    ReasoningRunStage7DispatchRead,
)
from rop.services.llm_boundary_contract import ALLOWED_BOUNDARY_OUTCOMES
from rop.services.llm_reasoning_provider import (
    LLMReasoningProviderError,
    LLMReasoningProviderResponse,
    LLMReasoningRequest,
)
from rop.services.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionService,
)
from rop.services.reasoning_run_stage_7_dispatch import (
    REASONING_RUN_STAGE_7_DISPATCH_SOURCE_TASK_157,
    ReasoningRunStage7DispatchService,
)
from rop.services.reasoning_run_stage_7_request import (
    ReasoningRunStage7RequestService,
)
from rop.services.reasoning_run_stage_7_request_audit import (
    ReasoningRunStage7RequestAuditService,
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

DISPATCH_KEYS = {
    "dispatch_status",
    "available",
    "session_id",
    "request_status",
    "request_audit_status",
    "request_fingerprint",
    "outcome",
    "dispatch_source",
    "provider_response",
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
            "certification_status": self._status,
            "certified": certified,
            "release_ready": certified,
        }


class _FakeProvider:
    """Deterministic test-only provider. No network, no model, no state."""

    def __init__(
        self,
        text: str = '{"candidate_assessments": []}',
        response_provider: str = "fake-provider",
        response_model: str = "fake-model",
    ) -> None:
        self.provider_name = response_provider
        self.model_name = response_model
        self.response = LLMReasoningProviderResponse(
            provider=response_provider, model=response_model, text=text
        )
        self.calls: list[LLMReasoningRequest] = []

    def generate_reasoning(
        self, request: LLMReasoningRequest
    ) -> LLMReasoningProviderResponse:
        self.calls.append(request)
        return self.response


class _MutatingProvider(_FakeProvider):
    """Hostile fake that mutates everything it can reach on the handoff."""

    def __init__(self) -> None:
        super().__init__()
        self.seen_payload: dict | None = None

    def generate_reasoning(
        self, request: LLMReasoningRequest
    ) -> LLMReasoningProviderResponse:
        self.calls.append(request)
        self.seen_payload = json.loads(json.dumps(request.payload))
        request.payload["session_id"] = "tampered-session"
        request.payload["reasoning_pipeline"] = {"tampered": True}
        observations = request.payload.get("observations")
        if isinstance(observations, list):
            observations.append({"evil": True})
            if observations and isinstance(observations[0], dict):
                observations[0]["text"] = "tampered"
        request.payload.clear()
        return self.response


class _CanonicalFailureProvider:
    provider_name = "canonical-failure"
    model_name = "canonical-failure"

    def generate_reasoning(
        self, request: LLMReasoningRequest
    ) -> LLMReasoningProviderResponse:
        raise LLMReasoningProviderError("provider could not produce a response")


class _ParseFailureProvider:
    provider_name = "parse-failure"
    model_name = "parse-failure"

    def generate_reasoning(
        self, request: LLMReasoningRequest
    ) -> LLMReasoningProviderResponse:
        raise ValueError("invalid json output")


class _HostileException(Exception):
    def __str__(self) -> str:
        raise RuntimeError("hostile __str__")


class _HostileProvider:
    provider_name = "hostile"
    model_name = "hostile"

    def generate_reasoning(
        self, request: LLMReasoningRequest
    ) -> LLMReasoningProviderResponse:
        raise _HostileException()


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
            "metadata": {"source": "stage-7-dispatch-test"},
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


def _build_package(db: Session, sid: str) -> dict:
    service = ReasoningRunStage7RequestService(
        admission_service=ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("CERTIFIED")
        )
    )
    package = service.build(db, UUID(sid))
    assert package["request_status"] == "PACKAGED"
    return package


def _audit(db: Session, package: object) -> dict:
    service = ReasoningRunStage7RequestAuditService(
        admission_service=ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("CERTIFIED")
        )
    )
    audit = service.audit(db, package)
    assert audit["request_audit_status"] == "CONSISTENT"
    return audit


def _projection(result: dict) -> dict:
    return {key: value for key, value in result.items() if key != "provider_response"}


def test_explicit_fake_provider_dispatch_succeeds() -> None:
    sid = _seed_full_session("Task 157 dispatch success")
    provider = _FakeProvider()
    service = ReasoningRunStage7DispatchService(provider=provider)
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        audit = _audit(db, package)
        result = service.dispatch(request=package, request_audit=audit)

    assert set(result) == DISPATCH_KEYS
    assert result["dispatch_status"] == "DISPATCHED"
    assert result["available"] is True
    assert result["session_id"] == sid
    assert result["request_status"] == "PACKAGED"
    assert result["request_audit_status"] == "CONSISTENT"
    assert result["request_fingerprint"] == package["context_fingerprint"]
    assert result["outcome"] is None
    assert result["dispatch_source"] == REASONING_RUN_STAGE_7_DISPATCH_SOURCE_TASK_157
    assert result["provider_response"] is provider.response
    assert len(provider.calls) == 1
    handed = provider.calls[0]
    assert handed.payload == package["payload"]
    assert handed.context_fingerprint == package["context_fingerprint"]


def test_provider_absent_is_model_unavailable() -> None:
    sid = _seed_full_session("Task 157 provider absent")
    service = ReasoningRunStage7DispatchService()
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        audit = _audit(db, package)
        result = service.dispatch(request=package, request_audit=audit)

    assert result["dispatch_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["outcome"] == "MODEL_UNAVAILABLE"
    assert result["request_fingerprint"] is None
    assert result["provider_response"] is None


def test_material_gates_fail_closed_without_provider_call() -> None:
    sid = _seed_full_session("Task 157 material gates")
    provider = _FakeProvider()
    service = ReasoningRunStage7DispatchService(provider=provider)
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        audit = _audit(db, package)

        missing = service.dispatch(request=None, request_audit=audit)
        assert missing["dispatch_status"] == "UNAVAILABLE"
        assert missing["outcome"] == "INPUT_UNAVAILABLE"
        assert missing["session_id"] == ""
        assert missing["request_status"] is None
        assert missing["request_fingerprint"] is None
        assert missing["provider_response"] is None

        no_status = service.dispatch(request={}, request_audit=audit)
        assert no_status["dispatch_status"] == "UNAVAILABLE"
        assert no_status["outcome"] == "INPUT_UNAVAILABLE"

        blocked = service.dispatch(
            request={**package, "request_status": "BLOCKED"}, request_audit=audit
        )
        assert blocked["dispatch_status"] == "BLOCKED"
        assert blocked["available"] is False
        assert blocked["outcome"] is None
        assert blocked["request_status"] == "BLOCKED"

        request_unavailable = service.dispatch(
            request={**package, "request_status": "UNAVAILABLE"}, request_audit=audit
        )
        assert request_unavailable["dispatch_status"] == "UNAVAILABLE"
        assert request_unavailable["outcome"] == "INPUT_UNAVAILABLE"
        assert request_unavailable["request_status"] == "UNAVAILABLE"

        audit_missing = service.dispatch(request=package, request_audit=None)
        assert audit_missing["dispatch_status"] == "UNAVAILABLE"
        assert audit_missing["outcome"] == "INPUT_UNAVAILABLE"
        assert audit_missing["request_status"] == "PACKAGED"

        audit_unavailable = service.dispatch(
            request=package, request_audit={"request_audit_status": "UNAVAILABLE"}
        )
        assert audit_unavailable["dispatch_status"] == "UNAVAILABLE"
        assert audit_unavailable["request_audit_status"] == "UNAVAILABLE"
        assert audit_unavailable["outcome"] == "INPUT_UNAVAILABLE"

        audit_inconsistent = service.dispatch(
            request=package, request_audit={"request_audit_status": "INCONSISTENT"}
        )
        assert audit_inconsistent["dispatch_status"] == "BLOCKED"
        assert audit_inconsistent["outcome"] is None
        assert audit_inconsistent["request_audit_status"] == "INCONSISTENT"

        payload_missing = service.dispatch(
            request={**package, "payload": None}, request_audit=audit
        )
        assert payload_missing["dispatch_status"] == "UNAVAILABLE"
        assert payload_missing["outcome"] == "INPUT_UNAVAILABLE"

        fingerprint_missing = service.dispatch(
            request={**package, "context_fingerprint": None}, request_audit=audit
        )
        assert fingerprint_missing["dispatch_status"] == "UNAVAILABLE"
        assert fingerprint_missing["outcome"] == "INPUT_UNAVAILABLE"

        assert provider.calls == []


def test_unconsumable_payload_fails_closed() -> None:
    sid = _seed_full_session("Task 157 unconsumable payload")
    provider = _FakeProvider()
    service = ReasoningRunStage7DispatchService(provider=provider)
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        audit = _audit(db, package)
        result = service.dispatch(
            request={**package, "payload": {"generator": (n for n in (1, 2))}},
            request_audit=audit,
        )

    assert result["dispatch_status"] == "UNAVAILABLE"
    assert result["outcome"] == "INPUT_INCONSISTENT"
    assert result["provider_response"] is None
    assert provider.calls == []


def test_canonical_provider_failure_is_model_unavailable() -> None:
    sid = _seed_full_session("Task 157 canonical failure")
    service = ReasoningRunStage7DispatchService(provider=_CanonicalFailureProvider())
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        audit = _audit(db, package)
        result = service.dispatch(request=package, request_audit=audit)

    assert result["dispatch_status"] == "UNAVAILABLE"
    assert result["outcome"] == "MODEL_UNAVAILABLE"
    assert result["provider_response"] is None


def test_provider_parse_failure_uses_canonical_taxonomy() -> None:
    sid = _seed_full_session("Task 157 parse failure")
    service = ReasoningRunStage7DispatchService(provider=_ParseFailureProvider())
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        audit = _audit(db, package)
        result = service.dispatch(request=package, request_audit=audit)

    assert result["dispatch_status"] == "UNAVAILABLE"
    assert result["outcome"] == "MODEL_OUTPUT_INVALID"
    assert result["outcome"] in ALLOWED_BOUNDARY_OUTCOMES
    assert result["provider_response"] is None


def test_hostile_provider_exception_never_escapes() -> None:
    sid = _seed_full_session("Task 157 hostile provider")
    service = ReasoningRunStage7DispatchService(provider=_HostileProvider())
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        audit = _audit(db, package)
        result = service.dispatch(request=package, request_audit=audit)

    assert result["dispatch_status"] == "UNAVAILABLE"
    assert result["outcome"] == "MODEL_UNAVAILABLE"
    assert result["provider_response"] is None
    rendered = json.dumps(_projection(result)).lower()
    assert "hostile" not in rendered
    assert "runtimeerror" not in rendered


def test_provider_mutation_cannot_reach_rop_state() -> None:
    sid = _seed_full_session("Task 157 mutation")
    provider = _MutatingProvider()
    service = ReasoningRunStage7DispatchService(provider=provider)
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        snapshot = copy.deepcopy(package)
        audit = _audit(db, package)
        result = service.dispatch(request=package, request_audit=audit)

    assert result["dispatch_status"] == "DISPATCHED"
    assert len(provider.calls) == 1
    assert provider.seen_payload == snapshot["payload"]
    assert package == snapshot
    assert result["request_fingerprint"] == snapshot["context_fingerprint"]


def test_provider_nested_mutation_cannot_reach_rop_state() -> None:
    sid = _seed_full_session("Task 157 nested mutation")
    provider = _MutatingProvider()
    service = ReasoningRunStage7DispatchService(provider=provider)
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        snapshot = copy.deepcopy(package)
        audit = _audit(db, package)
        service.dispatch(request=package, request_audit=audit)

    original = snapshot["payload"]["observations"]
    assert original
    assert package["payload"]["observations"] == original
    assert package["payload"]["observations"][0]["text"] == "Patient reports chest pain"
    assert all("evil" not in item for item in package["payload"]["observations"])


def test_malformed_provider_metadata_passes_through_unvalidated() -> None:
    sid = _seed_full_session("Task 157 malformed metadata")
    provider = _FakeProvider()
    malformed = LLMReasoningProviderResponse(provider="", model="", text=123)
    provider.response = malformed
    service = ReasoningRunStage7DispatchService(provider=provider)
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        audit = _audit(db, package)
        result = service.dispatch(request=package, request_audit=audit)

    assert result["dispatch_status"] == "DISPATCHED"
    assert result["provider_response"] is malformed
    assert len(provider.calls) == 1


def test_provider_call_count_is_exactly_one() -> None:
    sid = _seed_full_session("Task 157 call count")
    provider = _FakeProvider()
    service = ReasoningRunStage7DispatchService(provider=provider)
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        audit = _audit(db, package)
        first = service.dispatch(request=package, request_audit=audit)
        assert len(provider.calls) == 1
        second = service.dispatch(request=package, request_audit=audit)
        assert len(provider.calls) == 2
        blocked = service.dispatch(
            request={**package, "request_status": "BLOCKED"}, request_audit=audit
        )
        assert len(provider.calls) == 2

    assert first["dispatch_status"] == "DISPATCHED"
    assert second["dispatch_status"] == "DISPATCHED"
    assert blocked["dispatch_status"] == "BLOCKED"


def test_dispatch_result_is_deterministic() -> None:
    sid = _seed_full_session("Task 157 determinism")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        audit = _audit(db, package)
        first = ReasoningRunStage7DispatchService(provider=_FakeProvider()).dispatch(
            request=package, request_audit=audit
        )
        second = ReasoningRunStage7DispatchService(provider=_FakeProvider()).dispatch(
            request=package, request_audit=audit
        )

    first_projection = _projection(first)
    second_projection = _projection(second)
    assert first_projection == second_projection
    assert json.dumps(first_projection, sort_keys=True) == json.dumps(
        second_projection, sort_keys=True
    )


def test_no_provider_auto_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROP_LLM_PROVIDER", "fake-provider")
    monkeypatch.setenv("LLM_REASONING_PROVIDER", "fake-provider")
    monkeypatch.setenv("LLM_PROVIDER", "fake-provider")
    sid = _seed_full_session("Task 157 no auto-selection")
    service = ReasoningRunStage7DispatchService()
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        audit = _audit(db, package)
        result = service.dispatch(request=package, request_audit=audit)

    assert result["dispatch_status"] == "UNAVAILABLE"
    assert result["outcome"] == "MODEL_UNAVAILABLE"
    assert result["provider_response"] is None

    init = inspect.signature(ReasoningRunStage7DispatchService.__init__)
    assert init.parameters["provider"].default is None

    import rop.services.reasoning_run_stage_7_dispatch as module

    for attr in (
        "PROVIDER_REGISTRY",
        "DEFAULT_PROVIDER",
        "AUTO_PROVIDER",
        "PROVIDER_FACTORY",
    ):
        assert not hasattr(module, attr)


def test_no_concrete_provider_module_present() -> None:
    import rop

    root = Path(rop.__file__).resolve().parent
    stems = [path.stem.lower() for path in root.rglob("*.py")]
    for token in _CONCRETE_PROVIDER_TOKENS:
        assert not any(token in stem for stem in stems)
        assert importlib.util.find_spec(f"rop.services.{token}") is None


def test_dispatch_module_source_is_clean() -> None:
    import rop.schemas.reasoning_run_stage_7_dispatch as schema_module
    import rop.services.reasoning_run_stage_7_dispatch as module

    for source in (inspect.getsource(module), inspect.getsource(schema_module)):
        lowered = source.lower()
        for token in _PROHIBITED_SOURCE_TOKENS:
            assert token not in lowered


def test_dispatch_schema_is_strict() -> None:
    valid = {
        "dispatch_status": "DISPATCHED",
        "available": True,
        "session_id": "session-1",
        "request_status": "PACKAGED",
        "request_audit_status": "CONSISTENT",
        "request_fingerprint": "a" * 64,
        "outcome": None,
        "dispatch_source": REASONING_RUN_STAGE_7_DISPATCH_SOURCE_TASK_157,
    }
    validated = ReasoningRunStage7DispatchRead.model_validate(valid)
    assert validated.dispatch_status == "DISPATCHED"

    with pytest.raises(ValidationError):
        ReasoningRunStage7DispatchRead.model_validate({**valid, "extra": 1})
    with pytest.raises(ValidationError):
        ReasoningRunStage7DispatchRead.model_validate(
            {**valid, "dispatch_status": "DONE"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DispatchRead.model_validate({**valid, "available": False})
    with pytest.raises(ValidationError):
        ReasoningRunStage7DispatchRead.model_validate(
            {**valid, "request_fingerprint": None}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DispatchRead.model_validate(
            {**valid, "outcome": "MODEL_UNAVAILABLE"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DispatchRead.model_validate(
            {**valid, "request_audit_status": "INCONSISTENT"}
        )

    blocked = ReasoningRunStage7DispatchRead.model_validate(
        {
            **valid,
            "dispatch_status": "BLOCKED",
            "available": False,
            "request_fingerprint": None,
            "request_status": "BLOCKED",
            "request_audit_status": None,
        }
    )
    assert blocked.outcome is None
    with pytest.raises(ValidationError):
        ReasoningRunStage7DispatchRead.model_validate(
            {**valid, "dispatch_status": "BLOCKED", "available": False}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DispatchRead.model_validate(
            {
                **valid,
                "dispatch_status": "BLOCKED",
                "available": False,
                "request_fingerprint": None,
                "outcome": "MODEL_UNAVAILABLE",
            }
        )

    with pytest.raises(ValidationError):
        ReasoningRunStage7DispatchRead.model_validate(
            {
                **valid,
                "dispatch_status": "UNAVAILABLE",
                "available": False,
                "request_fingerprint": None,
                "outcome": None,
            }
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7DispatchRead.model_validate(
            {
                **valid,
                "dispatch_status": "UNAVAILABLE",
                "available": False,
                "request_fingerprint": None,
                "outcome": "BOGUS",
            }
        )
    for outcome in ALLOWED_BOUNDARY_OUTCOMES:
        unavailable = ReasoningRunStage7DispatchRead.model_validate(
            {
                **valid,
                "dispatch_status": "UNAVAILABLE",
                "available": False,
                "request_fingerprint": None,
                "outcome": outcome,
            }
        )
        assert unavailable.outcome == outcome
