"use strict";

// Behavioural harness for Task 230 conversation UI.
// Runs the real src/rop/web/static/app.js against a minimal DOM/fetch mock
// and drives actual click/submit handlers.
//
// Usage: node conversations_ui_harness.cjs <app.js path> <scenario>
//   scenarios:
//     selection-preserved    - navigating pages does not deselect
//     http-503-ambiguous     - 503 on selected conv marks ambiguous, blocks retry
//     reload-click-clears    - clicking selected title reloads; ambiguity clears only on success
//     reload-failure-keeps   - failed reload keeps ambiguity
//     refresh-last-page      - post-success refresh uses fresh total from server
//     switch-clears-messages - failed fetch on switch never shows old msgs under new title
//     duplicate-during-load  - submit blocked while reload in flight

const fs = require("fs");

function makeEl(id) {
  const listeners = {};
  const attrs = {};
  const el = {
    id, tagName: "DIV", className: "", _text: "",
    value: "", disabled: false, hidden: false, checked: false,
    type: "text", colSpan: 1, children: [], parentNode: null,
    dataset: {},
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k]; },
    removeAttribute(k) { delete attrs[k]; },
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
    removeChild(c) {
      const i = this.children.indexOf(c);
      if (i >= 0) this.children.splice(i, 1);
      c.parentNode = null; return c;
    },
    insertBefore(c, ref) {
      if (ref == null) return this.appendChild(c);
      const i = this.children.indexOf(ref);
      if (i < 0) return this.appendChild(c);
      this.children.splice(i, 0, c); c.parentNode = this; return c;
    },
    addEventListener(evt, cb) { (listeners[evt] = listeners[evt] || []).push(cb); },
    removeEventListener(evt, cb) {
      const l = listeners[evt]; if (l) { const i = l.indexOf(cb); if (i >= 0) l.splice(i, 1); }
    },
    focus() {},
    click() {
      const l = listeners["click"] || [];
      for (const cb of l) cb({ preventDefault() {}, target: this });
    },
    _listeners: listeners, _attrs: attrs,
  };
  Object.defineProperty(el, "textContent", {
    get() { return this._text; },
    set(v) { this._text = String(v); this.children = []; },
  });
  Object.defineProperty(el, "firstChild", { get() { return this.children[0] || null; } });
  return el;
}

function textOf(el) {
  if (!el) return "";
  let s = el._text || "";
  for (const c of el.children) s += textOf(c);
  return s;
}

// element ids we need: every getElementById in app.js for the conversations
// module, plus the general chat ones (they must exist so the top-level
// module loads without null errors).
const ids = [
  "request-form", "message", "submit", "status", "history",
  "confirmation-card", "confirmation-summary", "confirmation-display-code",
  "confirmation-expiry", "confirmation-code-input",
  "confirmation-confirm", "confirmation-cancel",
  "records-load", "records-export", "records-delete", "records-status",
  "records-pagination", "records-prev", "records-next", "records-range",
  "records-table", "records-tbody",
  "conversations-section", "conversations-new", "conversations-status",
  "conversations-list", "conversations-empty",
  "conversations-pagination", "conversations-prev", "conversations-next",
  "conversations-range",
  "conversation-view", "conversation-view-heading",
  "conversation-current-title", "conversation-rename-input",
  "conversation-rename", "conversation-delete",
  "conversation-messages-status", "conversation-messages",
  "conversation-messages-empty",
  "messages-pagination", "messages-prev", "messages-next", "messages-range",
  "composer-mode", "message-help",
];
const registry = {};
for (const id of ids) registry[id] = makeEl(id);
// The real HTML marks the confirmation card hidden initially; the mock
// default of false would cause the submit handler to short-circuit.
registry["confirmation-card"].hidden = true;
registry["conversation-view"].hidden = true;
registry["conversations-pagination"].hidden = true;
registry["messages-pagination"].hidden = true;
const body = makeEl("body");
const documentMock = {
  getElementById(id) { return registry[id] || null; },
  createElement(tag) { const e = makeEl(null); e.tagName = String(tag).toUpperCase(); return e; },
  body,
};

// fetch mock: queue of handlers consumed in order.
const queue = [];
const fetchLog = [];
function enqueue(fn) { queue.push(fn); }
async function fetchMock(url, opts) {
  fetchLog.push({ url: String(url), method: (opts && opts.method) || "GET" });
  const h = queue.shift();
  if (!h) throw new Error("unexpected fetch: " + url);
  return h(String(url), opts);
}
function jsonResponse(payload, status, headers) {
  status = status || 200;
  const hs = Object.assign({}, headers || {});
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get(k) { return hs[k] || hs[k.toLowerCase()] || null; } },
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  };
}

const confirmQueue = [];
const windowMock = { confirm: () => confirmQueue.shift() };
const URLMock = { createObjectURL: () => "blob:x", revokeObjectURL: () => {} };
const BlobMock = function(parts, opts) { this.parts = parts; this.opts = opts; };
function setTimeoutImmediate(fn) { fn(); return 0; }

function runApp() {
  // Expose windowMock globally so scenario helpers can inspect
  // window.__mickyConversations without going through the app's closure.
  Object.defineProperty(global, "window", {
    value: windowMock,
    configurable: true,
    writable: true,
  });
  const src = fs.readFileSync(process.argv[2], "utf8").replace(/^\uFEFF/, "");
  const fn = new Function(
    "document", "window", "fetch", "URL", "Blob", "setTimeout", src
  );
  fn(documentMock, windowMock, fetchMock, URLMock, BlobMock, setTimeoutImmediate);
}

function drain(n) {
  let p = Promise.resolve();
  for (let i = 0; i < (n || 12); i++) {
    p = p.then(() => new Promise((r) => setImmediate(r)));
  }
  return p;
}

module.exports = {
  runApp, drain, enqueue, jsonResponse, fetchLog,
  registry, documentMock, textOf, confirmQueue,
};

// ----------------------------------------------------------------------------
// Scenarios
// ----------------------------------------------------------------------------

const H = module.exports;

function conv(id, title) {
  return { id, title, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z" };
}
function msg(id, cid, role, seq, content) {
  return {
    id, conversation_id: cid, role, content, sequence: seq,
    created_at: "2026-01-01T00:00:00Z",
  };
}

function selectedId() {
  return global.window.__mickyConversations
    ? global.window.__mickyConversations.getSelectedId()
    : null;
}
function isAmbiguous(id) {
  return global.window.__mickyConversations.isAmbiguous(id);
}

// Common bootstrap: enqueue the initial list response, then runApp.
// runApp() synchronously triggers loadConversations(), so the queue
// handler must already be present.
async function bootstrap(initialConversations, initialTotal) {
  H.enqueue(async () => H.jsonResponse(initialConversations, 200,
    { "X-Total-Count": String(initialTotal) }));
  H.runApp();
  await H.drain(25);
  const list = H.registry["conversations-list"];
  if (list.children.length !== initialConversations.length) {
    throw new Error(
      "list did not render; got " + list.children.length + " children, " +
      "status: " + H.registry["conversations-status"].textContent
    );
  }
}

async function scenarioSelectionPreserved() {
  await bootstrap([conv("A", "A")], 2);

  // Select A
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(25);
  const beforePage = selectedId();

  // Navigate to page 2 (list page 2 shows only B)
  H.enqueue(async () => H.jsonResponse([conv("B", "B")], 200, { "X-Total-Count": "2" }));
  H.registry["conversations-next"].click();
  await H.drain(25);
  const afterPage = selectedId();

  return {
    ok: true,
    scenario: "selection-preserved",
    selectedBeforePage: beforePage,
    selectedAfterPage: afterPage,
    composerMode: H.registry["composer-mode"].textContent,
    preserved: beforePage === "A" && afterPage === "A",
  };
}

async function scenarioHttp503Ambiguous() {
  await bootstrap([conv("A", "A")], 1);

  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(25);

  // Submit a message whose persistence returns 503
  H.registry["message"].value = "hello";
  H.enqueue(async () => H.jsonResponse({ detail: "The exchange could not be completed." }, 503, {}));
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(30);

  const amb = isAmbiguous("A");
  const status1 = H.registry["status"].textContent;

  // Count fetches before attempting a second submit. If the retry is
  // blocked, no new fetch will occur.
  const before = H.fetchLog.length;
  // Enqueue a handler in case the fetch is wrongly made.
  H.enqueue(async () => H.jsonResponse({ status: "success", message: "x" }, 200, {}));
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(30);
  const after = H.fetchLog.length;

  return {
    ok: true,
    scenario: "http-503-ambiguous",
    ambiguous: amb,
    statusText: status1,
    blockedRetry: before === after,
  };
}

async function scenarioReloadClickClears() {
  await bootstrap([conv("A", "A")], 1);

  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(25);

  global.window.__mickyConversations.markAmbiguous("A");
  const before = isAmbiguous("A");

  // Click the already-selected title -> reloadSelected path
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(25);
  const after = isAmbiguous("A");

  return {
    ok: true,
    scenario: "reload-click-clears",
    ambiguousBeforeClick: before,
    ambiguousAfterClick: after,
    cleared: before === true && after === false,
  };
}

async function scenarioReloadFailureKeeps() {
  await bootstrap([conv("A", "A")], 1);

  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(25);

  global.window.__mickyConversations.markAmbiguous("A");

  // Click selected title; reload fetch fails
  H.enqueue(async () => { throw new Error("boom"); });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  const amb = isAmbiguous("A");

  return {
    ok: true,
    scenario: "reload-failure-keeps",
    ambiguous: amb,
    kept: amb === true,
  };
}

async function scenarioRefreshLastPage() {
  await bootstrap([conv("A", "A")], 1);

  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "400" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(25);

  // Submit; success response; then two follow-up fetches:
  //   1) limit=1 offset=0 to get fresh total = 402
  //   2) last page at offset 400
  H.registry["message"].value = "hi";
  H.enqueue(async () => H.jsonResponse({
    status: "success", message: "Hello! I can help.",
  }, 200, {}));
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([msg("m0", "A", "user", 0, "x")], 200,
      { "X-Total-Count": "402" });
  });
  H.enqueue(async (url) => {
    if (!url.includes("offset=400")) throw new Error("expected offset=400, got " + url);
    return H.jsonResponse([
      msg("m400", "A", "user", 400, "hello"),
      msg("m401", "A", "assistant", 401, "Hello! I can help."),
    ], 200, { "X-Total-Count": "402" });
  });
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(30);

  const messageFetches = H.fetchLog.map((f) => f.url).filter((u) => u.includes("/messages"));
  return {
    ok: true,
    scenario: "refresh-last-page",
    messageFetches,
    usedFreshTotal: messageFetches.some((u) => u.includes("limit=1&offset=0")),
    loadedLastPage: messageFetches.some((u) => u.includes("offset=400")),
  };
}

async function scenarioSwitchClearsMessages() {
  await bootstrap([conv("A", "A"), conv("B", "B")], 2);

  // Select A
  H.enqueue(async () => H.jsonResponse(
    [msg("m1", "A", "user", 0, "fromA")], 200, { "X-Total-Count": "1" }
  ));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(25);
  const msgsAfterA = H.textOf(H.registry["conversation-messages"]);

  // Now click B; message fetch fails
  H.enqueue(async () => { throw new Error("boom"); });
  H.registry["conversations-list"].children[1].children[0].click();
  await H.drain(30);
  const msgsAfterB = H.textOf(H.registry["conversation-messages"]);

  return {
    ok: true,
    scenario: "switch-clears-messages",
    msgsAfterA_containsFromA: msgsAfterA.includes("fromA"),
    msgsAfterB_containsFromA: msgsAfterB.includes("fromA"),
    cleared: msgsAfterB.indexOf("fromA") < 0,
  };
}

const SCENARIOS = {
  "selection-preserved": scenarioSelectionPreserved,
  "http-503-ambiguous": scenarioHttp503Ambiguous,
  "reload-click-clears": scenarioReloadClickClears,
  "reload-failure-keeps": scenarioReloadFailureKeeps,
  "refresh-last-page": scenarioRefreshLastPage,
  "switch-clears-messages": scenarioSwitchClearsMessages,
};

(async function main() {
  const name = process.argv[3];
  const fn = SCENARIOS[name];
  if (!fn) {
    console.error("unknown scenario:", name);
    process.exit(2);
  }
  try {
    const result = await fn();
    process.stdout.write(JSON.stringify(result) + "\n");
    process.exit(0);
  } catch (err) {
    console.error("SCENARIO FAILURE [" + name + "]:", err.message);
    process.exit(1);
  }
})();
