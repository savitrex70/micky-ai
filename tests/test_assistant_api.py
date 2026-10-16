"""Tests for the capability-routed assistant request endpoint."""

import pytest
from fastapi.testclient import TestClient

from rop.capabilities.registry import HELP_RESPONSE
from rop.database import SessionLocal
from rop.main import app

ENDPOINT = "/api/assistant/requests"
UNSUPPORTED_MESSAGE = (
    "No matching capability is currently available. "
    "This request was not executed and was not saved."
)

HELP_ALIASES = (
    "help",
    "what can you do",
    "show capabilities",
    "list capabilities",
    "list available capabilities",
)


def _post(message: str):
    with TestClient(app) as client:
        return client.post(ENDPOINT, json={"message": message})


@pytest.mark.parametrize("alias", HELP_ALIASES)
def test_help_alias_returns_success_envelope(alias: str) -> None:
    response = _post(alias)

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "success", "message": HELP_RESPONSE}


@pytest.mark.parametrize(
    "message",
    [
        "HELP",
        "  help  ",
        "Help.",
        "help!",
        "what can you do?",
        "What can you do",
        "  LIST  AVAILABLE  CAPABILITIES  ",
    ],
)
def test_help_aliases_normalize_in_endpoint(message: str) -> None:
    response = _post(message)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["message"] == HELP_RESPONSE


@pytest.mark.parametrize(
    "message",
    [
        "help me create a reminder",
        "what can you do and save a note",
        "help me",
        "please help",
        "capabilities",
    ],
)
def test_unregistered_phrases_return_unsupported(message: str) -> None:
    response = _post(message)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "unsupported-capability",
        "message": UNSUPPORTED_MESSAGE,
    }


def test_ordinary_request_remains_unsupported() -> None:
    response = _post("What is the weather today?")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unsupported-capability"


def test_extended_help_phrase_does_not_match_or_leak_sentinel() -> None:
    marker = "SENTINEL_9F2A_HELP"
    # "help <marker>" is not an exact alias, so it must NOT match Help.
    # It falls through to unsupported-capability, and the sentinel must
    # not appear anywhere in the response.
    response = _post(f"help {marker}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unsupported-capability"
    assert marker not in response.text


def test_unsupported_response_does_not_echo_user_message() -> None:
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
            json={"message": "help", "priority": "high"},
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
            json={"message": "help", "extra": marker},
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

    help_response = _post("help")
    unsupported_response = _post("what is the weather today")

    assert help_response.status_code == 200
    assert unsupported_response.status_code == 200
    assert calls["count"] == 0


def test_existing_health_endpoints_unaffected() -> None:
    with TestClient(app) as client:
        live = client.get("/health")

    assert live.status_code == 200
    assert live.json() == {"status": "healthy"}


def test_readiness_endpoint_shape_unchanged() -> None:
    with TestClient(app) as client:
        ready = client.get("/health/ready")

    assert ready.status_code in (200, 503)
    body = ready.json()
    if ready.status_code == 200:
        assert body == {"status": "ready", "database": "ok"}
    else:
        assert body == {"status": "not_ready", "database": "unavailable"}


def test_sessions_routes_still_registered() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/sessions" in paths
    assert "/sessions/{session_id}" in paths
