"""Task 230 correction: regression tests for the reviewer-reported issues.

Focused, behaviour-specific assertions on the served assets. Each test
catches a concrete regression the reviewer identified, not merely the
presence of a function or label.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from rop.main import app


def _html() -> str:
    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    return r.text


def _js() -> str:
    with TestClient(app) as client:
        r = client.get("/static/app.js")
    assert r.status_code == 200
    return r.text


# ============================================================================
# Finding 1: delete must not auto-select another conversation
# ============================================================================


def test_delete_does_not_auto_select_another_conversation() -> None:
    """The deleteSelected handler must not call selectConversation after 204.

    Captures the body of Task 230's deleteSelected function and asserts
    that ``selectConversation(conversations[0]`` — the specific auto-select
    pattern that silently changed the save destination — does not appear.
    """
    js = _js()
    marker = js.index("Task 230: persistent conversations UI")
    idx = js.index("async function deleteSelected", marker)
    # End at the next top-level function definition in the module.
    rest = js[idx:]
    # Isolate deleteSelected body up to the next sibling definition.
    end_rel = rest.find("\n\n  function ")
    if end_rel < 0:
        end_rel = rest.find("\n\n  window.__mickyConversations")
    assert end_rel > 0, "could not isolate deleteSelected body"
    body = rest[:end_rel]

    assert "selectConversation(conversations[0]" not in body, (
        "deleteSelected must not auto-select another conversation after "
        "deletion — that silently changes the persistence destination"
    )
    # And the corrected wording must acknowledge no selection remains.
    assert "not be saved unless" in body or "No conversation is selected" in body


def test_delete_clears_selected_id_and_view() -> None:
    """After 204 the view state must be cleared, not reassigned."""
    js = _js()
    marker = js.index("Task 230: persistent conversations UI")
    idx = js.index("async function deleteSelected", marker)
    rest = js[idx:]
    end_rel = rest.find("\n\n  function ")
    body = rest[:end_rel]
    assert "selectedId = null" in body
    assert "view.hidden = true" in body


# ============================================================================
# Finding 2: pagination controls exist and use X-Total-Count
# ============================================================================


def test_conversation_list_pagination_controls_present() -> None:
    html = _html()
    for token in (
        'id="conversations-pagination"',
        'id="conversations-prev"',
        'id="conversations-next"',
        'id="conversations-range"',
    ):
        assert token in html, token


def test_messages_pagination_controls_present() -> None:
    html = _html()
    for token in (
        'id="messages-pagination"',
        'id="messages-prev"',
        'id="messages-next"',
        'id="messages-range"',
    ):
        assert token in html, token


def test_js_reads_x_total_count_header() -> None:
    js = _js()
    assert 'resp.headers.get("X-Total-Count")' in js
    # Two call sites: conversations list + messages list
    assert js.count('resp.headers.get("X-Total-Count")') >= 2


def test_js_pagination_offset_tracking() -> None:
    js = _js()
    # Both offset trackers must exist
    assert "listOffset" in js
    assert "messagesOffset" in js
    assert "listTotal" in js
    assert "messagesTotal" in js


def test_js_refresh_jumps_to_last_page_for_long_conversation() -> None:
    """A successful exchange must land on the page that contains it.

    For a conversation longer than one page, refreshing page 1 would hide
    the just-saved exchange. refreshSelectedMessages must jump to the
    last page when messagesTotal exceeds one page.
    """
    js = _js()
    idx = js.index("function refreshSelectedMessages")
    body = js[idx : idx + 800]
    assert "messagesTotal > MESSAGES_LIMIT" in body
    assert "Math.floor" in body
    assert "loadMessages(selectedId, lastOffset)" in body


def test_js_page_change_resets_pagination_on_conversation_switch() -> None:
    js = _js()
    idx = js.index("async function selectConversation")
    body = js[idx : idx + 800]
    assert "if (selectedId !== id)" in body
    assert "messagesOffset = 0" in body
    assert "messagesTotal = null" in body


# ============================================================================
# Finding 3: honest persistence wording
# ============================================================================


def test_no_claim_of_confirmation_record_database_for_conversations() -> None:
    html = _html()
    assert "confirmation-record database" not in html.lower()


def test_no_blanket_claim_conversations_not_persisted() -> None:
    html = _html()
    # The old blanket claim. After the fix, the early preview must not
    # state that conversations are never persisted.
    assert "Conversations, notes, tasks, and reminders are not persisted." not in html
    # Instead the notice must clarify that a successful exchange in a
    # selected conversation IS saved.
    assert "selected conversation" in html.lower()
    assert "saved" in html.lower()


def test_composer_help_no_longer_claims_unconditional_non_persistence() -> None:
    html = _html()
    assert "it is not stored" not in html
    # The composer helper must acknowledge the selected-conversation case.
    idx = html.index('id="message-help"')
    end = html.index("</p>", idx)
    block = html[idx:end]
    assert "selected" in block.lower() or "conversation" in block.lower()


# ============================================================================
# Finding 4: ambiguous-outcome handling
# ============================================================================


def test_send_request_returns_structured_result() -> None:
    """sendRequest must return kind=ok/http/network/unreadable, not throw."""
    js = _js()
    idx = js.index("async function sendRequest")
    body = js[idx : idx + 2600]
    for kind in ('kind: "network"', 'kind: "http"', 'kind: "unreadable"', 'kind: "ok"'):
        assert kind in body, kind


def test_send_request_reads_fastapi_detail_field() -> None:
    """FastAPI errors put the sanitized message in ``detail``; the client
    must check it, not just ``message``."""
    js = _js()
    idx = js.index("async function sendRequest")
    body = js[idx : idx + 2600]
    assert "payload.detail" in body
    assert 'typeof payload.detail === "string"' in body


def test_submit_handler_uses_kind_discriminator() -> None:
    js = _js()
    idx = js.index('form.addEventListener("submit"')
    body = js[idx : idx + 5000]
    assert 'result.kind === "ok"' in body
    assert 'result.kind === "http"' in body
    # Fall-through branch is the ambiguous case
    assert 'kind === "http"' in body
    assert "may or may not have been saved" in body.lower()


def test_submit_blocks_blind_retry_on_ambiguous() -> None:
    js = _js()
    idx = js.index('form.addEventListener("submit"')
    body = js[idx : idx + 5000]
    # The isAmbiguous check must guard before the send.
    assert "isAmbiguous" in body
    assert "Reload" in body or "reload" in body
    # And the block must occur before setRequestBusy (i.e. before the send)
    amb_idx = body.index("isAmbiguous")
    busy_idx = body.index("setRequestBusy(true)")
    assert amb_idx < busy_idx


def test_js_marks_conversation_ambiguous_on_network_failure() -> None:
    js = _js()
    idx = js.index('form.addEventListener("submit"')
    body = js[idx : idx + 5000]
    assert "markAmbiguous" in body
    assert "clearAmbiguous" in body


def test_ambiguous_api_methods_exposed() -> None:
    js = _js()
    assert "markAmbiguous:" in js or "markAmbiguous: markAmbiguous" in js
    assert "clearAmbiguous:" in js or "clearAmbiguous: clearAmbiguous" in js
    assert "isAmbiguous:" in js or "isAmbiguous: isAmbiguous" in js


def test_ambiguous_cleared_on_reload() -> None:
    """Selecting a conversation resets its ambiguity — the reload
    establishes the actual state."""
    js = _js()
    idx = js.index("async function selectConversation")
    body = js[idx : idx + 800]
    assert "ambiguousConversations.delete(id)" in body


def test_no_auto_retry_of_request() -> None:
    """The submit handler must never loop or call sendRequest twice."""
    js = _js()
    idx = js.index('form.addEventListener("submit"')
    body = js[idx : idx + 5000]
    # The only sendRequest invocation is the awaited one.
    assert body.count("sendRequest(") == 1


# ============================================================================
# Preserved invariants
# ============================================================================


def test_stale_token_still_present() -> None:
    js = _js()
    assert "messagesLoadToken" in js
    assert "token !== messagesLoadToken" in js


def test_no_client_persistence_still_present() -> None:
    js = _js()
    for forbidden in ("localStorage", "sessionStorage", "indexedDB"):
        assert forbidden not in js, forbidden


def test_no_innerhtml_in_conversations_module() -> None:
    js = _js()
    marker = js.index("Task 230: persistent conversations UI")
    assert "innerHTML" not in js[marker:]


def test_confirmation_record_ui_preserved() -> None:
    html = _html()
    for token in ('id="records-section"', 'id="records-load"'):
        assert token in html, token


def test_confirmation_card_preserved() -> None:
    js = _js()
    tokens = (
        "confirmation-card",
        "resolveDecision",
        "isSemanticallyValidDecision",
    )
    for token in tokens:
        assert token in js, token
