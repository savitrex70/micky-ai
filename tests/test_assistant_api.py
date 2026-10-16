"""Tests for the honest placeholder assistant request endpoint."""

from fastapi.testclient import TestClient

from rop.database import SessionLocal
from rop.main import app

ENDPOINT = "/api/assistant/requests"
UNSUPPORTED_MESSAGE = (
    "No assistant capability is currently connected. "
    "This request was not executed and was not saved."
)


def _post(message: str):
    with TestClient(app) as client:
        return client.post(ENDPOINT, json={"message": message})


def test_valid_request_returns_unsupported_capability() -> None:
    response = _post("What is the weather today?")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "unsupported-capability",
        "message": UNSUPPORTED_MESSAGE,
    }


def test_response_does_not_echo_user_message() -> None:
    marker = "UNIQUE_MARKER_7F2A9D"
    response = _post(f"Please remember this exact string: {marker}")

    assert response.status_code == 200
    assert marker not in response.text


def test_empty_message_rejected() -> None:
    response = _post("")
    assert response.status_code == 422


def test_whitespace_only_message_rejected() -> None:
    for value in ("   ", "\t", "\n", "  \t\n  "):
        response = _post(value)
        assert response.status_code == 422, f"expected 422 for {value!r}"


def test_overlong_message_rejected() -> None:
    response = _post("x" * 2001)
    assert response.status_code == 422


def test_unexpected_fields_rejected() -> None:
    with TestClient(app) as client:
        response = client.post(
            ENDPOINT,
            json={"message": "hello", "priority": "high"},
        )
    assert response.status_code == 422


def test_missing_field_rejected() -> None:
    with TestClient(app) as client:
        response = client.post(ENDPOINT, json={})
    assert response.status_code == 422


def test_non_string_message_rejected() -> None:
    with TestClient(app) as client:
        response = client.post(ENDPOINT, json={"message": 123})
    assert response.status_code == 422


def test_validation_error_does_not_echo_input() -> None:
    marker = "SENTINEL_LEAK_VALUE_B41C"
    with TestClient(app) as client:
        response = client.post(
            ENDPOINT,
            json={"message": "hello", "extra": marker},
        )
    assert response.status_code == 422
    assert marker not in response.text


def test_endpoint_does_not_touch_database(monkeypatch) -> None:
    calls = {"count": 0}
    real = SessionLocal

    def fake_session_local(*args, **kwargs):
        calls["count"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr("rop.database.SessionLocal", fake_session_local)
    response = _post("just checking the wiring")

    assert response.status_code == 200
    assert calls["count"] == 0


def test_existing_health_endpoints_unaffected() -> None:
    with TestClient(app) as client:
        live = client.get("/health")

    assert live.status_code == 200
    assert live.json() == {"status": "healthy"}


def test_readiness_endpoint_shape_unchanged() -> None:
    with TestClient(app) as client:
        ready = client.get("/health/ready")

    # Readiness probes the configured database. Against PostgreSQL it is
    # 200; without a reachable database it is 503. Either way, the body
    # must be the exact shape defined in Task 217.
    assert ready.status_code in (200, 503)
    body = ready.json()
    if ready.status_code == 200:
        assert body == {"status": "ready", "database": "ok"}
    else:
        assert body == {"status": "not_ready", "database": "unavailable"}


def test_sessions_routes_still_registered() -> None:
    """The /sessions routes must remain in the OpenAPI schema.

    We inspect the generated OpenAPI schema rather than app.routes internals,
    because included routers are wrapped and their individual paths are not
    exposed as flat entries. The schema is the developer-facing contract and
    is stable across FastAPI versions.
    """
    paths = set(app.openapi()["paths"].keys())
    assert "/sessions" in paths
    assert "/sessions/{session_id}" in paths
