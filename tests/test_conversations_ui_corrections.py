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


def test_no_client_content_persistence_except_boolean_request_guard() -> None:
    """Only a non-content ambiguity bit may survive reload; no user data or IDs."""
    js = _js()
    marker = js.index("Task 230: persistent conversations UI")
    assistant_shell = js[:marker]
    conversations_ui = js[marker:]

    assert "localStorage" not in js
    assert "indexedDB" not in js
    assert "sessionStorage" not in conversations_ui
    assert "micky.ai.request-outcome-unresolved.v1" in assistant_shell
    assert 'setItem(REQUEST_OUTCOME_UNRESOLVED_KEY, "1")' in assistant_shell
    assert (
        "setItem(REQUEST_OUTCOME_UNRESOLVED_KEY, selectedConversationId)"
        not in assistant_shell
    )
    assert "setItem(REQUEST_OUTCOME_UNRESOLVED_KEY, text)" not in assistant_shell


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
    """Selection survives navigating between realistic list pages.

    Compares the selected ID against itself across the page changes rather
    than against a fixed literal — the harness fixture now produces UUIDs,
    and the preservation property is that the ID is unchanged, not that it
    equals a specific string.
    """
    out = _run_scenario("selection-preserved")
    before = out["selectedBefore"]
    assert before, "no conversation was selected initially"
    assert out["selectedAfterPage2"] == before
    assert out["selectedAfterPage1"] == before
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


# --- Correction 6: list serialization + strict message validation + 404
#     submission body assertion -----------------------------------------


def test_list_requests_serialize_while_loading() -> None:
    """Multiple refresh clicks while a request is in flight must produce
    one request at a time, not overlapping requests."""
    out = _run_scenario("list-serialization")
    assert out["oneAtATime"] is True, out
    assert out["fetchesWhilePending"] == 1, out
    assert out["fetchesAfterFirst"] == 2, out
    assert out["fetchesAfterSecond"] == 3, out
    assert out["fetchesFinal"] == 3, out


def test_ambiguous_404_post_is_transient_no_conversation_id() -> None:
    """After a confirmed 404 clears the selection, the next submission must
    be sent WITHOUT conversation_id, proving no other conversation was
    silently selected."""
    out = _run_scenario("ambiguous-404-blocks-repost")
    assert out["selectionCleared"] is True
    assert out["ambiguityCleared"] is True
    assert out["postCount"] == 1, out
    assert out["hasConversationId"] is False, out
    assert out["submissionIsTransient"] is True, out
    assert "conversation_id" not in (out["postBody"] or {})


def test_recovery_malformed_records_keeps_ambiguity() -> None:
    out = _run_scenario("recovery-malformed-records")
    assert out["kept"] is True, out


def test_recovery_missing_total_keeps_ambiguity() -> None:
    out = _run_scenario("recovery-missing-total")
    assert out["kept"] is True, out


def test_recovery_invalid_total_keeps_ambiguity() -> None:
    out = _run_scenario("recovery-invalid-total")
    assert out["kept"] is True, out


def test_recovery_empty_page_inconsistent_with_total_keeps_ambiguity() -> None:
    out = _run_scenario("recovery-empty-inconsistent")
    assert out["kept"] is True, out


def test_recovery_empty_legitimate_clears_ambiguity() -> None:
    """A genuinely empty conversation (total 0, empty page) must recover
    successfully."""
    out = _run_scenario("recovery-empty-legitimate")
    assert out["ambBefore"] is True
    assert out["cleared"] is True


# --- Correction 7: full API schema validation --------------------------


def test_recovery_invalid_message_uuid_keeps_ambiguity() -> None:
    """A record with a non-UUID id must be rejected; ambiguity stays set."""
    out = _run_scenario("recovery-invalid-message-uuid")
    assert out["kept"] is True, out


def test_recovery_invalid_timestamp_keeps_ambiguity() -> None:
    """A record with a non-ISO created_at must be rejected; ambiguity stays
    set."""
    out = _run_scenario("recovery-invalid-timestamp")
    assert out["kept"] is True, out


def test_recovery_fractional_fresh_total_keeps_ambiguity() -> None:
    """A fractional fresh-total header (e.g. 400.5) must not be accepted and
    must not be used to compute the target offset."""
    out = _run_scenario("recovery-fractional-fresh-total")
    assert out["kept"] is True, out


def test_refresh_malformed_record_preserves_state() -> None:
    """A list response containing a malformed conversation record must not
    overwrite committed pagination state."""
    out = _run_scenario("refresh-malformed-record")
    assert out["rowsPreserved"] is True, out
    assert out["rangePreserved"] is True, out
    assert out["isError"] is True, out


def test_refresh_invalid_list_total_preserves_state() -> None:
    """A list response with a fractional X-Total-Count must not commit any
    new state."""
    out = _run_scenario("refresh-invalid-list-total")
    assert out["rowsPreserved"] is True, out
    assert out["isError"] is True, out


def test_refresh_malformed_then_valid_recovers() -> None:
    """A malformed refresh followed by a valid refresh succeeds cleanly."""
    out = _run_scenario("refresh-malformed-then-valid")
    assert out["failed"] is True, out
    assert out["recovered"] is True, out


# ---- Correction 8: strict datetime and 201-to-200 race recovery ----


def test_recovery_impossible_calendar_date_keeps_ambiguity() -> None:
    """2026-02-31T00:00:00Z is an impossible calendar date; JavaScript
    would normalize it via Date.parse, so a component validator must
    reject it and keep ambiguity set."""
    out = _run_scenario("recovery-impossible-date")
    assert out["kept"] is True, out


def test_recovery_invalid_timezone_offset_keeps_ambiguity() -> None:
    """An offset like +99:00 is not a real timezone; the record must be
    rejected and ambiguity kept."""
    out = _run_scenario("recovery-invalid-offset")
    assert out["kept"] is True, out


def test_recovery_valid_timezone_offset_clears_ambiguity() -> None:
    """A valid +05:30 offset timestamp must be accepted and recovery may
    complete."""
    out = _run_scenario("recovery-valid-offset")
    assert out["ambBefore"] is True, out
    assert out["cleared"] is True, out


def test_recovery_message_for_other_conversation_keeps_ambiguity() -> None:
    """A syntactically valid UUID belonging to a different conversation
    must be rejected for the selected conversation."""
    out = _run_scenario("recovery-wrong-conversation")
    assert out["kept"] is True, out


def test_refresh_missing_list_total_preserves_state() -> None:
    """A conversation-list response without an X-Total-Count header must
    not overwrite committed state and must show a distinct error."""
    out = _run_scenario("recovery-missing-list-total")
    assert out["rowsPreserved"] is True, out
    assert out["rangePreserved"] is True, out
    assert out["selectionPreserved"] is True, out
    assert out["statusKind"] == "error", out
    assert "total" in out["statusText"].lower(), out


def test_refresh_impossible_date_in_list_preserves_state() -> None:
    """A conversation-list record with an impossible calendar date must
    not overwrite committed state and must show a distinct error."""
    out = _run_scenario("recovery-impossible-date-in-list")
    assert out["rowsPreserved"] is True, out
    assert out["rangePreserved"] is True, out
    assert out["selectionPreserved"] is True, out
    assert out["statusKind"] == "error", out
    assert "malformed" in out["statusText"].lower(), out


def test_recovery_201_to_200_race_retries_and_clears() -> None:
    """When fresh total (201) no longer matches the latest-page response
    (200, empty at offset 200), the empty page must not be accepted as
    history. A bounded retry against the fresh authoritative total must
    occur and clear ambiguity only after a valid current page renders."""
    out = _run_scenario("recovery-201-to-200-race")
    assert out["ambBefore"] is True, out
    assert out["emptyAt200ThenRetryAt0"] is True, out
    assert out["clearedAfterRetry"] is True, out


def test_recovery_201_to_200_guard_held_until_valid_page() -> None:
    """While the bounded retry is pending and until a valid latest page
    is rendered, the ambiguity guard must remain set. No blind
    resubmission beyond the bounded retry."""
    out = _run_scenario("recovery-201-to-200-race-guard-held")
    assert out["ambBefore"] is True, out
    assert out["guardHeldDuring"] is True, out
    assert out["keptAfterInvalidRetry"] is True, out
    assert out["noBlindResubmission"] is True, out


# ---- Correction 9: year-zero rejection + transactional latest-page ----


def test_recovery_year_zero_keeps_ambiguity() -> None:
    """0000-02-29T00:00:00Z must be rejected: Python datetime MINYEAR is 1."""
    out = _run_scenario("recovery-year-zero")
    assert out["kept"] is True, out


def test_recovery_year_one_clears_ambiguity() -> None:
    """0001-01-01T00:00:00Z is the boundary valid year and must be accepted."""
    out = _run_scenario("recovery-year-one")
    assert out["ambBefore"] is True, out
    assert out["cleared"] is True, out


def test_recovery_hour_24_keeps_ambiguity() -> None:
    """Hour 24 is not valid; the record must be rejected."""
    out = _run_scenario("recovery-hour-24")
    assert out["kept"] is True, out


def test_recovery_valid_leap_day_clears_ambiguity() -> None:
    """2024-02-29T00:00:00Z is a legitimate leap-day timestamp."""
    out = _run_scenario("recovery-valid-leap-day")
    assert out["ambBefore"] is True, out
    assert out["cleared"] is True, out


def test_refresh_year_zero_in_list_preserves_state() -> None:
    """A conversation-list record with year zero must not overwrite state."""
    out = _run_scenario("recovery-year-zero-in-list")
    assert out["rowsPreserved"] is True, out
    assert out["rangePreserved"] is True, out
    assert out["selectionPreserved"] is True, out
    assert out["statusKind"] == "error", out


def test_recovery_201_to_200_no_bad_commit() -> None:
    """When the 201->200 race is followed by a failed retry, no impossible
    page state (empty at offset === total > 0) may be committed.

    Documented behaviour on failed retry: the page is cleared and left
    unverified -- offset 0, total None (unverified), rendered 0. Assert
    each field explicitly so the test enforces its own claim."""
    out = _run_scenario("recovery-201-to-200-race-no-bad-commit")
    assert out["ambBefore"] is True, out
    assert out["kept"] is True, out
    assert out["impossibleRange"] is False, out
    assert out["stateCoherent"] is True, out
    assert out["stateUnverified"] is True, out
    state = out["state"]
    assert state["offset"] == 0, state
    assert state["total"] is None, state
    assert state["rendered"] == 0, state


# ---- Correction 10: fractional precision + switch rendered-count ----


def test_recovery_fractional_seconds_out_of_range_keeps_ambiguity() -> None:
    """Seven fractional-second digits exceed Python datetime's microsecond
    precision; the record must be rejected and ambiguity kept."""
    out = _run_scenario("recovery-fractional-precision")
    assert out["kept"] is True, out


def test_refresh_fractional_seconds_in_list_preserves_state() -> None:
    """A conversation-list record with seven fractional-second digits must
    not overwrite committed rows, range, or selection."""
    out = _run_scenario("recovery-fractional-precision-in-list")
    assert out["rowsPreserved"] is True, out
    assert out["rangePreserved"] is True, out
    assert out["selectionPreserved"] is True, out
    assert out["statusKind"] == "error", out


def test_switch_failure_rendered_count_matches_dom() -> None:
    """After a failed conversation switch, messagesRenderedCount must be
    zero to match the cleared DOM."""
    out = _run_scenario("switch-failure-rendered-count-coherent")
    assert out["renderedMatchesDom"] is True, out
    assert out["state"]["rendered"] == 0, out
    assert out["totalUnverified"] is True, out


# ---- Correction 11: deletion invalidates stale message loads ----


def test_delete_stale_response_cannot_repopulate() -> None:
    """A message-load response that resolves AFTER the conversation has been
    deleted via confirmed 204 must be rejected by the token bump and must
    not repopulate message state or the DOM."""
    out = _run_scenario("delete-stale-response-cannot-repopulate")
    assert out["ambBefore"] is True, out
    assert out["clearedOnDelete"] is True, out
    assert out["selectionCleared"] is True, out
    assert out["ambiguityCleared"] is True, out
    assert out["staleBlocked"] is True, out
    assert out["stateAfterStale"]["offset"] == 0, out
    assert out["stateAfterStale"]["total"] is None, out
    assert out["stateAfterStale"]["rendered"] == 0, out
    assert out["domAfterStale"] == 0, out


def test_delete_resets_pagination_state() -> None:
    """Confirmed conversation deletion must reset offset, total, and rendered
    count, and clear the selection."""
    out = _run_scenario("delete-resets-pagination-state")
    assert out["offsetReset"] is True, out
    assert out["totalReset"] is True, out
    assert out["renderedReset"] is True, out
    assert out["selectedCleared"] is True, out
    assert out["after"]["offset"] == 0, out
    assert out["after"]["total"] is None, out
    assert out["after"]["rendered"] == 0, out


# ---- Batch A: creation ambiguity guard + schema + naive datetime ----


def test_create_response_malformed_sets_ambiguity() -> None:
    """A 201 response missing created_at/updated_at must not be trusted as a
    valid selection; the ambiguity guard must be set."""
    out = _run_scenario("create-response-malformed")
    assert out["ambiguous"] is True, out
    assert out["selected"] is None, out


def test_create_response_naive_timestamp_sets_ambiguity() -> None:
    """A 201 response with a naive (no-offset) created_at is outside the
    API read contract and must set the guard rather than being selected."""
    out = _run_scenario("create-response-naive-timestamp")
    assert out["ambiguous"] is True, out
    assert out["selected"] is None, out


def test_create_network_fail_blocks_retry() -> None:
    """After a network failure during creation, a second New click must
    not issue another POST while the outcome is unresolved."""
    out = _run_scenario("create-network-fail-blocks-retry")
    assert out["ambiguousAfterFail"] is True, out
    assert out["noSecondPost"] is True, out


def test_create_reconcile_via_refresh_clears_guard() -> None:
    """A successful list refresh reconciles an ambiguous creation, clearing
    the guard so a subsequent New click can issue a POST again."""
    out = _run_scenario("create-reconcile-via-refresh")
    assert out["ambiguousAfterFail"] is True, out
    assert out["ambiguousAfterRefresh"] is False, out
    assert out["secondPostAttempted"] is True, out


def test_recovery_naive_timestamp_keeps_ambiguity() -> None:
    """A message record with a naive created_at is rejected and ambiguity
    remains active."""
    out = _run_scenario("recovery-naive-timestamp")
    assert out["kept"] is True, out


# ---- Batch B: creation selection-clearing and rename scoping ----


def test_create_clears_old_message_state_on_new_selection() -> None:
    """Creating a new conversation must invalidate any in-flight load and
    reset message state before presenting the new selection."""
    out = _run_scenario("create-stale-response-cannot-repopulate")
    assert out["selectedIsNew"] is True, out
    assert out["clearedOnCreate"] is True, out
    assert out["staleBlocked"] is True, out
    assert out["domStillEmpty"] is True, out


def test_rename_response_for_previous_target_does_not_touch_new_selection() -> None:
    """A PATCH response for A must not mutate B's title even if B is
    selected when the response arrives."""
    out = _run_scenario("rename-a-then-switch-to-b")
    assert out["bStillSelected"] is True, out
    assert out["bTitleUnchanged"] is True, out
    assert out["aTitleUpdated"] is True, out


# ---- Batch C: send/refresh scoping and in-flight lifecycle ----


def test_send_pending_switch_to_b_does_not_refresh_b() -> None:
    """A send for A resolving after the user switched to B must not trigger
    a refresh of B on A's behalf, and must leave B selected."""
    out = _run_scenario("send-pending-switch-to-b")
    assert out["bStillSelected"] is True, out
    assert out["noRefreshForA"] is True, out


def test_send_during_reload_blocked() -> None:
    """Submitting while a reload's total-count fetch is pending must be
    blocked, because messagesInFlight covers the whole operation."""
    out = _run_scenario("send-during-reload-blocked")
    assert out["loadingCoversWholeOperation"] is True, out
    assert out["sendBlocked"] is True, out


def test_delete_invalidated_load_not_stuck() -> None:
    """Deleting a conversation with a message load in flight must clear
    messagesInFlight, and a subsequently-resolving stale response must not
    re-set it."""
    out = _run_scenario("delete-invalidated-load-not-stuck")
    assert out["flagClearedOnDelete"] is True, out
    assert out["stillClearAfterStale"] is True, out
    assert out["selectionCleared"] is True, out


# ---- Batch D: list lifecycle, delete sync, page-shape validation ----


def test_delete_last_item_on_last_page_recovers_offset() -> None:
    """Deleting the only item on a non-first page must recover to offset 0
    and commit a coherent range."""
    out = _run_scenario("delete-last-item-on-last-page")
    assert out["offsetRecovered"] is True, out
    assert out["rowsCoherent"] is True, out
    assert out["rangeCoherent"] is True, out
    assert out["selectedAfter"] is None, out


def test_delete_one_item_updates_total_and_range() -> None:
    """Deleting a single item from a 51-row total must update the range and
    row count coherently after reconciliation."""
    out = _run_scenario("delete-one-item-updates-total")
    assert out["rangeUpdated"] is True, out
    assert out["rowsCoherent"] is True, out


def test_list_in_flight_does_not_reintroduce_deleted() -> None:
    """A list refresh resolving after a confirmed delete must not commit the
    deleted conversation back into the list. Asserts by rendered title
    (not by a data-id attribute the UI does not set)."""
    out = _run_scenario("list-in-flight-does-not-reintroduce-deleted")
    assert out["deletedNotReintroduced"] is True, out
    assert out["rowCountCoherent"] is True, out
    assert out["hasC0"] is False, out


def test_list_response_rejects_oversize_page() -> None:
    """A response with more rows than LIST_LIMIT must not be committed."""
    out = _run_scenario("list-rejects-oversize-page")
    assert out["rowsPreserved"] is True, out
    assert out["rangePreserved"] is True, out
    assert out["isError"] is True, out


def test_list_response_rejects_empty_at_nonzero_offset() -> None:
    """An empty page at a nonzero offset with a positive total is impossible
    and must not be committed."""
    out = _run_scenario("list-rejects-empty-at-nonzero-offset")
    assert out["rowsPreserved"] is True, out
    assert out["rangePreserved"] is True, out
    assert out["isError"] is True, out


# ---- Batch E: cross-flow interleavings and ordered-slice validation ----


def test_switch_while_delete_pending_keeps_b_selected() -> None:
    """Deleting A while the user has switched to B must not clear B's
    selection or message state, must clear A's ambiguity marker, must
    remove A from the rendered list, and must not claim that no
    conversation is selected while B is active."""
    out = _run_scenario("switch-while-delete-pending")
    assert out["bStillSelected"] is True, out
    assert out["bStateIntact"] is True, out
    assert out["ambC0BeforeDelete"] is True, out
    assert out["ambC0WhilePending"] is True, out
    assert out["markerCleared"] is True, out
    assert out["c0Absent"] is True, out
    assert out["statusHonest"] is True, out


def test_stale_invalidated_resolves_after_new_fail_keeps_b() -> None:
    """A stale message response for A resolving after a failed load for B
    must not corrupt B's selected state."""
    out = _run_scenario("stale-invalidated-resolves-after-new-fail")
    assert out["bStillSelected"] is True, out
    assert out["noCorruption"] is True, out


def test_recovery_rejects_out_of_order_sequence() -> None:
    """A latest-page response with individually valid records that are not
    in ascending sequence order must not clear ambiguity."""
    out = _run_scenario("recovery-rejects-out-of-order-sequence")
    assert out["kept"] is True, out


# ---- Batch 13.4: F1b/F2/F3/F6/F7 regression tests ----


def test_create_ambiguous_old_response_does_not_clear() -> None:
    out = _run_scenario("create-ambiguous-old-response-does-not-clear")
    assert out["ambiguousAfterFail"] is True, out
    assert out["guardHeldAfterStaleResponse"] is True, out


def test_create_ambiguous_nonzero_offset_does_not_clear() -> None:
    out = _run_scenario("create-ambiguous-nonzero-offset-does-not-clear")
    assert out["ambiguousAfterFail"] is True, out
    assert out["guardHeldAfterPagination"] is True, out


def test_recovery_rejects_oversize_message_page() -> None:
    out = _run_scenario("recovery-rejects-oversize-message-page")
    assert out["kept"] is True, out


def test_recovery_rejects_wrong_slice_position() -> None:
    out = _run_scenario("recovery-rejects-wrong-slice-position")
    assert out["kept"] is True, out


def test_rename_network_loss_reconciles_via_list() -> None:
    out = _run_scenario("rename-network-loss-reconciles-via-list")
    assert out["reconciled"] is True, out


def test_rename_404_clears_selection() -> None:
    out = _run_scenario("rename-404-clears-selection")
    assert out["selectionCleared"] is True, out
    assert out["rowRemoved"] is True, out


def test_rename_404_preserves_other_selection() -> None:
    out = _run_scenario("rename-404-preserves-other-selection")
    assert out["bPreserved"] is True, out
    assert out["c0Removed"] is True, out


def test_list_rejects_hex_total() -> None:
    out = _run_scenario("list-rejects-hex-total")
    assert out["rowsPreserved"] is True, out
    assert out["isError"] is True, out


def test_list_rejects_exponent_total() -> None:
    out = _run_scenario("list-rejects-exponent-total")
    assert out["rowsPreserved"] is True, out
    assert out["isError"] is True, out


def test_send_unknown_status_marks_ambiguous() -> None:
    out = _run_scenario("send-unknown-status-marks-ambiguous")
    assert out["markedAmbiguous"] is True, out


def test_send_missing_message_marks_ambiguous() -> None:
    out = _run_scenario("send-missing-message-marks-ambiguous")
    assert out["markedAmbiguous"] is True, out


def test_send_invalid_challenge_uses_global_guard_not_history_guard() -> None:
    out = _run_scenario("send-invalid-challenge-marks-ambiguous")
    assert out["markedAmbiguous"] is True, out
    assert out["noConversationAmbiguity"] is True, out


# ---- Batch 14: fix rename lock, actual response schema, and POST ambiguity ----


def test_rename_controls_reset_and_second_rename_works() -> None:
    out = _run_scenario("rename-controls-reset-after-success")
    assert out["enabledAfterFirst"] is True, out
    assert out["enabledAfterSecond"] is True, out
    assert out["secondRenameSent"] is True, out
    assert out["secondTitleApplied"] is True, out


def test_rename_unknown_outcome_blocks_retry() -> None:
    out = _run_scenario("rename-unknown-outcome-blocks-retry")
    assert out["retryBlocked"] is True, out
    assert out["buttonReenabled"] is True, out
    assert out["statusWarns"] is True, out


def test_rename_404_reconciles_pagination() -> None:
    out = _run_scenario("rename-404-clears-selection")
    assert out["selectionCleared"] is True, out
    assert out["rowRemoved"] is True, out
    assert out["totalIsZero"] is True, out
    assert out["offsetIsZero"] is True, out
    assert out["pagerHidden"] is True, out
    assert out["rangeCoherent"] is True, out
    assert out["renameButtonEnabled"] is True, out


def test_send_unsupported_capability_is_valid() -> None:
    out = _run_scenario("send-unsupported-capability-valid")
    assert out["noAmbiguity"] is True, out
    assert out["responseNotRetried"] is True, out
    assert out["cardHidden"] is True, out


def test_confirmation_required_without_challenge_is_valid() -> None:
    out = _run_scenario("confirmation-required-no-challenge-valid")
    assert out["noAmbiguity"] is True, out
    assert out["noUsableChallengeCard"] is True, out
    assert out["serverMessageShown"] is True, out
    assert out["postCount"] == 1, out


def test_confirmation_required_with_valid_challenge_is_shown() -> None:
    out = _run_scenario("confirmation-required-valid-challenge-shown")
    assert out["cardShown"] is True, out
    assert out["exactlyOnePost"] is True, out


def test_ambiguous_request_guard_survives_conversation_switch() -> None:
    out = _run_scenario("ambiguous-request-blocks-after-switch")
    assert out["selectedIsB"] is True, out
    assert out["flagPersisted"] is True, out
    assert out["secondPostBlocked"] is True, out


def test_ambiguous_transient_request_does_not_blindly_retry() -> None:
    out = _run_scenario("ambiguous-transient-request-blocks-retry")
    assert out["noConversationId"] is True, out
    assert out["flagPersisted"] is True, out
    assert out["secondPostBlocked"] is True, out


def test_persisted_ambiguous_guard_blocks_after_reload() -> None:
    out = _run_scenario("persisted-ambiguous-guard-blocks-request")
    assert out["noNewPost"] is True, out
    assert out["flagStillPresent"] is True, out


def test_send_challenge_rejects_extra_fields() -> None:
    out = _run_scenario("send-challenge-extra-field-guarded")
    assert out["cardHidden"] is True, out
    assert out["globalGuarded"] is True, out
    assert out["postCount"] == 1, out


def test_send_response_rejects_extra_fields() -> None:
    out = _run_scenario("send-response-extra-field-guarded")
    assert out["globalGuarded"] is True, out
    assert out["postCount"] == 1, out


def test_uncertain_decision_acknowledgement_clears_locked_card_only() -> None:
    out = _run_scenario("decision-unknown-ack-clears-locked-card")
    assert out["lockedBeforeAck"] is True, out
    assert out["cardDismissedAfterAck"] is True, out
    assert out["guardClearedAfterAck"] is True, out
    assert out["noRequestSentByAck"] is True, out
    assert out["acknowledgementStatus"] is True, out

def test_rename_404_from_off_page_reconciles_pagination_and_preserves_selection() -> None:
    """A stale rename target returning 404 while another conversation is
    selected on the last page must not leave offset/total/range inconsistent."""
    out = _run_scenario("rename-404-off-page-keeps-pagination-coherent")
    assert out["bPreserved"] is True, out
    assert out["c0Absent"] is True, out
    assert out["offset"] == 0, out
    assert out["total"] == 50, out
    assert out["rowCount"] == 50, out
    assert out["range"] == "Showing 1–50 of 50", out
    assert out["paginationCoherent"] is True, out


def test_rename_5xx_reconciles_target_before_reporting() -> None:
    """A server error may be returned after the PATCH committed, so read the
    exact target and establish the resulting title before permitting retry."""
    out = _run_scenario("rename-5xx-reconciles-target-before-reporting")
    assert out["reconciled"] is True, out
    assert out["onePatchThenRead"] is True, out
    assert out["buttonEnabled"] is True, out


def test_rename_5xx_with_failed_reconciliation_blocks_retry() -> None:
    """An inconclusive PATCH and failed follow-up read must leave the
    conversation guarded instead of blindly sending another PATCH."""
    out = _run_scenario("rename-5xx-unresolved-blocks-another-patch")
    assert out["guarded"] is True, out
    assert out["buttonEnabledAfterFirst"] is True, out
    assert out["blockedRetry"] is True, out
