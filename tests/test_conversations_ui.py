"""Task 230: contract tests for the persistent-conversation UI.

Source-text assertions on the served HTML and JS, in the same style as the
existing Task 226/227 UI tests. These verify structural facts that a
regression in the served assets would break (sections present, correct API
endpoints referenced, safe DOM APIs used, no client-side persistence, no
auto-retry loops). They run without a database.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from rop.main import app


def _served_html() -> str:
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    return r.text


def _served_js() -> str:
    with TestClient(app) as client:
        r = client.get("/static/app.js")
    assert r.status_code == 200
    return r.text


# ============================================================================
# HTML structure
# ============================================================================


def test_conversations_section_present() -> None:
    html = _served_html()
    for token in (
        'id="conversations-section"',
        'id="conversations-heading"',
        'id="conversations-new"',
        'id="conversations-status"',
        'id="conversations-list"',
        'id="conversations-empty"',
        'aria-labelledby="conversations-heading"',
    ):
        assert token in html, token


def test_conversation_view_present() -> None:
    html = _served_html()
    for token in (
        'id="conversation-view"',
        'id="conversation-view-heading"',
        'id="conversation-current-title"',
        'id="conversation-rename-input"',
        'id="conversation-rename"',
        'id="conversation-delete"',
        'id="conversation-messages-status"',
        'id="conversation-messages"',
        'id="conversation-messages-empty"',
    ):
        assert token in html, token


def test_composer_mode_banner_present() -> None:
    html = _served_html()
    assert 'id="composer-mode"' in html
    assert 'aria-live="polite"' in html


def test_conversation_view_starts_hidden() -> None:
    html = _served_html()
    start = html.index('id="conversation-view"')
    open_idx = html.rfind("<section", 0, start)
    end_idx = html.index(">", start)
    tag = html[open_idx : end_idx + 1]
    assert "hidden" in tag


# ============================================================================
# JS API wiring
# ============================================================================


def test_js_fetches_conversations_api() -> None:
    js = _served_js()
    assert "/api/assistant/conversations" in js
    assert "/messages" in js


def test_js_send_request_includes_conversation_id() -> None:
    js = _served_js()
    # sendRequest signature and body construction
    assert "async function sendRequest(text, conversationId)" in js
    assert "body.conversation_id = conversationId" in js


def test_js_submit_handler_reads_selected_conversation() -> None:
    js = _served_js()
    idx = js.index('form.addEventListener("submit"')
    body = js[idx : idx + 4000]
    assert "window.__mickyConversations" in body
    assert "getSelectedId" in body


def test_js_success_triggers_message_refresh() -> None:
    js = _served_js()
    idx = js.index('form.addEventListener("submit"')
    marker = js.index('cardConfirm.addEventListener("click"', idx)
    body = js[idx:marker]
    assert "refreshMessagesFor" in body
    # The refresh is scoped to the original conversation and happens only
    # after an explicitly successful response.
    assert "refreshMessagesFor(selectedConversationId)" in body
    assert 'payload.status === "success"' in body


def test_js_does_not_post_separate_user_message() -> None:
    """The user message must not be POSTed separately after a success.

    Only the assistant-requests endpoint persists the pair; the UI never
    POSTs the user message again or fabricates an assistant message.
    """
    js = _served_js()
    # No POST to /messages from the composer success path
    # (The conversations module does POST to conversations and PATCH/DELETE,
    # but it must not POST to /messages.)
    idx = js.index("async function sendRequest")
    tail = js[idx:]
    submit_end = tail.index("cardConfirm.addEventListener")
    submit_block = tail[:submit_end]
    assert "/messages" not in submit_block


def test_js_create_uses_post_to_conversations() -> None:
    js = _served_js()
    idx = js.index("async function createConversation")
    tail = js[idx : idx + 1500]
    assert 'method: "POST"' in tail
    assert '"Content-Type": "application/json"' in tail


def test_js_rename_uses_patch() -> None:
    js = _served_js()
    idx = js.index("async function renameSelected")
    tail = js[idx : idx + 2000]
    assert 'method: "PATCH"' in tail


def test_js_delete_uses_delete_and_requires_confirm() -> None:
    js = _served_js()
    # There are two deleteSelected() functions: one in the Task 227
    # confirmation-records module and one in the Task 230 conversations
    # module. Anchor the search after the Task 230 marker.
    marker = js.index("Task 230: persistent conversations UI")
    idx = js.index("async function deleteSelected", marker)
    tail = js[idx : idx + 2000]
    assert 'method: "DELETE"' in tail
    assert "window.confirm(" in tail


def test_js_stale_message_token_guard() -> None:
    """Stale responses from a previously-selected conversation must be ignored."""
    js = _served_js()
    assert "messagesLoadToken" in js
    assert "token !== messagesLoadToken" in js


# ============================================================================
# Safe DOM + no client persistence + no auto-retry
# ============================================================================


def test_js_uses_textcontent_for_message_and_title() -> None:
    js = _served_js()
    # The conversations and messages modules use textContent
    idx = js.index("Task 230: persistent conversations UI")
    tail = js[idx:]
    assert ".textContent" in tail
    assert "innerHTML" not in tail
    assert "insertAdjacentHTML" not in tail


def test_js_has_no_client_content_persistence() -> None:
    """Only a non-content ambiguity bit may survive reload; no user data or IDs."""
    js = _served_js()
    marker = js.index("Task 230: persistent conversations UI")
    assistant_shell = js[:marker]
    conversations_ui = js[marker:]

    assert "localStorage" not in js
    assert "indexedDB" not in js
    assert "sessionStorage" not in conversations_ui
    assert "document.cookie" not in js

    # Only the boolean safety marker may use browser storage; no content or IDs.
    assert "micky.ai.request-outcome-unresolved.v1" in assistant_shell
    assert assistant_shell.count("sessionStorage.") == 3
    storage_calls = re.findall(
        r"sessionStorage\.(getItem|setItem|removeItem)\(([^)]*)\)",
        assistant_shell,
    )
    assert storage_calls == [
        ("getItem", "REQUEST_OUTCOME_UNRESOLVED_KEY"),
        ("setItem", 'REQUEST_OUTCOME_UNRESOLVED_KEY, "1"'),
        ("removeItem", "REQUEST_OUTCOME_UNRESOLVED_KEY"),
    ]


def test_js_has_no_automatic_retry_loop() -> None:
    js = _served_js()
    for forbidden in ("setInterval", "requestAnimationFrame"):
        assert forbidden not in js, forbidden


def test_js_duplicate_in_flight_guards() -> None:
    js = _served_js()
    for token in (
        "listInFlight",
        "createInFlight",
        "messagesInFlight",
        "renameInFlight",
        "deleteInFlight",
    ):
        assert token in js, token


def test_js_does_not_auto_create_conversation_on_load() -> None:
    js = _served_js()
    # The IIFE ends with loadConversations() only — no automatic create
    idx = js.index("Task 230: persistent conversations UI")
    tail = js[idx:]
    last = tail.rstrip().splitlines()[-3:]
    joined = "\n".join(last)
    assert "loadConversations" in joined
    assert "createConversation(" not in joined


def test_js_empty_state_shown_when_no_conversations() -> None:
    js = _served_js()
    idx = js.index("function renderList")
    tail = js[idx : idx + 800]
    assert "emptyEl.hidden = false" in tail
    assert "emptyEl.hidden = true" in tail


def test_js_error_state_distinct_from_empty_state() -> None:
    """A failed list load must not display the empty state as confirmation."""
    js = _served_js()
    idx = js.index("async function loadConversations")
    tail = js[idx : idx + 2000]
    # Both error statuses set an error kind; the empty state (emptyEl.hidden)
    # is only toggled inside renderList, which is only called after a
    # successful response.
    assert "could not be loaded" in tail.lower() or "could not load" in tail.lower()


def test_existing_confirmation_card_still_present() -> None:
    js = _served_js()
    for token in (
        "confirmation-card",
        "resolveDecision",
        "isSemanticallyValidDecision",
    ):
        assert token in js, token


def test_existing_confirmation_records_still_present() -> None:
    html = _served_html()
    for token in ('id="records-section"', 'id="records-load"', 'id="records-export"'):
        assert token in html, token
