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
