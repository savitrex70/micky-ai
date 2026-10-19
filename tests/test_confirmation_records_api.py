"""Task 227: user-controlled confirmation-record API tests.

These tests run against the project's configured PostgreSQL test database
(``ROP_TEST_DATABASE_URL``, database name ending in ``_test``). Without that
variable they skip rather than touching the application database. Every test
truncates ``assistant_confirmations`` for isolation.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from rop.api import confirmation_records as records_module
from rop.authorization.policy import (
    authorization_policy_identity,
    build_default_policy,
)
from rop.database import get_db
from rop.main import app
from rop.models import AssistantConfirmation
from rop.repositories.assistant_confirmation import (
    MAX_INSPECTION_LIMIT,
    AssistantConfirmationRepository,
)
from rop.schemas.assistant_confirmation import (
    MAX_DELETION_BATCH,
    PendingConfirmationDraft,
)
from rop.schemas.authorization import (
    AuthorizationReason,
    ProposedOperation,
    RiskLevel,
)

TEST_DATABASE_URL = os.environ.get("ROP_TEST_DATABASE_URL", "")
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
DEFAULT_LIFETIME = timedelta(minutes=5)
POLICY_IDENTITY = authorization_policy_identity(build_default_policy())

ORIGIN_HEADERS = {
    "origin": "http://127.0.0.1:8000",
    "content-type": "application/json",
}
BASE_URL = "http://127.0.0.1:8000"


def _skip_reason() -> str | None:
    if not TEST_DATABASE_URL:
        return (
            "ROP_TEST_DATABASE_URL is not set; PostgreSQL confirmation-record "
            "API tests require an explicit test database"
        )
    try:
        database = make_url(TEST_DATABASE_URL).database or ""
    except Exception:
        return "ROP_TEST_DATABASE_URL is not a valid database URL"
    if not database.endswith("_test"):
        return "ROP_TEST_DATABASE_URL database name must end with '_test'"
    return None


@pytest.fixture(scope="session")
def pg_engine():
    reason = _skip_reason()
    if reason is not None:
        pytest.skip(reason)
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1"))
    except Exception as exc:
        engine.dispose()
        pytest.skip(
            "PostgreSQL test database is unreachable " f"({type(exc).__name__})"
        )
    yield engine
    engine.dispose()


@pytest.fixture
def clean_db(pg_engine):
    with Session(pg_engine) as session:
        session.execute(text("TRUNCATE assistant_confirmations"))
        session.commit()
    yield


@pytest.fixture
def db(pg_engine, clean_db):
    with Session(pg_engine) as session:
        yield session
        session.rollback()


@pytest.fixture(autouse=True)
def _use_real_db(pg_engine, clean_db):
    """Override the app's get_db to the real test database.

    ``tests/test_api.py`` installs a session-scoped SQLite override on the
    shared app at import time. This fixture takes precedence for the duration
    of each test and restores whatever was previously installed.
    """
    testing_session = sessionmaker(bind=pg_engine)

    def override():
        with testing_session() as session:
            yield session

    previous = app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides[get_db] = override
    try:
        yield
    finally:
        if previous is not None:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client():
    return TestClient(app, base_url=BASE_URL)


def _make_draft(
    *, operation_id: str = "demo-write", expires_in_minutes: int = 5
) -> PendingConfirmationDraft:
    return PendingConfirmationDraft(
        operation=ProposedOperation(operation_id=operation_id),
        challenge_id=uuid4().hex,
        display_code_hash="0" * 64,
        display_code_salt="0" * 32,
        policy_identity=POLICY_IDENTITY,
        policy_version="1",
        required_risk=RiskLevel.CONSEQUENTIAL,
        required_reason=AuthorizationReason.AUTHORIZATION_REQUIRED,
        expires_at=NOW + timedelta(minutes=expires_in_minutes),
    )


def _create_records(db: Session, count: int) -> list[UUID]:
    """Insert ``count`` pending records, returning their database UUIDs."""
    repo = AssistantConfirmationRepository()
    ids: list[UUID] = []
    for _ in range(count):
        record = repo.create_pending(db, _make_draft(), now=NOW)
        ids.append(record.id)
    db.commit()
    return ids


# ============================================================================
# Inspection
# ============================================================================


def test_list_empty(client: TestClient) -> None:
    response = client.get("/api/assistant/confirmation-records")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_record_count"] == 0
    assert payload["record_count"] == 0
    assert payload["records"] == []
    assert payload["is_complete"] is True


def test_list_pagination(client: TestClient, db: Session) -> None:
    _create_records(db, 5)
    page1 = client.get("/api/assistant/confirmation-records?limit=2&offset=0").json()
    assert page1["record_count"] == 2
    assert page1["total_record_count"] == 5
    assert page1["has_more"] is True
    assert page1["next_offset"] == 2
    page2 = client.get("/api/assistant/confirmation-records?limit=2&offset=2").json()
    assert page2["record_count"] == 2
    assert page2["offset"] == 2
    page3 = client.get("/api/assistant/confirmation-records?limit=2&offset=4").json()
    assert page3["record_count"] == 1
    assert page3["has_more"] is False
    assert page3["is_complete"] is False  # offset != 0
    # Ordering is deterministic across pages
    all_ids = [r["id"] for p in (page1, page2, page3) for r in p["records"]]
    assert len(set(all_ids)) == 5


def test_list_rejects_invalid_limit(client: TestClient) -> None:
    response = client.get("/api/assistant/confirmation-records?limit=0")
    assert response.status_code == 422
    response = client.get(
        f"/api/assistant/confirmation-records?limit={MAX_INSPECTION_LIMIT + 1}"
    )
    assert response.status_code == 422


def test_list_rejects_negative_offset(client: TestClient) -> None:
    response = client.get("/api/assistant/confirmation-records?offset=-1")
    assert response.status_code == 422


def test_list_excludes_secret_fields(client: TestClient, db: Session) -> None:
    _create_records(db, 1)
    payload = client.get("/api/assistant/confirmation-records").json()
    record = payload["records"][0]
    for forbidden in (
        "challenge_id",
        "display_code_hash",
        "display_code_salt",
        "material_digest",
        "material_digest_salt",
    ):
        assert forbidden not in record
    # The safe id is a UUID
    UUID(record["id"])
    assert record["material_state"] == "ABSENT"


# ============================================================================
# Export
# ============================================================================


def test_export_empty(client: TestClient) -> None:
    response = client.get("/api/assistant/confirmation-records/export")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_record_count"] == 0
    assert payload["page_count"] == 0
    assert payload["is_complete"] is True
    assert payload["pages"] == []


def test_export_all_records(client: TestClient, db: Session) -> None:
    _create_records(db, 5)
    response = client.get("/api/assistant/confirmation-records/export")
    payload = response.json()
    assert payload["is_complete"] is True
    assert payload["total_record_count"] == 5
    total = sum(len(p["records"]) for p in payload["pages"])
    assert total == 5


def test_export_walks_multiple_pages(
    client: TestClient, db: Session, monkeypatch
) -> None:
    monkeypatch.setattr(records_module, "_EXPORT_PAGE_LIMIT", 2)
    _create_records(db, 5)
    payload = client.get("/api/assistant/confirmation-records/export").json()
    assert payload["is_complete"] is True
    assert payload["total_record_count"] == 5
    assert payload["page_count"] == 3
    # Each page preserves its own metadata
    for page in payload["pages"]:
        assert page["format"] == "rop.assistant-confirmation-records"
        assert page["version"] == "1"
    total = sum(len(p["records"]) for p in payload["pages"])
    assert total == 5


def test_export_excludes_secrets(client: TestClient, db: Session) -> None:
    _create_records(db, 2)
    payload = client.get("/api/assistant/confirmation-records/export").json()
    for page in payload["pages"]:
        for record in page["records"]:
            for forbidden in (
                "challenge_id",
                "display_code_hash",
                "display_code_salt",
                "material_digest",
                "material_digest_salt",
            ):
                assert forbidden not in record


# ============================================================================
# Deletion
# ============================================================================


def test_delete_requires_origin(client: TestClient, db: Session) -> None:
    ids = _create_records(db, 1)
    response = client.post(
        "/api/assistant/confirmation-records",
        headers={"content-type": "application/json"},
        json={"record_ids": [str(ids[0])]},
    )
    assert response.status_code == 403


def test_delete_requires_json(client: TestClient, db: Session) -> None:
    _create_records(db, 1)
    response = client.post(
        "/api/assistant/confirmation-records",
        headers={
            "origin": "http://127.0.0.1:8000",
            "content-type": "text/plain",
        },
        content="not json",
    )
    assert response.status_code == 403


def test_delete_missing_field(client: TestClient) -> None:
    response = client.post(
        "/api/assistant/confirmation-records",
        headers=ORIGIN_HEADERS,
        json={},
    )
    assert response.status_code == 422


def test_delete_unknown_field(client: TestClient, db: Session) -> None:
    ids = _create_records(db, 1)
    response = client.post(
        "/api/assistant/confirmation-records",
        headers=ORIGIN_HEADERS,
        json={"record_ids": [str(ids[0])], "everything": True},
    )
    assert response.status_code == 422


def test_delete_empty_list(client: TestClient) -> None:
    response = client.post(
        "/api/assistant/confirmation-records",
        headers=ORIGIN_HEADERS,
        json={"record_ids": []},
    )
    assert response.status_code == 422


def test_delete_non_uuid(client: TestClient) -> None:
    response = client.post(
        "/api/assistant/confirmation-records",
        headers=ORIGIN_HEADERS,
        json={"record_ids": ["not-a-uuid"]},
    )
    assert response.status_code == 422


def test_delete_oversized_batch(client: TestClient) -> None:
    fake_ids = [str(uuid4()) for _ in range(MAX_DELETION_BATCH + 1)]
    response = client.post(
        "/api/assistant/confirmation-records",
        headers=ORIGIN_HEADERS,
        json={"record_ids": fake_ids},
    )
    assert response.status_code == 422


def test_delete_selected(client: TestClient, db: Session) -> None:
    ids = _create_records(db, 3)
    response = client.post(
        "/api/assistant/confirmation-records",
        headers=ORIGIN_HEADERS,
        json={"record_ids": [str(ids[0]), str(ids[1])]},
    )
    assert response.status_code == 200
    assert response.json()["deleted_count"] == 2
    remaining = client.get("/api/assistant/confirmation-records").json()[
        "total_record_count"
    ]
    assert remaining == 1


def test_delete_unknown_id_not_inflated(client: TestClient, db: Session) -> None:
    ids = _create_records(db, 1)
    fake = uuid4()
    response = client.post(
        "/api/assistant/confirmation-records",
        headers=ORIGIN_HEADERS,
        json={"record_ids": [str(ids[0]), str(fake)]},
    )
    assert response.status_code == 200
    assert response.json()["deleted_count"] == 1


def test_delete_failure_rolls_back(
    client: TestClient, db: Session, monkeypatch
) -> None:
    ids = _create_records(db, 1)

    def boom(self, session, record_ids):
        raise RuntimeError("db failure")

    monkeypatch.setattr(AssistantConfirmationRepository, "delete_by_ids", boom)
    response = client.post(
        "/api/assistant/confirmation-records",
        headers=ORIGIN_HEADERS,
        json={"record_ids": [str(ids[0])]},
    )
    assert response.status_code == 503
    # The record is still present
    with Session(db.get_bind()) as check:
        count = check.scalar(
            select(AssistantConfirmation).where(AssistantConfirmation.id == ids[0])
        )
        assert count is not None


def test_delete_pending_record_invalidates_challenge(
    client: TestClient, db: Session, pg_engine
) -> None:
    """After deleting a pending record, the challenge cannot be decided."""
    repo = AssistantConfirmationRepository()
    draft = _make_draft()
    record = repo.create_pending(db, draft, now=NOW)
    db.commit()
    rec_id = record.id
    challenge_id = draft.challenge_id

    del_resp = client.post(
        "/api/assistant/confirmation-records",
        headers=ORIGIN_HEADERS,
        json={"record_ids": [str(rec_id)]},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted_count"] == 1

    decide_resp = client.post(
        f"/api/assistant/confirmations/{challenge_id}/decision",
        headers=ORIGIN_HEADERS,
        json={"decision": "cancel"},
    )
    assert decide_resp.status_code == 200
    assert decide_resp.json()["status"] == "refused"
    assert decide_resp.json()["executed"] is False


# ============================================================================
# Clinical separation
# ============================================================================


def test_records_api_never_touches_reasoning_sessions(
    client: TestClient, db: Session, pg_engine
) -> None:
    """No confirmation-record endpoint writes to clinical tables."""
    with Session(pg_engine) as check:
        before = check.scalar(text("select count(*) from reasoning_sessions"))
    _create_records(db, 2)
    client.get("/api/assistant/confirmation-records")
    client.get("/api/assistant/confirmation-records/export")
    with Session(pg_engine) as check:
        after = check.scalar(text("select count(*) from reasoning_sessions"))
    assert before == after
