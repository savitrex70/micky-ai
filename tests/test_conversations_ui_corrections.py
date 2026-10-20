"""Task 230 correction: regression tests for the reviewer-reported issues.

Focused, behaviour-specific assertions on the served assets. Each test
catches a concrete regression the reviewer identified, not merely the
presence of a function or label.
"""

from __future__ import annotations

import json as _json
import shutil as _shutil
import subprocess as _subprocess
from pathlib import Path as _Path

from fastapi.testclient import TestClient

from rop.main import app

# Note: five static-text tests for conversation-UI behaviour were
# removed here after Task 230 correction 2. Each asserted a specific
# string that the corrected implementation intentionally no longer
# emits. Their behaviour is now proven by the executable Node DOM
# scenarios at the bottom of this file (test_*_behavioural), which
# run the real app.js against a DOM/fetch mock and drive actual
# click/submit handlers.


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


# ============================================================================
# Executable behavioural tests via the Node DOM harness
# ============================================================================
#
# These run the real app.js inside a minimal DOM/fetch mock
# (tests/conversations_ui_harness.cjs) and drive actual click/submit
# handlers. They are behaviour tests, not source-text assertions.


def _run_scenario(name: str) -> dict:
    node = _shutil.which("node")
    if node is None:
        import pytest as _pytest

        _pytest.skip("node is not available; behavioural UI tests require it")
    here = _Path(__file__).resolve().parent
    harness = here / "conversations_ui_harness.cjs"
    app_js = here.parent / "src" / "rop" / "web" / "static" / "app.js"
    assert harness.is_file(), f"harness missing: {harness}"
    assert app_js.is_file(), f"app.js missing: {app_js}"
    result = _subprocess.run(
        [node, str(harness), str(app_js), name],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"harness[{name}] failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return _json.loads(result.stdout.strip().splitlines()[-1])


def test_selection_preserved_across_pages() -> None:
    out = _run_scenario("selection-preserved")
    assert out["selectedBeforePage"] == "A"
    assert out["selectedAfterPage"] == "A"
    assert "save" in out["composerMode"].lower()
    assert out["preserved"] is True


def test_http_503_marks_ambiguous_and_blocks_retry() -> None:
    out = _run_scenario("http-503-ambiguous")
    assert out["ambiguous"] is True, "503 must mark the conversation ambiguous"
    assert out["blockedRetry"] is True, "a blind retry must not be allowed"
    body_lower = out["statusText"].lower()
    assert "may or may not" in body_lower or "confirmed" in body_lower


def test_reload_click_clears_ambiguity() -> None:
    out = _run_scenario("reload-click-clears")
    assert out["ambiguousBeforeClick"] is True
    assert out["ambiguousAfterClick"] is False
    assert out["cleared"] is True


def test_reload_failure_keeps_ambiguity() -> None:
    out = _run_scenario("reload-failure-keeps")
    assert out["ambiguous"] is True
    assert out["kept"] is True


def test_refresh_uses_fresh_total_and_loads_last_page() -> None:
    out = _run_scenario("refresh-last-page")
    assert (
        out["usedFreshTotal"] is True
    ), "refresh must query fresh total, not reuse cached"
    assert (
        out["loadedLastPage"] is True
    ), "refresh must land on the page containing the newest messages"


def test_switch_clears_stale_messages_on_fetch_failure() -> None:
    out = _run_scenario("switch-clears-messages")
    assert out["msgsAfterA_containsFromA"] is True
    assert (
        out["msgsAfterB_containsFromA"] is False
    ), "conversation A's messages must not remain visible under B's title"
    assert out["cleared"] is True
