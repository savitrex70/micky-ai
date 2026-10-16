"use strict";

(function () {
  const form = document.getElementById("request-form");
  const input = document.getElementById("message");
  const submit = document.getElementById("submit");
  const status = document.getElementById("status");
  const history = document.getElementById("history");

  const MAX = 2000;
  let inFlight = false;

  function setStatus(text, kind) {
    status.textContent = text;
    if (kind) {
      status.setAttribute("data-kind", kind);
    } else {
      status.removeAttribute("data-kind");
    }
  }

  function setBusy(busy) {
    inFlight = busy;
    submit.disabled = busy;
    input.disabled = busy;
    submit.textContent = busy ? "Sending\u2026" : "Send request";
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

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    if (inFlight) {
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

    setBusy(true);
    setStatus("Sending\u2026", "pending");

    try {
      const payload = await sendRequest(text);
      addHistory(text, payload.message, payload.status);
      setStatus("Response received. This request was not executed.", "info");
      input.value = "";
    } catch (err) {
      const message =
        err && err.message ? err.message : "Something went wrong.";
      setStatus(message, "error");
    } finally {
      setBusy(false);
      input.focus();
    }
  });
})();
