"""Task 154: Stage 7 per-session LLM admission tests.

Covers the read-only admission decision over the canonical Task 152
Stage 6 certification: CERTIFIED admits, NO_MATERIAL blocks (an empty
deterministic session must never be sent to an LLM), BLOCKED and
UNVERIFIABLE block, an unreadable certification is UNAVAILABLE, an
incoherent certification record can never admit, exact session
isolation, determinism, read-only behavior, strict schema, and no
provider invocation. No model, no network, no concrete provider.
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
from rop.schemas.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionRead,
)
from rop.services.llm_reasoning import LLMReasoningService
from rop.services.reasoning_run_stage_6_certification import (
    ReasoningRunStage6CertificationContractError,
)
from rop.services.reasoning_run_stage_7_admission import (
    REASONING_RUN_STAGE_7_ADMISSION_SOURCE_TASK_154,
    ReasoningRunStage7AdmissionService,
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

ADMISSION_KEYS = {
    "requested_session_id",
    "admission_status",
    "admitted",
    "stage_6_certification_status",
    "stage_6_release_ready",
    "stage_6_certification_consistent",
    "finding_count",
    "findings",
    "admission_source",
}


class _CertificationStub:
    """Records handoff calls and returns one coherent Stage 6 verdict."""

    def __init__(self, status: str) -> None:
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


class _IncoherentCertificationStub:
    """Claims CERTIFIED while the record contradicts itself."""

    def certify(self, db: Session, session_id: UUID) -> dict[str, object]:
        return {
            "certification_status": "CERTIFIED",
            "certified": False,
            "release_ready": False,
        }


class _ContractErrorStub:
    def certify(self, db: Session, session_id: UUID) -> dict[str, object]:
        raise ReasoningRunStage6CertificationContractError("GATE_UNREADABLE", "forged")


@pytest.fixture(autouse=True)
def _reset_db() -> Generator[None, None, None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    app.dependency_overrides[get_db] = override_get_db
    yield


def _create_session(user_input: str = "Patient reports chest pain") -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "stage-7-admission-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def test_certified_admits() -> None:
    sid = _create_session()
    stub = _CertificationStub("CERTIFIED")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7AdmissionService(certification_service=stub)
        result = service.evaluate(db, UUID(sid))
    assert set(result) == ADMISSION_KEYS
    assert result["requested_session_id"] == sid
    assert result["admission_status"] == "ADMITTED"
    assert result["admitted"] is True
    assert result["admitted"] == (result["admission_status"] == "ADMITTED")
    assert result["stage_6_certification_status"] == "CERTIFIED"
    assert result["stage_6_release_ready"] is True
    assert result["stage_6_certification_consistent"] is True
    assert result["findings"] == []
    assert result["finding_count"] == 0
    assert result["admission_source"] == REASONING_RUN_STAGE_7_ADMISSION_SOURCE_TASK_154
    assert stub.calls == [UUID(sid)]


def test_no_material_blocks_real_empty_session() -> None:
    sid = _create_session()
    with TestingSessionLocal() as db:
        result = ReasoningRunStage7AdmissionService().evaluate(db, UUID(sid))
    assert result["admission_status"] == "BLOCKED"
    assert result["admitted"] is False
    assert result["stage_6_certification_status"] == "NO_MATERIAL"
    assert result["stage_6_release_ready"] is False
    assert result["stage_6_certification_consistent"] is True
    assert result["findings"] == ["STAGE_6_CERTIFICATION_NOT_CERTIFIED:NO_MATERIAL"]
    assert result["finding_count"] == 1


def test_blocked_and_unverifiable_certifications_block() -> None:
    sid = _create_session()
    for status in ("BLOCKED", "UNVERIFIABLE"):
        stub = _CertificationStub(status)
        with TestingSessionLocal() as db:
            service = ReasoningRunStage7AdmissionService(certification_service=stub)
            result = service.evaluate(db, UUID(sid))
        assert stub.calls == [UUID(sid)]
        assert result["admission_status"] == "BLOCKED"
        assert result["admitted"] is False
        assert result["stage_6_certification_status"] == status
        assert result["stage_6_certification_consistent"] is True
        assert result["findings"] == [f"STAGE_6_CERTIFICATION_NOT_CERTIFIED:{status}"]


def test_contract_failure_is_unavailable() -> None:
    sid = _create_session()
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7AdmissionService(
            certification_service=_ContractErrorStub()
        )
        result = service.evaluate(db, UUID(sid))
    assert result["admission_status"] == "UNAVAILABLE"
    assert result["admitted"] is False
    assert result["stage_6_certification_status"] == "UNAVAILABLE"
    assert result["stage_6_release_ready"] is False
    assert result["stage_6_certification_consistent"] is False
    assert result["findings"] == ["STAGE_6_CERTIFICATION_UNREADABLE:GATE_UNREADABLE"]
    assert result["finding_count"] == 1


def test_incoherent_certification_record_can_never_admit() -> None:
    sid = _create_session()
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7AdmissionService(
            certification_service=_IncoherentCertificationStub()
        )
        result = service.evaluate(db, UUID(sid))
    assert result["admission_status"] == "BLOCKED"
    assert result["admitted"] is False
    assert result["stage_6_certification_consistent"] is False
    assert result["findings"] == ["STAGE_6_CERTIFICATION_INCOHERENT"]


def test_exact_session_isolation() -> None:
    sid_a = _create_session("Patient A reports chest pain")
    sid_b = _create_session("Patient B reports chest pain")
    stub = _CertificationStub("CERTIFIED")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7AdmissionService(certification_service=stub)
        result_a = service.evaluate(db, UUID(sid_a))
        result_b = service.evaluate(db, UUID(sid_b))
    assert stub.calls == [UUID(sid_a), UUID(sid_b)]
    assert result_a["requested_session_id"] == sid_a
    assert result_b["requested_session_id"] == sid_b

    with TestingSessionLocal() as db:
        real_a = ReasoningRunStage7AdmissionService().evaluate(db, UUID(sid_a))
        real_b = ReasoningRunStage7AdmissionService().evaluate(db, UUID(sid_b))
    assert real_a["requested_session_id"] == sid_a
    assert real_b["requested_session_id"] == sid_b
    assert real_a["admission_status"] == real_b["admission_status"] == "BLOCKED"
    assert real_a["stage_6_certification_status"] == "NO_MATERIAL"
    assert real_b["stage_6_certification_status"] == "NO_MATERIAL"


def test_repeated_evaluation_is_deterministic() -> None:
    sid = _create_session()
    with TestingSessionLocal() as db:
        first = ReasoningRunStage7AdmissionService().evaluate(db, UUID(sid))
        second = ReasoningRunStage7AdmissionService().evaluate(db, UUID(sid))
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def _table_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f"SELECT COUNT(*) FROM {table.name}")
            ).scalar_one()
            for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
        }


def test_admission_is_read_only_and_invokes_no_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _create_session()
    counts_before = _table_counts()

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Stage 7 admission must stay read-only")

    monkeypatch.setattr(Session, "add", _forbidden)
    monkeypatch.setattr(Session, "merge", _forbidden)
    monkeypatch.setattr(Session, "delete", _forbidden)
    monkeypatch.setattr(Session, "commit", _forbidden)
    monkeypatch.setattr(LLMReasoningService, "build", _forbidden)
    monkeypatch.setattr(LLMReasoningService, "build_for_session", _forbidden)

    with TestingSessionLocal() as db:
        admitted = ReasoningRunStage7AdmissionService(
            certification_service=_CertificationStub("CERTIFIED")
        ).evaluate(db, UUID(sid))
        blocked = ReasoningRunStage7AdmissionService().evaluate(db, UUID(sid))

    assert admitted["admission_status"] == "ADMITTED"
    assert blocked["admission_status"] == "BLOCKED"
    assert _table_counts() == counts_before


def test_admission_schema_is_strict() -> None:
    valid = {
        "requested_session_id": "00000000-0000-0000-0000-000000000001",
        "admission_status": "ADMITTED",
        "admitted": True,
        "stage_6_certification_status": "CERTIFIED",
        "stage_6_release_ready": True,
        "stage_6_certification_consistent": True,
        "finding_count": 0,
        "findings": [],
        "admission_source": REASONING_RUN_STAGE_7_ADMISSION_SOURCE_TASK_154,
    }
    validated = ReasoningRunStage7AdmissionRead.model_validate(valid)
    assert validated.admission_status == "ADMITTED"
    with pytest.raises(ValidationError):
        ReasoningRunStage7AdmissionRead.model_validate({**valid, "winner": "model_a"})
    with pytest.raises(ValidationError):
        ReasoningRunStage7AdmissionRead.model_validate(
            {**valid, "admission_status": "CERTIFIED"}
        )
