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

  async function sendRequest(text) {
    const response = await fetch("/api/assistant/requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (err) {
      payload = null;
    }
    if (!response.ok) {
      const detail =
        payload && typeof payload.message === "string"
          ? payload.message
          : "The server rejected the request (HTTP " + response.status + ").";
      throw new Error(detail);
    }
    if (!payload || typeof payload.status !== "string") {
      throw new Error("The server returned an unexpected response.");
    }
    return payload;
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

    setRequestBusy(true);
    setStatus("Sending\u2026", "pending");

    try {
      const payload = await sendRequest(text);
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
        setStatus(
          "The deletion could not be completed (HTTP " + resp.status +
            "). No records were removed.",
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
