"""Task 131: deterministic missing-information lifecycle tests.

Proves creation, repeat-detection stability, resolution with reason,
stale-state preservation, conflicting-update determinism, and
consistency checking -- all rule-based, no AI. No network beyond the
test app.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.missing_information import MissingInformationItem
from rop.schemas.missing_information_lifecycle import (
    MissingInformationLifecycleRead,
)
from rop.services.missing_information import MissingInformationService
from rop.services.missing_information_lifecycle import (
    MISSING_INFORMATION_LIFECYCLE_SOURCE_TASK_131,
    MissingInformationLifecycleContractError,
    MissingInformationLifecycleService,
)
from rop.services.observation import ObservationService

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
def _ensure_own_db_override() -> Generator[None, None, None]:
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
            "metadata": {"source": "lifecycle-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _add_observation(session_id: str, text: str, type: str = "symptom") -> str:
    o = client.post(
        f"/sessions/{session_id}/observations",
        json={
            "text": text,
            "type": type,
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert o.status_code == 201
    return str(o.json()["id"])


def _observations(session_id: str) -> list[Any]:
    with TestingSessionLocal() as db:
        return ObservationService().list_by_session(db, UUID(session_id))


def _stored(session_id: str) -> list[Any]:
    with TestingSessionLocal() as db:
        return MissingInformationService().list_by_session(db, UUID(session_id))


def _evaluate(session_id: str) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return MissingInformationLifecycleService().evaluate(
            db, UUID(session_id), _observations(session_id)
        )


def _reconcile(session_id: str) -> dict[str, Any]:
    with TestingSessionLocal() as db:
        return MissingInformationLifecycleService().reconcile(
            db, UUID(session_id), _observations(session_id)
        )


def test_creation_reports_new_items() -> None:
    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    record = _reconcile(sid)

    assert record["available"] is True
    assert record["profile"] == "chest_pain"
    assert record["lifecycle_source"] == MISSING_INFORMATION_LIFECYCLE_SOURCE_TASK_131
    assert MissingInformationLifecycleRead.model_validate(record)
    assert {e["state"] for e in record["items"]} == {"NEW"}
    assert len(_stored(sid)) == len(record["items"])
    assert len(record["items"]) == 6


def test_repeat_detection_is_stable_without_duplicates() -> None:
    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    first = _reconcile(sid)
    count = len(_stored(sid))
    second = _reconcile(sid)

    assert {e["state"] for e in second["items"]} == {"PERSISTING"}
    assert len(_stored(sid)) == count
    assert [e["key"] for e in first["items"]] == [e["key"] for e in second["items"]]


def test_resolution_reports_reason_and_satisfying_observation() -> None:
    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    _reconcile(sid)
    age_id = _add_observation(sid, "Age 55 years", type="age")

    record = _reconcile(sid)
    resolved = [e for e in record["items"] if e["state"] == "RESOLVED"]
    assert len(resolved) == 1
    assert resolved[0]["key"] == "age"
    assert resolved[0]["satisfying_observation_ids"] == [age_id]
    assert "satisfied" in resolved[0]["reason"]
    assert len(_stored(sid)) == 5
    assert all(row.item != "Age" for row in _stored(sid))


def test_stale_state_preserved_for_provenance() -> None:
    from rop.repositories import MissingInformationRepository

    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    with TestingSessionLocal() as db:
        MissingInformationRepository().replace_for_session(
            db,
            UUID(sid),
            [MissingInformationItem("legacy-profile", "legacy-key", "Legacy")],
            template_name="legacy-profile",
        )
        db.commit()
    record = _reconcile(sid)
    stale = [e for e in record["items"] if e["state"] == "STALE"]
    assert len(stale) == 1
    assert stale[0]["template"] == "legacy-profile"
    # Reconcile keeps stale rows for provenance instead of erasing them.
    assert any(row.template == "legacy-profile" for row in _stored(sid))


def test_conflicting_updates_are_deterministic() -> None:
    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    first = _reconcile(sid)
    _add_observation(sid, "Blood pressure 120/80", type="measurement")
    second = _reconcile(sid)
    third = _reconcile(sid)
    fourth = _reconcile(sid)
    # The transition reconcile reports the resolution; steady state is
    # then stable and deterministic across repeats.
    assert third == fourth
    assert first != second
    resolved_keys = {e["key"] for e in second["items"] if e["state"] == "RESOLVED"}
    assert "blood_pressure" in resolved_keys
    assert {e["state"] for e in third["items"]} == {"PERSISTING"}


def test_consistency_flags_unknown_template() -> None:
    from rop.repositories import MissingInformationRepository

    sid = _create_session("Patient reports chest pain")
    _add_observation(sid, "Patient reports chest pain")
    with TestingSessionLocal() as db:
        MissingInformationRepository().replace_for_session(
            db,
            UUID(sid),
            [MissingInformationItem("no-such-profile", "x", "X")],
            template_name="no-such-profile",
        )
        db.commit()
    with TestingSessionLocal() as db:
        service = MissingInformationLifecycleService()
        issues = service.check_consistency(db, UUID(sid), _observations(sid))
    assert any(issue.startswith("unknown_profile_template") for issue in issues)


def test_unknown_session_raises() -> None:
    with TestingSessionLocal() as db:
        with pytest.raises(MissingInformationLifecycleContractError):
            MissingInformationLifecycleService().evaluate(db, uuid4(), [])
