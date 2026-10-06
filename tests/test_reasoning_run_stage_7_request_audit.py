"""Task 156: Stage 7 request provenance and integrity audit tests.

Covers the independent audit of the Task 155 request package: a correct
package is CONSISTENT; fingerprint, session, certification, admission,
source, and payload-field tampering are each detected as INCONSISTENT
without trusting the builder's flags; missing package material or an
unreadable verification input is UNAVAILABLE. Also proves the audit is
read-only, never mutates the canonical request, is deterministic, and
calls no provider. No model, no network, no concrete provider.
"""

from __future__ import annotations

import copy
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
from rop.schemas.reasoning_run_stage_7_request_audit import (
    ReasoningRunStage7RequestAuditRead,
)
from rop.services.llm_reasoning import LLMReasoningService
from rop.services.llm_request_serialization import compute_fingerprint
from rop.services.reasoning_context import ReasoningContextContractError
from rop.services.reasoning_run_stage_7_admission import (
    ReasoningRunStage7AdmissionContractError,
    ReasoningRunStage7AdmissionService,
)
from rop.services.reasoning_run_stage_7_request import (
    ReasoningRunStage7RequestService,
)
from rop.services.reasoning_run_stage_7_request_audit import (
    REASONING_RUN_STAGE_7_REQUEST_AUDIT_SOURCE_TASK_156,
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

AUDIT_KEYS = {
    "request_audit_status",
    "available",
    "session_consistent",
    "admission_consistent",
    "certification_consistent",
    "source_consistent",
    "payload_consistent",
    "fingerprint_consistent",
    "finding_count",
    "findings",
    "audit_source",
}


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


class _AdmissionContractErrorStub:
    def evaluate(self, db: Session, session_id: UUID) -> dict[str, object]:
        raise ReasoningRunStage7AdmissionContractError("FORGED_UNREADABLE", "forged")


class _ContextContractErrorStub:
    def build_for_session(self, db: Session, session_id: UUID) -> dict[str, object]:
        raise ReasoningContextContractError("SESSION_NOT_FOUND", "forged")


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
            "metadata": {"source": "stage-7-request-audit-test"},
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


def _audit(
    db: Session,
    package: object,
    admission_service: object | None = None,
    reasoning_context_service: object | None = None,
) -> dict:
    service = ReasoningRunStage7RequestAuditService(
        admission_service=(
            admission_service
            if admission_service is not None
            else ReasoningRunStage7AdmissionService(
                certification_service=_CertificationStub("CERTIFIED")
            )
        ),
        reasoning_context_service=reasoning_context_service,
    )
    return service.audit(db, package)


def test_correct_package_is_consistent() -> None:
    sid = _seed_full_session("Task 156 consistent")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        result = _audit(db, package)

    assert set(result) == AUDIT_KEYS
    assert result["request_audit_status"] == "CONSISTENT"
    assert result["available"] is True
    assert result["session_consistent"] is True
    assert result["admission_consistent"] is True
    assert result["certification_consistent"] is True
    assert result["source_consistent"] is True
    assert result["payload_consistent"] is True
    assert result["fingerprint_consistent"] is True
    assert result["findings"] == []
    assert result["finding_count"] == 0
    assert result["audit_source"] == REASONING_RUN_STAGE_7_REQUEST_AUDIT_SOURCE_TASK_156


def test_fingerprint_mismatch_is_inconsistent() -> None:
    sid = _seed_full_session("Task 156 fingerprint")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        package["context_fingerprint"] = "0" * 64
        result = _audit(db, package)

    assert result["request_audit_status"] == "INCONSISTENT"
    assert result["available"] is True
    assert result["fingerprint_consistent"] is False
    assert "FINGERPRINT_MISMATCH" in result["findings"]
    assert result["session_consistent"] is True
    assert result["admission_consistent"] is True
    assert result["certification_consistent"] is True
    assert result["source_consistent"] is True
    assert result["payload_consistent"] is True


def test_session_mismatch_is_inconsistent() -> None:
    sid_a = _seed_full_session("Task 156 session A")
    sid_b = _seed_full_session("Task 156 session B")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid_a)
        package["session_id"] = sid_b
        result = _audit(db, package)

    assert result["request_audit_status"] == "INCONSISTENT"
    assert result["session_consistent"] is False
    assert f"SESSION_IDENTITY_MISMATCH:{sid_a}" in result["findings"]


def test_unexpected_payload_field_is_inconsistent() -> None:
    sid = _seed_full_session("Task 156 unexpected field")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        package["payload"]["evil_field"] = "injected"
        package["context_fingerprint"] = compute_fingerprint(package["payload"])
        result = _audit(db, package)

    assert result["request_audit_status"] == "INCONSISTENT"
    assert result["payload_consistent"] is False
    assert "PAYLOAD_UNEXPECTED_FIELD:evil_field" in result["findings"]
    assert "PAYLOAD_NOT_CANONICAL" in result["findings"]
    assert result["fingerprint_consistent"] is True
    assert result["session_consistent"] is True


def test_missing_payload_field_is_inconsistent() -> None:
    sid = _seed_full_session("Task 156 missing field")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        package["payload"].pop("observations")
        package["context_fingerprint"] = compute_fingerprint(package["payload"])
        result = _audit(db, package)

    assert result["request_audit_status"] == "INCONSISTENT"
    assert result["payload_consistent"] is False
    assert "PAYLOAD_MISSING_FIELD:observations" in result["findings"]
    assert result["fingerprint_consistent"] is True


def test_wrong_request_source_is_inconsistent() -> None:
    sid = _seed_full_session("Task 156 source")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        package["request_source"] = "FORGED_SOURCE"
        result = _audit(db, package)

    assert result["request_audit_status"] == "INCONSISTENT"
    assert result["source_consistent"] is False
    assert "REQUEST_SOURCE_MISMATCH:FORGED_SOURCE" in result["findings"]
    assert result["session_consistent"] is True
    assert result["payload_consistent"] is True
    assert result["fingerprint_consistent"] is True


def test_admission_status_mismatch_is_inconsistent() -> None:
    sid = _seed_full_session("Task 156 admission echo")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        package["admission_status"] = "BLOCKED"
        result = _audit(db, package)

    assert result["request_audit_status"] == "INCONSISTENT"
    assert result["admission_consistent"] is False
    assert "ADMISSION_STATUS_MISMATCH:BLOCKED" in result["findings"]
    assert result["certification_consistent"] is True


def test_certification_status_mismatch_is_inconsistent() -> None:
    sid = _seed_full_session("Task 156 certification echo")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        package["stage_6_certification_status"] = "BLOCKED"
        result = _audit(db, package)

    assert result["request_audit_status"] == "INCONSISTENT"
    assert result["certification_consistent"] is False
    assert "STAGE_6_CERTIFICATION_MISMATCH:BLOCKED" in result["findings"]
    assert result["admission_consistent"] is True


def test_not_admitted_recomputation_is_inconsistent() -> None:
    sid = _create_session("Task 156 not admitted recompute")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        forged_admission = type(
            "ForgedAdmission",
            (),
            {
                "evaluate": lambda self, db, session_id: {
                    "admission_status": "BLOCKED",
                    "stage_6_certification_status": "NO_MATERIAL",
                }
            },
        )()
        real_context = _audit(db, package)["payload_consistent"]
        result = _audit(db, package, admission_service=forged_admission)

    assert real_context is True
    assert result["request_audit_status"] == "INCONSISTENT"
    assert result["admission_consistent"] is False
    assert "ADMISSION_NOT_ADMITTED:BLOCKED" in result["findings"]


def test_missing_package_material_is_unavailable() -> None:
    sid = _seed_full_session("Task 156 missing material")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)

        missing = _audit(db, None)
        assert missing["request_audit_status"] == "UNAVAILABLE"
        assert missing["available"] is False
        assert missing["findings"] == ["REQUEST_PACKAGE_MISSING"]
        assert missing["session_consistent"] is False
        assert missing["fingerprint_consistent"] is False

        blocked = _audit(db, {"request_status": "BLOCKED"})
        assert blocked["request_audit_status"] == "UNAVAILABLE"
        assert blocked["findings"] == ["REQUEST_NOT_PACKAGED:BLOCKED"]

        no_payload = _audit(
            db,
            {
                "request_status": "PACKAGED",
                "session_id": sid,
                "admission_status": "ADMITTED",
                "stage_6_certification_status": "CERTIFIED",
                "context_fingerprint": "a" * 64,
                "payload": None,
                "request_source": "forged",
            },
        )
        assert no_payload["request_audit_status"] == "UNAVAILABLE"
        assert no_payload["findings"] == ["REQUEST_PAYLOAD_MISSING"]

        no_fingerprint = _audit(
            db,
            {
                **package,
                "context_fingerprint": None,
            },
        )
        assert no_fingerprint["request_audit_status"] == "UNAVAILABLE"
        assert no_fingerprint["findings"] == ["FINGERPRINT_MISSING"]


def test_unreadable_verification_inputs_are_unavailable() -> None:
    sid = _seed_full_session("Task 156 unreadable")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)

        context_failure = _audit(
            db,
            package,
            reasoning_context_service=_ContextContractErrorStub(),
        )
        assert context_failure["request_audit_status"] == "UNAVAILABLE"
        assert context_failure["available"] is False
        assert "CONTEXT_UNREADABLE:SESSION_NOT_FOUND" in context_failure["findings"]
        assert context_failure["session_consistent"] is False
        assert context_failure["admission_consistent"] is False

        admission_failure = _audit(
            db,
            package,
            admission_service=_AdmissionContractErrorStub(),
        )
        assert admission_failure["request_audit_status"] == "UNAVAILABLE"
        assert "ADMISSION_UNREADABLE:FORGED_UNREADABLE" in admission_failure["findings"]
        assert admission_failure["admission_consistent"] is False


def test_audit_does_not_mutate_canonical_request_and_is_deterministic() -> None:
    sid = _seed_full_session("Task 156 immutable")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        snapshot = json.loads(json.dumps(package))
        first = _audit(db, package)
        second = _audit(db, package)
        assert package == snapshot
        assert first == second
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
        first["findings"].append("tampered_by_test")
        first["request_audit_status"] = "UNAVAILABLE"
        tampered_again = _audit(db, package)
    assert package == snapshot
    assert tampered_again == second


def _table_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f"SELECT COUNT(*) FROM {table.name}")
            ).scalar_one()
            for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
        }


def test_audit_is_read_only_and_invokes_no_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _seed_full_session("Task 156 read-only")
    with TestingSessionLocal() as db:
        package = _build_package(db, sid)
        snapshot = copy.deepcopy(package)

        counts_before = _table_counts()

        def _forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("Stage 7 request audit must stay read-only")

        monkeypatch.setattr(Session, "add", _forbidden)
        monkeypatch.setattr(Session, "merge", _forbidden)
        monkeypatch.setattr(Session, "delete", _forbidden)
        monkeypatch.setattr(Session, "commit", _forbidden)
        monkeypatch.setattr(LLMReasoningService, "build", _forbidden)
        monkeypatch.setattr(LLMReasoningService, "build_for_session", _forbidden)

        consistent = _audit(db, package)
        inconsistent = _audit(db, {**package, "context_fingerprint": "0" * 64})

        assert consistent["request_audit_status"] == "CONSISTENT"
        assert inconsistent["request_audit_status"] == "INCONSISTENT"
        assert _table_counts() == counts_before
    assert package == snapshot


def test_audit_schema_is_strict() -> None:
    valid = {
        "request_audit_status": "CONSISTENT",
        "available": True,
        "session_consistent": True,
        "admission_consistent": True,
        "certification_consistent": True,
        "source_consistent": True,
        "payload_consistent": True,
        "fingerprint_consistent": True,
        "finding_count": 0,
        "findings": [],
        "audit_source": REASONING_RUN_STAGE_7_REQUEST_AUDIT_SOURCE_TASK_156,
    }
    validated = ReasoningRunStage7RequestAuditRead.model_validate(valid)
    assert validated.request_audit_status == "CONSISTENT"
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestAuditRead.model_validate({**valid, "extra": 1})
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestAuditRead.model_validate(
            {**valid, "request_audit_status": "PACKAGED"}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestAuditRead.model_validate(
            {**valid, "session_consistent": False}
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestAuditRead.model_validate(
            {
                **valid,
                "request_audit_status": "UNAVAILABLE",
                "available": False,
                "admission_consistent": False,
                "certification_consistent": False,
                "source_consistent": False,
                "payload_consistent": False,
                "fingerprint_consistent": False,
                "session_consistent": True,
            }
        )
    with pytest.raises(ValidationError):
        ReasoningRunStage7RequestAuditRead.model_validate(
            {
                **valid,
                "request_audit_status": "INCONSISTENT",
                "available": True,
                "fingerprint_consistent": False,
                "finding_count": 2,
                "findings": ["B", "A"],
            }
        )


def test_service_module_carries_no_provider_call() -> None:
    import inspect

    import rop.services.reasoning_run_stage_7_request_audit as module

    source = inspect.getsource(module)
    assert "generate_reasoning" not in source
    assert "LLMReasoningService" not in source
