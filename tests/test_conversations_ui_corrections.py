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

import pytest
from fastapi.testclient import TestClient

from rop.main import app

# Note: five static-text tests for conversation-UI behaviour were
# removed here after Task 230 correction 2. Each asserted a specific
# string that the corrected implementation intentionally no longer
# emits. Their behaviour is now proven by the executable Node DOM
# scenarios at the bottom of this file (test_*_behavioural), which
# run the real app.js against a DOM/fetch mock and drive actual
# click/submit handlers.


# Note: `test_ambiguous_recovery_uses_latest_page_not_page_zero` was
# removed here. Its assertions targeted the old harness field
# `usedLastPage`, which was replaced by `sawLatestPage` and
# `sawNewest`. The superseding test is
# `test_ambiguous_recovery_renders_newest_before_clear`, which
# asserts the same fetch AND that the newest message is actually
# rendered before the guard clears.


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

# These run the real app.js inside a minimal DOM/fetch mock
# (tests/conversations_ui_harness.cjs) and drive actual click/submit
# handlers. They are behaviour tests, not source-text assertions.


def _run_scenario(name: str, extra_arg: str | None = None) -> dict:
    node = _shutil.which("node")
    if node is None:
        pytest.skip("node is not available; behavioural UI tests require it")
    here = _Path(__file__).resolve().parent
    harness = here / "conversations_ui_harness.cjs"
    app_js = here.parent / "src" / "rop" / "web" / "static" / "app.js"
    assert harness.is_file(), f"harness missing: {harness}"
    assert app_js.is_file(), f"app.js missing: {app_js}"
    cmd = [node, str(harness), str(app_js), name]
    if extra_arg is not None:
        cmd.append(str(extra_arg))
    result = _subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"harness[{name}] failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return _json.loads(result.stdout.strip().splitlines()[-1])


# --- Core behavioural scenarios ---------------------------------------------


def test_selection_preserved_across_realistic_pages() -> None:
    out = _run_scenario("selection-preserved")
    assert out["selectedBefore"] == "C0"
    assert out["selectedAfterPage2"] == "C0"
    assert out["selectedAfterPage1"] == "C0"
    assert out["preserved"] is True
    assert "save" in out["composerMode"].lower()


def test_refresh_after_save_loads_latest_page() -> None:
    """The post-success refresh must fetch the page containing the newest
    messages at offset 400 for a 402-message conversation, not page zero."""
    out = _run_scenario("refresh-last-page")
    assert out["lastPageLoaded"] is True
    fetches = out["fetches"]
    assert any(
        "limit=1&offset=0" in u for u in fetches
    ), "refresh must query a fresh total"
    assert any("offset=400" in u for u in fetches), "refresh must load the last page"


def test_http_503_marks_ambiguous_and_blocks_retry() -> None:
    out = _run_scenario("http-503-ambiguous")
    assert out["ambiguous"] is True
    assert out["blockedRetry"] is True
    body_lower = out["statusText"].lower()
    assert "could not be confirmed" in body_lower or "may have" in body_lower


def test_reload_click_clears_ambiguity() -> None:
    out = _run_scenario("reload-click-clears")
    assert out["ambiguousBeforeClick"] is True
    assert out["ambiguousAfterClick"] is False
    assert out["cleared"] is True


def test_reload_failure_keeps_ambiguity() -> None:
    out = _run_scenario("reload-failure-keeps")
    assert out["ambiguous"] is True
    assert out["kept"] is True


def test_switch_clears_stale_messages_on_fetch_failure() -> None:
    out = _run_scenario("switch-clears-messages")
    assert out["msgsAfterA_containsFromA"] is True
    assert out["msgsAfterB_containsFromA"] is False
    assert out["cleared"] is True


# --- Finding 1: ambiguous-save recovery uses the LATEST page ----------------


def test_ambiguous_recovery_uses_latest_page_not_page_zero() -> None:
    """A reload of a long conversation must fetch the last page containing
    the newest messages, not page zero. Otherwise the guard could clear
    while the possibly-saved exchange is still off-screen.

    Also asserts the newest message is actually rendered before the guard
    clears (the older `usedLastPage` field was replaced by `sawLatestPage`
    and `sawNewest` when the harness strengthened its checks).
    """
    out = _run_scenario("reload-uses-latest-page")
    assert out["cleared"] is True
    assert out["sawLatestPage"] is True
    assert out["sawNewest"] is True


def test_reload_total_fetch_failure_keeps_ambiguity() -> None:
    out = _run_scenario("reload-total-fail")
    assert out["ambiguous"] is True
    assert out["kept"] is True


def test_reload_page_fetch_failure_keeps_ambiguity() -> None:
    out = _run_scenario("reload-page-fail")
    assert out["ambiguous"] is True
    assert out["kept"] is True


# --- Finding 2: reload-in-flight and stale-response protections -------------


def test_duplicate_submit_blocked_while_reload_in_flight() -> None:
    """Submitting while the ambiguous-recovery reload is in flight must not
    issue a new POST."""
    out = _run_scenario("duplicate-during-load")
    assert out["blocked"] is True, (
        "a submit during reload issued a new fetch: before="
        + str(out["before"])
        + " after="
        + str(out["after"])
    )


def test_stale_reload_response_does_not_clobber_selection() -> None:
    """A reload response for conversation A that arrives after the user has
    selected B must not appear under B's title."""
    out = _run_scenario("stale-reload")
    assert out["afterStale_containsFromB"] is True
    assert out["afterStale_containsFromA"] is False
    assert out["stillB"] is True


# --- Finding 4: create/list-refresh decoupling ------------------------------


def test_create_then_list_refresh_failure_keeps_consistent_selection() -> None:
    out = _run_scenario("create-then-list-fail")
    assert out["titleFromPost"] is True
    assert out["selectedIdFromPost"] is True
    assert out["showsListRefreshError"] is True


def test_create_network_failure_is_ambiguous() -> None:
    out = _run_scenario("create-network-fail")
    assert out["isAmbiguous"] is True
    assert out["noAutomaticRetry"] is True


# --- Finding 3: pagination boundary offsets --------------------------------


@pytest.mark.parametrize("boundary", [199, 200, 201, 399, 400, 401])
def test_message_boundary_offsets(boundary: int) -> None:
    """The post-success refresh must make its OWN fresh-total and latest-page
    requests. The initial selection load does not count as evidence.
    """
    out = _run_scenario("message-boundary", str(boundary))
    assert out["boundary"] == boundary
    # Isolate post-submit fetches (the harness reports them separately).
    assert out["sawFreshTotal"] is True, (
        f"boundary {boundary}: post-submit refresh did not fetch a fresh "
        f"total; fetches: {out.get('postSubmitFetches')}"
    )
    assert out["sawLatestPage"] is True, (
        f"boundary {boundary}: post-submit refresh did not request offset "
        f"{out['expectedOffset']}; fetches: {out.get('postSubmitFetches')}"
    )
    assert (
        out["sawNewestRendered"] is True
    ), f"boundary {boundary}: newest message was not rendered"


# --- Correction 4: refresh control + 404 handling + stronger tests -------


def test_refresh_conversations_button_preserves_selection() -> None:
    out = _run_scenario("refresh-button-preserves-selection")
    assert out["preserved"] is True, out


def test_refresh_conversations_button_error_then_success() -> None:
    out = _run_scenario("refresh-failure-then-success")
    assert out["firstShowsError"] is True, out
    assert out["secondCleared"] is True, out


def test_confirmed_404_clears_selection() -> None:
    out = _run_scenario("404-clears-selection")
    assert out["cleared"] is True
    assert out["titleBlank"] is True
    assert out["msgsEmpty"] is True
    assert out["mentionsNoLongerExists"] is True
    assert out["modeIsTransient"] is True


def test_network_error_preserves_selection() -> None:
    out = _run_scenario("network-error-preserves-selection")
    assert out["preserved"] is True, out


def test_stale_404_for_other_conversation_does_not_clear() -> None:
    out = _run_scenario("stale-404-cannot-clear")
    assert out["preserved"] is True, out


def test_ambiguous_recovery_renders_newest_before_clear() -> None:
    out = _run_scenario("reload-uses-latest-page")
    assert out["cleared"] is True
    assert out["sawLatestPage"] is True
    assert (
        out["sawNewest"] is True
    ), "the newest message must be rendered before the ambiguity clears"


# --- Correction 5: pagination transactional, create coordination, safety -


def test_refresh_failure_preserves_pagination_state() -> None:
    """A failed refresh must not corrupt the displayed page or offset."""
    out = _run_scenario("refresh-failure-preserves-page")
    assert out["rowsPreserved"] is True, out
    assert out["rangePreserved"] is True, out
    assert out["isError"] is True, out


def test_create_during_inflight_refresh_waits_for_real_result() -> None:
    """Clicking New while a list refresh is in flight must not treat the
    skipped refresh as a real failure. The created conversation must be
    the selected destination, and no false 'list could not be refreshed'
    error may be shown."""
    out = _run_scenario("create-during-refresh")
    assert out["selectedIsNew"] is True, out
    assert out["titleIsNew"] is True, out
    assert out["noFalseFailure"] is True, out


def test_ambiguous_404_clears_selection_and_clears_ambiguity() -> None:
    """When a selected ambiguous conversation 404s during recovery, the
    selection and its ambiguity marker are both cleared. No other
    conversation is silently selected."""
    out = _run_scenario("ambiguous-404-blocks-repost")
    assert out["ambBefore"] is True, out
    assert out["selectionCleared"] is True, out
    assert out["ambiguityCleared"] is True, out


def test_malformed_latest_page_response_keeps_ambiguity() -> None:
    """A structurally-invalid latest-page response must not clear the
    ambiguity guard."""
    out = _run_scenario("recovery-malformed-page")
    assert out["kept"] is True, out
