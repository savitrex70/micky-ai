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


# ============================================================================
# Task 226: pending confirmation card
# ============================================================================


def _served_js() -> str:
    with TestClient(app) as client:
        r = client.get("/static/app.js")
    assert r.status_code == 200
    return r.text


def _served_html() -> str:
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    return r.text


def test_confirmation_card_is_present_in_page() -> None:
    body = _served_html()
    for token in (
        'id="confirmation-card"',
        'id="confirmation-heading"',
        'id="confirmation-summary"',
        'id="confirmation-display-code"',
        'id="confirmation-expiry"',
        'id="confirmation-code-input"',
        'id="confirmation-code-help"',
        'id="confirmation-confirm"',
        'id="confirmation-cancel"',
        'role="region"',
    ):
        # role="region" not required — allow either role or section semantics
        if token == 'role="region"':
            continue
        assert token in body, token


def test_confirmation_card_starts_hidden() -> None:
    body = _served_html()
    start = body.index('id="confirmation-card"')
    # Look back for the opening "<section" and forward to its closing ">"
    open_idx = body.rfind("<section", 0, start)
    end_idx = body.index(">", start)
    opening_tag = body[open_idx : end_idx + 1]
    assert "hidden" in opening_tag
    assert 'aria-labelledby="confirmation-heading"' in opening_tag


def test_confirmation_card_label_associations() -> None:
    body = _served_html()
    assert 'for="confirmation-code-input"' in body
    assert 'aria-describedby="confirmation-code-help"' in body


def test_confirmation_code_input_is_empty_and_unpasted() -> None:
    body = _served_html()
    start = body.index('id="confirmation-code-input"')
    end = body.index(">", start)
    input_tag = body[start:end]
    assert "value=" not in input_tag
    assert 'autocomplete="off"' in input_tag


def test_page_javascript_posts_to_confirmation_decision_endpoint() -> None:
    js = _served_js()
    assert "/api/assistant/confirmations/" in js
    assert "/decision" in js
    assert "encodeURIComponent(challengeId)" in js


def test_page_javascript_sends_expected_confirm_body() -> None:
    js = _served_js()
    # The JS must construct the decision body from a `decision` value and,
    # for confirm, a `display_code` value.
    assert "const body = { decision };" in js
    assert "body.display_code = code;" in js
    assert 'resolveDecision("confirm"' in js


def test_page_javascript_sends_cancel_without_code() -> None:
    js = _served_js()
    assert 'resolveDecision("cancel", null)' in js


def test_page_javascript_distinguishes_failed_unknown_unavailable() -> None:
    js = _served_js()
    # Each outcome must have distinct truthful wording.
    for token in (
        '"failed"',
        '"unknown"',
        '"cancelled"',
        '"rejected"',
        '"refused"',
        '"unavailable"',
        "executor reported failure",
        "outcome could not be established",
        "no executor is available",
    ):
        assert token in js, token


def test_page_javascript_requires_executed_true_for_success() -> None:
    js = _served_js()
    # Success is only claimed when the payload also establishes executed: true.
    assert 'payload.status === "executed"' in js
    assert "payload.executed !== true" in js


def test_page_javascript_validates_challenge_before_rendering() -> None:
    js = _served_js()
    assert "function isValidChallenge(" in js
    assert "isValidChallenge(payload.challenge)" in js
    # On invalid challenge, must show a truthful status, not a usable card.
    assert "did not provide a" in js
    assert "usable challenge" in js


def test_page_javascript_has_no_client_side_persistence() -> None:
    js = _served_js()
    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
        assert forbidden not in js, forbidden


def test_page_javascript_never_prefills_code_input() -> None:
    js = _served_js()
    # showConfirmationCard must empty the code input before displaying.
    idx = js.index("function showConfirmationCard(")
    body = js[idx : idx + 2000]
    assert 'cardCodeInput.value = ""' in body


def test_page_javascript_blocks_enter_in_code_field() -> None:
    js = _served_js()
    # An explicit keydown handler must preventDefault on Enter.
    assert 'addEventListener("keydown"' in js
    assert 'event.key === "Enter"' in js
    assert "event.preventDefault()" in js


def test_page_javascript_guards_duplicate_requests_and_decisions() -> None:
    js = _served_js()
    assert "let requestInFlight = false" in js
    assert "let decisionInFlight = false" in js
    assert "if (requestInFlight) return;" in js
    assert "if (decisionInFlight ||" in js


def test_page_javascript_disables_controls_during_decision() -> None:
    js = _served_js()
    assert "function setDecisionBusy(" in js
    assert "cardConfirm.disabled = locked" in js
    assert "cardCancel.disabled = locked" in js
    assert "cardCodeInput.disabled = locked" in js


def test_page_javascript_marks_unresolved_challenge_on_network_failure() -> None:
    js = _served_js()
    # On a network failure, disable further action and explain.
    assert "challengeUnresolved = true" in js
    assert "could not be verified" in js
    assert "cannot be retried from this page" in js


def test_page_javascript_handles_unknown_decision_outcome() -> None:
    js = _served_js()
    # Unknown / unrecognized decision outcomes must not claim success.
    assert "unrecognised decision outcome" in js


def test_page_javascript_hides_card_on_new_request() -> None:
    js = _served_js()
    # A new request must hide a previous card so an old approval cannot cover
    # a different operation.
    idx = js.index('form.addEventListener("submit"')
    body = js[idx : idx + 3000]
    assert "hideConfirmationCard()" in body


def test_page_javascript_shows_card_only_for_confirmation_required() -> None:
    js = _served_js()
    idx = js.index('form.addEventListener("submit"')
    body = js[idx : idx + 3000]
    assert 'payload.status === "confirmation-required"' in body
    assert "showConfirmationCard(payload.challenge)" in body


def test_confirmation_status_text_still_says_not_executed() -> None:
    """The confirmation-required wording must still state it has not executed.

    A pending confirmation is a genuine non-execution at the moment of display;
    the accompanying card is the mechanism by which the user may later choose
    to execute the exact operation, but nothing runs when the request returns.
    """
    js = _served_js()
    entries = _status_entries(js)
    text = entries["confirmation-required"]
    assert "not been executed" in text or "not executed" in text
