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
  // A POST whose result is unknown may have left a durable confirmation
  // challenge pending even when no usable challenge ID reached the browser.
  // Persist only this boolean guard across reloads; never persist content or IDs.
  const REQUEST_OUTCOME_UNRESOLVED_KEY = "micky.ai.request-outcome-unresolved.v1";
  function readRequestOutcomeUnresolved() {
    try {
      return !!window.sessionStorage &&
        window.sessionStorage.getItem(REQUEST_OUTCOME_UNRESOLVED_KEY) === "1";
    } catch (err) {
      return false;
    }
  }
  let requestOutcomeUnresolved = readRequestOutcomeUnresolved();

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

  function markRequestOutcomeUnresolved() {
    requestOutcomeUnresolved = true;
    try {
      if (window.sessionStorage) {
        window.sessionStorage.setItem(REQUEST_OUTCOME_UNRESOLVED_KEY, "1");
      }
    } catch (err) {
      // The in-memory guard still blocks retries for this page lifetime.
    }
  }

  function clearRequestOutcomeUnresolved() {
    requestOutcomeUnresolved = false;
    try {
      if (window.sessionStorage) {
        window.sessionStorage.removeItem(REQUEST_OUTCOME_UNRESOLVED_KEY);
      }
    } catch (err) {
      // A stale persisted guard will ask for the same acknowledgement again.
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
    if (!challenge || typeof challenge !== "object" || Array.isArray(challenge)) {
      return false;
    }
    const allowedFields = new Set([
      "challenge_id",
      "summary",
      "display_code",
      "expires_at",
    ]);
    if (Object.keys(challenge).some((key) => !allowedFields.has(key))) {
      return false;
    }
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

    // Keep this set aligned with AssistantStatus in
    // src/rop/schemas/assistant.py, not only the dispatch implementation.
    const validStatuses = new Set([
      "success",
      "unsupported-capability",
      "clarification-required",
      "confirmation-required",
      "refused",
    ]);
    if (!validStatuses.has(payload.status)) {
      return { kind: "unexpected", reason: "unknown_status" };
    }

    // Every documented non-success AssistantStatus guarantees that no
    // conversation exchange was persisted. Preserve that distinction even
    // if the optional message/challenge shape is malformed.
    const noConversationSave = payload.status !== "success";
    const allowedResponseFields = new Set(["status", "message", "challenge"]);
    if (Object.keys(payload).some((key) => !allowedResponseFields.has(key))) {
      return {
        kind: "unexpected",
        reason: "unexpected_field",
        noConversationSave: noConversationSave,
      };
    }
    if (typeof payload.message !== "string") {
      return {
        kind: "unexpected",
        reason: "missing_message",
        noConversationSave: noConversationSave,
      };
    }

    const challengePresent =
      payload.challenge !== undefined && payload.challenge !== null;
    if (payload.status === "confirmation-required") {
      // The schema makes challenge optional: for example, a confirmation
      // requirement can be reported when no executor/challenge is available.
      // Validate it when present, because a malformed challenge may already
      // have been persisted even though the browser cannot safely display it.
      if (challengePresent && !isValidChallenge(payload.challenge)) {
        return {
          kind: "unexpected",
          reason: "invalid_challenge",
          noConversationSave: true,
        };
      }
    } else if (challengePresent) {
      // A challenge on another status contradicts the server response
      // contract; do not discard the possibility it was persisted.
      return {
        kind: "unexpected",
        reason: "unexpected_challenge",
        noConversationSave: noConversationSave,
      };
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
    markRequestOutcomeUnresolved();
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

    // Unknown POST outcomes remain guarded across reloads. This click can
    // only acknowledge the risk; it never replays the previous request.
    if (requestOutcomeUnresolved) {
      const acknowledged = window.confirm(
        "An earlier request's complete outcome is unknown. A saved exchange " +
          "or confirmation may need review, depending on the response. No " +
          "request will be sent by this click. Choose OK only after reviewing " +
          "conversation history and confirmation records where relevant; " +
          "press Send again later if you decide to proceed. The previous POST " +
          "will never be retried."
      );
      if (!acknowledged) {
        setStatus(
          "A prior request remains unresolved. No request was sent or " +
            "retried; review the confirmation records before proceeding.",
          "ambiguous"
        );
        return;
      }
      // If a known challenge decision became uncertain, the card's controls
      // are intentionally locked. The explicit acknowledgement dismisses only
      // the local card; it does not claim the server challenge was cancelled.
      if (challengeUnresolved) {
        hideConfirmationCard();
      }
      clearRequestOutcomeUnresolved();
      setStatus(
        "You acknowledged the unresolved outcome. This click did not send " +
          "or retry a request. Check conversation history where applicable, " +
          "then press Send again only when ready.",
        "info"
      );
      return;
    }

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
              payload.message +
                " The response did not include a usable confirmation " +
                "challenge, so this page cannot complete confirmation.",
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
            // Scope both operations to the conversation that actually
            // received the send. If the user has switched to B while A's
            // response was in flight, A's success must not clear B's
            // ambiguity or trigger a reload of B.
            window.__mickyConversations.clearAmbiguousFor(selectedConversationId);
            window.__mickyConversations.refreshMessagesFor(selectedConversationId);
          }
        }
      } else if (result.kind === "http") {
        const isSelectedConv = !!selectedConversationId;
        if (isSelectedConv && result.status === 409) {
          // The persistence boundary rolls back a sequence conflict. Still
          // require the user to reload history before deliberately retrying.
          window.__mickyConversations.markAmbiguous(selectedConversationId);
          setStatus(
            "The save was rejected because of a concurrent update and " +
              "nothing was stored. Reload the conversation to inspect the " +
              "actual history before retrying.",
            "error"
          );
        } else if (result.status >= 500) {
          if (isSelectedConv && window.__mickyConversations) {
            window.__mickyConversations.markAmbiguous(selectedConversationId);
          }
          // A server error can occur after part of the request workflow ran.
          // Persist a global guard because an issued confirmation challenge
          // cannot always be identified from an error envelope.
          markRequestOutcomeUnresolved();
          setStatus(
            "The server returned HTTP " + result.status + " but the full " +
              "request outcome is not established. " + result.detail +
              " The exchange may or may not be present in the conversation " +
              "history. Do not resend; inspect the stored state before " +
              "acknowledging this uncertainty.",
            "ambiguous"
          );
        } else {
          // Validation, origin, or missing-conversation rejections happen
          // before a successful dispatch/persistence and are safe to retry.
          setStatus(result.detail, "error");
        }

      } else {
        // Network, unreadable, and structurally invalid responses do not
        // establish whether dispatch completed or whether a challenge was
        // created. Lock new POSTs globally, including transient requests.
        if (
          selectedConversationId &&
          !result.noConversationSave &&
          window.__mickyConversations
        ) {
          window.__mickyConversations.markAmbiguous(selectedConversationId);
        }
        markRequestOutcomeUnresolved();
        const persistenceNote = result.noConversationSave
          ? "The server status indicates that no conversation exchange was saved. "
          : selectedConversationId
            ? "The conversation exchange may or may not have been saved. "
            : "This request had no conversation_id and was not saved to a conversation. ";
        setStatus(
          "The server's response could not be established. " +
            persistenceNote +
            "A confirmation challenge may still be pending. Do not resend. " +
            "Review confirmation records before acknowledging this uncertainty.",
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
  // Monotonic token to reject stale list responses (mirrors the message
  // token pattern).
  let listLoadToken = 0;
  let listOffset = 0;
  let listTotal = null;
  let messagesOffset = 0;
  let messagesTotal = null;
  let messagesRenderedCount = 0;
  // Conversations whose last request produced an outcome we could not
  // establish. While a conversation is in this set the composer refuses a
  // blind resubmit until the user reloads the conversation.
  const ambiguousConversations = new Set();
  const renameAmbiguousConversations = new Set();
  let createInFlight = false;
  // Set when a prior creation's outcome is unknown; blocks a second POST
  // until the user reconciles via a list refresh or page reload.
  let creationAmbiguous = false;
  // The value of listLoadToken at the moment creationAmbiguous was set.
  // Only a list response whose token is strictly greater (i.e. a request
  // started after the ambiguity was recorded) can clear the flag.
  let creationAmbiguityToken = 0;
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
    // Hide on empty total OR empty current page. The second condition covers
    // transient states (post-delete before reconciliation) where the local
    // rows have been cleared but the server-side total is still positive;
    // rendering "Showing 1-0 of 50" in that window is incoherent.
    if (listTotal === null || listTotal === 0 || conversations.length === 0) {
      convPager.hidden = true;
      convPrev.disabled = true;
      convNext.disabled = true;
      convRange.textContent = listTotal === 0 ? "Showing 0 of 0" : "";
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

  // UUID v1-v5 shape check (8-4-4-4-12 hex, case-insensitive). Matches
  // the string form produced by Pydantic's UUID serializer, which is the
  // only form the API emits in practice.
  const _UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  function isUuid(value) {
    return typeof value === "string" && _UUID_RE.test(value);
  }
  // ISO 8601 datetime with explicit calendar, clock, and timezone
  // component validation. Date.parse() alone is insufficient: JavaScript
  // normalizes impossible values (e.g. 2026-02-31T00:00:00Z becomes
  // March 3) instead of rejecting them, so a malformed record could pass
  // validation. Every accepted datetime must satisfy:
  //   YYYY-MM-DDTHH:MM:SS
  //   optional fractional seconds
  //   required timezone: Z or +/-HH:MM
  // and each component must be in its real range, including real
  // days-per-month and leap years. The timezone is required because the
  // backend stores timestamps as DateTime(timezone=True); a naive
  // timestamp is outside the API read contract.
  const _ISO_DATETIME_RE =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:(?:Z)|(?:([+-])(\d{2}):(\d{2})))$/;

  function _isLeapYear(y) {
    return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  }

  function _daysInMonth(y, m) {
    switch (m) {
      case 2:
        return _isLeapYear(y) ? 29 : 28;
      case 4:
      case 6:
      case 9:
      case 11:
        return 30;
      default:
        return 31;
    }
  }

  function isIsoDateTime(value) {
    if (typeof value !== "string") return false;
    const m = _ISO_DATETIME_RE.exec(value);
    if (!m) return false;
    const year = Number(m[1]);
    // Reject year zero. Python's datetime MINYEAR is 1, so the API read
    // schema cannot produce a year-0 timestamp; the calendar checks below
    // would otherwise treat year 0 as a leap year.
    if (year < 1) return false;
    const month = Number(m[2]);
    const day = Number(m[3]);
    const hour = Number(m[4]);
    const minute = Number(m[5]);
    const second = Number(m[6]);
    if (month < 1 || month > 12) return false;
    if (day < 1 || day > _daysInMonth(year, month)) return false;
    if (hour > 23 || minute > 59 || second > 59) return false;
    if (m[7] !== undefined) {
      const offH = Number(m[8]);
      const offM = Number(m[9]);
      if (offH > 23 || offM > 59) return false;
    }
    return true;
  }

  // Validate a single conversation record against the AssistantConversationRead
  // contract: UUID id, string title, and parseable datetime timestamps.
  function isValidConversationRecord(c) {
    if (!c || typeof c !== "object") return false;
    if (!isUuid(c.id)) return false;
    if (typeof c.title !== "string") return false;
    if (!isIsoDateTime(c.created_at)) return false;
    if (!isIsoDateTime(c.updated_at)) return false;
    return true;
  }

  // Validate a single message record against the API read contract.
  // Reject anything that could not have been produced by a valid
  // successful response, so a malformed body cannot be mistaken for
  // successfully-established history.
  function isValidMessageRecord(m, expectedConversationId) {
    if (!m || typeof m !== "object") return false;
    if (!isUuid(m.id)) return false;
    if (!isUuid(m.conversation_id)) return false;
    if (expectedConversationId && m.conversation_id !== expectedConversationId) {
      return false;
    }
    if (m.role !== "user" && m.role !== "assistant") return false;
    if (typeof m.content !== "string") return false;
    if (!Number.isInteger(m.sequence) || m.sequence < 0) return false;
    if (!isIsoDateTime(m.created_at)) return false;
    return true;
  }

  // Parse the X-Total-Count header. Returns null for missing or invalid
  // values so a caller cannot mistake an absent count for zero.
  function parseTotalCount(headerValue) {
    if (headerValue === null || headerValue === undefined) return null;
    const trimmed = String(headerValue).trim();
    if (trimmed === "") return null;
    // The API emits a plain non-negative decimal integer. Reject alternate
    // numeric notations (exponent "1e2", hex "0x10", signs) that Number()
    // would otherwise accept.
    if (!/^[0-9]+$/.test(trimmed)) return null;
    const n = Number(trimmed);
    if (!Number.isSafeInteger(n)) return null;
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
    const token = ++listLoadToken;
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
        // Validate every record before committing any state.
        for (const c of payload) {
          if (!isValidConversationRecord(c)) {
            setStatus(
              statusEl,
              "The conversation list response contained a malformed " +
                "record. Click \u201CRefresh conversations\u201D to try " +
                "again.",
              "error"
            );
            return { ok: false, reason: "malformed_record" };
          }
        }
        const totalCount = parseTotalCount(resp.headers.get("X-Total-Count"));
        if (totalCount === null) {
          setStatus(
            statusEl,
            "The conversation list response did not include a valid total " +
              "count. Click \u201CRefresh conversations\u201D to try again.",
            "error"
          );
          return { ok: false, reason: "invalid_total" };
        }
        // Page-shape validation. Reject responses that cannot represent a
        // coherent page under the API's LIST_LIMIT and total contract.
        if (payload.length > LIST_LIMIT) {
          setStatus(
            statusEl,
            "The conversation list response contained more records than " +
              "requested. Click \u201CRefresh conversations\u201D to try " +
              "again.",
            "error"
          );
          return { ok: false, reason: "oversize_page" };
        }
        if (totalCount === 0) {
          if (offset !== 0 || payload.length !== 0) {
            setStatus(
              statusEl,
              "The conversation list response was inconsistent with its " +
                "total. Click \u201CRefresh conversations\u201D to try again.",
              "error"
            );
            return { ok: false, reason: "impossible_page" };
          }
        } else {
          if (offset >= totalCount) {
            setStatus(
              statusEl,
              "The conversation list response referenced an invalid page. " +
                "Click \u201CRefresh conversations\u201D to try again.",
              "error"
            );
            return { ok: false, reason: "impossible_offset" };
          }
          if (payload.length === 0) {
            setStatus(
              statusEl,
              "The conversation list response was inconsistent with its " +
                "total. Click \u201CRefresh conversations\u201D to try again.",
              "error"
            );
            return { ok: false, reason: "impossible_page" };
          }
          if (offset + payload.length > totalCount) {
            setStatus(
              statusEl,
              "The conversation list response was inconsistent with its " +
                "total. Click \u201CRefresh conversations\u201D to try again.",
              "error"
            );
            return { ok: false, reason: "impossible_page" };
          }
          if (payload.length < LIST_LIMIT && offset + payload.length < totalCount) {
            setStatus(
              statusEl,
              "The conversation list response was shorter than the reported " +
                "total. Click \u201CRefresh conversations\u201D to try again.",
              "error"
            );
            return { ok: false, reason: "short_page" };
          }
        }
        // Reject the response if a newer loadConversations call has started
        // (e.g. from deleteSelected's reconciliation, or a user refresh).
        if (token !== listLoadToken) {
          return { ok: false, reason: "stale" };
        }
        // ---- Commit the new state as one atomic step. ----
        listTotal = totalCount;
        listOffset = offset;
        conversations = payload;
        // Reconcile an ambiguous creation ONLY when this list response was
        // (a) an offset-zero refresh, and (b) initiated after the ambiguity
        // was recorded. A pre-existing in-flight request cannot reconcile
        // the outcome it predates; a pagination fetch cannot either.
        if (
          creationAmbiguous &&
          offset === 0 &&
          token > creationAmbiguityToken
        ) {
          creationAmbiguous = false;
        }
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
    if (creationAmbiguous) {
      setStatus(
        statusEl,
        "A previous creation could not be confirmed. Reload the page " +
          "or click Refresh conversations to verify the actual saved " +
          "conversations before creating another.",
        "ambiguous"
      );
      return;
    }
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
        creationAmbiguous = true;
        creationAmbiguityToken = listLoadToken;
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
        creationAmbiguous = true;
        creationAmbiguityToken = listLoadToken;
        setStatus(
          statusEl,
          "The conversation creation response could not be read. The " +
            "server may have created the conversation. Reload the page to " +
            "verify the actual saved conversations.",
          "ambiguous"
        );
        return;
      }
      // Validate the create response against the API read contract
      // (AssistantConversationRead): UUID id, string title, ISO datetime
      // created_at and updated_at. A response missing any of those fields
      // is not a reliable authority for the new conversation.
      if (!isValidConversationRecord(payload)) {
        creationAmbiguous = true;
        creationAmbiguityToken = listLoadToken;
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
      // Treat this as a conversation switch: invalidate any in-flight
      // message load for the previous selection, clear its pagination
      // state, and clear its DOM before the new conversation's title is
      // presented. Without this, a stale response from the previous
      // selection could repopulate the display under the new title.
      messagesLoadToken++;
      messagesInFlight = false;
      messagesOffset = 0;
      messagesTotal = null;
      messagesRenderedCount = 0;
      while (msgsEl.firstChild) msgsEl.removeChild(msgsEl.firstChild);
      msgsEmpty.hidden = true;
      renderMsgsPagination();
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
      // Refresh succeeded and the row is present. Before starting a
      // message reload for the created conversation, verify the user has
      // not switched to a different conversation while the refresh was
      // pending: a reload here would invalidate the new selection's
      // in-flight message request on behalf of an earlier create.
      setStatus(statusEl, "", null);
      if (selectedId !== createdId) {
        return;
      }
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
  // Offset of the last page for a given total. This is the only offset
  // at which a non-empty conversation's newest history can begin, and
  // zero for a small or empty conversation.
  function latestOffsetFor(total) {
    if (total <= MESSAGES_LIMIT) return 0;
    return Math.floor((total - 1) / MESSAGES_LIMIT) * MESSAGES_LIMIT;
  }

  // True only when the committed messages state is a correct current
  // latest page for the given total. Rejects the case where the total
  // dropped to exactly the requested offset after the page was fetched
  // (an empty response at offset === total > 0), which is the 201->200
  // race the task requires us to block.
  function isCurrentLatestPage(total) {
    if (total === null || typeof total !== "number" || total < 0) return false;
    if (total === 0) {
      return messagesOffset === 0 && messagesRenderedCount === 0;
    }
    if (messagesRenderedCount === 0) return false;
    if (messagesOffset !== latestOffsetFor(total)) return false;
    if (messagesOffset + messagesRenderedCount !== total) return false;
    return true;
  }

  async function reloadLatest(id) {
    const token = ++messagesLoadToken;
    // messagesInFlight covers the WHOLE latest-history operation (total
    // fetch, page fetch, and bounded retry), so a user cannot slip a send
    // in during the preliminary total-fetch window.
    messagesInFlight = true;
    renderMsgsPagination();
    try {
      return await _reloadLatestInner(id, token);
    } finally {
      // Only the current generation owns the loading flag; an invalidated
      // request (e.g. by deleteSelected) must not clear it.
      if (token === messagesLoadToken) {
        messagesInFlight = false;
        renderMsgsPagination();
      }
    }
  }

  async function _reloadLatestInner(id, token) {
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
      freshTotal = parseTotalCount(resp.headers.get("X-Total-Count"));
      if (freshTotal === null) return false;
    } catch (err) {
      return false;
    }
    if (token !== messagesLoadToken || selectedId !== id) return false;

    // First attempt is transactional: the page is committed only when it
    // is a valid current latest page for the total in the same response.
    // A stale response is NOT committed and reports its new total.
    const targetOffset = latestOffsetFor(freshTotal);
    const first = await loadMessages(id, targetOffset, token, {
      requireLatest: true,
    });
    if (first === "not_found") return "not_found";
    if (first === true) return true;
    if (!first || typeof first !== "object" || !first.stale) return false;

    // One bounded retry against the new authoritative total. Never more.
    const retryOffset = latestOffsetFor(first.responseTotal);
    if (retryOffset === targetOffset) {
      setStatus(
        msgsStatus,
        "The latest conversation history could not be verified; " +
          "reload again to establish the current state.",
        "error"
      );
      return false;
    }
    if (token !== messagesLoadToken || selectedId !== id) return false;

    const second = await loadMessages(id, retryOffset, token, {
      requireLatest: true,
    });
    if (second === "not_found") return "not_found";
    if (second === true) return true;
    if (!second || typeof second !== "object" || !second.stale) return false;

    setStatus(
      msgsStatus,
      "The latest conversation history shifted again during recovery; " +
        "reload again to establish the current state.",
      "error"
    );
    return false;
  }

  // Called when the server confirms (via 404) that the selected
  // conversation no longer exists. Clears all UI state tied to it so it
  // cannot remain an active save destination, and invalidates any
  // in-flight message load so a stale response cannot resurrect it.
  function clearSelectionBecauseMissing(id) {
    if (selectedId !== id) return;
    messagesLoadToken++; // invalidate in-flight loads for this id
    // The invalidated load will not clear the flag in its own finally
    // (token mismatch); reset it here so the UI does not stay "loading".
    messagesInFlight = false;
    selectedId = null;
    selectedTitle = null;
    currentTitleEl.textContent = "";
    while (msgsEl.firstChild) msgsEl.removeChild(msgsEl.firstChild);
    msgsEmpty.hidden = true;
    messagesOffset = 0;
    messagesTotal = null;
    messagesRenderedCount = 0;
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
      messagesRenderedCount = 0;
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
  async function loadMessages(id, offset, externalToken, opts) {
    opts = opts || {};
    const requireLatest = opts.requireLatest === true;
    if (typeof offset !== "number") offset = 0;
    const token =
      typeof externalToken === "number" ? externalToken : ++messagesLoadToken;
    // Only the token owner can bump the token; if a token was supplied, we
    // do not bump it again (the caller already established the generation).
    if (typeof externalToken !== "number") messagesLoadToken = token;
    // Only the token owner manages the loading flag. When a caller supplies
    // an externalToken (reloadLatest), that caller owns the whole operation
    // and loadMessages must not clear the flag for it.
    const ownsLoading = typeof externalToken !== "number";
    if (ownsLoading) messagesInFlight = true;
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
      // Ordered-slice validation: a page of valid-looking records is not
      // enough -- it must represent an actual ordered slice of the
      // conversation. Reject duplicate IDs within a page and reject any
      // non-ascending sequence, so a syntactically valid response cannot
      // silently clear ambiguity with the wrong messages.
      const _seenMessageIds = new Set();
      let _prevSequence = -1;
      for (const m of payload) {
        if (_seenMessageIds.has(m.id)) {
          setStatus(
            msgsStatus,
            "The message list response contained duplicate records; " +
              "history could not be established.",
            "error"
          );
          return false;
        }
        _seenMessageIds.add(m.id);
        if (m.sequence <= _prevSequence) {
          setStatus(
            msgsStatus,
            "The message list response was not in the expected order; " +
              "history could not be established.",
            "error"
          );
          return false;
        }
        _prevSequence = m.sequence;
      }
      // Strict ordered-slice validation. The repository allocates
      // sequence numbers contiguously from zero (append = max + 1) and
      // exposes no individual-message deletion, so a well-formed page at
      // offset O must have payload[i].sequence === O + i for all i, and
      // payload.length must not exceed MESSAGES_LIMIT. This is stricter
      // than "unique ascending": it rejects a page of sequences
      // 100,101,102 pretending to be the page at offset 0.
      if (payload.length > MESSAGES_LIMIT) {
        setStatus(
          msgsStatus,
          "The message list response contained more records than " +
            "requested; history could not be established.",
          "error"
        );
        return false;
      }
      for (let _i = 0; _i < payload.length; _i++) {
        if (payload[_i].sequence !== offset + _i) {
          setStatus(
            msgsStatus,
            "The message list response was not the expected ordered " +
              "slice; history could not be established.",
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
      // Reject an empty page at any offset above zero. The final page of
      // a non-empty conversation always has records; an empty page at a
      // non-zero offset means the total changed underneath us. In
      // latest-page recovery mode this becomes a coded stale result so
      // the caller can retry against the fresh total WITHOUT committing
      // the contradictory empty page.
      if (payload.length === 0 && offset > 0) {
        if (requireLatest) {
          return { stale: true, responseTotal: headerTotal };
        }
        setStatus(
          msgsStatus,
          "The message list response was inconsistent with its total.",
          "error"
        );
        return false;
      }
      // Latest-page recovery is transactional: do not commit until the
      // page's offset, record count, and total agree with the
      // latest-page calculation for that total.
      if (requireLatest) {
        const expectedOffset = latestOffsetFor(headerTotal);
        const validLatest =
          headerTotal === 0
            ? offset === 0 && payload.length === 0
            : payload.length > 0 &&
              offset === expectedOffset &&
              offset + payload.length === headerTotal;
        if (!validLatest) {
          return { stale: true, responseTotal: headerTotal };
        }
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
      if (ownsLoading && token === messagesLoadToken) {
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
    messagesRenderedCount = 0;
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

  // Apply a server-confirmed title to the target record only. A response
  // for A must never mutate B's title, even if B is selected when the
  // response arrives; the visible heading is updated only if the target
  // is still selected.
  function _applyRenameResult(targetId, title) {
    const conv = findConversation(targetId);
    if (conv) {
      conv.title = title;
    }
    if (selectedId === targetId) {
      selectedTitle = title;
      currentTitleEl.textContent = title;
    }
    renderList();
  }

  // Reconcile a confirmed-404 rename target: remove from list; clear the
  // selection only if that target remains selected (never clear B
  // because A is missing).
  function _setRenameStatus(targetId, message, kind) {
    if (selectedId === targetId) {
      setStatus(msgsStatus, message, kind);
    } else {
      setStatus(statusEl, message, kind);
    }
  }

  async function _reconcileMissingRenameTarget(targetId) {
    // Save the page the user was viewing before local cleanup potentially
    // backs up an emptied last page. A confirmed 404 means the server's
    // authoritative total may now be smaller than that offset.
    const preferredOffset = listOffset;
    const targetWasSelected = selectedId === targetId;
    const targetWasKnown =
      targetWasSelected || !!findConversation(targetId);
    conversations = conversations.filter((c) => c.id !== targetId);
    if (targetWasKnown && listTotal !== null && listTotal > 0) {
      listTotal = Math.max(0, listTotal - 1);
    }
    if (
      listOffset > 0 &&
      (conversations.length === 0 ||
        (listTotal !== null && listOffset >= listTotal))
    ) {
      listOffset = Math.max(0, listOffset - LIST_LIMIT);
    }
    // Invalidate any stale list response before reconciling the confirmed 404.
    listLoadToken++;
    renameAmbiguousConversations.delete(targetId);
    ambiguousConversations.delete(targetId);

    if (targetWasSelected) {
      messagesLoadToken++;
      messagesInFlight = false;
      selectedId = null;
      selectedTitle = null;
      view.hidden = true;
      currentTitleEl.textContent = "";
      while (msgsEl.firstChild) msgsEl.removeChild(msgsEl.firstChild);
      msgsEmpty.hidden = true;
      messagesOffset = 0;
      messagesTotal = null;
      messagesRenderedCount = 0;
      renderMsgsPagination();
    }

    renderList();
    renderConvPagination();
    updateComposerMode();

    let syncResult = null;
    try {
      // Always refresh page zero first. Reusing a last-page offset before
      // learning the new total can request offset === total after the
      // missing target is removed; loadConversations correctly rejects that
      // empty page and would otherwise leave stale pagination committed.
      syncResult = await loadConversations(0);
      // Preserve the user's page where it remains valid under the new total.
      // If it is now out of range, the successful page-zero refresh remains
      // the authoritative, coherent view.
      if (
        syncResult &&
        syncResult.ok &&
        preferredOffset > 0 &&
        listTotal !== null &&
        preferredOffset < listTotal
      ) {
        const restoredPage = await loadConversations(preferredOffset);
        if (restoredPage && restoredPage.ok) {
          syncResult = restoredPage;
        }
      }
    } catch (err) {
      syncResult = null;
    }
    const message = syncResult && syncResult.ok
      ? "The conversation no longer exists on the server; the list and " +
        "pagination have been reconciled."
      : "The conversation no longer exists on the server. Its local row " +
        "was removed, but list reconciliation failed; refresh the list.";
    _setRenameStatus(targetWasSelected ? null : targetId, message,
      syncResult && syncResult.ok ? "info" : "error");
  }

  // The list may be paginated or the selection may have switched while the
  // PATCH was in flight. Read the exact target by ID instead of guessing its
  // state from whichever list page is currently visible.
  async function _reconcileRenameOutcome(targetId) {
    let response;
    try {
      response = await fetch(
        "/api/assistant/conversations/" + encodeURIComponent(targetId),
        { method: "GET" }
      );
    } catch (err) {
      return { kind: "unknown" };
    }
    if (response.status === 404) {
      await _reconcileMissingRenameTarget(targetId);
      return { kind: "missing" };
    }
    if (!response.ok) return { kind: "unknown" };

    let payload;
    try {
      payload = await response.json();
    } catch (err) {
      return { kind: "unknown" };
    }
    if (!isValidConversationRecord(payload) || payload.id !== targetId) {
      return { kind: "unknown" };
    }
    _applyRenameResult(targetId, payload.title);
    return { kind: "found", title: payload.title };
  }

  async function renameSelected() {
    if (renameInFlight || !selectedId) return;
    const targetId = selectedId;
    if (renameAmbiguousConversations.has(targetId)) {
      setStatus(
        msgsStatus,
        "A previous rename outcome for this conversation remains " +
          "unverified. Do not retry it until the page is reloaded and the " +
          "server state is inspected.",
        "ambiguous"
      );
      return;
    }
    const newTitle = renameInput.value.trim();
    if (!newTitle) {
      setStatus(msgsStatus, "Enter a title before renaming.", "error");
      renameInput.focus();
      return;
    }

    renameInFlight = true;
    renameBtn.disabled = true;
    setStatus(msgsStatus, "Renaming…", "info");
    let needsReconcile = false;
    try {
      let response;
      try {
        response = await fetch(
          "/api/assistant/conversations/" + encodeURIComponent(targetId),
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: newTitle }),
          }
        );
      } catch (err) {
        needsReconcile = true;
      }

      if (response && response.status === 404) {
        await _reconcileMissingRenameTarget(targetId);
        return;
      }
      if (response && !response.ok) {
        if (response.status >= 500) {
          // A server error may be generated after the update committed (for
          // example, while building the response). Read the target record
          // before declaring failure or permitting another PATCH.
          needsReconcile = true;
        } else {
          // A 4xx response other than the confirmed-missing 404 is a
          // definite rejection of this update under the API contract.
          renameAmbiguousConversations.delete(targetId);
          _setRenameStatus(
            targetId,
            "The conversation could not be renamed (HTTP " +
              response.status + ").",
            "error"
          );
          return;
        }
      }

      if (response && response.ok) {
        let payload;
        try {
          payload = await response.json();
        } catch (err) {
          needsReconcile = true;
          payload = null;
        }
        if (!needsReconcile) {
          if (!isValidConversationRecord(payload) || payload.id !== targetId) {
            needsReconcile = true;
          } else {
            renameAmbiguousConversations.delete(targetId);
            _applyRenameResult(targetId, payload.title);
            if (selectedId === targetId && renameInput.value.trim() === newTitle) {
              renameInput.value = "";
            }
            _setRenameStatus(
              targetId,
              selectedId === targetId ? "Renamed." :
                "Renamed conversation “" + payload.title + "”.",
              "info"
            );
            return;
          }
        }
      }

      if (needsReconcile) {
        _setRenameStatus(
          targetId,
          "The rename response could not be confirmed; checking the " +
            "server's current record…",
          "info"
        );
        let reconciliation;
        try {
          reconciliation = await _reconcileRenameOutcome(targetId);
        } catch (err) {
          reconciliation = { kind: "unknown" };
        }
        if (reconciliation.kind === "missing") return;
        if (reconciliation.kind === "found") {
          renameAmbiguousConversations.delete(targetId);
          if (selectedId === targetId && renameInput.value.trim() === newTitle) {
            renameInput.value = "";
          }
          const message = reconciliation.title === newTitle
            ? "The server's current record confirms the title “" +
              reconciliation.title + "”."
            : "The rename did not take effect. The server's current title is “" +
              reconciliation.title + "”; you can retry deliberately.";
          _setRenameStatus(targetId, message, "info");
          return;
        }

        renameAmbiguousConversations.add(targetId);
        _setRenameStatus(
          targetId,
          "The rename outcome remains unverified because the follow-up " +
            "read failed or was invalid. The rename button will stay " +
            "guarded for this conversation until the page is reloaded and " +
            "the server's state is inspected.",
          "ambiguous"
        );
      }
    } catch (err) {
      renameAmbiguousConversations.add(targetId);
      _setRenameStatus(
        targetId,
        "The rename outcome remains unverified. The rename button will " +
          "stay guarded for this conversation until the page is reloaded " +
          "and the server's state is inspected.",
        "ambiguous"
      );
    } finally {
      // Every return and every exception must release the shared control.
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
      // Documented API response: 204 is a confirmed delete; 404 is
      // confirmation that the target no longer exists. Both are treated as
      // confirmed. Any other status is inconclusive and must not perform
      // confirmed-deletion cleanup.
      const confirmed = resp.status === 204 || resp.status === 404;
      if (!confirmed) {
        setStatus(
          msgsStatus,
          "The conversation could not be deleted (HTTP " + resp.status + ").",
          "error"
        );
        return;
      }
      conversations = conversations.filter((c) => c.id !== deletingId);
      // Invalidate any in-flight list fetch so a pre-delete response cannot
      // reintroduce the deleted conversation into the committed list.
      listLoadToken++;
      // Locally adjust the total; the bounded refresh below reconciles with
      // the server's authoritative count.
      if (listTotal !== null && listTotal > 0) listTotal -= 1;
      // If deleting the last row on a non-first page leaves the offset out
      // of range, back up to a valid offset before refreshing.
      if (conversations.length === 0 && listOffset > 0) {
        listOffset = Math.max(0, listOffset - LIST_LIMIT);
      }
      // The deleted conversation's ambiguity marker is always removed on
      // confirmed deletion, regardless of whether the user has switched to
      // a different conversation while the DELETE was pending.
      ambiguousConversations.delete(deletingId);
      renameAmbiguousConversations.delete(deletingId);
      if (selectedId === deletingId) {
        // Only clear the current selection's message state when the deleted
        // conversation is still selected. If the user switched to B, B's
        // state must survive.
        messagesLoadToken++;
        messagesInFlight = false;
        selectedId = null;
        selectedTitle = null;
        view.hidden = true;
        currentTitleEl.textContent = "";
        while (msgsEl.firstChild) msgsEl.removeChild(msgsEl.firstChild);
        msgsEmpty.hidden = true;
        messagesOffset = 0;
        messagesTotal = null;
        messagesRenderedCount = 0;
        renderMsgsPagination();
      }
      renderList();
      renderConvPagination();
      updateComposerMode();
      // Bounded refresh from the (possibly recovered) offset. On failure,
      // keep the locally-adjusted state and tell the user honestly that the
      // list could not be reconciled.
      const syncRes = await loadConversations(listOffset);
      if (!syncRes || !syncRes.ok) {
        setStatus(
          msgsStatus,
          "The conversation was deleted, but the list could not be " +
            "refreshed. Click \u201CRefresh conversations\u201D to " +
            "reconcile.",
          "error"
        );
      } else if (selectedId !== null) {
        // A different conversation is still selected; do not claim that no
        // conversation is selected.
        setStatus(
          msgsStatus,
          "Conversation deleted. The previously-selected conversation " +
            "remains active.",
          "info"
        );
      } else {
        setStatus(
          msgsStatus,
          "Conversation deleted. No conversation is selected; the next " +
            "request will not be saved unless you select one.",
          "info"
        );
      }
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
  // Refresh messages for a specific conversation. No-op if the caller's
  // target is no longer selected -- a send's success must not trigger a
  // reload of a conversation the user has since switched to.
  async function refreshMessagesFor(expectedId) {
    if (!expectedId) return;
    if (selectedId !== expectedId) return;
    const ok = await reloadLatest(expectedId);
    if (ok === "not_found") {
      clearSelectionBecauseMissing(expectedId);
      return;
    }
    if (ok !== true && selectedId === expectedId) {
      setStatus(
        msgsStatus,
        "The exchange could not be confirmed in the conversation history. " +
          "Reload the conversation to verify the actual persisted state.",
        "error"
      );
    }
  }

  async function refreshSelectedMessages() {
    if (!selectedId) return;
    await refreshMessagesFor(selectedId);
  }

  function markAmbiguous(id) {
    if (id) ambiguousConversations.add(id);
  }

  function clearAmbiguousFor(id) {
    if (id) ambiguousConversations.delete(id);
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
    clearAmbiguousFor: clearAmbiguousFor,
    refreshMessagesFor: refreshMessagesFor,
    isAmbiguous: isAmbiguous,
    reloadSelected: reloadSelected,
    isLoadingMessages: function () {
      return messagesInFlight;
    },
    messagesState: function () {
      return {
        offset: messagesOffset,
        total: messagesTotal,
        rendered: messagesRenderedCount,
      };
    },
    createState: function () {
      return { ambiguous: creationAmbiguous };
    },
    conversationsState: function () {
      return conversations.map(function (c) {
        return { id: c.id, title: c.title };
      });
    },
    listState: function () {
      return {
        offset: listOffset,
        total: listTotal,
        rowCount: conversations.length,
        range: convRange.textContent,
        paginationHidden: convPager.hidden,
      };
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
