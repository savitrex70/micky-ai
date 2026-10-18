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

  // Every status the server can report for the assistant request endpoint.
  // Every non-success wording states that nothing ran. "confirmation-required"
  // is set right after the pending card is shown, and the operation has indeed
  // not executed at that moment.
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

  // Decision outcomes. "executed" is success only when the response also
  // establishes `executed: true` (checked separately before this text is
  // used). The others describe what actually happened without overclaiming.
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
    "refused": "The decision was refused. Nothing was authorized.",
    "unavailable":
      "Not carried out: no executor is available for this operation, so " +
      "nothing ran.",
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
    cardConfirm.disabled = locked;
    cardCancel.disabled = locked;
    cardCodeInput.disabled = locked;
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
      // The request was attempted, but the connection failed before the
      // response arrived. We do not know whether the server processed the
      // decision. Do not automatically retry; disable further action.
      challengeUnresolved = true;
      setDecisionBusy(false);
      setStatus(
        "The decision could not be verified because the connection failed. " +
        "This confirmation cannot be retried from this page; start a new " +
        "request if you want to try again.",
        "error"
      );
      return;
    }

    if (!result.ok || !isValidDecisionPayload(result.payload)) {
      challengeUnresolved = true;
      setDecisionBusy(false);
      setStatus(
        "The decision response could not be verified. This confirmation " +
        "cannot be retried from this page.",
        "error"
      );
      return;
    }

    const payload = result.payload;

    // "executed" is only success when the response also says executed: true.
    if (payload.status === "executed" && payload.executed !== true) {
      challengeUnresolved = true;
      setDecisionBusy(false);
      setStatus(
        "The server reported execution but did not confirm it. Treat the " +
        "outcome as unknown.",
        "error"
      );
      return;
    }

    addHistory(summaryForHistory, payload.message, payload.status);
    hideConfirmationCard();
    setDecisionBusy(false);
    setStatus(describeDecision(payload.status), "info");
    input.focus();
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    if (requestInFlight) return;

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

    // Any new request hides a previously shown card: the server never lets
    // an old approval cover a different operation.
    hideConfirmationCard();
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

  // Enter inside the code field must never submit a confirmation. The user
  // must activate Confirm deliberately.
  cardCodeInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
    }
  });
})();
