from __future__ import annotations

import inspect
from collections.abc import Generator
from datetime import datetime
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
from rop.models.reasoning_run_receipt import ReasoningRunReceipt
from rop.schemas.reasoning_run_receipt import (
    ReasoningRunReceiptHistoryRead,
    ReasoningRunReceiptRead,
)
from rop.services.reasoning_run_receipt import ReasoningRunReceiptService

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
            "metadata": {"source": "history-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _insert_receipt(
    session_id: UUID,
    input_fingerprint: str,
    outcome: str = "COMPLETED",
    created_at: datetime | None = None,
) -> ReasoningRunReceipt:
    row = ReasoningRunReceipt(
        session_id=session_id,
        input_fingerprint=input_fingerprint,
        exogenous_snapshot={"source": "unit-test"},
        outcome=outcome,
    )
    if created_at is not None:
        row.created_at = created_at
    with TestingSessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def test_history_returns_completed_receipts_for_session() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "a" * 64)
    _insert_receipt(sid, "b" * 64)

    r = client.get(f"/sessions/{sid}/reasoning-run/history")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == str(sid)
    assert len(body["receipts"]) == 2
    assert all(item["outcome"] == "COMPLETED" for item in body["receipts"])
    assert body["receipts"] == sorted(
        body["receipts"],
        key=lambda item: (item["created_at"], item["id"]),
    )


def test_history_excludes_other_sessions_and_non_completed_rows() -> None:
    sid = UUID(_create_session())
    other = UUID(_create_session())
    _insert_receipt(sid, "c" * 64)
    _insert_receipt(other, "d" * 64)
    _insert_receipt(sid, "e" * 64, outcome="PENDING")

    r = client.get(f"/sessions/{sid}/reasoning-run/history")
    assert r.status_code == 200
    body = r.json()
    assert len(body["receipts"]) == 1
    assert body["receipts"][0]["input_fingerprint"] == "c" * 64


def test_history_orders_deterministically() -> None:
    sid = UUID(_create_session())
    first = _insert_receipt(sid, "f" * 64, created_at=datetime(2024, 1, 1, 0, 0, 0))
    second = _insert_receipt(
        sid,
        "g" * 64,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
    )

    r = client.get(f"/sessions/{sid}/reasoning-run/history")
    assert r.status_code == 200
    body = r.json()
    ordered = sorted(
        body["receipts"],
        key=lambda item: (item["created_at"], item["id"]),
    )
    assert body["receipts"] == ordered
    assert {item["id"] for item in body["receipts"]} == {str(first.id), str(second.id)}


def test_history_missing_session_404() -> None:
    sid = uuid4()
    r = client.get(f"/sessions/{sid}/reasoning-run/history")
    assert r.status_code == 404
    assert r.json()["detail"] == "Session not found"


def test_history_service_is_read_only() -> None:
    sid = UUID(_create_session())
    _insert_receipt(sid, "h" * 64)

    with TestingSessionLocal() as db:
        before = len(ReasoningRunReceiptService().list_completed_by_session(db, sid))

    r = client.get(f"/sessions/{sid}/reasoning-run/history")
    assert r.status_code == 200

    with TestingSessionLocal() as db:
        after = len(ReasoningRunReceiptService().list_completed_by_session(db, sid))

    assert before == after
    assert r.json()["receipts"][0]["input_fingerprint"] == "h" * 64


def test_history_schema_rejects_extra_fields() -> None:
    payload = {
        "session_id": str(uuid4()),
        "receipts": [
            {
                "id": str(uuid4()),
                "session_id": str(uuid4()),
                "input_fingerprint": "i" * 64,
                "exogenous_snapshot": {},
                "outcome": "COMPLETED",
                "created_at": "2024-01-01T00:00:00+00:00",
                "extra": True,
            }
        ],
    }
    with pytest.raises(ValidationError):
        ReasoningRunReceiptHistoryRead.model_validate(payload)

    with pytest.raises(ValidationError):
        ReasoningRunReceiptRead.model_validate(payload["receipts"][0])

    top_level = {"session_id": str(uuid4()), "receipts": [], "smuggled": True}
    with pytest.raises(ValidationError):
        ReasoningRunReceiptHistoryRead.model_validate(top_level)


# ---------------------------------------------------------------------------
# Task 138 helpers for execution-derived state checks
# ---------------------------------------------------------------------------


def _add_observation(session_id: str, text: str) -> None:
    o = client.post(
        f"/sessions/{session_id}/observations",
        json={
            "text": text,
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert o.status_code == 201


def _executed_fingerprint(session_id: str) -> str:
    """Complete one idempotent execution; return its canonical fingerprint."""
    r = client.post(f"/sessions/{session_id}/reasoning-run/execute-idempotent")
    assert r.status_code == 200
    envelope = r.json()
    assert envelope["disposition"] == "EXECUTED_NEW"
    return envelope["result"]["input_fingerprint"]


def _counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f'SELECT COUNT(*) FROM "{table.name}"')
            ).scalar_one()
            for table in Base.metadata.sorted_tables
        }


# ---------------------------------------------------------------------------
# Required Task 138 coverage: determinism, exact fields, no side effects
# ---------------------------------------------------------------------------


def test_repeated_identical_history_requests_are_deterministic() -> None:
    """Repeated identical requests return identical persisted content."""
    sid = UUID(_create_session())
    _insert_receipt(sid, "1" * 64, created_at=datetime(2024, 1, 1, 0, 0, 0))
    _insert_receipt(sid, "2" * 64, created_at=datetime(2024, 1, 1, 0, 0, 0))

    url = f"/sessions/{sid}/reasoning-run/history"
    first = client.get(url)
    assert first.status_code == 200
    for _ in range(3):
        again = client.get(url)
        assert again.status_code == 200
        assert again.json() == first.json()


def test_history_preserves_exact_persisted_receipt_fields() -> None:
    """Each returned item equals the persisted row, field for field."""
    sid = UUID(_create_session())
    row = _insert_receipt(sid, "5" * 64, created_at=datetime(2024, 6, 1, 8, 30, 0))

    r = client.get(f"/sessions/{sid}/reasoning-run/history")
    assert r.status_code == 200
    items = r.json()["receipts"]
    assert len(items) == 1
    item = items[0]
    assert set(item) == {
        "id",
        "session_id",
        "input_fingerprint",
        "exogenous_snapshot",
        "outcome",
        "created_at",
    }
    with TestingSessionLocal() as db:
        persisted = db.get(ReasoningRunReceipt, row.id)
        assert persisted is not None
        assert item == {
            "id": str(persisted.id),
            "session_id": str(persisted.session_id),
            "input_fingerprint": persisted.input_fingerprint,
            "exogenous_snapshot": persisted.exogenous_snapshot,
            "outcome": persisted.outcome,
            "created_at": persisted.created_at.isoformat(),
        }


def test_history_performs_no_execution_and_no_derived_state_mutation() -> None:
    """A history read performs no execution and mutates no state.

    Derived reasoning state is built by a real idempotent execution
    first; after repeated history reads every table count and every
    derived collection is byte-for-byte unchanged.
    """
    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    _executed_fingerprint(sid)

    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )
        from rop.services.candidate_generation import CandidateGenerationService
        from rop.services.missing_information import MissingInformationService

        receipts_before = ReasoningRunReceiptRepository().count_by_session(
            db, UUID(sid)
        )
        candidates_before = len(
            CandidateGenerationService().list_by_session(db, UUID(sid))
        )
        missing_before = len(MissingInformationService().list_by_session(db, UUID(sid)))
    counts_before = _counts()

    for _ in range(2):
        r = client.get(f"/sessions/{sid}/reasoning-run/history")
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == sid
        assert len(body["receipts"]) == receipts_before
        assert all(item["outcome"] == "COMPLETED" for item in body["receipts"])

    with TestingSessionLocal() as db:
        from rop.repositories.reasoning_run_receipt import (
            ReasoningRunReceiptRepository,
        )
        from rop.services.candidate_generation import CandidateGenerationService
        from rop.services.missing_information import MissingInformationService

        assert (
            ReasoningRunReceiptRepository().count_by_session(db, UUID(sid))
            == receipts_before
        )
        assert (
            len(CandidateGenerationService().list_by_session(db, UUID(sid)))
            == candidates_before
        )
        assert (
            len(MissingInformationService().list_by_session(db, UUID(sid)))
            == missing_before
        )
    assert _counts() == counts_before


def test_history_service_and_repository_path_is_read_only_source() -> None:
    """The Task 138 code path contains no write or execution primitive."""
    from rop.repositories.reasoning_run_receipt import ReasoningRunReceiptRepository
    from rop.services import reasoning_run_receipt as receipt_mod

    service_source = inspect.getsource(receipt_mod)
    for token in (
        "db.commit",
        "db.add",
        "db.flush",
        "execute_for_session",
        "ReasoningRunExecutionService",
    ):
        assert token not in service_source

    repo_method_source = inspect.getsource(
        ReasoningRunReceiptRepository.list_completed_by_session
    )
    for token in ("db.add", "db.commit", "db.flush", "db.delete", ".update("):
        assert token not in repo_method_source


def test_task_138_introduces_no_provider_or_model_integration() -> None:
    """No model/provider runtime, keys, or inference appears in Task 138 code."""
    from pathlib import Path

    import rop

    root = Path(rop.__file__).parent
    modules = (
        root / "services" / "reasoning_run_receipt.py",
        root / "repositories" / "reasoning_run_receipt.py",
        root / "schemas" / "reasoning_run_receipt.py",
        root / "api" / "sessions.py",
    )
    banned = (
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "claude",
        "api_key",
        "apikey",
    )
    for path in modules:
        source = path.read_text(encoding="utf-8").lower()
        for token in banned:
            assert token not in source, f"{path.name} contains {token!r}"


# ---------------------------------------------------------------------------
# Task 137 regression: single-receipt inspection contract is unchanged
# ---------------------------------------------------------------------------


def test_task_137_receipt_inspection_endpoint_remains_unchanged() -> None:
    from rop.services.reasoning_run_receipt import (
        REASONING_RUN_RECEIPT_SERVICE_SOURCE_TASK_137,
    )

    sid = _create_session()
    _add_observation(sid, "Patient reports chest pain")
    fingerprint = _executed_fingerprint(sid)

    r = client.get(
        f"/sessions/{sid}/reasoning-run/receipt",
        params={"input_fingerprint": fingerprint},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "found",
        "available",
        "requested_session_id",
        "requested_input_fingerprint",
        "receipt",
        "receipt_source",
    }
    assert body["found"] is True
    assert body["available"] is True
    assert body["requested_session_id"] == sid
    assert body["requested_input_fingerprint"] == fingerprint
    assert body["receipt_source"] == REASONING_RUN_RECEIPT_SERVICE_SOURCE_TASK_137
    assert set(body["receipt"]) == {
        "id",
        "session_id",
        "input_fingerprint",
        "exogenous_snapshot",
        "outcome",
        "created_at",
    }
    assert body["receipt"]["session_id"] == sid
    assert body["receipt"]["input_fingerprint"] == fingerprint
    assert body["receipt"]["outcome"] == "COMPLETED"

    missing = client.get(
        f"/sessions/{sid}/reasoning-run/receipt",
        params={"input_fingerprint": "0" * 64},
    )
    assert missing.status_code == 200
    missing_body = missing.json()
    assert missing_body["found"] is False
    assert missing_body["receipt"] is None
    assert missing_body["requested_input_fingerprint"] == "0" * 64
