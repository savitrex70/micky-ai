"use strict";

(function () {
  const form = document.getElementById("request-form");
  const input = document.getElementById("message");
  const submit = document.getElementById("submit");
  const status = document.getElementById("status");
  const history = document.getElementById("history");

  const card = document.getElementById("confirmation-card");
  const cardSummary = document.getElementById("confirmation-summary");
  const cardDisplayCode = document.getElementById("confirmation-display-code");
  const cardExpiry = document.getElementById("confirmation-expiry");
  const cardCodeInput = document.getElementById("confirmation-code-input");
  const cardConfirm = document.getElementById("confirmation-confirm");
  const cardCancel = document.getElementById("confirmation-cancel");

  const MAX = 2000;

  let requestInFlight = false;
  let decisionInFlight = false;
  let activeChallengeId = null;
  let challengeUnresolved = false;
  // Set true when the server reports no executor is available for this
  // operation. Once true, Confirm and the code field stay disabled so the
  // interface never offers Confirm as a route to execution for an operation
  // the server says cannot be executed. Cancel remains available so the
  // user can withdraw the pending challenge.
  let challengeCannotExecute = false;

  const STATUS_TEXT = {
    "success": "Capability responded. See the reply below.",
    "unsupported-capability":
      "No capability matched. The request was not executed.",
    "clarification-required":
      "More detail is needed before an operation can be selected, so nothing " +
      "was run. The request was not executed.",
    "confirmation-required":
      "This operation needs your explicit confirmation before it may run. " +
      "It was not executed.",
    "refused":
      "The authorization policy did not permit this operation. The request " +
      "was not executed.",
  };

  const DECISION_TEXT = {
    "executed": "Confirmed and executed successfully.",
    "failed":
      "Confirmed, but the executor reported failure. Success was not " +
      "established.",
    "unknown":
      "Confirmed, but the outcome could not be established. Do not assume " +
      "success or definite failure.",
    "cancelled": "Cancelled. The operation did not run.",
    "rejected": "Rejected. The operation did not run.",
    "refused":
      "The decision was refused. The challenge may or may not still be " +
      "pending.",
    "unavailable":
      "Not carried out: no executor is available for this operation.",
  };

  const DECISION_EXECUTED_REQUIREMENT = {
    executed: true,
    failed: true,
    unknown: true,
    cancelled: false,
    rejected: false,
    refused: false,
    unavailable: false,
  };

  function describeStatus(value) {
    const text = STATUS_TEXT[value];
    if (typeof text === "string") return text;
    return (
      "The server returned an unrecognised status. The request was not " +
      "executed."
    );
  }

  function describeDecision(value) {
    if (
      typeof value === "string" &&
      Object.prototype.hasOwnProperty.call(DECISION_TEXT, value)
    ) {
      return DECISION_TEXT[value];
    }
    return "The server returned an unrecognised decision outcome.";
  }

  function setStatus(text, kind) {
    status.textContent = text;
    if (kind) {
      status.setAttribute("data-kind", kind);
    } else {
      status.removeAttribute("data-kind");
    }
  }

  function setRequestBusy(busy) {
    requestInFlight = busy;
    submit.disabled = busy;
    input.disabled = busy;
    submit.textContent = busy ? "Sending\u2026" : "Send request";
  }

  function setDecisionBusy(busy) {
    decisionInFlight = busy;
    const locked = busy || challengeUnresolved;
    const confirmBlocked = locked || challengeCannotExecute;
    cardConfirm.disabled = confirmBlocked;
    cardCancel.disabled = locked;
    cardCodeInput.disabled = confirmBlocked;
  }

  function addHistory(prompt, reply, badge) {
    const li = document.createElement("li");

    const badgeEl = document.createElement("span");
    badgeEl.className = "badge";
    badgeEl.textContent = badge;
    li.appendChild(badgeEl);

    const promptEl = document.createElement("p");
    promptEl.className = "prompt";
    promptEl.textContent = prompt;
    li.appendChild(promptEl);

    const replyEl = document.createElement("p");
    replyEl.className = "reply";
    replyEl.textContent = reply;
    li.appendChild(replyEl);

    history.insertBefore(li, history.firstChild);
  }

  function isValidChallenge(challenge) {
    if (!challenge || typeof challenge !== "object") return false;
    const id = challenge.challenge_id;
    const summary = challenge.summary;
    const code = challenge.display_code;
    const expires = challenge.expires_at;
    if (typeof id !== "string" || id.length < 16 || id.length > 128) return false;
    if (typeof summary !== "string" || summary.length < 1 || summary.length > 2000) {
      return false;
    }
    if (typeof code !== "string" || code.length < 1 || code.length > 64) return false;
    if (typeof expires !== "string") return false;
    const t = Date.parse(expires);
    if (Number.isNaN(t)) return false;
    return true;
  }

  function formatLocalExpiry(iso) {
    try {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return "an unreadable time";
      return d.toLocaleString();
    } catch (err) {
      return "an unreadable time";
    }
  }

  function hideConfirmationCard() {
    activeChallengeId = null;
    challengeUnresolved = false;
    challengeCannotExecute = false;
    card.hidden = true;
    cardSummary.textContent = "";
    cardDisplayCode.textContent = "";
    cardExpiry.textContent = "";
    cardCodeInput.value = "";
    cardConfirm.disabled = false;
    cardCancel.disabled = false;
    cardCodeInput.disabled = false;
  }

  function showConfirmationCard(challenge) {
    activeChallengeId = challenge.challenge_id;
    challengeUnresolved = false;
    challengeCannotExecute = false;
    cardSummary.textContent = challenge.summary;
    cardDisplayCode.textContent = challenge.display_code;
    cardExpiry.textContent =
      "Expires at " + formatLocalExpiry(challenge.expires_at) +
      " (browser-local time). The server decides whether the challenge is " +
      "still valid.";
    cardCodeInput.value = "";
    cardConfirm.disabled = false;
    cardCancel.disabled = false;
    cardCodeInput.disabled = false;
    card.hidden = false;
    card.focus();
  }

  // Structured result so callers can distinguish what actually happened.
  //
  //   kind = "ok"         server responded 2xx with a usable body
  //   kind = "http"       server responded non-2xx (definite rejection)
  //   kind = "network"    fetch threw (server may or may not have processed)
  //   kind = "unreadable" body could not be parsed (server did respond)
  //   kind = "unexpected" body was structurally invalid (server did respond)
  //
  // The last three do NOT establish whether the exchange was saved.
  async function sendRequest(text, conversationId) {
    const body = { message: text };
    if (conversationId) {
      body.conversation_id = conversationId;
    }
    let response;
    try {
      response = await fetch("/api/assistant/requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (err) {
      return { kind: "network" };
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch (err) {
      payload = null;
    }
    if (!response.ok) {
      // FastAPI errors put a sanitized string in ``detail``; some assistant
      // responses use ``message``. Prefer whichever is present.
      let detail = null;
      if (payload && typeof payload.detail === "string") {
        detail = payload.detail;
      } else if (payload && typeof payload.message === "string") {
        detail = payload.message;
      } else {
        detail = "The server rejected the request (HTTP " + response.status + ").";
      }
      return { kind: "http", status: response.status, detail: detail };
    }
    if (!payload || typeof payload.status !== "string") {
      return { kind: "unreadable" };
    }
    return { kind: "ok", payload: payload };
  }

  async function sendDecision(challengeId, decision, code) {
    const body = { decision };
    if (code !== null && code !== undefined) {
      body.display_code = code;
    }
    const url =
      "/api/assistant/confirmations/" +
      encodeURIComponent(challengeId) +
      "/decision";
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (err) {
      payload = null;
    }
    return { ok: response.ok, status: response.status, payload };
  }

  function isValidDecisionPayload(payload) {
    if (!payload || typeof payload !== "object") return false;
    if (typeof payload.status !== "string") return false;
    if (typeof payload.executed !== "boolean") return false;
    if (typeof payload.message !== "string") return false;
    return true;
  }

  function isSemanticallyValidDecision(payload) {
    if (!isValidDecisionPayload(payload)) return false;
    if (
      !Object.prototype.hasOwnProperty.call(
        DECISION_EXECUTED_REQUIREMENT,
        payload.status
      )
    ) {
      return false;
    }
    if (payload.status === "executed" && payload.executed !== true) return false;
    const expectedExecuted = DECISION_EXECUTED_REQUIREMENT[payload.status];
    return payload.executed === expectedExecuted;
  }

  // The server's response told us nothing reliable about whether the
  // decision was processed. Do not claim the challenge is pending, does not
  // exist, or was resolved. Do not retry. Lock the controls for this card.
  function markChallengeUnresolved() {
    challengeUnresolved = true;
    setDecisionBusy(false);
    setStatus(
      "The decision outcome could not be verified. The challenge may still " +
        "be pending on the server or may already have transitioned; its " +
        "state is unknown from here. Do not assume the operation did not " +
        "run. This page will not automatically retry the decision.",
      "error"
    );
  }

  async function resolveDecision(decision, code) {
    if (decisionInFlight || activeChallengeId === null || challengeUnresolved) {
      return;
    }
    const challengeId = activeChallengeId;
    const summaryForHistory = cardSummary.textContent;

    setDecisionBusy(true);
    setStatus("Sending decision\u2026", "pending");

    let result;
    try {
      result = await sendDecision(challengeId, decision, code);
    } catch (err) {
      markChallengeUnresolved();
      return;
    }

    if (!result.ok || !isSemanticallyValidDecision(result.payload)) {
      markChallengeUnresolved();
      return;
    }

    const payload = result.payload;

    // The server uses "unavailable" before consuming the challenge when no
    // executor exists. The challenge may still be pending. Keep the card
    // visible, disable Confirm / code entry (there is nothing to execute
    // against in this build), and leave Cancel available so the user can
    // explicitly withdraw the pending challenge.
    if (payload.status === "unavailable") {
      challengeCannotExecute = true;
      setDecisionBusy(false);
      setStatus(
        "No executor is available for this operation, so it cannot be " +
          "executed here. The challenge may still be pending on the " +
          "server. Use Cancel to withdraw it.",
        "error"
      );
      cardCancel.focus();
      return;
    }

    // "refused" is a generic server-side refusal. It can mean a wrong code
    // (challenge still pending), an expired/locked/invalidated challenge,
    // or an already-consumed one. Do not treat it as terminal. Keep the
    // card visible so the user can decide again or cancel, and prevent a
    // new request from silently replacing it.
    if (payload.status === "refused") {
      setDecisionBusy(false);
      if (challengeCannotExecute) {
        setStatus(
          "The decision was refused. The challenge may still be pending " +
            "on the server or may already have transitioned. Do not " +
            "assume the operation did not run. No executor is available " +
            "for this operation; use Cancel to withdraw it.",
          "error"
        );
        cardCancel.focus();
      } else {
        setStatus(
          "The decision was refused. The challenge may still be pending " +
            "(for example, if the code was wrong) or may already have " +
            "transitioned (expired, locked, invalidated, or already " +
            "decided). Do not assume the operation did not run. Enter " +
            "the display code again, or choose Cancel to withdraw it.",
          "error"
        );
        cardCodeInput.value = "";
        cardCodeInput.focus();
      }
      return;
    }

    // Terminal outcomes: cancelled, rejected, executed, failed, unknown.
    // All of these establish a server-side terminal transition, so it is
    // safe to clear the card and add the outcome to history.
    addHistory(summaryForHistory, payload.message, payload.status);
    hideConfirmationCard();
    setDecisionBusy(false);
    setStatus(describeDecision(payload.status), "info");
    input.focus();
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    if (requestInFlight) return;

    // A pending or unresolved confirmation must be resolved before a new
    // request may start. Starting a new request would silently abandon an
    // outstanding server-side challenge.
    if (!card.hidden || challengeUnresolved) {
      if (challengeUnresolved) {
        markChallengeUnresolved();
      } else {
        setStatus(
          "Resolve the pending confirmation first: choose Cancel to " +
            "discard it, or Confirm with the display code. Starting a " +
            "new request would abandon an outstanding server-side " +
            "challenge.",
          "error"
        );
        cardCancel.focus();
      }
      return;
    }

    const text = input.value;
    if (!text.trim()) {
      setStatus("Enter a request before sending.", "error");
      input.focus();
      return;
    }
    if (text.length > MAX) {
      setStatus("Request is longer than " + MAX + " characters.", "error");
      return;
    }

    const selectedConversationId = window.__mickyConversations
      ? window.__mickyConversations.getSelectedId()
      : null;

    // Refuse a blind re-submit when a previous send's outcome was not
    // established. The user must reload the conversation first.
    if (
      selectedConversationId &&
      window.__mickyConversations &&
      window.__mickyConversations.isAmbiguous(selectedConversationId)
    ) {
      setStatus(
        "A previous request's save could not be confirmed. Click the " +
          "selected conversation's title in the list to reload its history " +
          "and establish the actual state before retrying.",
        "error"
      );
      return;
    }
    // Also block while a reload of the selected conversation is running:
    // sending before the reload completes would defeat the recovery.
    if (
      selectedConversationId &&
      window.__mickyConversations &&
      window.__mickyConversations.isLoadingMessages()
    ) {
      setStatus(
        "The conversation is still loading. Wait for it to finish before " +
          "sending.",
        "info"
      );
      return;
    }

    setRequestBusy(true);
    setStatus("Sending\u2026", "pending");

    try {
      const result = await sendRequest(text, selectedConversationId);

      if (result.kind === "ok") {
        const payload = result.payload;
        addHistory(text, payload.message, payload.status);
        if (payload.status === "confirmation-required") {
          if (isValidChallenge(payload.challenge)) {
            showConfirmationCard(payload.challenge);
            setStatus(describeStatus(payload.status), "info");
          } else {
            setStatus(
              "The server asked for confirmation but did not provide a " +
                "usable challenge. Nothing can be confirmed here.",
              "error"
            );
          }
        } else {
          setStatus(describeStatus(payload.status), "info");
        }
        input.value = "";
        // After a successful persisted turn, refresh the message list so
        // the just-saved user/assistant pair is visible. The server owns
        // that persistence; we do not POST the pair ourselves.
        if (selectedConversationId && payload.status === "success") {
          if (window.__mickyConversations) {
            window.__mickyConversations.clearAmbiguous();
            window.__mickyConversations.refreshSelectedMessages();
          }
        }
      } else if (result.kind === "http") {
        const isSelectedConv = !!selectedConversationId;
        if (isSelectedConv && result.status === 409) {
          // Recognized sequence conflict: the pair was rolled back and is
          // NOT stored. Still require a reload before a retry, so the user
          // verifies the visible history rather than trusting the error
          // category alone.
          window.__mickyConversations.markAmbiguous(selectedConversationId);
          setStatus(
            "The save was rejected because of a concurrent update and " +
              "nothing was stored. Reload the conversation to inspect the " +
              "actual history before retrying.",
            "error"
          );
        } else if (isSelectedConv && result.status === 503) {
          // Persistence failure around commit. The save may or may not
          // have completed. Must be treated as ambiguous, not definite.
          window.__mickyConversations.markAmbiguous(selectedConversationId);
          setStatus(
            "The exchange could not be confirmed as saved. It may or may " +
              "not have been stored. Reload the conversation to establish " +
              "the actual state before retrying.",
            "ambiguous"
          );
        } else {
          // Definite non-persistence rejection (validation, refusal,
          // missing conversation). Safe to show and allow retry.
          setStatus(result.detail, "error");
        }
      } else {
        // Ambiguous outcome (network / unreadable / unexpected). We cannot
        // establish whether the exchange was saved. Mark the selected
        // conversation as ambiguous so the next send is blocked until a
        // reload establishes the actual state.
        if (selectedConversationId && window.__mickyConversations) {
          window.__mickyConversations.markAmbiguous(selectedConversationId);
        }
        setStatus(
          "The server's response could not be established. The exchange " +
            "may or may not have been saved. Reload the selected " +
            "conversation (click its title in the list) to verify the " +
            "actual state before retrying.",
          "ambiguous"
        );
      }
    } catch (err) {
      const message =
        err && err.message ? err.message : "Something went wrong.";
      setStatus(message, "error");
    } finally {
      setRequestBusy(false);
      if (card.hidden) input.focus();
    }
  });

  cardConfirm.addEventListener("click", function () {
    const code = cardCodeInput.value.trim();
    if (!code) {
      setStatus(
        "Enter the display code shown above before confirming.",
        "error"
      );
      cardCodeInput.focus();
      return;
    }
    resolveDecision("confirm", code);
  });

  cardCancel.addEventListener("click", function () {
    resolveDecision("cancel", null);
  });

  cardCodeInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
    }
  });
})();

// ============================================================================
// Confirmation records management (Task 227)
// ============================================================================
(function () {
  const loadBtn = document.getElementById("records-load");
  const exportBtn = document.getElementById("records-export");
  const deleteBtn = document.getElementById("records-delete");
  const statusEl = document.getElementById("records-status");
  const pagination = document.getElementById("records-pagination");
  const prevBtn = document.getElementById("records-prev");
  const nextBtn = document.getElementById("records-next");
  const rangeEl = document.getElementById("records-range");
  const table = document.getElementById("records-table");
  const tbody = document.getElementById("records-tbody");

  if (!loadBtn || !statusEl || !tbody) return;

  const PAGE_SIZE = 50;
  let currentOffset = 0;
  let inFlight = false;
  let currentRecords = [];
  const selectedIds = new Set();

  function setStatus(text, kind) {
    statusEl.textContent = text;
    if (kind) statusEl.setAttribute("data-kind", kind);
    else statusEl.removeAttribute("data-kind");
  }

  function setBusy(busy) {
    inFlight = busy;
    loadBtn.disabled = busy;
    exportBtn.disabled = busy;
    updateDeleteButton();
  }

  function updateDeleteButton() {
    deleteBtn.disabled = inFlight || selectedIds.size === 0;
  }

  function clearTable() {
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
  }

  function describeStatus(value) {
    const map = {
      PENDING: "Pending",
      CONSUMED: "Consumed",
      REJECTED: "Rejected",
      CANCELLED: "Cancelled",
      EXPIRED: "Expired",
      INVALIDATED: "Invalidated",
      LOCKED: "Locked",
    };
    return map[value] || value;
  }

  function describeMaterial(state) {
    if (state === "ABSENT") return "Never present";
    if (state === "REDACTED") return "Redacted by retention";
    if (state === "RETAINED") return "Retained";
    return state;
  }

  function describeOutcome(value) {
    if (value === null || value === undefined) return "—";
    const map = {
      NOT_RUN: "Not run",
      FAILED: "Failed",
      SUCCEEDED: "Succeeded",
      UNKNOWN_AFTER_CONSUME: "Unknown after consume",
    };
    return map[value] || value;
  }

  function formatTime(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return "—";
      return d.toLocaleString();
    } catch (err) {
      return "—";
    }
  }

  function renderRows(records) {
    clearTable();
    if (records.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 8;
      td.className = "records-empty";
      td.textContent = "No records.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    for (const rec of records) {
      const tr = document.createElement("tr");

      // checkbox cell
      const cbTd = document.createElement("td");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = selectedIds.has(rec.id);
      cb.setAttribute("aria-label", "Select record " + rec.operation_id);
      cb.addEventListener("change", function () {
        if (cb.checked) selectedIds.add(rec.id);
        else selectedIds.delete(rec.id);
        updateDeleteButton();
      });
      cbTd.appendChild(cb);
      tr.appendChild(cbTd);

      const opTd = document.createElement("td");
      opTd.textContent = rec.operation_id;
      tr.appendChild(opTd);

      const statusTd = document.createElement("td");
      statusTd.textContent = describeStatus(rec.status);
      tr.appendChild(statusTd);

      const riskTd = document.createElement("td");
      riskTd.textContent = rec.required_risk + " / " + rec.required_reason;
      tr.appendChild(riskTd);

      const outcomeTd = document.createElement("td");
      outcomeTd.textContent = describeOutcome(rec.outcome);
      tr.appendChild(outcomeTd);

      const materialTd = document.createElement("td");
      materialTd.textContent = describeMaterial(rec.material_state);
      tr.appendChild(materialTd);

      const createdTd = document.createElement("td");
      createdTd.textContent = formatTime(rec.created_at);
      tr.appendChild(createdTd);

      const terminalTd = document.createElement("td");
      terminalTd.textContent = formatTime(rec.terminal_at);
      tr.appendChild(terminalTd);

      tbody.appendChild(tr);
    }
  }

  function renderPagination(total, offset, count) {
    if (total === 0) {
      pagination.hidden = true;
      return;
    }
    pagination.hidden = false;
    const end = offset + count;
    rangeEl.textContent =
      "Showing " + (offset + 1) + "–" + end + " of " + total;
    prevBtn.disabled = inFlight || offset <= 0;
    nextBtn.disabled = inFlight || end >= total;
  }

  // Low-level fetch + parse. Returns {ok:true,payload} or {ok:false,reason}
  // so callers can decide their own wording and never mistake a fetch
  // failure for a server-reported state.
  async function fetchPage(offset) {
    const url =
      "/api/assistant/confirmation-records?limit=" +
      PAGE_SIZE +
      "&offset=" +
      offset;
    let resp;
    try {
      resp = await fetch(url, { method: "GET" });
    } catch (err) {
      return { ok: false, reason: "unreachable" };
    }
    if (!resp.ok) {
      return { ok: false, reason: "http " + resp.status };
    }
    let payload;
    try {
      payload = await resp.json();
    } catch (err) {
      return { ok: false, reason: "unreadable" };
    }
    if (
      !payload ||
      !Array.isArray(payload.records) ||
      typeof payload.total_record_count !== "number"
    ) {
      return { ok: false, reason: "unexpected" };
    }
    return { ok: true, payload };
  }

  function applyPage(offset, payload) {
    currentOffset = offset;
    currentRecords = payload.records;
    // Drop selections that are no longer on the visible page
    for (const id of Array.from(selectedIds)) {
      if (!currentRecords.some((r) => r.id === id)) selectedIds.delete(id);
    }
    table.hidden =
      currentRecords.length === 0 && payload.total_record_count === 0;
    renderRows(currentRecords);
    renderPagination(
      payload.total_record_count,
      offset,
      currentRecords.length
    );
    updateDeleteButton();
  }

  function describeFetchError(reason) {
    if (reason === "unreachable") {
      return (
        "Could not reach the server to load records. " +
        "Check that the local API is running."
      );
    }
    if (reason === "unreadable") {
      return "The server returned an unreadable response.";
    }
    if (reason === "unexpected") {
      return "The server returned an unexpected response.";
    }
    return "The server could not return confirmation records (" + reason + ").";
  }

  async function loadPage(offset) {
    if (inFlight) return;
    setBusy(true);
    setStatus("Loading records\u2026", "info");
    try {
      const res = await fetchPage(offset);
      if (!res.ok) {
        setStatus(describeFetchError(res.reason), "error");
        return;
      }
      applyPage(offset, res.payload);
      setStatus(
        currentRecords.length === 0
          ? "No confirmation records stored."
          : "Loaded " +
              currentRecords.length +
              " of " +
              res.payload.total_record_count +
              " records.",
        "info"
      );
    } finally {
      setBusy(false);
    }
  }

  async function downloadExport() {
    if (inFlight) return;
    setBusy(true);
    setStatus("Preparing complete export\u2026", "info");
    try {
      const resp = await fetch("/api/assistant/confirmation-records/export", {
        method: "GET",
      });
      if (!resp.ok) {
        setStatus(
          "The export could not be produced (HTTP " + resp.status + ").",
          "error"
        );
        return;
      }
      let payload;
      try {
        payload = await resp.json();
      } catch (err) {
        setStatus("The export response could not be read.", "error");
        return;
      }
      if (!payload || payload.is_complete !== true) {
        setStatus(
          "The export did not complete and cannot be treated as a full " +
            "capture. Try again when the record store is stable.",
          "error"
        );
        return;
      }
      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      });
      // Prefer the server-declared attachment filename so the browser's
      // download and the API's response agree. Fall back to a stable local
      // name if the header is unavailable.
      const disposition = resp.headers.get("Content-Disposition") || "";
      const match = /filename="([^"]+)"/.exec(disposition);
      const filename = match ? match[1] : "confirmation-records-export.json";
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      setTimeout(function () {
        URL.revokeObjectURL(url);
      }, 0);
      setStatus(
        "Exported " +
          payload.total_record_count +
          " records (" +
          payload.page_count +
          " page" +
          (payload.page_count === 1 ? "" : "s") +
          ").",
        "info"
      );
    } catch (err) {
      setStatus(
        "The export could not be produced because the server was " +
          "unreachable.",
        "error"
      );
    } finally {
      setBusy(false);
    }
  }

  async function deleteSelected() {
    if (inFlight || selectedIds.size === 0) return;
    const ids = Array.from(selectedIds);
    const pendingOnPage = currentRecords.filter(
      (r) => ids.includes(r.id) && r.status === "PENDING"
    ).length;
    let confirmMessage =
      "Delete " + ids.length + " confirmation record" +
      (ids.length === 1 ? "" : "s") + "?\n\n" +
      "This permanently removes the selected records from the " +
      "confirmation-record store.";
    if (pendingOnPage > 0) {
      confirmMessage +=
        "\n\n" + pendingOnPage + " of them " +
        (pendingOnPage === 1 ? "is still pending" : "are still pending") +
        ". Deleting a pending record also removes its stored challenge; " +
        "that challenge cannot be confirmed or executed afterwards. " +
        "Deletion is not the same as Confirm or Cancel.";
    }
    if (!window.confirm(confirmMessage)) {
      return;
    }
    setBusy(true);
    setStatus("Deleting selected records\u2026", "info");
    try {
      const resp = await fetch("/api/assistant/confirmation-records", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ record_ids: ids }),
      });
      if (!resp.ok) {
        // A non-OK status does not establish whether the server removed any
        // record. Say only what the response actually supports.
        setStatus(
          "The server did not confirm the deletion (HTTP " + resp.status +
            "). Reload to verify the actual state.",
          "error"
        );
        return;
      }
      let payload;
      try {
        payload = await resp.json();
      } catch (err) {
        setStatus(
          "The deletion response could not be read. Reload to verify the " +
            "actual state.",
          "error"
        );
        return;
      }
      if (!payload || typeof payload.deleted_count !== "number") {
        setStatus(
          "The deletion response was unexpected. Reload to verify the " +
            "actual state.",
          "error"
        );
        return;
      }
      selectedIds.clear();
      setStatus(
        "Deleted " + payload.deleted_count + " record" +
          (payload.deleted_count === 1 ? "" : "s") + ". Refreshing\u2026",
        "info"
      );
      // Release the guard first: the refresh below bypasses loadPage's
      // duplicate-submission check on purpose, because it is the same
      // logical operation that just succeeded. The refresh still guards
      // against a concurrent user click because setBusy(true) re-blocks
      // the buttons below.
      const remaining = currentRecords.length - payload.deleted_count;
      const nextOffset =
        remaining <= 0 && currentOffset > 0
          ? Math.max(0, currentOffset - PAGE_SIZE)
          : currentOffset;
      setBusy(false);
      setBusy(true);
      const res = await fetchPage(nextOffset);
      if (res.ok) {
        applyPage(nextOffset, res.payload);
        setStatus(
          "Deleted " + payload.deleted_count + " record" +
            (payload.deleted_count === 1 ? "" : "s") + ". " +
            (res.payload.records.length === 0
              ? "No confirmation records stored."
              : "Showing " +
                res.payload.records.length +
                " of " +
                res.payload.total_record_count +
                " records."),
          "info"
        );
      } else {
        setStatus(
          "Deleted " + payload.deleted_count + " record" +
            (payload.deleted_count === 1 ? "" : "s") +
            ". The records table could not be refreshed; reload to see " +
            "the current state.",
          "error"
        );
      }
    } catch (err) {
      setStatus(
        "The deletion could not be completed because the server was " +
          "unreachable. No records were confirmed deleted; reload to verify.",
        "error"
      );
    } finally {
      setBusy(false);
    }
  }

  loadBtn.addEventListener("click", function () {
    loadPage(currentOffset);
  });
  exportBtn.addEventListener("click", downloadExport);
  deleteBtn.addEventListener("click", deleteSelected);
  prevBtn.addEventListener("click", function () {
    if (currentOffset <= 0) return;
    loadPage(Math.max(0, currentOffset - PAGE_SIZE));
  });
  nextBtn.addEventListener("click", function () {
    loadPage(currentOffset + PAGE_SIZE);
  });
})();

// ============================================================================
// Task 230: persistent conversations UI
// ============================================================================
(function () {
  const LIST_LIMIT = 50;
  const MESSAGES_LIMIT = 200;

  const section = document.getElementById("conversations-section");
  const newBtn = document.getElementById("conversations-new");
  const refreshBtn = document.getElementById("conversations-refresh");
  const statusEl = document.getElementById("conversations-status");
  const listEl = document.getElementById("conversations-list");
  const emptyEl = document.getElementById("conversations-empty");
  const view = document.getElementById("conversation-view");
  const currentTitleEl = document.getElementById("conversation-current-title");
  const renameInput = document.getElementById("conversation-rename-input");
  const renameBtn = document.getElementById("conversation-rename");
  const deleteBtn = document.getElementById("conversation-delete");
  const msgsStatus = document.getElementById("conversation-messages-status");
  const msgsEl = document.getElementById("conversation-messages");
  const convPager = document.getElementById("conversations-pagination");
  const convPrev = document.getElementById("conversations-prev");
  const convNext = document.getElementById("conversations-next");
  const convRange = document.getElementById("conversations-range");
  const msgsPager = document.getElementById("messages-pagination");
  const msgsPrev = document.getElementById("messages-prev");
  const msgsNext = document.getElementById("messages-next");
  const msgsRange = document.getElementById("messages-range");
  const msgsEmpty = document.getElementById("conversation-messages-empty");
  const composerMode = document.getElementById("composer-mode");

  if (!section || !listEl) return;

  let conversations = [];
  let selectedId = null;
  let selectedTitle = null;
  let listInFlight = false;
  let listInFlightPromise = null;
  let listOffset = 0;
  let listTotal = null;
  let messagesOffset = 0;
  let messagesTotal = null;
  let messagesRenderedCount = 0;
  // Conversations whose last request produced an outcome we could not
  // establish. While a conversation is in this set the composer refuses a
  // blind resubmit until the user reloads the conversation.
  const ambiguousConversations = new Set();
  let createInFlight = false;
  let messagesInFlight = false;
  let renameInFlight = false;
  let deleteInFlight = false;
  // Monotonic token to reject stale message responses.
  let messagesLoadToken = 0;

  function setStatus(el, text, kind) {
    el.textContent = text;
    if (kind) el.setAttribute("data-kind", kind);
    else el.removeAttribute("data-kind");
  }

  function updateComposerMode() {
    if (!composerMode) return;
    if (selectedId) {
      composerMode.textContent =
        "Sending will save this exchange to the selected conversation.";
      composerMode.setAttribute("data-kind", "persist");
    } else {
      composerMode.textContent =
        "No conversation is selected. This turn will not be saved.";
      composerMode.removeAttribute("data-kind");
    }
  }

  function findConversation(id) {
    return conversations.find((c) => c.id === id) || null;
  }

  function renderList() {
    while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
    if (conversations.length === 0) {
      emptyEl.hidden = false;
      return;
    }
    emptyEl.hidden = true;
    for (const conv of conversations) {
      const li = document.createElement("li");
      li.dataset.selected = conv.id === selectedId ? "true" : "false";

      const titleBtn = document.createElement("button");
      titleBtn.type = "button";
      titleBtn.className = "conv-title";
      titleBtn.textContent = conv.title;
      titleBtn.setAttribute("aria-current", conv.id === selectedId ? "true" : "false");
      titleBtn.addEventListener("click", () => {
        if (conv.id === selectedId) {
          // Clicking the already-selected conversation reloads its history.
          // This is the advertised ambiguity-recovery action, so it must
          // actually trigger a reload even when the id is unchanged.
          reloadSelected();
          return;
        }
        selectConversation(conv.id);
      });
      li.appendChild(titleBtn);

      const updated = document.createElement("span");
      updated.className = "conv-updated";
      try {
        updated.textContent = new Date(conv.updated_at).toLocaleString();
      } catch (err) {
        updated.textContent = "";
      }
      li.appendChild(updated);

      listEl.appendChild(li);
    }
    // If the selected conversation is not on this page, say so rather than
    // silently dropping the selection.
    if (selectedId && !findConversation(selectedId)) {
      const note = document.createElement("li");
      note.className = "conv-off-page";
      note.textContent =
        "The selected conversation is on another page; its title remains " +
        "active and the composer will still save to it.";
      listEl.appendChild(note);
    }
  }

  function renderConvPagination() {
    if (listTotal === null || listTotal === 0) {
      convPager.hidden = true;
      return;
    }
    convPager.hidden = false;
    const end = listOffset + conversations.length;
    convRange.textContent =
      "Showing " + (listTotal === 0 ? 0 : listOffset + 1) + "\u2013" + end +
      " of " + listTotal;
    convPrev.disabled = listInFlight || listOffset <= 0;
    convNext.disabled = listInFlight || end >= listTotal;
  }

  // Validate a single message record against the API read contract.
  // Reject anything that could not have been produced by a valid
  // successful response, so a malformed body cannot be mistaken for
  // successfully-established history.
  function isValidMessageRecord(m, expectedConversationId) {
    if (!m || typeof m !== "object") return false;
    if (typeof m.id !== "string" || !m.id) return false;
    if (typeof m.conversation_id !== "string" || !m.conversation_id) return false;
    if (expectedConversationId && m.conversation_id !== expectedConversationId) {
      return false;
    }
    if (m.role !== "user" && m.role !== "assistant") return false;
    if (typeof m.content !== "string") return false;
    if (!Number.isInteger(m.sequence) || m.sequence < 0) return false;
    if (typeof m.created_at !== "string" || !m.created_at) return false;
    return true;
  }

  // Parse the X-Total-Count header. Returns null for missing or invalid
  // values so a caller cannot mistake an absent count for zero.
  function parseTotalCount(headerValue) {
    if (headerValue === null || headerValue === undefined) return null;
    const trimmed = String(headerValue).trim();
    if (trimmed === "") return null;
    const n = Number(trimmed);
    if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) return null;
    return n;
  }

  // Fetch one page of conversations. Returns { ok: true } on success and
  // { ok: false, reason } otherwise. The committed list state (listOffset,
  // conversations, listTotal) is only mutated AFTER a valid response has
  // been parsed and validated — a failed or malformed response leaves the
  // previous rows and offset intact so the pagination controls continue
  // to describe the page the user is actually looking at.
  //
  // If another list fetch is already in flight, this one waits for it to
  // settle and then runs its own request rather than silently no-op'ing.
  // A caller (e.g. the create-conversation workflow) that awaits this
  // function is therefore guaranteed to observe a real result of *its*
  // request, not of an unrelated earlier one.
  async function loadConversations(offset) {
    // Serialize: wait until no request is in flight, rechecking after
    // each wait. Single-threaded JS guarantees this while loop is the
    // only place that flips listInFlight from false to true, so multiple
    // callers cannot start overlapping requests.
    while (listInFlight && listInFlightPromise) {
      try {
        await listInFlightPromise;
      } catch (err) {
        // ignore: our own request below will surface any real failure
      }
    }
    if (typeof offset !== "number") offset = listOffset;
    listInFlight = true;
    if (refreshBtn) refreshBtn.disabled = true;
    // Update pagination button states immediately so a user cannot queue
    // overlapping clicks while the request is being prepared.
    renderConvPagination();
    setStatus(statusEl, "Loading conversations\u2026", "info");
    listInFlightPromise = (async () => {
      try {
        const resp = await fetch(
          "/api/assistant/conversations?limit=" + LIST_LIMIT + "&offset=" + offset,
          { method: "GET" }
        );
        if (!resp.ok) {
          setStatus(
            statusEl,
            "Could not load conversations (HTTP " + resp.status + "). " +
              "Click \u201CRefresh conversations\u201D to try again.",
            "error"
          );
          return { ok: false, reason: "http_" + resp.status };
        }
        let payload;
        try {
          payload = await resp.json();
        } catch (err) {
          setStatus(
            statusEl,
            "The conversation list response was unreadable. Click " +
              "\u201CRefresh conversations\u201D to try again.",
            "error"
          );
          return { ok: false, reason: "unreadable" };
        }
        if (!Array.isArray(payload)) {
          setStatus(
            statusEl,
            "The conversation list response was unexpected. Click " +
              "\u201CRefresh conversations\u201D to try again.",
            "error"
          );
          return { ok: false, reason: "unexpected" };
        }
        const headerTotal = resp.headers.get("X-Total-Count");
        // ---- Commit the new state as one atomic step. ----
        listTotal = headerTotal !== null ? Number(headerTotal) : null;
        listOffset = offset;
        conversations = payload;
        renderList();
        renderConvPagination();
        updateComposerMode();
        setStatus(statusEl, "", null);
        if (selectedId) {
          const sel = findConversation(selectedId);
          if (sel) {
            selectedTitle = sel.title;
            currentTitleEl.textContent = sel.title;
          }
        }
        return { ok: true };
      } catch (err) {
        setStatus(
          statusEl,
          "The conversation list could not be loaded because the server " +
            "was unreachable. Click \u201CRefresh conversations\u201D to " +
            "try again.",
          "error"
        );
        return { ok: false, reason: "network" };
      } finally {
        listInFlight = false;
        if (refreshBtn) refreshBtn.disabled = false;
        renderConvPagination();
      }
    })();
    try {
      return await listInFlightPromise;
    } finally {
      // Only clear the reference if another caller has not already
      // started its own request. The IIFE's own finally resets
      // listInFlight; this guard prevents a late waiter from wiping a
      // newer caller's promise.
      listInFlightPromise = null;
    }
  }

  async function createConversation() {
    if (createInFlight) return;
    createInFlight = true;
    newBtn.disabled = true;
    setStatus(statusEl, "Creating conversation\u2026", "info");
    try {
      let resp;
      try {
        resp = await fetch("/api/assistant/conversations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: "New conversation" }),
        });
      } catch (err) {
        // Network failure: the server may have created the conversation
        // before the browser lost the response. Treat as ambiguous: do not
        // claim definite failure, do not repeat the POST, and tell the
        // user to reload the list to establish what actually happened.
        setStatus(
          statusEl,
          "The conversation creation could not be confirmed. The server " +
            "may have created it before the response was lost. Reload the " +
            "page to verify the actual saved conversations before " +
            "creating another.",
          "ambiguous"
        );
        return;
      }
      if (!resp.ok) {
        setStatus(
          statusEl,
          "The conversation could not be created (HTTP " + resp.status + ").",
          "error"
        );
        return;
      }
      let payload;
      try {
        payload = await resp.json();
      } catch (err) {
        // Server did respond, but we cannot parse it — treat as ambiguous.
        setStatus(
          statusEl,
          "The conversation creation response could not be read. The " +
            "server may have created the conversation. Reload the page to " +
            "verify the actual saved conversations.",
          "ambiguous"
        );
        return;
      }
      // Validate the fields the UI relies on. Both must be present for us
      // to trust this as the authority for the new conversation.
      if (
        !payload ||
        typeof payload.id !== "string" ||
        typeof payload.title !== "string"
      ) {
        setStatus(
          statusEl,
          "The conversation creation response was unexpected. The server " +
            "may have created it. Reload the page to verify.",
          "ambiguous"
        );
        return;
      }
      // The POST response is authoritative for id and title. Record the
      // title directly BEFORE any list refresh, so that even a failed
      // refresh cannot leave us showing the previous conversation's title
      // or a blank one.
      const createdId = payload.id;
      const createdTitle = payload.title;
      selectedId = createdId;
      selectedTitle = createdTitle;
      currentTitleEl.textContent = createdTitle;
      view.hidden = false;
      updateComposerMode();
      renderList();
      // Now try to refresh the list so the new row is visible. No
      // listOffset mutation before the response: loadConversations commits
      // the new offset only on success. Its return value tells us whether
      // its own request actually ran and succeeded, so we never confuse a
      // skipped refresh with a completed one.
      const refreshResult = await loadConversations(0);
      if (!refreshResult || !refreshResult.ok) {
        // Real refresh failure: the row and selection remain valid from
        // the POST response.
        setStatus(
          statusEl,
          "The conversation was created, but the list could not be " +
            "refreshed. Its title and selection are kept. Click " +
            "\u201CRefresh conversations\u201D in the Saved conversations " +
            "toolbar to retry the refresh.",
          "error"
        );
        return;
      }
      if (!findConversation(createdId)) {
        // Refresh succeeded but the created conversation is not present on
        // the visible page (unusual — a fresh creation typically appears
        // at the top of page zero — but handled truthfully rather than
        // pretending it was found).
        setStatus(
          statusEl,
          "The conversation was created, but it is not on the current " +
            "list page. Click \u201CRefresh conversations\u201D to reload " +
            "the list.",
          "error"
        );
        return;
      }
      // Refresh succeeded and the row is present; load latest messages.
      setStatus(statusEl, "", null);
      setStatus(msgsStatus, "Loading messages\u2026", "info");
      const ok = await reloadLatest(createdId);
      if (ok === "not_found") {
        clearSelectionBecauseMissing(createdId);
        return;
      }
      if (ok !== true && selectedId === createdId) {
        setStatus(
          msgsStatus,
          "The latest conversation history could not be loaded. Reload " +
            "to try again.",
          "error"
        );
      }
    } finally {
      createInFlight = false;
      newBtn.disabled = false;
    }
  }

  function renderMessages(messages) {
    while (msgsEl.firstChild) msgsEl.removeChild(msgsEl.firstChild);
    if (messages.length === 0) {
      msgsEmpty.hidden = false;
      return;
    }
    msgsEmpty.hidden = true;
    for (const m of messages) {
      const li = document.createElement("li");
      li.dataset.role = m.role;
      const roleEl = document.createElement("span");
      roleEl.className = "msg-role";
      roleEl.textContent = m.role;
      li.appendChild(roleEl);
      const contentEl = document.createElement("p");
      contentEl.className = "msg-content";
      contentEl.textContent = m.content;
      li.appendChild(contentEl);
      msgsEl.appendChild(li);
    }
  }

  // Reload the LATEST persisted messages for `id`, using a fresh total
  // count rather than assuming page zero is sufficient. For a conversation
  // longer than MESSAGES_LIMIT, the newest messages — including a possibly
  // saved exchange — are at the end. This is the recovery path for an
  // ambiguous save and the ordinary-load path for any selection.
  //
  // Returns true only when a fresh total was obtained, the page it points
  // at was fetched successfully, and the result was rendered for `id`
  // under the same generation token. Any failure returns false and the
  // caller must NOT clear the ambiguity marker.
  async function reloadLatest(id) {
    const token = ++messagesLoadToken;
    // Ask for a single record to obtain a fresh total.
    let freshTotal;
    try {
      const resp = await fetch(
        "/api/assistant/conversations/" +
          encodeURIComponent(id) +
          "/messages?limit=1&offset=0",
        { method: "GET" }
      );
      if (token !== messagesLoadToken || selectedId !== id) return false;
      if (resp.status === 404) return "not_found";
      if (!resp.ok) return false;
      const headerTotal = resp.headers.get("X-Total-Count");
      if (headerTotal === null) return false;
      freshTotal = Number(headerTotal);
      if (!Number.isFinite(freshTotal) || freshTotal < 0) return false;
    } catch (err) {
      return false;
    }
    if (token !== messagesLoadToken || selectedId !== id) return false;
    let targetOffset = 0;
    if (freshTotal > MESSAGES_LIMIT) {
      targetOffset =
        Math.floor((freshTotal - 1) / MESSAGES_LIMIT) * MESSAGES_LIMIT;
    }
    // Now load the actual page containing the newest messages.
    const ok = await loadMessages(id, targetOffset, token);
    if (ok === "not_found") return "not_found";
    if (!ok) return false;
    // Recovery is only established when the rendered page ends exactly
    // at the current total for the same conversation and generation.
    // This catches the case where records were added between the
    // fresh-total fetch and the page fetch (our offset is no longer the
    // last page) and the case where records were deleted (offset might
    // be past the end).
    if (token !== messagesLoadToken || selectedId !== id) return false;
    if (messagesTotal !== null && messagesTotal > 0) {
      const pageEnd = messagesOffset + messagesRenderedCount;
      if (pageEnd !== messagesTotal) {
        setStatus(
          msgsStatus,
          "The latest conversation history shifted while loading; " +
            "reload again to establish the current state.",
          "error"
        );
        return false;
      }
    }
    return true;
  }

  // Called when the server confirms (via 404) that the selected
  // conversation no longer exists. Clears all UI state tied to it so it
  // cannot remain an active save destination, and invalidates any
  // in-flight message load so a stale response cannot resurrect it.
  function clearSelectionBecauseMissing(id) {
    if (selectedId !== id) return;
    messagesLoadToken++; // invalidate in-flight loads for this id
    selectedId = null;
    selectedTitle = null;
    currentTitleEl.textContent = "";
    while (msgsEl.firstChild) msgsEl.removeChild(msgsEl.firstChild);
    msgsEmpty.hidden = true;
    messagesOffset = 0;
    messagesTotal = null;
    renderMsgsPagination();
    view.hidden = true;
    ambiguousConversations.delete(id);
    renderList();
    updateComposerMode();
    setStatus(
      msgsStatus,
      "The selected conversation no longer exists on the server; it has " +
        "been cleared. Future turns are transient unless you select " +
        "another conversation.",
      "error"
    );
  }

  async function selectConversation(id, opts) {
    opts = opts || {};
    const isSwitch = selectedId !== id;
    if (isSwitch) {
      // Clear prior messages BEFORE the fetch. If the fetch fails, the user
      // must not see one conversation's messages under another's title.
      messagesOffset = 0;
      messagesTotal = null;
      while (msgsEl.firstChild) msgsEl.removeChild(msgsEl.firstChild);
      msgsEmpty.hidden = true;
      renderMsgsPagination();
    }
    selectedId = id;
    // Prefer the title from the loaded list. When the selected conversation
    // is not on the current page, fall back to the previously known title
    // rather than reusing another conversation's title or showing blank.
    const conv = findConversation(id);
    if (conv) {
      selectedTitle = conv.title;
    } else if (!selectedTitle) {
      selectedTitle = "";
    }
    currentTitleEl.textContent = selectedTitle;
    view.hidden = false;
    renderList();
    updateComposerMode();
    if (!opts.preserveStatus) {
      setStatus(statusEl, "", null);
    }
    setStatus(msgsStatus, "Loading messages\u2026", "info");
    const ok = await reloadLatest(id);
    if (ok === "not_found") {
      clearSelectionBecauseMissing(id);
      return;
    }
    if (ok === true && selectedId === id) {
      ambiguousConversations.delete(id);
    } else if (selectedId === id) {
      setStatus(
        msgsStatus,
        "The latest conversation history could not be loaded. The " +
          "actual persisted state is not confirmed; do not resend until " +
          "reloading succeeds.",
        "error"
      );
    }
  }

  function renderMsgsPagination() {
    if (messagesTotal === null || messagesTotal === 0) {
      msgsPager.hidden = true;
      return;
    }
    msgsPager.hidden = false;
    const end = messagesOffset + msgsEl.children.length;
    msgsRange.textContent =
      "Showing " + (messagesOffset + 1) + "\u2013" + end +
      " of " + messagesTotal;
    msgsPrev.disabled = messagesInFlight || messagesOffset <= 0;
    msgsNext.disabled = messagesInFlight || end >= messagesTotal;
  }

  // Returns true only when the fetch succeeded, the body was valid, and
  // the response was for the current conversation/load token. A false
  // result must NOT be interpreted as "the conversation is empty".
  async function loadMessages(id, offset, externalToken) {
    if (typeof offset !== "number") offset = 0;
    const token =
      typeof externalToken === "number" ? externalToken : ++messagesLoadToken;
    // Only the token owner can bump the token; if a token was supplied, we
    // do not bump it again (the caller already established the generation).
    if (typeof externalToken !== "number") messagesLoadToken = token;
    messagesInFlight = true;
    setStatus(msgsStatus, "Loading messages\u2026", "info");
    try {
      const resp = await fetch(
        "/api/assistant/conversations/" +
          encodeURIComponent(id) +
          "/messages?limit=" +
          MESSAGES_LIMIT +
          "&offset=" +
          offset,
        { method: "GET" }
      );
      if (token !== messagesLoadToken) return false; // stale
      if (resp.status === 404) {
        // A confirmed 404 for this exact conversation means it no longer
        // exists. Callers translate that to a cleared selection.
        return "not_found";
      }
      if (!resp.ok) {
        setStatus(
          msgsStatus,
          "Could not load messages (HTTP " + resp.status + ").",
          "error"
        );
        return false;
      }
      let payload;
      try {
        payload = await resp.json();
      } catch (err) {
        if (token !== messagesLoadToken) return false;
        setStatus(msgsStatus, "The message list response was unreadable.", "error");
        return false;
      }
      if (token !== messagesLoadToken) return false; // stale
      if (!Array.isArray(payload)) {
        setStatus(msgsStatus, "The message list response was unexpected.", "error");
        return false;
      }
      // Validate every record against the read contract. A malformed
      // record (missing required field, wrong role, wrong conversation,
      // non-integer sequence) invalidates the response.
      for (const m of payload) {
        if (!isValidMessageRecord(m, id)) {
          setStatus(
            msgsStatus,
            "The message list response contained a malformed record; " +
              "history could not be established.",
            "error"
          );
          return false;
        }
      }
      // Require a valid X-Total-Count header. Missing or invalid totals
      // are rejected so a caller cannot treat an unverified page as
      // successful recovery.
      const headerTotal = parseTotalCount(resp.headers.get("X-Total-Count"));
      if (headerTotal === null) {
        setStatus(
          msgsStatus,
          "The message list response did not include a valid total count.",
          "error"
        );
        return false;
      }
      // Consistency: offset + rendered must not exceed the total, and a
      // short page (fewer records than MESSAGES_LIMIT) whose end is still
      // short of the total is inconsistent.
      if (offset + payload.length > headerTotal) {
        setStatus(
          msgsStatus,
          "The message list response was inconsistent with its total.",
          "error"
        );
        return false;
      }
      if (payload.length < MESSAGES_LIMIT && offset + payload.length < headerTotal) {
        setStatus(
          msgsStatus,
          "The message list response was shorter than the reported total.",
          "error"
        );
        return false;
      }
      messagesTotal = headerTotal;
      messagesOffset = offset;
      messagesRenderedCount = payload.length;
      renderMessages(payload);
      renderMsgsPagination();
      setStatus(msgsStatus, "", null);
      return true;
    } catch (err) {
      if (token !== messagesLoadToken) return false;
      setStatus(
        msgsStatus,
        "Messages could not be loaded because the server was unreachable.",
        "error"
      );
      return false;
    } finally {
      if (token === messagesLoadToken) {
        messagesInFlight = false;
        renderMsgsPagination();
      }
    }
  }

  // Explicit "reload the selected conversation" action. This is the
  // advertised recovery for an ambiguous save, so it must work even when
  // the conversation is already selected. It does not touch selection
  // state, and it clears the ambiguity marker only after a successful load.
  async function reloadSelected() {
    if (!selectedId) return;
    const id = selectedId;
    // Clear prior messages up front so a failed reload cannot leave the
    // previous content visible under the title.
    messagesOffset = 0;
    messagesTotal = null;
    while (msgsEl.firstChild) msgsEl.removeChild(msgsEl.firstChild);
    msgsEmpty.hidden = true;
    renderMsgsPagination();
    setStatus(msgsStatus, "Loading messages\u2026", "info");
    const ok = await reloadLatest(id);
    if (ok === "not_found") {
      clearSelectionBecauseMissing(id);
      return;
    }
    if (ok === true && selectedId === id) {
      ambiguousConversations.delete(id);
    } else if (selectedId === id) {
      setStatus(
        msgsStatus,
        "The latest conversation history could not be loaded. The " +
          "actual persisted state is not confirmed; do not resend until " +
          "reloading succeeds.",
        "error"
      );
    }
  }

  async function renameSelected() {
    if (renameInFlight || !selectedId) return;
    const newTitle = renameInput.value.trim();
    if (!newTitle) {
      setStatus(msgsStatus, "Enter a title before renaming.", "error");
      renameInput.focus();
      return;
    }
    renameInFlight = true;
    renameBtn.disabled = true;
    setStatus(msgsStatus, "Renaming\u2026", "info");
    try {
      const resp = await fetch(
        "/api/assistant/conversations/" + encodeURIComponent(selectedId),
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: newTitle }),
        }
      );
      if (!resp.ok) {
        setStatus(
          msgsStatus,
          "The conversation could not be renamed (HTTP " + resp.status + ").",
          "error"
        );
        return;
      }
      let payload;
      try {
        payload = await resp.json();
      } catch (err) {
        setStatus(msgsStatus, "The rename response was unreadable.", "error");
        return;
      }
      // Update local state only after the server confirmed.
      const conv = findConversation(selectedId);
      if (conv && payload && typeof payload.title === "string") {
        conv.title = payload.title;
      }
      currentTitleEl.textContent = conv ? conv.title : "";
      renderList();
      renameInput.value = "";
      setStatus(msgsStatus, "Renamed.", "info");
    } catch (err) {
      setStatus(
        msgsStatus,
        "Rename failed because the server was unreachable.",
        "error"
      );
    } finally {
      renameInFlight = false;
      renameBtn.disabled = false;
    }
  }

  async function deleteSelected() {
    if (deleteInFlight || !selectedId) return;
    const conv = findConversation(selectedId);
    const title = conv ? conv.title : "this conversation";
    const ok = window.confirm(
      'Delete "' +
        title +
        '"?\n\nThis permanently removes the conversation and its messages.'
    );
    if (!ok) return;
    deleteInFlight = true;
    deleteBtn.disabled = true;
    const deletingId = selectedId;
    setStatus(msgsStatus, "Deleting\u2026", "info");
    try {
      const resp = await fetch(
        "/api/assistant/conversations/" + encodeURIComponent(deletingId),
        { method: "DELETE" }
      );
      if (resp.status !== 204) {
        setStatus(
          msgsStatus,
          "The conversation could not be deleted (HTTP " + resp.status + ").",
          "error"
        );
        return;
      }
      conversations = conversations.filter((c) => c.id !== deletingId);
      if (selectedId === deletingId) {
        selectedId = null;
        view.hidden = true;
        currentTitleEl.textContent = "";
        while (msgsEl.firstChild) msgsEl.removeChild(msgsEl.firstChild);
        msgsEmpty.hidden = true;
      }
      renderList();
      updateComposerMode();
      setStatus(
        msgsStatus,
        "Conversation deleted. No conversation is selected; the next " +
          "request will not be saved unless you select one.",
        "info"
      );
      // Do not auto-select another conversation after deletion. Silently
      // picking a new save destination would let subsequent exchanges be
      // persisted to a conversation the user did not choose.
    } catch (err) {
      setStatus(
        msgsStatus,
        "Deletion failed because the server was unreachable. The " +
          "conversation may or may not still exist; reload to verify.",
        "error"
      );
    } finally {
      deleteInFlight = false;
      deleteBtn.disabled = false;
    }
  }

  function getSelectedId() {
    return selectedId;
  }

  // After a saved exchange, reload the latest persisted history via the
  // same authoritative path used for recovery: fresh total, then the page
  // containing the newest messages. Delegating here keeps the post-success
  // refresh and the ambiguous-save recovery behaviourally identical.
  async function refreshSelectedMessages() {
    if (!selectedId) return;
    const id = selectedId;
    const ok = await reloadLatest(id);
    if (ok === "not_found") {
      clearSelectionBecauseMissing(id);
      return;
    }
    if (ok !== true && selectedId === id) {
      setStatus(
        msgsStatus,
        "The exchange could not be confirmed in the conversation history. " +
          "Reload the conversation to verify the actual persisted state.",
        "error"
      );
    }
  }

  function markAmbiguous(id) {
    if (id) ambiguousConversations.add(id);
  }

  function clearAmbiguous() {
    if (selectedId) ambiguousConversations.delete(selectedId);
  }

  function isAmbiguous(id) {
    return !!id && ambiguousConversations.has(id);
  }

  window.__mickyConversations = {
    getSelectedId: getSelectedId,
    refreshSelectedMessages: refreshSelectedMessages,
    markAmbiguous: markAmbiguous,
    clearAmbiguous: clearAmbiguous,
    isAmbiguous: isAmbiguous,
    reloadSelected: reloadSelected,
    isLoadingMessages: function () {
      return messagesInFlight;
    },
  };

  newBtn.addEventListener("click", createConversation);
  if (refreshBtn) {
    refreshBtn.addEventListener("click", function () {
      // No listOffset mutation before the response: loadConversations
      // commits the new offset only after a valid response.
      loadConversations(0);
    });
  }
  renameBtn.addEventListener("click", renameSelected);
  deleteBtn.addEventListener("click", deleteSelected);
  convPrev.addEventListener("click", function () {
    if (listInFlight) return;
    if (listOffset > 0) {
      loadConversations(Math.max(0, listOffset - LIST_LIMIT));
    }
  });
  convNext.addEventListener("click", function () {
    if (listInFlight) return;
    if (listTotal !== null && listOffset + conversations.length < listTotal) {
      loadConversations(listOffset + LIST_LIMIT);
    }
  });
  msgsPrev.addEventListener("click", function () {
    if (selectedId && messagesOffset > 0) {
      loadMessages(selectedId, Math.max(0, messagesOffset - MESSAGES_LIMIT));
    }
  });
  msgsNext.addEventListener("click", function () {
    if (
      selectedId &&
      messagesTotal !== null &&
      messagesOffset + msgsEl.children.length < messagesTotal
    ) {
      loadMessages(selectedId, messagesOffset + MESSAGES_LIMIT);
    }
  });
  renameInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      renameSelected();
    }
  });

  // Initial load
  loadConversations();
})();
