from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from rop.api.health import check_database, get_database_check
from rop.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.fixture
def client_factory() -> Iterator[Callable[[Callable[[], None]], TestClient]]:
    def build(check: Callable[[], None]) -> TestClient:
        app.dependency_overrides[get_database_check] = lambda: check
        return TestClient(app)

    yield build
    app.dependency_overrides.pop(get_database_check, None)


def test_liveness_succeeds_when_database_unavailable(client_factory) -> None:
    def failing() -> None:
        raise SQLAlchemyError("simulated database failure")

    with client_factory(failing) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_readiness_returns_200_when_database_reachable(client_factory) -> None:
    def ok() -> None:
        return None

    with client_factory(ok) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


def test_readiness_returns_503_when_database_unreachable(client_factory) -> None:
    def failing() -> None:
        raise SQLAlchemyError("connection refused")

    with client_factory(failing) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}


def test_readiness_response_does_not_leak_connection_details(
    client_factory,
) -> None:
    sentinel = "SENTINEL_SECRET_TOKEN_9F3A"
    leaked_url = f"postgresql+psycopg://user:{sentinel}@db.example/rop"

    def failing() -> None:
        raise SQLAlchemyError(f"could not connect to {leaked_url}")

    with client_factory(failing) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert sentinel not in response.text
    assert "postgresql" not in response.text
    assert leaked_url not in response.text


class _RecordingConnection:
    def __init__(self, *, fail: bool) -> None:
        self._fail = fail
        self.closed = False

    def execute(self, _statement):
        if self._fail:
            raise SQLAlchemyError("simulated failure")
        return None

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info) -> bool:
        self.close()
        return False


class _RecordingEngine:
    def __init__(self, connection: _RecordingConnection) -> None:
        self._connection = connection

    def connect(self) -> _RecordingConnection:
        return self._connection


def test_check_database_closes_connection_on_success() -> None:
    connection = _RecordingConnection(fail=False)

    check_database(_RecordingEngine(connection))

    assert connection.closed


def test_check_database_closes_connection_on_failure() -> None:
    connection = _RecordingConnection(fail=True)

    with pytest.raises(SQLAlchemyError):
        check_database(_RecordingEngine(connection))

    assert connection.closed
