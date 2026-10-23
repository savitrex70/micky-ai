"""Tests for the local Micky AI web interface."""

import json as _json
import re
import shutil as _shutil
import subprocess as _subprocess
from pathlib import Path as _Path

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
    "confirmation-unavailable": "safe confirmation challenge could not be created",
    "execution-failed": "established failure",
    "execution-unknown": "final outcome is not established",
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


def test_clinical_workspace_runs_fully_audited_rop_workflow() -> None:
    """The local clinical panel exposes the existing audited ROP pipeline."""
    with TestClient(app) as client:
        page = client.get("/")
        workspace_js = client.get("/static/workspace.js")

    assert page.status_code == 200
    assert workspace_js.status_code == 200
    assert 'id="clinical-run-reasoning"' in page.text
    assert 'id="clinical-reasoning-result"' in page.text
    assert "/reasoning-run/execute-fully-audited" in workspace_js.text
    assert "result.package_consistent === true" in workspace_js.text
    assert "clinicalReasoningResult.textContent = JSON.stringify(result, null, 2)" in (
        workspace_js.text
    )
    assert "does not establish clinical validity" in workspace_js.text



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


def _assert_no_client_content_persistence(js: str) -> None:
    """Allow only the non-content request-outcome safety bit in sessionStorage."""
    for forbidden in ("localStorage", "indexedDB", "document.cookie"):
        assert forbidden not in js, forbidden

    assert "micky.ai.request-outcome-unresolved.v1" in js
    assert js.count("sessionStorage.") == 3
    storage_calls = re.findall(
        r"sessionStorage\.(getItem|setItem|removeItem)\(([^)]*)\)",
        js,
    )
    assert storage_calls == [
        ("getItem", "REQUEST_OUTCOME_UNRESOLVED_KEY"),
        ("setItem", 'REQUEST_OUTCOME_UNRESOLVED_KEY, "1"'),
        ("removeItem", "REQUEST_OUTCOME_UNRESOLVED_KEY"),
    ]


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


def test_page_javascript_has_no_client_content_persistence() -> None:
    _assert_no_client_content_persistence(_served_js())


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
    # Confirm and code-input may be blocked either by in-flight state or by
    # "cannot execute"; Cancel is only blocked by in-flight/unresolved.
    assert "cardConfirm.disabled = confirmBlocked" in js
    assert "cardCancel.disabled = locked" in js
    assert "cardCodeInput.disabled = confirmBlocked" in js


def test_page_javascript_marks_unresolved_challenge_on_network_failure() -> None:
    js = _served_js()
    # On a network failure, disable further action and explain that the
    # state is unknown. The wording must not claim the challenge is still
    # pending, and must not claim it was retried.
    assert "challengeUnresolved = true" in js
    assert "could not be verified" in js
    assert "will not automatically retry" in js


def test_page_javascript_handles_unknown_decision_outcome() -> None:
    js = _served_js()
    # Unknown / unrecognized decision outcomes must not claim success.
    assert "unrecognised decision outcome" in js


def test_page_javascript_blocks_new_request_while_card_pending() -> None:
    js = _served_js()
    # A visible challenge blocks ordinary requests. If a decision outcome is
    # uncertain, a separate explicit acknowledgement may dismiss the local
    # card, but that acknowledgement must not send a new POST itself.
    idx = js.index('form.addEventListener("submit"')
    marker = 'cardConfirm.addEventListener("click"'
    body = js[idx : js.index(marker, idx)]
    assert "if (!card.hidden || challengeUnresolved)" in body
    assert "Resolve the pending confirmation first" in body
    assert "const acknowledged = window.confirm(" in body
    assert "if (!acknowledged)" in body
    ack = body.index("const acknowledged = window.confirm(")
    hide = body.index("hideConfirmationCard()", ack)
    clear = body.index("clearRequestOutcomeUnresolved()", ack)
    send = body.index("const result = await sendRequest", ack)
    assert ack < hide < clear < send
    # This code path returns before sendRequest; the next user click is
    # required to submit any new request.
    assert "This click did not send " in body
    guard = body.index("if (!card.hidden || challengeUnresolved)")
    value_read = body.index("const text = input.value;")
    assert guard < value_read


def test_page_javascript_shows_card_only_for_confirmation_required() -> None:
    js = _served_js()
    idx = js.index('form.addEventListener("submit"')
    marker = 'cardConfirm.addEventListener("click"'
    body = js[idx : js.index(marker, idx)]
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


def test_page_javascript_validates_status_executed_consistency() -> None:
    """An invalid status/executed pair must not be accepted as a decision.

    The reviewer flagged that `cancelled` + `executed: true` was previously
    accepted and displayed as "cancelled", even though the server said an
    executor ran. The JS now requires the status and the executed flag to
    agree, per the ConfirmationDecisionStatus contract.
    """
    js = _served_js()
    assert "function isSemanticallyValidDecision(" in js
    assert "DECISION_EXECUTED_REQUIREMENT" in js
    for status in (
        "executed",
        "failed",
        "unknown",
        "cancelled",
        "rejected",
        "refused",
        "unavailable",
    ):
        assert status + ":" in js, status
    # The requirement map must show executed-only statuses requiring true.
    assert "executed: true" in js
    assert "cancelled: false" in js
    assert "unavailable: false" in js


def test_page_javascript_rejects_inconsistent_decision_response() -> None:
    js = _served_js()
    # resolveDecision must route a semantically invalid payload to the
    # unresolved path, not to the "cancelled" or other non-execution paths.
    idx = js.index("async function resolveDecision")
    body = js[idx : idx + 6000]
    assert "isSemanticallyValidDecision(result.payload)" in body
    assert "markChallengeUnresolved()" in body
    # The wording lives inside markChallengeUnresolved, which is defined
    # earlier in the file. Confirm it exists at all.
    assert "could not be verified" in js


def test_page_javascript_unresolved_does_not_claim_pending_or_nothing_ran() -> None:
    js = _served_js()
    idx = js.index("function markChallengeUnresolved")
    end = js.index("\n  }", idx) + 4
    body = js[idx:end]
    # Must warn against assuming the operation did not run (phrases may be
    # split across concatenated string literals, so check fragments).
    assert "Do not assume the operation did not" in body
    assert "run." in body
    # Must not claim the challenge is definitively still pending.
    assert "remains pending until it expires" not in body
    # Must acknowledge the state is unknown rather than pending.
    assert "may still" in body
    assert "already have transitioned" in body
    assert "state is unknown" in body
    # Must state that retry is not automatic.
    assert "will not automatically retry" in body


def test_page_javascript_does_not_auto_retry_decision() -> None:
    js = _served_js()
    # There must be no recursive or repeated call to resolveDecision or
    # sendDecision from the unresolved path.
    idx = js.index("function markChallengeUnresolved")
    end = js.index("\n  }", idx) + 4
    body = js[idx:end]
    assert "resolveDecision(" not in body
    assert "sendDecision(" not in body


def test_page_javascript_recognises_unknown_status_wording() -> None:
    js = _served_js()
    # describeDecision must handle a status not in the map without claiming
    # success or non-execution.
    assert "unrecognised decision outcome" in js


def test_page_javascript_preserves_executed_true_requirement() -> None:
    js = _served_js()
    # Even with isSemanticallyValidDecision, the explicit executed guard
    # must remain.
    assert 'payload.status === "executed" && payload.executed !== true' in js


def test_page_javascript_unavailable_keeps_card_and_blocks_confirm() -> None:
    """An `unavailable` response must not hide the card.

    The server can return `unavailable` before consuming the challenge.
    The interface must keep the pending card visible, disable Confirm (there
    is no executor to run against), and leave Cancel available.
    """
    js = _served_js()
    # Handle the unavailable status distinctly, before the terminal path.
    idx = js.index("async function resolveDecision")
    body = js[idx : idx + 4500]
    assert 'payload.status === "unavailable"' in body
    assert "challengeCannotExecute = true" in body
    # Must explicitly say the challenge may still be pending.
    assert "The challenge may still be pending" in body
    # Must point the user at Cancel.
    assert "Use Cancel to withdraw" in body or "use Cancel to withdraw" in body
    # Must NOT call hideConfirmationCard on this path.
    unavail_idx = body.index('payload.status === "unavailable"')
    next_block_idx = body.index('payload.status === "refused"', unavail_idx)
    unavail_block = body[unavail_idx:next_block_idx]
    assert "hideConfirmationCard" not in unavail_block


def test_page_javascript_refused_keeps_card() -> None:
    """A refused response must not be treated as a terminal state.

    The server uses a generic refusal for wrong code, expired, locked,
    invalidated, and not-pending challenges. The UI must preserve the card
    and allow the user to decide again or cancel.
    """
    js = _served_js()
    idx = js.index("async function resolveDecision")
    body = js[idx : idx + 4500]
    assert 'payload.status === "refused"' in body
    refused_idx = body.index('payload.status === "refused"')
    # Find the terminal path marker after refused
    terminal_idx = body.index("addHistory(summaryForHistory", refused_idx)
    refused_block = body[refused_idx:terminal_idx]
    assert "hideConfirmationCard" not in refused_block
    # Refusal must acknowledge the challenge state is uncertain.
    assert "may still be pending" in refused_block
    # Code input must be cleared so a retry enters fresh.
    assert "cardCodeInput.value" in refused_block


def test_page_javascript_confirm_blocked_when_cannot_execute() -> None:
    js = _served_js()
    # setDecisionBusy must respect challengeCannotExecute for the confirm
    # controls (button + code input), while leaving cancel enabled.
    idx = js.index("function setDecisionBusy")
    end = js.index("\n  }", idx) + 4
    body = js[idx:end]
    assert "challengeCannotExecute" in body
    assert "confirmBlocked" in body
    assert "cardConfirm.disabled = confirmBlocked" in body
    assert "cardCodeInput.disabled = confirmBlocked" in body
    # Cancel must remain independent of challengeCannotExecute.
    assert "cardCancel.disabled = locked" in body
    assert "cardCancel.disabled = confirmBlocked" not in body


def test_page_javascript_cancelled_clears_card() -> None:
    """A valid cancelled response is terminal and clears the card."""
    js = _served_js()
    idx = js.index("async function resolveDecision")
    body = js[idx : idx + 4500]
    # The terminal path (after unavailable and refused branches) must call
    # addHistory and hideConfirmationCard.
    terminal = body[body.index("// Terminal outcomes") :]
    assert "addHistory(summaryForHistory" in terminal
    assert "hideConfirmationCard" in terminal


def test_page_javascript_terminal_path_excludes_unavailable_and_refused() -> None:
    """unavailable and refused must be handled by earlier returns."""
    js = _served_js()
    idx = js.index("async function resolveDecision")
    body = js[idx : idx + 4500]
    unavailable_idx = body.index('payload.status === "unavailable"')
    refused_idx = body.index('payload.status === "refused"')
    terminal_idx = body.index("// Terminal outcomes")
    assert unavailable_idx < refused_idx < terminal_idx
    # Both earlier branches must return before the terminal path.
    assert "return;" in body[unavailable_idx:refused_idx]
    assert "return;" in body[refused_idx:terminal_idx]


# ============================================================================
# Task 227: confirmation-records management UI
# ============================================================================


def test_records_section_is_present_and_accessible() -> None:
    html = _served_html()
    for token in (
        'id="records-section"',
        'id="records-heading"',
        'id="records-load"',
        'id="records-export"',
        'id="records-delete"',
        'id="records-status"',
        'id="records-pagination"',
        'id="records-prev"',
        'id="records-next"',
        'id="records-range"',
        'id="records-table"',
        'id="records-tbody"',
        'aria-labelledby="records-heading"',
        'aria-live="polite"',
    ):
        assert token in html, token


def test_records_delete_button_starts_disabled() -> None:
    html = _served_html()
    start = html.index('id="records-delete"')
    open_idx = html.rfind("<button", 0, start)
    end_idx = html.index(">", start)
    tag = html[open_idx : end_idx + 1]
    assert "disabled" in tag


def test_records_selection_scope_is_explicit() -> None:
    html = _served_html()
    # The help text must state that selection is limited to the current page.
    assert "current page" in html
    # And it must warn that deleting a pending record removes the challenge.
    assert "pending record" in html or "still pending" in html
    assert "cannot be confirmed" in html or "cannot be confirmed or executed" in html


def test_records_js_fetches_records_and_export_locally() -> None:
    js = _served_js()
    assert "/api/assistant/confirmation-records" in js
    assert "/api/assistant/confirmation-records/export" in js
    # No external origins referenced.
    for forbidden in ("http://", "https://"):
        assert forbidden not in js, forbidden


def test_records_js_deletes_with_origin_safe_body() -> None:
    js = _served_js()
    assert "JSON.stringify({ record_ids: ids })" in js
    # The deletion body must not contain any other field.
    assert "record_ids: ids, " not in js
    # The body must be sent with a JSON content type.
    assert '"Content-Type": "application/json"' in js


def test_records_js_requires_explicit_confirmation_before_delete() -> None:
    js = _served_js()
    # A confirmation dialog must gate the deletion request.
    assert "window.confirm(" in js
    # And the dialog must state the deletion is permanent.
    assert "permanently removes" in js


def test_records_js_reports_pending_scope_in_delete_dialog() -> None:
    js = _served_js()
    # The confirmation dialog for pending records must explain the challenge
    # removal and the inability to confirm/execute afterwards.
    assert "still pending" in js or "is still pending" in js
    assert "Deletion is not the same as Confirm or Cancel" in js


def test_records_js_uses_safe_dom_apis_only() -> None:
    js = _served_js()
    # The whole app.js has no innerHTML usage; this is enforced globally by
    # test_page_javascript_renders_replies_without_html_injection, but we
    # confirm the records section specifically uses textContent.
    idx = js.index("function renderRows")
    end = js.index("function renderPagination", idx)
    body = js[idx:end]
    assert "textContent" in body
    assert "innerHTML" not in body
    assert "insertAdjacentHTML" not in body


def test_records_js_has_no_client_content_persistence() -> None:
    # The entire app has a single, non-content request-outcome guard. The
    # confirmation-record interface must not persist record content, IDs,
    # material values, or other state in browser storage.
    _assert_no_client_content_persistence(_served_js())


def test_records_js_has_no_automatic_retry_or_polling() -> None:
    js = _served_js()
    forbidden_tokens = (
        "setInterval",
        "requestAnimationFrame",
        'addEventListener("visibilitychange"',
    )
    for forbidden in forbidden_tokens:
        assert forbidden not in js, forbidden


def test_records_js_guards_duplicate_submissions() -> None:
    js = _served_js()
    # The records module has its own inFlight flag guarding load/export/delete.
    # Search the whole served JS (the records IIFE is ~15k chars; the
    # short-lived `requestInFlight` used elsewhere is a distinct variable).
    idx = js.index("Confirmation records management")
    tail = js[idx:]
    end = tail.index("})();") if "})();" in tail else len(tail)
    body = tail[:end]
    assert "let inFlight = false" in body
    assert "if (inFlight) return" in body
    # And the delete button stays disabled while a request is in flight.
    assert "updateDeleteButton" in body


def test_records_js_truthful_export_requires_is_complete() -> None:
    js = _served_js()
    # An export is only presented as a download when the server says
    # is_complete === true.
    assert "payload.is_complete !== true" in js
    assert "is_complete" in js


def test_records_js_reports_http_failures_honestly() -> None:
    js = _served_js()
    # The load, delete, and export calls all check resp.ok and surface an
    # error status rather than claiming success.
    assert "HTTP " in js
    # The delete response is only reported as a success when deleted_count is
    # a number.
    assert 'typeof payload.deleted_count !== "number"' in js


def test_records_js_updates_delete_selection_scope() -> None:
    js = _served_js()
    # When the page changes, selection state is scoped to the visible page.
    assert "currentRecords.some((r) => r.id === id)" in js
    assert "selectedIds.delete(id)" in js


def test_records_js_renders_material_state_truthfully() -> None:
    js = _served_js()
    # The three material states must be reported distinctly.
    assert "Never present" in js
    assert "Redacted by retention" in js
    assert "Retained" in js


def test_records_js_renders_outcome_states_truthfully() -> None:
    js = _served_js()
    for token in ("Not run", "Failed", "Succeeded", "Unknown after consume"):
        assert token in js, token


def test_existing_confirmation_card_functionality_intact() -> None:
    """Confirm the Task 226 card and rules still exist alongside records UI."""
    js = _served_js()
    for token in (
        "confirmation-card",
        "resolveDecision",
        "isSemanticallyValidDecision",
        "challengeCannotExecute",
        'payload.status === "unavailable"',
        'payload.status === "refused"',
    ):
        assert token in js, token


def test_records_js_delete_refreshes_via_fetchpage() -> None:
    """After a successful delete, the deleted row must be removed from the
    displayed dataset.

    A text-only assertion that loadPage() is called is not enough: loadPage
    returns immediately when inFlight is true, which is exactly the bug we
    fixed. This test asserts that the delete handler now:
      * fetches the post-deletion page through the low-level fetchPage()
        helper (not loadPage), and
      * calls applyPage() to render the fresh records,
      * and releases the inFlight guard before that fetch so the reload is
        not short-circuited.
    """
    js = _served_js()
    idx = js.index("async function deleteSelected")
    tail = js[idx:]
    end = tail.index("\n  }", 0) + 3
    body = tail[:end]
    assert "fetchPage(" in body
    assert "applyPage(" in body
    # The guard must be released before the refresh fetch — otherwise the
    # regression this test protects would return.
    guard_release = body.index("setBusy(false)")
    fetch_idx = body.index("fetchPage(")
    assert guard_release < fetch_idx, (
        "setBusy(false) must precede the refresh fetch so it is not "
        "short-circuited by the inFlight guard"
    )
    # loadPage must not be used for the post-delete refresh
    assert "loadPage(" not in body


def test_records_js_export_uses_content_disposition_filename() -> None:
    js = _served_js()
    idx = js.index("async function downloadExport")
    tail = js[idx:]
    end = tail.index("\n  }", 0) + 3
    body = tail[:end]
    assert 'resp.headers.get("Content-Disposition")' in body
    assert "confirmation-records-export.json" in body


def test_page_notice_describes_persisted_data_accurately() -> None:
    """The notice distinguishes the separate saved-data areas accurately."""
    html = _served_html()
    notice = html.lower()
    assert "nothing is saved." not in notice
    assert "confirmation records" in notice
    assert "retention" in notice or "redaction" in notice
    assert "selected conversation" in notice
    assert "only a successful exchange" in notice
    assert "notes, tasks, and reminders" in notice
    assert "private workspace" in notice
    assert "confirmation before it is applied" in notice
    assert "clinical reasoning data" in notice
    assert "Conversations, notes, tasks, and reminders are not persisted." not in html


# ============================================================================
# Behavioural test of the records UI via a real JS engine (Node)
# ============================================================================
#
# The source-text assertions above are retained as useful smoke checks, but
# they cannot prove that clicking Delete actually causes the deleted row to
# disappear from the rendered table. This test loads the real app.js into a
# minimal DOM/fetch harness (tests/records_ui_harness.cjs) and executes the
# actual delete handler, then asserts the observable DOM state.


def _run_harness(scenario: str) -> dict:
    node = _shutil.which("node")
    if node is None:
        import pytest as _pytest

        _pytest.skip("node is not available; behavioural UI test requires it")

    here = _Path(__file__).resolve().parent
    harness = here / "records_ui_harness.cjs"
    app_js = here.parent / "src" / "rop" / "web" / "static" / "app.js"
    assert harness.is_file(), f"harness missing: {harness}"
    assert app_js.is_file(), f"app.js missing: {app_js}"

    result = _subprocess.run(
        [node, str(harness), str(app_js), scenario],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise AssertionError(
            "harness failed:\nstdout:\n" + result.stdout + "\nstderr:\n" + result.stderr
        )
    line = result.stdout.strip().splitlines()[-1]
    return _json.loads(line)


def test_records_ui_delete_refresh_behavioural() -> None:
    """Executing the real delete handler removes the deleted row from the DOM.

    This is the behavioural proof the source-text test cannot provide:
    the harness loads the served app.js, seeds two records, selects one,
    confirms deletion, mocks a successful delete response and a refreshed
    list, and asserts the deleted row is gone from the rendered table.
    """
    out = _run_harness("delete-refresh")
    assert out["ok"] is True
    assert out["initialContainsA"] is True, "row A must be visible before delete"
    assert out["initialContainsB"] is True, "row B must be visible before delete"
    # The deleted row must disappear after the handler runs.
    assert (
        out["finalContainsA"] is False
    ), "deleted row still present in the rendered table:\n" + out.get("finalText", "")
    # The un-deleted row must remain.
    assert (
        out["finalContainsB"] is True
    ), "un-deleted row missing from the rendered table:\n" + out.get("finalText", "")
    # Status must reflect the actual deletion count reported by the server.
    assert out["statusMentionsDeleted"] is True, out.get("statusText", "")


def test_records_ui_duplicate_delete_blocked_behavioural() -> None:
    """A second Delete click while one is in flight must not issue a second POST.

    Executes the real handler against a fetch mock whose POST hangs until
    released; the second click is dispatched while the first is still in
    flight. The harness reports how many POSTs were actually issued.
    """
    out = _run_harness("duplicate-click")
    assert out["ok"] is True
    assert out["postCalls"] == 1, (
        "duplicate Delete click issued " + str(out["postCalls"]) + " POSTs"
    )
