"use strict";

(function () {
  const byId = (id) => document.getElementById(id);
  const itemForm = byId("workspace-create-form");
  const itemKind = byId("workspace-kind");
  const itemTitle = byId("workspace-title");
  const itemContent = byId("workspace-content");
  const dueFields = byId("workspace-reminder-fields");
  const dueInput = byId("workspace-due");
  const timezoneInput = byId("workspace-timezone");
  const itemStatus = byId("workspace-status");
  const itemList = byId("workspace-items");
  const itemFilter = byId("workspace-filter");
  const overdueBox = byId("workspace-overdue");
  const abandonButton = byId("workspace-abandon");
  const retrievalRootForm = byId("retrieval-root-form");
  const retrievalPathInput = byId("retrieval-root-path");
  const rootsList = byId("retrieval-roots");
  const rootsStatus = byId("retrieval-root-status");
  const searchForm = byId("retrieval-search-form");
  const searchQuery = byId("retrieval-query");
  const searchStatus = byId("retrieval-search-status");
  const searchResults = byId("retrieval-results");
  const clinicalForm = byId("clinical-session-form");
  const clinicalStatus = byId("clinical-status");
  const clinicalSessions = byId("clinical-sessions");
  const clinicalPanel = byId("clinical-observations-panel");
  const clinicalSelectedHeading = byId("clinical-selected-heading");
  const clinicalSelectedMeta = byId("clinical-selected-meta");
  const clinicalObservationForm = byId("clinical-observation-form");
  const clinicalObservationStatus = byId("clinical-observation-status");
  const clinicalObservations = byId("clinical-observations");
  const clinicalExtract = byId("clinical-extract");
  const clinicalRunReasoning = byId("clinical-run-reasoning");
  const clinicalReasoningResult = byId("clinical-reasoning-result");
  const PENDING_KEY = "micky.ai.workspace-pending-key.v1";

  let items = [];
  let selectedClinicalSession = null;
  let clinicalRunInFlight = false;
  let busy = false;
  let pending = readPendingKey();

  function setText(node, message) {
    if (node) node.textContent = message || "";
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  function button(label, onClick, className) {
    const node = element("button", label, className);
    node.type = "button";
    node.addEventListener("click", onClick);
    return node;
  }

  function readPendingKey() {
    try {
      const raw = window.sessionStorage.getItem(PENDING_KEY);
      if (!raw) return null;
      const value = JSON.parse(raw);
      if (!value || typeof value.key !== "string" ||
          typeof value.fingerprint !== "string") return null;
      return value;
    } catch (err) {
      return null;
    }
  }

  function writePendingKey(value) {
    pending = value;
    try {
      if (value) window.sessionStorage.setItem(PENDING_KEY, JSON.stringify(value));
      else window.sessionStorage.removeItem(PENDING_KEY);
    } catch (err) {
      // The server receipt is authoritative. If local recovery storage is
      // unavailable, don't invent a replacement key during this page session.
    }
    abandonButton.hidden = !value;
  }

  async function fingerprint(value) {
    if (!window.crypto || !window.crypto.subtle) {
      throw new Error("Secure operation IDs are unavailable in this browser.");
    }
    const bytes = new TextEncoder().encode(JSON.stringify(value));
    const digest = await window.crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest))
      .map((part) => part.toString(16).padStart(2, "0")).join("");
  }

  async function jsonRequest(url, options) {
    const response = await fetch(url, options || {});
    let payload = null;
    try {
      payload = await response.json();
    } catch (err) {
      payload = null;
    }
    if (!response.ok) {
      const detail = payload && typeof payload.detail === "string"
        ? payload.detail
        : "The local service returned HTTP " + response.status + ".";
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function currentTimezone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    } catch (err) {
      return "UTC";
    }
  }

  function formatDate(value, timezone) {
    const date = new Date(value);
    if (!value || Number.isNaN(date.getTime())) return "No valid due time";
    try {
      const formatted = new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: timezone || undefined,
      }).format(date);
      return formatted + (timezone ? " (" + timezone + ")" : "");
    } catch (err) {
      return date.toLocaleString();
    }
  }

  function toLocalInput(value, timezone) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone || currentTimezone(),
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(date).reduce((result, part) => {
      result[part.type] = part.value;
      return result;
    }, {});
    return parts.year + "-" + parts.month + "-" + parts.day + "T" +
      parts.hour + ":" + parts.minute;
  }

  function setBusy(value) {
    busy = value;
    for (const control of itemForm.elements) control.disabled = value;
    for (const control of retrievalRootForm.elements) control.disabled = value;
    abandonButton.disabled = value;
  }

  function clearPending() {
    writePendingKey(null);
    setBusy(false);
  }

  async function readReceipt(key) {
    return jsonRequest("/api/assistant/workspace/receipts/" + encodeURIComponent(key));
  }

  async function refreshItems() {
    try {
      const filter = itemFilter.value;
      const query = filter === "all" ? "" : "?kind=" + encodeURIComponent(filter);
      const response = await jsonRequest("/api/assistant/workspace/items" + query);
      if (!Array.isArray(response)) throw new Error("The workspace list was not valid.");
      items = response;
      renderItems();
    } catch (err) {
      setText(itemStatus, "Workspace could not be loaded: " + err.message);
    }
  }

  function renderItems() {
    itemList.replaceChildren();
    overdueBox.replaceChildren();
    const now = Date.now();
    const overdue = items.filter((item) =>
      item.kind === "reminder" && !item.completed &&
      Number.isFinite(new Date(item.due_at).getTime()) &&
      new Date(item.due_at).getTime() <= now
    );
    overdueBox.hidden = overdue.length === 0;
    if (overdue.length) {
      overdueBox.appendChild(element("h3", "Overdue reminders"));
      const list = element("ul");
      overdue.forEach((item) => {
        list.appendChild(element(
          "li", item.title + " — " + formatDate(item.due_at, item.timezone)
        ));
      });
      overdueBox.appendChild(list);
    }
    if (!items.length) {
      itemList.appendChild(element("p", "No items in this view yet.", "help"));
      return;
    }
    items.forEach((item) => {
      const card = element("article", undefined, "workspace-card");
      card.appendChild(element("h3", item.title));
      card.appendChild(element(
        "p",
        item.kind.toUpperCase() + " · " + (item.completed ? "Completed" : "Open"),
        "help"
      ));
      if (item.content) card.appendChild(element("p", item.content));
      if (item.kind === "reminder") {
        card.appendChild(element("p", formatDate(item.due_at, item.timezone), "help"));
      }
      const actions = element("div", undefined, "workspace-actions");
      actions.appendChild(button("Edit", () => editItem(item)));
      actions.appendChild(button("Delete", () => deleteItem(item), "danger-button"));
      if (item.kind === "task") {
        actions.appendChild(button(
          item.completed ? "Mark open" : "Mark complete",
          () => prepareChange({
            kind: "task",
            action: "complete",
            item_id: item.id,
            completed: !item.completed,
          }, itemStatus)
        ));
      }
      card.appendChild(actions);
      itemList.appendChild(card);
    });
  }

  async function prepareChange(input, statusNode) {
    if (busy) return;
    if (!byId("confirmation-card").hidden) {
      setText(statusNode, "Resolve the visible confirmation before preparing another change.");
      return;
    }
    const body = Object.assign({}, input);
    try {
      const signatureBody = Object.assign({}, body);
      delete signatureBody.idempotency_key;
      const currentFingerprint = await fingerprint(signatureBody);
      if (pending && pending.fingerprint !== currentFingerprint) {
        setText(
          statusNode,
          "An earlier operation is unresolved. Re-enter its exact values or " +
          "resolve/abandon its confirmation before preparing another change."
        );
        return;
      }
      if (!pending) {
        if (!window.crypto || typeof window.crypto.randomUUID !== "function") {
          throw new Error("Secure operation IDs are unavailable in this browser.");
        }
        pending = { key: window.crypto.randomUUID(), fingerprint: currentFingerprint };
        writePendingKey(pending);
      }
      body.idempotency_key = pending.key;
      setBusy(true);
      setText(statusNode, "Preparing exact change for confirmation…");
      const result = await jsonRequest("/api/assistant/workspace/changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (result.status === "success") {
        clearPending();
        setText(statusNode, result.message);
        await refreshWorkspace();
      } else if (
        result.status === "confirmation-required" &&
        result.challenge &&
        window.__mickyWorkspaceUI
      ) {
        setText(statusNode, result.message);
        window.__mickyWorkspaceUI.showConfirmationCard(result.challenge);
      } else {
        setText(statusNode, result.message || "The change was not applied.");
        if (result.status === "confirmation-unavailable") {
          setText(
            statusNode,
            result.message + " You may retry only with the same operation key and exact values."
          );
        }
      }
    } catch (err) {
      setText(statusNode, "The change request could not be verified: " + err.message);
    } finally {
      setBusy(false);
      abandonButton.hidden = !pending;
    }
  }

  async function refreshWorkspace() {
    await Promise.all([refreshItems(), refreshRoots()]);
  }

  async function abandonPending() {
    if (!pending || busy) return;
    if (!window.confirm(
      "Abandon this unused operation key? The server will refuse while a " +
      "matching confirmation is active or the operation has completed."
    )) return;
    setBusy(true);
    try {
      await jsonRequest(
        "/api/assistant/workspace/receipts/" + encodeURIComponent(pending.key),
        { method: "DELETE", headers: { "Content-Type": "application/json" }, body: "{}" }
      );
      clearPending();
      setText(itemStatus, "The unused operation key was abandoned.");
    } catch (err) {
      setText(itemStatus, err.message);
    } finally {
      setBusy(false);
    }
  }

  async function editItem(item) {
    const title = window.prompt("New title", item.title);
    if (title === null) return;
    const content = window.prompt("Details (one line; leave blank to clear)", item.content || "");
    if (content === null) return;
    const payload = {
      kind: item.kind,
      action: "update",
      item_id: item.id,
      title: title,
    };
    if (content.trim() === "") {
      payload.clear_content = true;
    } else {
      payload.content = content;
    }
    if (item.kind === "reminder") {
      const tz = window.prompt("Timezone (IANA name)", item.timezone || currentTimezone());
      if (tz === null) return;
      const due = window.prompt(
        "Local due time (YYYY-MM-DDTHH:MM)",
        toLocalInput(item.due_at, tz)
      );
      if (due === null) return;
      payload.timezone = tz;
      payload.due_local = due;
    }
    await prepareChange(payload, itemStatus);
  }

  async function deleteItem(item) {
    if (!window.confirm("Prepare a confirmed deletion of " + item.kind + " \"" + item.title + "\"?")) return;
    await prepareChange({ kind: item.kind, action: "delete", item_id: item.id }, itemStatus);
  }

  async function refreshRoots() {
    try {
      const roots = await jsonRequest("/api/assistant/workspace/retrieval-roots");
      rootsList.replaceChildren();
      if (!Array.isArray(roots)) throw new Error("The authorized folder list was not valid.");
      if (!roots.length) rootsList.appendChild(element("li", "No folders authorized."));
      roots.forEach((root) => {
        const li = element("li");
        li.appendChild(element("span", root.path));
        li.appendChild(button("Remove folder", () => prepareChange({
          kind: "retrieval_root",
          action: "remove",
          item_id: root.id,
        }, rootsStatus)));
        rootsList.appendChild(li);
      });
    } catch (err) {
      setText(rootsStatus, "Folder list could not be loaded: " + err.message);
    }
  }

  async function searchLocalFiles(query) {
    const response = await jsonRequest("/api/assistant/retrieval/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query, limit: 20 }),
    });
    searchResults.replaceChildren();
    setText(
      searchStatus,
      "Examined " + response.files_examined + " file(s); skipped " +
      response.skipped_files + " file(s); skipped " +
      (response.skipped_entries || 0) + " filesystem entr(y/ies); found " +
      response.matches.length + " match(es)." +
      (response.roots_rejected
        ? " " + response.roots_rejected + " authorized folder(s) were not searched " +
          "because they failed a safety check (changed, unavailable, or not a permitted local folder)."
        : "") +
      (response.roots_skipped
        ? " " + response.roots_skipped + " authorized folder(s) were not searched " +
          "in this request (limit " + response.roots_limit + " folders per search)."
        : "")
    );
    if (!response.matches.length) {
      searchResults.appendChild(element("li", "No matches found in authorized folders."));
    }
    response.matches.forEach((match) => {
      const li = element("li", undefined, "workspace-card");
      li.appendChild(element("strong", match.path));
      li.appendChild(element("p", match.snippet));
      searchResults.appendChild(li);
    });
  }

  async function loadClinicalSessions() {
    try {
      const sessions = await jsonRequest("/api/sessions?offset=0&limit=50");
      clinicalSessions.replaceChildren();
      if (!sessions.length) {
        clinicalSessions.appendChild(element("p", "No clinical reasoning sessions yet.", "help"));
      }
      sessions.forEach((session) => {
        const card = element("article", undefined, "workspace-card");
        card.appendChild(element("h3", session.domain + " · " + session.status));
        card.appendChild(element("p", session.user_input, "help"));
        card.appendChild(button("Open clinical session", () => selectClinicalSession(session)));
        clinicalSessions.appendChild(card);
      });
    } catch (err) {
      setText(clinicalStatus, "ROP sessions could not be loaded: " + err.message);
    }
  }

  async function selectClinicalSession(session) {
    selectedClinicalSession = session;
    clinicalPanel.hidden = false;
    setText(clinicalSelectedHeading, "Clinical reasoning session " + session.id);
    setText(
      clinicalSelectedMeta,
      session.domain + " · " + session.status +
      " · Clinical-only identifier; not an assistant conversation ID."
    );
    await loadClinicalObservations();
  }

  async function loadClinicalObservations() {
    if (!selectedClinicalSession) return;
    try {
      const observations = await jsonRequest(
        "/api/sessions/" + encodeURIComponent(selectedClinicalSession.id) + "/observations"
      );
      clinicalObservations.replaceChildren();
      if (!observations.length) clinicalObservations.appendChild(element("li", "No observations recorded."));
      observations.forEach((observation) => {
        const li = element("li");
        li.appendChild(element(
          "strong", observation.type + " · confidence " + observation.confidence
        ));
        li.appendChild(element("p", observation.text));
        li.appendChild(element("p", "Source: " + observation.source, "help"));
        clinicalObservations.appendChild(li);
      });
    } catch (err) {
      setText(clinicalObservationStatus, "Observations could not be loaded: " + err.message);
    }
  }

  itemKind.addEventListener("change", () => {
    dueFields.hidden = itemKind.value !== "reminder";
  });
  itemForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const kind = itemKind.value;
    const payload = {
      kind,
      action: "create",
      title: itemTitle.value,
      content: itemContent.value,
    };
    if (kind === "reminder") {
      payload.due_local = dueInput.value;
      payload.timezone = timezoneInput.value || currentTimezone();
    }
    await prepareChange(payload, itemStatus);
  });
  itemFilter.addEventListener("change", refreshItems);
  byId("workspace-refresh").addEventListener("click", refreshWorkspace);
  abandonButton.addEventListener("click", abandonPending);

  retrievalRootForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await prepareChange({
      kind: "retrieval_root",
      action: "add",
      path: retrievalPathInput.value,
    }, rootsStatus);
  });
  searchForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!searchQuery.value.trim()) {
      setText(searchStatus, "Enter search terms first.");
      return;
    }
    try {
      setText(searchStatus, "Searching only authorized local folders…");
      await searchLocalFiles(searchQuery.value.trim());
    } catch (err) {
      setText(searchStatus, "Local search failed: " + err.message);
    }
  });

  clinicalForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      status: "open",
      domain: byId("clinical-domain").value,
      user_input: byId("clinical-input").value,
      current_stage: "initial",
      notes: byId("clinical-notes").value || null,
      metadata: {},
    };
    try {
      const created = await jsonRequest("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setText(clinicalStatus, "Created clinical reasoning session " + created.id + ".");
      await loadClinicalSessions();
      await selectClinicalSession(created);
    } catch (err) {
      setText(clinicalStatus, "Clinical session was not created: " + err.message);
    }
  });

  clinicalObservationForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selectedClinicalSession) return;
    const payload = {
      text: byId("clinical-observation-text").value,
      type: byId("clinical-observation-type").value,
      confidence: Number(byId("clinical-observation-confidence").value),
      source: byId("clinical-observation-source").value,
    };
    try {
      await jsonRequest(
        "/api/sessions/" + encodeURIComponent(selectedClinicalSession.id) + "/observations",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );
      setText(clinicalObservationStatus, "Observation added to the clinical session.");
      await loadClinicalObservations();
    } catch (err) {
      setText(clinicalObservationStatus, "Observation was not added: " + err.message);
    }
  });

  clinicalExtract.addEventListener("click", async () => {
    if (!selectedClinicalSession) return;
    try {
      const response = await jsonRequest(
        "/api/sessions/" + encodeURIComponent(selectedClinicalSession.id) + "/extract-observations",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: byId("clinical-observation-text").value }),
        }
      );
      setText(
        clinicalObservationStatus,
        "ROP extraction stored " + (response.observations || []).length + " observation(s)."
      );
      await loadClinicalObservations();
    } catch (err) {
      setText(clinicalObservationStatus, "Extraction failed: " + err.message);
    }
  });

  clinicalRunReasoning.addEventListener("click", async () => {
    if (!selectedClinicalSession || clinicalRunInFlight) return;
    clinicalRunInFlight = true;
    clinicalRunReasoning.disabled = true;
    clinicalReasoningResult.hidden = false;
    clinicalReasoningResult.textContent = "Running the fully audited deterministic ROP workflow…";
    setText(
      clinicalObservationStatus,
      "Running the deterministic reasoning workflow. This may take a moment."
    );
    try {
      const result = await jsonRequest(
        "/api/sessions/" +
          encodeURIComponent(selectedClinicalSession.id) +
          "/reasoning-run/execute-fully-audited",
        { method: "POST" }
      );
      clinicalReasoningResult.textContent = JSON.stringify(result, null, 2);
      if (result.package_consistent === true) {
        setText(
          clinicalObservationStatus,
          "The audit package is internally consistent. Review the execution outcome and limitations below; this does not establish clinical validity."
        );
      } else {
        setText(
          clinicalObservationStatus,
          "The reasoning response is not backed by a consistent audit package. Do not treat it as accepted."
        );
      }
    } catch (err) {
      clinicalReasoningResult.textContent = "";
      setText(
        clinicalObservationStatus,
        "The reasoning workflow did not return a verified result: " + err.message
      );
    } finally {
      clinicalRunInFlight = false;
      clinicalRunReasoning.disabled = false;
    }
  });

  window.addEventListener("micky-workspace-confirmation-outcome", async (event) => {
    if (!pending) return;
    const result = event.detail || {};
    if (result.status === "executed") {
      try {
        const receipt = await readReceipt(pending.key);
        if (receipt.status === "succeeded") {
          clearPending();
          setText(itemStatus, receipt.message);
          await refreshWorkspace();
        } else {
          setText(itemStatus, "The confirmation reported execution, but its receipt is not verified. Keep the same key; do not retry with a new one.");
        }
      } catch (err) {
        setText(itemStatus, "The operation may have completed; receipt recovery failed. Do not retry with a new key.");
      }
    } else if (["failed", "cancelled", "rejected"].includes(result.status)) {
      try {
        await jsonRequest(
          "/api/assistant/workspace/receipts/" + encodeURIComponent(pending.key),
          { method: "DELETE", headers: { "Content-Type": "application/json" }, body: "{}" }
        );
        clearPending();
        setText(itemStatus, result.status === "failed"
          ? "The change failed and was not committed; you may prepare it again."
          : "The change was not applied; its operation key was abandoned.");
      } catch (err) {
        setText(itemStatus, "The decision ended but the operation key remains reserved: " + err.message);
      }
    } else if (result.status === "unknown") {
      try {
        const receipt = await readReceipt(pending.key);
        if (receipt.status === "succeeded") {
          clearPending();
          setText(itemStatus, receipt.message);
          await refreshWorkspace();
        } else {
          setText(
            itemStatus,
            "The confirmation outcome is unknown. Inspect the receipt and confirmation records; do not retry with a new key."
          );
        }
      } catch (err) {
        setText(itemStatus, "The confirmation outcome is unknown. Do not retry with a new key.");
      }
    }
  });

  async function refreshRecovery() {
    if (!pending) return;
    try {
      const receipt = await readReceipt(pending.key);
      if (receipt.status === "succeeded") {
        clearPending();
        setText(itemStatus, receipt.message);
        await refreshWorkspace();
      } else {
        setText(
          itemStatus,
          receipt.message +
            " Do not prepare a different operation until this key is resolved."
        );
      }
    } catch (err) {
      setText(itemStatus, "The prior operation cannot yet be verified. Do not create a new operation key.");
    }
  }

  timezoneInput.value = currentTimezone();
  dueFields.hidden = true;
  refreshWorkspace();
  loadClinicalSessions();
  refreshRecovery();
  // In-app reminder surfacing only; no background or OS notification.
  window.setInterval(refreshItems, 60000);
})();