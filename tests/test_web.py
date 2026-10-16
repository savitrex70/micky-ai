"""Tests for the local Micky AI web interface."""

from fastapi.testclient import TestClient

from rop.main import app


def test_root_serves_micky_ai_interface() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "Micky AI" in body
    assert 'id="request-form"' in body
    assert 'id="message"' in body
    assert 'id="submit"' in body
    assert 'id="history"' in body
    assert 'id="status"' in body
    assert 'aria-live="polite"' in body


def test_root_references_only_local_assets() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    body = response.text
    assert 'href="/static/app.css"' in body
    assert 'src="/static/app.js"' in body

    forbidden = ["http://", "https://", "//cdn", "cdn.", "unpkg", "jsdelivr"]
    for needle in forbidden:
        assert needle not in body, f"page references external resource: {needle}"


def test_static_assets_are_served_locally() -> None:
    with TestClient(app) as client:
        css = client.get("/static/app.css")
        js = client.get("/static/app.js")

    assert css.status_code == 200
    assert "text/css" in css.headers.get("content-type", "")
    assert css.text.strip()

    assert js.status_code == 200
    assert "javascript" in js.headers.get("content-type", "")
    assert js.text.strip()


def test_favicon_returns_204() -> None:
    with TestClient(app) as client:
        response = client.get("/favicon.ico")

    assert response.status_code == 204
    assert response.content == b""


def test_docs_and_openapi_still_available() -> None:
    with TestClient(app) as client:
        docs = client.get("/docs")
        openapi = client.get("/openapi.json")

    assert docs.status_code == 200
    assert openapi.status_code == 200
    spec = openapi.json()
    assert "/health" in spec["paths"]
    assert "/health/ready" in spec["paths"]
    assert "/api/assistant/requests" in spec["paths"]


def test_history_region_announces_new_entries_accessibly() -> None:
    """The response-history list must be an accessible live region.

    We assert the semantics on the actual ``#history`` element, not on the
    separate status paragraph, so that a future change to the status
    paragraph cannot silently strip live-region behaviour from the history
    log.
    """
    with TestClient(app) as client:
        response = client.get("/")

    body = response.text
    assert 'id="history"' in body

    # Extract the <ul id="history" ...> opening tag and everything up to its
    # closing "></ul>" so assertions are scoped to the history element.
    start = body.index('id="history"')
    end = body.index("></ul>", start)
    history_block = body[start:end]

    assert 'role="log"' in history_block
    assert 'aria-live="polite"' in history_block
    assert 'aria-relevant="additions"' in history_block
    assert 'aria-atomic="false"' in history_block
