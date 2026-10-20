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
﻿// ----------------------------------------------------------------------------
// Scenarios
// ----------------------------------------------------------------------------
const H = module.exports;

function conv(id, title) {
  return {
    id, title,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  };
}
function msg(id, cid, role, seq, content) {
  return {
    id, conversation_id: cid, role, content, sequence: seq,
    created_at: "2026-01-01T00:00:00Z",
  };
}
function pageOfConversations(pageIndex, pageSize, total) {
  const start = pageIndex * pageSize;
  const end = Math.min(start + pageSize, total);
  const out = [];
  for (let i = start; i < end; i++) out.push(conv("C" + i, "Conversation " + i));
  return out;
}
function pageOfMessages(cid, offset, limit, total) {
  const start = offset;
  const end = Math.min(offset + limit, total);
  const out = [];
  for (let i = start; i < end; i++) {
    out.push(msg("m" + i, cid, i % 2 === 0 ? "user" : "assistant",
                 i, "msg " + i));
  }
  return out;
}
function selectedId() {
  return global.window.__mickyConversations
    ? global.window.__mickyConversations.getSelectedId()
    : null;
}
function isAmbiguous(id) {
  return global.window.__mickyConversations.isAmbiguous(id);
}

async function bootstrap(pageIndex, pageSize, total) {
  const page = pageOfConversations(pageIndex, pageSize, total);
  H.enqueue(async () => H.jsonResponse(page, 200,
    { "X-Total-Count": String(total) }));
  H.runApp();
  await H.drain(25);
}

// Enqueue the two fetches that a select/reload of `conversationId` needs
// (fresh total via limit=1, then the latest page at the correct offset),
// then click row `rowIdx` and wait for handlers to run.
async function selectViaUI(rowIdx, conversationId, total, pageFn) {
  H.enqueue(async (url) => {
    if (!url.includes("limit=1&offset=0")) {
      throw new Error("expected total fetch, got " + url);
    }
    return H.jsonResponse([], 200, { "X-Total-Count": String(total) });
  });
  H.enqueue(async (url) => {
    const expectedOffset = total > 200
      ? Math.floor((total - 1) / 200) * 200
      : 0;
    if (!url.includes("offset=" + expectedOffset)) {
      throw new Error("expected offset=" + expectedOffset + ", got " + url);
    }
    const page = pageFn ? pageFn(expectedOffset) : [];
    return H.jsonResponse(page, 200, { "X-Total-Count": String(total) });
  });
  const list = H.registry["conversations-list"];
  if (list.children.length <= rowIdx) {
    throw new Error("row " + rowIdx + " missing (have " + list.children.length + ")");
  }
  list.children[rowIdx].children[0].click();
  await H.drain(30);
}

// --- 1. Selection preserved across realistic list pages -------------------
async function scenarioSelectionPreserved() {
  await bootstrap(0, 50, 51);
  await selectViaUI(0, "C0", 0);
  const before = selectedId();
  H.enqueue(async (url) => {
    if (!url.includes("offset=50")) throw new Error("expected offset=50, got " + url);
    return H.jsonResponse(pageOfConversations(1, 50, 51), 200,
      { "X-Total-Count": "51" });
  });
  H.registry["conversations-next"].click();
  await H.drain(25);
  const afterPage2 = selectedId();
  H.enqueue(async (url) => {
    if (!url.includes("offset=0")) throw new Error("expected offset=0, got " + url);
    return H.jsonResponse(pageOfConversations(0, 50, 51), 200,
      { "X-Total-Count": "51" });
  });
  H.registry["conversations-prev"].click();
  await H.drain(25);
  const afterPage1 = selectedId();
  return {
    ok: true, scenario: "selection-preserved",
    selectedBefore: before,
    selectedAfterPage2: afterPage2,
    selectedAfterPage1: afterPage1,
    composerMode: H.registry["composer-mode"].textContent,
    preserved: before === "C0" && afterPage2 === "C0" && afterPage1 === "C0",
  };
}

// --- 2. Refresh after save loads latest page at 402 ----------------------
async function scenarioRefreshLastPage() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  H.registry["message"].value = "hi";
  H.enqueue(async () => H.jsonResponse({ status: "success", message: "ok" }, 200, {}));
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "402" });
  });
  H.enqueue(async (url) => {
    if (!url.includes("offset=400")) throw new Error("expected offset=400, got " + url);
    return H.jsonResponse(pageOfMessages("C0", 400, 200, 402), 200,
      { "X-Total-Count": "402" });
  });
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(40);
  const fetches = H.fetchLog.map((f) => f.url).filter((u) => u.includes("/messages"));
  return {
    ok: true, scenario: "refresh-last-page",
    fetches, lastPageLoaded: fetches.some((u) => u.includes("offset=400")),
  };
}

// --- 3. 503 marks ambiguous and blocks retry ------------------------------
async function scenarioHttp503Ambiguous() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.registry["message"].value = "hello";
  H.enqueue(async () => H.jsonResponse({ detail: "err" }, 503, {}));
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(30);
  const amb = isAmbiguous("C0");
  const before = H.fetchLog.length;
  H.enqueue(async () => H.jsonResponse({ status: "success", message: "x" }, 200, {}));
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(25);
  const after = H.fetchLog.length;
  return {
    ok: true, scenario: "http-503-ambiguous",
    ambiguous: amb, blockedRetry: before === after,
    statusText: H.registry["status"].textContent,
  };
}

// --- 4. Clicking selected title reloads and clears ambiguity -------------
async function scenarioReloadClickClears() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous("C0");
  const before = isAmbiguous("C0");
  await selectViaUI(0, "C0", 0);   // reload via title click
  const after = isAmbiguous("C0");
  return {
    ok: true, scenario: "reload-click-clears",
    ambiguousBeforeClick: before, ambiguousAfterClick: after,
    cleared: before === true && after === false,
  };
}

// --- 5. Reload failure keeps ambiguity -----------------------------------
async function scenarioReloadFailureKeeps() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous("C0");
  H.enqueue(async () => { throw new Error("boom"); });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "reload-failure-keeps",
    ambiguous: isAmbiguous("C0"), kept: isAmbiguous("C0") === true,
  };
}

// --- 6. Switch clears stale messages -------------------------------------
async function scenarioSwitchClearsMessages() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 1, () => [msg("m0", "C0", "user", 0, "fromA")]);
  const msgsAfterA = H.textOf(H.registry["conversation-messages"]);
  H.enqueue(async () => { throw new Error("boom"); });
  H.registry["conversations-list"].children[1].children[0].click();
  await H.drain(30);
  const msgsAfterB = H.textOf(H.registry["conversation-messages"]);
  return {
    ok: true, scenario: "switch-clears-messages",
    msgsAfterA_containsFromA: msgsAfterA.includes("fromA"),
    msgsAfterB_containsFromA: msgsAfterB.includes("fromA"),
    cleared: msgsAfterB.indexOf("fromA") < 0,
  };
}

// --- 7. Ambiguous reload uses latest page (finding 1) --------------------
async function scenarioReloadUsesLatestPage() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous("C0");
  // Reload: fresh total 400, page at offset 200
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "400" });
  });
  H.enqueue(async (url) => {
    if (!url.includes("offset=200")) throw new Error("expected offset=200, got " + url);
    return H.jsonResponse(pageOfMessages("C0", 200, 200, 400), 200,
      { "X-Total-Count": "400" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  const cleared = !isAmbiguous("C0");
  return {
    ok: true, scenario: "reload-uses-latest-page",
    cleared, usedLastPage: true,
  };
}

// --- 8. Failed total fetch keeps ambiguity -------------------------------
async function scenarioReloadTotalFail() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous("C0");
  H.enqueue(async () => { throw new Error("total fetch boom"); });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "reload-total-fail",
    ambiguous: isAmbiguous("C0"), kept: isAmbiguous("C0") === true,
  };
}

// --- 9. Failed latest-page fetch keeps ambiguity -------------------------
async function scenarioReloadPageFail() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous("C0");
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "400" });
  });
  H.enqueue(async () => { throw new Error("page boom"); });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "reload-page-fail",
    ambiguous: isAmbiguous("C0"), kept: isAmbiguous("C0") === true,
  };
}

// --- 10. Duplicate submit blocked during reload --------------------------
async function scenarioDuplicateDuringLoad() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous("C0");
  // Start a reload whose total fetch we do NOT enqueue yet — it will hang
  let resolveTotal;
  H.enqueue(function () {
    return new Promise((resolve) => { resolveTotal = resolve; });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(5);
  // Attempt submit while total fetch is pending
  H.registry["message"].value = "hi";
  const before = H.fetchLog.length;
  H.enqueue(async () => H.jsonResponse({ status: "success", message: "x" }, 200, {}));
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(10);
  const after = H.fetchLog.length;
  // Release and let it drain so no hangs remain
  if (resolveTotal) resolveTotal(H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  await H.drain(20);
  return {
    ok: true, scenario: "duplicate-during-load",
    before, after, blocked: before === after,
  };
}

// --- 11. Stale reload response does not clobber newer selection ----------
async function scenarioStaleReload() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 1, () => [msg("m0", "C0", "user", 0, "fromA")]);
  // Start a reload of C0 that we will resolve AFTER switching to C1.
  let resolveA1;
  H.enqueue(function () {
    return new Promise((r) => { resolveA1 = r; });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(5);
  // Now switch to C1 — its fetch resolves normally
  await selectViaUI(1, "C1", 1, () => [msg("m0", "C1", "user", 0, "fromB")]);
  const afterB = H.textOf(H.registry["conversation-messages"]);
  // Release the stale A total fetch; its response should be ignored
  resolveA1(H.jsonResponse([], 200, { "X-Total-Count": "1" }));
  await H.drain(20);
  const afterStale = H.textOf(H.registry["conversation-messages"]);
  const selected = selectedId();
  return {
    ok: true, scenario: "stale-reload",
    afterB_containsFromB: afterB.includes("fromB"),
    afterStale_containsFromB: afterStale.includes("fromB"),
    afterStale_containsFromA: afterStale.includes("fromA"),
    selected, stillB: selected === "C1",
  };
}

// --- 12. Create succeeds, list refresh fails -----------------------------
async function scenarioCreateThenListFail() {
  await bootstrap(0, 50, 0);
  // Click New — POST succeeds
  H.enqueue(async () => H.jsonResponse(
    { id: "Cnew", title: "New conversation" }, 201, {}));
  // List refresh fails
  H.enqueue(async () => { throw new Error("list boom"); });
  H.registry["conversations-new"].click();
  await H.drain(30);
  const title = H.registry["conversation-current-title"].textContent;
  const sel = selectedId();
  const statusText = H.registry["conversations-status"].textContent;
  return {
    ok: true, scenario: "create-then-list-fail",
    title, selected: sel, statusText,
    titleFromPost: title === "New conversation",
    selectedIdFromPost: sel === "Cnew",
    showsListRefreshError: /could not be refreshed|created, but/i.test(statusText),
  };
}

// --- 13. Create POST network failure is ambiguous ------------------------
async function scenarioCreateNetworkFail() {
  await bootstrap(0, 50, 0);
  H.enqueue(async () => { throw new Error("network boom"); });
  H.registry["conversations-new"].click();
  await H.drain(20);
  const statusText = H.registry["conversations-status"].textContent;
  return {
    ok: true, scenario: "create-network-fail",
    statusText,
    isAmbiguous: /could not be confirmed|may have created/i.test(statusText),
    noAutomaticRetry: H.fetchLog.filter((f) => f.method === "POST").length === 1,
  };
}

// --- 14. Latest-page offset at a single boundary (argv[4] = total) ------
// The pytest wrapper invokes this scenario once per boundary so each run
// starts with a fresh harness in a fresh Node process.
async function scenarioMessageBoundary() {
  const boundary = parseInt(process.argv[4] || "402", 10);
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.registry["message"].value = "hi";
  H.enqueue(async () => H.jsonResponse({ status: "success", message: "ok" }, 200, {}));
  H.enqueue(async () => H.jsonResponse([], 200,
    { "X-Total-Count": String(boundary) }));
  const expected = Math.floor((boundary - 1) / 200) * 200;
  let sawExpected = false;
  H.enqueue(async (url) => {
    if (url.includes("offset=" + expected)) sawExpected = true;
    return H.jsonResponse([], 200, { "X-Total-Count": String(boundary) });
  });
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(40);
  return {
    ok: true, scenario: "message-boundary",
    boundary, expectedOffset: expected, sawExpected,
  };
}

// ----------------------------------------------------------------------------
// Registration
// ----------------------------------------------------------------------------
const SCENARIOS = {
  "selection-preserved": scenarioSelectionPreserved,
  "refresh-last-page": scenarioRefreshLastPage,
  "http-503-ambiguous": scenarioHttp503Ambiguous,
  "reload-click-clears": scenarioReloadClickClears,
  "reload-failure-keeps": scenarioReloadFailureKeeps,
  "switch-clears-messages": scenarioSwitchClearsMessages,
  "reload-uses-latest-page": scenarioReloadUsesLatestPage,
  "reload-total-fail": scenarioReloadTotalFail,
  "reload-page-fail": scenarioReloadPageFail,
  "duplicate-during-load": scenarioDuplicateDuringLoad,
  "stale-reload": scenarioStaleReload,
  "create-then-list-fail": scenarioCreateThenListFail,
  "create-network-fail": scenarioCreateNetworkFail,
  "message-boundary": scenarioMessageBoundary,
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
