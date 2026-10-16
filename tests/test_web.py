"""Tests for the local Micky AI web interface."""

import re

from fastapi.testclient import TestClient

from rop.main import app

_STATUS_MAP_START = "const STATUS_TEXT = {"

_STATUS_ENTRY = re.compile(
    r'"([a-z0-9-]+)":(.*?)(?=\n\s*"[a-z0-9-]+":|\Z)',
    re.DOTALL,
)

EXPECTED_STATUS_TEXT = {
    "success": "Capability responded",
    "unsupported-capability": "No capability matched",
    "clarification-required": "More detail is needed",
    "confirmation-required": "needs your explicit confirmation",
    "refused": "did not permit this operation",
}


def _status_entries(js: str) -> dict[str, str]:
    """Extract the page's status-to-text map from the served JavaScript."""
    start = js.index(_STATUS_MAP_START)
    block = js[start : js.index("};", start)]
    return {key: value for key, value in _STATUS_ENTRY.findall(block)}


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


def test_page_javascript_distinguishes_success_and_unsupported() -> None:
    """The page's JS must branch on both assistant statuses.

    This is a contract test on the served JS text: the browser must not
    claim a successful execution for an unsupported-capability response,
    and must not describe a success as unexecuted.
    """
    with TestClient(app) as client:
        js = client.get("/static/app.js")

    assert js.status_code == 200
    body = js.text

    # Success branch present and truthful.
    assert '"success"' in body or "'success'" in body
    assert "Capability responded" in body

    # Non-success branch present and truthful.
    assert "No capability matched" in body

    # The old blanket wording must be gone.
    assert "This request was not executed." not in body


def test_page_javascript_maps_every_status_to_its_own_truthful_text() -> None:
    """Every status has its own wording, and every non-success says nothing ran.

    The interface must not display a clarification requirement, a
    confirmation requirement, or a refusal as an unmatched capability or as
    a success.
    """
    with TestClient(app) as client:
        js = client.get("/static/app.js")

    assert js.status_code == 200
    entries = _status_entries(js.text)

    assert set(entries) == set(EXPECTED_STATUS_TEXT)

    for status, fragment in EXPECTED_STATUS_TEXT.items():
        assert fragment in entries[status], status

    # No status may reuse another status's wording.
    assert len(set(entries.values())) == len(entries)

    for status, text in entries.items():
        if status == "success":
            continue
        assert "not executed" in text.lower(), status


def test_page_javascript_renders_replies_without_html_injection() -> None:
    with TestClient(app) as client:
        js = client.get("/static/app.js")

    body = js.text
    assert "innerHTML" not in body
    assert "insertAdjacentHTML" not in body
    assert "textContent" in body
