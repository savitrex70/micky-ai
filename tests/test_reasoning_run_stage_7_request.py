"""Task 155: canonical Stage 7 provider request package tests.

Covers the provider-neutral request package built from the Task 154
admission verdict and the canonical Task 055 context: an admitted
session packages the exact Task 104 model-safe payload with a correct
fingerprint; blocked and unavailable admissions produce no package;
changed context changes the fingerprint; repeated builds are
deterministic; a tampered payload no longer matches its fingerprint;
privacy violations fail closed; construction is read-only and invokes
no provider. A canonical context whose payload names another session
fails closed with ``PAYLOAD_SESSION_ID_MISMATCH`` and is never
packaged; the public schema rejects contradictory status combinations,
foreign or missing payload session identities, and malformed
fingerprints. No model, no network, no concrete provider.
"""

from __future__ import annotations

import json
from collections.abc import Generator
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
from rop.schemas.reasoning_run_stage_7_request import (
    ReasoningRunStage7RequestRead,
)
from rop.services.llm_boundary_contract import PAYLOAD_FIELDS
from rop.services.llm_reasoning import LLMReasoningService
from rop.services.llm_request_serialization import (
    compute_fingerprint,
    serialize_context,
    validate_payload,
)
from rop.services.reasoning_context import ReasoningContextService
from rop.services.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionService,
)
from rop.services.reasoning_run_stage_7_request import (
    REASONING_RUN_STAGE_7_REQUEST_SOURCE_TASK_155,
    ReasoningRunStage7RequestContractError,
    ReasoningRunStage7RequestService,
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

REQUEST_KEYS = {
    "request_status",
    "available",
    "session_id",
    "admission_status",
    "stage_6_certification_status",
    "context_fingerprint",
    "payload",
    "request_source",
}


class _CertificationStub:
    """Records handoff calls and returns one coherent Stage 6 verdict."""

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


class _AdmissionStub:
    """Returns a fixed Task 154-shaped verdict and records calls."""

    def __init__(
        self, admission_status: str, certification_status: str = "CERTIFIED"
    ) -> None:
        self._admission_status = admission_status
        self._certification_status = certification_status
        self.calls: list[UUID] = []

    def evaluate(self, db: Session, session_id: UUID) -> dict[str, object]:
        self.calls.append(session_id)
        admitted = self._admission_status == "ADMITTED"
        return {
            "requested_session_id": str(session_id),
            "admission_status": self._admission_status,
            "admitted": admitted,
            "stage_6_certification_status": self._certification_status,
            "stage_6_release_ready": admitted,
            "stage_6_certification_consistent": True,
            "finding_count": 0,
            "findings": [],
            "admission_source": "REASONING_RUN_STAGE_7_ADMISSION_TASK_154",
        }


class _ExplodingContextService:
    """Proves the context is never read for a non-admitted session."""

    def build_for_session(self, db: Session, session_id: UUID) -> dict[str, object]:
        raise AssertionError("context must not be read for a non-admitted session")


class _StaticContextService:
    """Returns one fixed canonical context mapping for any session."""

    def __init__(self, context: dict[str, object]) -> None:
        self._context = context

    def build_for_session(self, db: Session, session_id: UUID) -> dict[str, object]:
        return self._context


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
            "metadata": {"source": "stage-7-request-test"},
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


def test_admitted_session_builds_package() -> None:
    sid = _seed_full_session("Task 155 packaged")
    certification = _CertificationStub("CERTIFIED")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7RequestService(
            admission_service=ReasoningRunStage7AdmissionService(
                certification_service=certification
            )
        )
        result = service.build(db, UUID(sid))

    assert set(result) == REQUEST_KEYS
    assert result["request_status"] == "PACKAGED"
    assert result["available"] is True
    assert result["session_id"] == sid
    assert result["admission_status"] == "ADMITTED"
    assert result["stage_6_certification_status"] == "CERTIFIED"
    assert result["request_source"] == REASONING_RUN_STAGE_7_REQUEST_SOURCE_TASK_155
    fingerprint = result["context_fingerprint"]
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    assert all(char in "0123456789abcdef" for char in fingerprint)
    payload = result["payload"]
    assert isinstance(payload, dict)
    assert set(payload) == set(PAYLOAD_FIELDS)
    assert payload["session_id"] == sid
    assert compute_fingerprint(payload) == fingerprint
    assert certification.calls == [UUID(sid)]


def test_payload_equals_canonical_serialization() -> None:
    sid = _seed_full_session("Task 155 canonical")
    with TestingSessionLocal() as db:
        context = ReasoningContextService().build_for_session(db, UUID(sid))
        expected = serialize_context(context)
        service = ReasoningRunStage7RequestService(
            admission_service=_AdmissionStub("ADMITTED")
        )
        result = service.build(db, UUID(sid))

    assert result["payload"] == expected
    assert validate_payload(result["payload"]) == []
    assert json.dumps(result["payload"], sort_keys=True) == json.dumps(
        expected, sort_keys=True
    )


def test_blocked_admission_produces_no_package() -> None:
    sid = _create_session("Task 155 blocked")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7RequestService(
            admission_service=ReasoningRunStage7AdmissionService(),
            reasoning_context_service=_ExplodingContextService(),
        )
        result = service.build(db, UUID(sid))

    assert set(result) == REQUEST_KEYS
    assert result["request_status"] == "BLOCKED"
    assert result["available"] is False
    assert result["session_id"] == sid
    assert result["admission_status"] == "BLOCKED"
    assert result["stage_6_certification_status"] == "NO_MATERIAL"
    assert result["context_fingerprint"] is None
    assert result["payload"] is None


def test_unavailable_admission_produces_no_package() -> None:
    sid = _create_session("Task 155 unavailable")
    admission = _AdmissionStub("UNAVAILABLE", "UNAVAILABLE")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7RequestService(
            admission_service=admission,
            reasoning_context_service=_ExplodingContextService(),
        )
        result = service.build(db, UUID(sid))

    assert result["request_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["admission_status"] == "UNAVAILABLE"
    assert result["context_fingerprint"] is None
    assert result["payload"] is None
    assert admission.calls == [UUID(sid)]


def test_nonexistent_session_is_unavailable() -> None:
    missing = UUID("00000000-0000-0000-0000-000000000123")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7RequestService(
            admission_service=_AdmissionStub("ADMITTED")
        )
        result = service.build(db, missing)

    assert result["request_status"] == "UNAVAILABLE"
    assert result["available"] is False
    assert result["context_fingerprint"] is None
    assert result["payload"] is None


def test_foreign_payload_session_is_rejected() -> None:
    requested = _create_session("Task 155 binding requested")
    foreign = _seed_full_session("Task 155 binding foreign")
    assert requested != foreign
    with TestingSessionLocal() as db:
        foreign_context = ReasoningContextService().build_for_session(db, UUID(foreign))
        assert foreign_context["available"] is True
        assert serialize_context(foreign_context)["session_id"] == foreign

        owner_result = ReasoningRunStage7RequestService(
            admission_service=_AdmissionStub("ADMITTED"),
            reasoning_context_service=_StaticContextService(foreign_context),
        ).build(db, UUID(foreign))
        assert owner_result["request_status"] == "PACKAGED"
        assert owner_result["payload"]["session_id"] == foreign

        with pytest.raises(ReasoningRunStage7RequestContractError) as excinfo:
            ReasoningRunStage7RequestService(
                admission_service=_AdmissionStub("ADMITTED"),
                reasoning_context_service=_StaticContextService(foreign_context),
            ).build(db, UUID(requested))

    assert excinfo.value.invariant == "PAYLOAD_SESSION_ID_MISMATCH"
    assert "requested session" in str(excinfo.value)


def test_changed_context_changes_fingerprint() -> None:
    sid = _seed_full_session("Task 155 changed")
    service = ReasoningRunStage7RequestService(
        admission_service=_AdmissionStub("ADMITTED")
    )
    with TestingSessionLocal() as db:
        first = service.build(db, UUID(sid))
    r = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports new shortness of breath",
            "type": "symptom",
            "confidence": 0.8,
            "source": "unit_test",
        },
    )
    assert r.status_code == 201
    with TestingSessionLocal() as db:
        second = service.build(db, UUID(sid))

    assert first["request_status"] == second["request_status"] == "PACKAGED"
    assert first["context_fingerprint"] != second["context_fingerprint"]
    assert first["payload"] != second["payload"]


def test_repeated_build_is_deterministic() -> None:
    sid = _seed_full_session("Task 155 deterministic")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7RequestService(
            admission_service=_AdmissionStub("ADMITTED")
        )
        first = service.build(db, UUID(sid))
        second = service.build(db, UUID(sid))

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert list(first["payload"]) == list(second["payload"])


def test_payload_tamper_breaks_fingerprint_and_copy_is_defensive() -> None:
    sid = _seed_full_session("Task 155 tamper")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7RequestService(
            admission_service=_AdmissionStub("ADMITTED")
        )
        first = service.build(db, UUID(sid))
        pristine = json.loads(json.dumps(first["payload"]))
        first["payload"]["observations"].append({"injected": "tamper"})
        assert compute_fingerprint(first["payload"]) != first["context_fingerprint"]
        second = service.build(db, UUID(sid))

    assert second["payload"] == pristine
    assert second["context_fingerprint"] == compute_fingerprint(pristine)


def test_raises_on_privacy_violation() -> None:
    sid = _create_session("Task 155 privacy")
    r = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "leaked api_key: ABCDEFGHIJKLMNOPQRSTUVWX123456",
            "type": "note",
            "confidence": 1.0,
            "source": "unit_test",
        },
    )
    assert r.status_code == 201
    client.post(f"/sessions/{sid}/generate-candidates")
    client.post(f"/sessions/{sid}/evaluate-evidence")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7RequestService(
            admission_service=_AdmissionStub("ADMITTED")
        )
        with pytest.raises(ReasoningRunStage7RequestContractError) as excinfo:
            service.build(db, UUID(sid))
    assert excinfo.value.invariant == "PAYLOAD_PRIVACY_VIOLATION"


def _table_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f"SELECT COUNT(*) FROM {table.name}")
            ).scalar_one()
            for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
        }


def test_package_construction_is_read_only_and_invokes_no_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid_packaged = _seed_full_session("Task 155 read-only packaged")
    sid_blocked = _create_session("Task 155 read-only blocked")
    counts_before = _table_counts()

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Stage 7 request packaging must stay read-only")

    monkeypatch.setattr(Session, "add", _forbidden)
    monkeypatch.setattr(Session, "merge", _forbidden)
    monkeypatch.setattr(Session, "delete", _forbidden)
    monkeypatch.setattr(Session, "commit", _forbidden)
    monkeypatch.setattr(LLMReasoningService, "build", _forbidden)
    monkeypatch.setattr(LLMReasoningService, "build_for_session", _forbidden)

    with TestingSessionLocal() as db:
        packaged = ReasoningRunStage7RequestService(
            admission_service=_AdmissionStub("ADMITTED")
        ).build(db, UUID(sid_packaged))
        blocked = ReasoningRunStage7RequestService(
            admission_service=ReasoningRunStage7AdmissionService()
        ).build(db, UUID(sid_blocked))

    assert packaged["request_status"] == "PACKAGED"
    assert blocked["request_status"] == "BLOCKED"
    assert _table_counts() == counts_before


def test_request_schema_is_strict() -> None:
    valid = {
        "request_status": "PACKAGED",
        "available": True,
        "session_id": "00000000-0000-0000-0000-000000000001",
        "admission_status": "ADMITTED",
        "stage_6_certification_status": "CERTIFIED",
        "context_fingerprint": "a" * 64,
        "payload": {"session_id": "00000000-0000-0000-0000-000000000001"},
        "request_source": REASONING_RUN_STAGE_7_REQUEST_SOURCE_TASK_155,
    }
    validated = ReasoningRunStage7RequestRead.model_validate(valid)
    assert validated.request_status == "PACKAGED"
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestRead.model_validate({**valid, "extra": 1})
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestRead.model_validate(
            {**valid, "request_status": "ADMITTED"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestRead.model_validate({**valid, "available": False})
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestRead.model_validate({**valid, "payload": None})
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestRead.model_validate(
            {
                **valid,
                "request_status": "BLOCKED",
                "available": False,
                "context_fingerprint": None,
                "payload": {"session_id": "forged"},
            }
        )


SESSION_A = "00000000-0000-0000-0000-00000000000a"
SESSION_B = "00000000-0000-0000-0000-00000000000b"


def _packaged_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "request_status": "PACKAGED",
        "available": True,
        "session_id": SESSION_A,
        "admission_status": "ADMITTED",
        "stage_6_certification_status": "CERTIFIED",
        "context_fingerprint": "a" * 64,
        "payload": {"session_id": SESSION_A},
        "request_source": REASONING_RUN_STAGE_7_REQUEST_SOURCE_TASK_155,
    }
    request.update(overrides)
    return request


def test_request_schema_rejects_contradictory_states() -> None:
    for override in (
        {"admission_status": "BLOCKED"},
        {"stage_6_certification_status": "NO_MATERIAL"},
        {"available": False},
    ):
        with pytest.raises(ValidationError):
            ReasoningRunStage7RequestRead.model_validate(_packaged_request(**override))

    blocked = _packaged_request(
        request_status="BLOCKED",
        available=False,
        admission_status="BLOCKED",
        stage_6_certification_status="NO_MATERIAL",
        context_fingerprint=None,
        payload=None,
    )
    assert (
        ReasoningRunStage7RequestRead.model_validate(blocked).request_status
        == "BLOCKED"
    )
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestRead.model_validate(
            {**blocked, "admission_status": "ADMITTED"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestRead.model_validate(
            {**blocked, "payload": {"session_id": SESSION_A}}
        )

    unavailable = _packaged_request(
        request_status="UNAVAILABLE",
        available=False,
        admission_status="UNAVAILABLE",
        stage_6_certification_status="UNAVAILABLE",
        context_fingerprint=None,
        payload=None,
    )
    assert (
        ReasoningRunStage7RequestRead.model_validate(unavailable).request_status
        == "UNAVAILABLE"
    )
    # An admitted session whose canonical context could not be read is
    # also UNAVAILABLE, so admission_status must not be forced.
    assert (
        ReasoningRunStage7RequestRead.model_validate(
            _packaged_request(
                request_status="UNAVAILABLE",
                available=False,
                context_fingerprint=None,
                payload=None,
            )
        ).admission_status
        == "ADMITTED"
    )
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestRead.model_validate(
            {**unavailable, "payload": {"session_id": SESSION_A}}
        )


def test_request_schema_binds_payload_to_session() -> None:
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestRead.model_validate(
            _packaged_request(payload={"session_id": SESSION_B})
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestRead.model_validate(_packaged_request(payload={}))
    validated = ReasoningRunStage7RequestRead.model_validate(_packaged_request())
    assert validated.payload == {"session_id": SESSION_A}


def test_request_schema_enforces_fingerprint_format() -> None:
    for bad in ("", "a" * 63, "a" * 65, "G" * 64, "A" * 64, "0" * 63 + "G"):
        with pytest.raises(ValidationError):
            ReasoningRunStage7RequestRead.model_validate(
                _packaged_request(context_fingerprint=bad)
            )
    for good in ("a" * 64, "0123456789abcdef" * 4):
        validated = ReasoningRunStage7RequestRead.model_validate(
            _packaged_request(context_fingerprint=good)
        )
        assert validated.context_fingerprint == good


def test_service_module_carries_no_provider_call() -> None:
    import inspect

    import rop.services.reasoning_run_stage_7_request as module

    source = inspect.getsource(module)
    assert "generate_reasoning" not in source
    assert "LLMReasoningService" not in source
