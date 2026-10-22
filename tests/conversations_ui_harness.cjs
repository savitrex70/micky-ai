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
  "conversations-section", "conversations-new", "conversations-refresh",
  "conversations-status",
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
  fetchLog.push({
    url: String(url),
    method: (opts && opts.method) || "GET",
    body: opts && typeof opts.body === "string" ? opts.body : null,
  });
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
const _sessionStorageValues = Object.create(null);
const windowMock = {
  confirm: () => confirmQueue.shift(),
  sessionStorage: {
    getItem(key) {
      return Object.prototype.hasOwnProperty.call(_sessionStorageValues, key)
        ? _sessionStorageValues[key] : null;
    },
    setItem(key, value) { _sessionStorageValues[key] = String(value); },
    removeItem(key) { delete _sessionStorageValues[key]; },
    clear() {
      for (const key of Object.keys(_sessionStorageValues)) {
        delete _sessionStorageValues[key];
      }
    },
  },
};
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
  registry, documentMock, textOf, confirmQueue, uuidFrom,
};

// ----------------------------------------------------------------------------
// Scenarios
// ----------------------------------------------------------------------------
﻿// ----------------------------------------------------------------------------
// Scenarios
// ----------------------------------------------------------------------------
const H = module.exports;

// Deterministic UUID-shape value derived from a short name. The app's
// validator only requires 8-4-4-4-12 hex; producing it deterministically
// keeps fixture IDs stable across runs while satisfying the contract.
function uuidFrom(name) {
  // FNV-1a 32-bit seeded twice with different offsets, concatenated to
  // produce 64 bits of hex. Enough distinctness that "C0" and "C1" are
  // visibly different.
  const s = String(name);
  function fnv(seed) {
    let h = seed >>> 0;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
    }
    return h >>> 0;
  }
  const a = fnv(0x811c9dc5);
  const b = fnv(0x050c5d1f);
  const hex = "0123456789abcdef";
  let out = "";
  for (let i = 0; i < 8; i++) out += hex[(a >>> (i * 4)) & 0xf];
  for (let i = 0; i < 8; i++) out += hex[(b >>> (i * 4)) & 0xf];
  // Pad with additional derived bits if needed to reach 32 hex chars.
  while (out.length < 32) out += hex[out.length % 16];
  return out.slice(0,8) + "-" + out.slice(8,12) + "-" + out.slice(12,16)
    + "-" + out.slice(16,20) + "-" + out.slice(20,32);
}
function conv(id, title) {
  return {
    id: uuidFrom(id),
    title,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  };
}
function msg(id, cid, role, seq, content) {
  return {
    id: uuidFrom(id),
    conversation_id: uuidFrom(cid),
    role, content, sequence: seq,
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
    preserved: before === uuidFrom("C0") && afterPage2 === uuidFrom("C0") && afterPage1 === uuidFrom("C0"),
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
  const amb = isAmbiguous(uuidFrom("C0"));
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
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const before = isAmbiguous(uuidFrom("C0"));
  await selectViaUI(0, "C0", 0);   // reload via title click
  const after = isAmbiguous(uuidFrom("C0"));
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
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => { throw new Error("boom"); });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "reload-failure-keeps",
    ambiguous: isAmbiguous(uuidFrom("C0")), kept: isAmbiguous(uuidFrom("C0")) === true,
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
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const fetchPosBefore = H.fetchLog.length;
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
  const cleared = !isAmbiguous(uuidFrom("C0"));
  // Only fetches after the reload click count.
  const postReload = H.fetchLog
    .slice(fetchPosBefore)
    .map((f) => f.url)
    .filter((u) => u.includes("/messages"));
  const sawLatestPage = postReload.some((u) => u.includes("offset=200"));
  // Verify the newest message (seq 399) is rendered before the guard cleared.
  const rendered = H.textOf(H.registry["conversation-messages"]);
  const sawNewest = rendered.indexOf("msg 399") >= 0;
  return {
    ok: true, scenario: "reload-uses-latest-page",
    cleared, sawLatestPage, sawNewest,
  };
}

// --- 8. Failed total fetch keeps ambiguity -------------------------------
async function scenarioReloadTotalFail() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => { throw new Error("total fetch boom"); });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "reload-total-fail",
    ambiguous: isAmbiguous(uuidFrom("C0")), kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

// --- 9. Failed latest-page fetch keeps ambiguity -------------------------
async function scenarioReloadPageFail() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "400" });
  });
  H.enqueue(async () => { throw new Error("page boom"); });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "reload-page-fail",
    ambiguous: isAmbiguous(uuidFrom("C0")), kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

// --- 10. Duplicate submit blocked during reload --------------------------
async function scenarioDuplicateDuringLoad() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
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
    selected, stillB: selected === uuidFrom("C1"),
  };
}

// --- 12. Create succeeds, list refresh fails -----------------------------
async function scenarioCreateThenListFail() {
  await bootstrap(0, 50, 0);
  // Click New — POST succeeds
  H.enqueue(async () => H.jsonResponse(
    conv("Cnew", "New conversation"), 201, {}));
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
    selectedIdFromPost: sel === uuidFrom("Cnew"),
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
  // Capture fetch-log position BEFORE submit so we can prove the
  // refresh did its own total + page fetches, rather than being
  // satisfied by the earlier selectViaUI's offset=0 page load.
  const fetchPosBeforeSubmit = H.fetchLog.length;
  H.enqueue(async () => H.jsonResponse({ status: "success", message: "ok" }, 200, {}));
  // Refresh: fresh total
  H.enqueue(async (url) => {
    if (!url.includes("limit=1&offset=0")) {
      throw new Error("refresh should query fresh total, got " + url);
    }
    return H.jsonResponse([], 200, { "X-Total-Count": String(boundary) });
  });
  const expected = Math.floor((boundary - 1) / 200) * 200;
  // Refresh: latest page
  H.enqueue(async (url) => {
    if (!url.includes("offset=" + expected)) {
      throw new Error("expected offset=" + expected + ", got " + url);
    }
    return H.jsonResponse(
      pageOfMessages("C0", expected, 200, boundary),
      200,
      { "X-Total-Count": String(boundary) },
    );
  });
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(40);
  // Only fetches made AFTER the submit count as proof of refresh.
  const postSubmit = H.fetchLog
    .slice(fetchPosBeforeSubmit)
    .map((f) => f.url)
    .filter((u) => u.includes("/messages"));
  const sawFreshTotal = postSubmit.some((u) => u.includes("limit=1&offset=0"));
  const sawLatestPage = postSubmit.some(
    (u) => u.includes("offset=" + expected)
  );
  // Verify the newest message is actually rendered, not just requested.
  const rendered = H.textOf(H.registry["conversation-messages"]);
  const newestIndex = boundary - 1;
  const sawNewestRendered = rendered.indexOf("msg " + newestIndex) >= 0;
  return {
    ok: true,
    scenario: "message-boundary",
    boundary,
    expectedOffset: expected,
    postSubmitFetches: postSubmit,
    sawFreshTotal,
    sawLatestPage,
    sawNewestRendered,
  };
}


// --- 15. Refresh conversations button preserves selection ---------------
async function scenarioRefreshButtonPreservesSelection() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  const before = selectedId();
  const beforeTitle = H.registry["conversation-current-title"].textContent;
  const beforeMode = H.registry["composer-mode"].textContent;
  // Click Refresh conversations — enqueued before click.
  // Use the SAME titles the bootstrap used so the app's legitimate
  // title-sync (server is authority) does not change the displayed title.
  H.enqueue(async (url) => {
    if (!url.includes("offset=0")) throw new Error("refresh must request offset=0, got " + url);
    return H.jsonResponse(
      [conv("C0", "Conversation 0"), conv("C1", "Conversation 1")],
      200,
      { "X-Total-Count": "2" }
    );
  });
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  const after = selectedId();
  const afterTitle = H.registry["conversation-current-title"].textContent;
  const afterMode = H.registry["composer-mode"].textContent;
  return {
    ok: true, scenario: "refresh-button-preserves-selection",
    before, after, beforeTitle, afterTitle, beforeMode, afterMode,
    preserved: before === uuidFrom("C0") && after === uuidFrom("C0") &&
               beforeTitle === afterTitle && beforeMode === afterMode,
  };
}

// --- 16. Refresh failure then success, error visible in between ----------
async function scenarioRefreshFailureThenSuccess() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  // First refresh fails
  H.enqueue(async () => { throw new Error("refresh boom"); });
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  const errStatus = H.registry["conversations-status"].textContent;
  const errKind = H.registry["conversations-status"].getAttribute("data-kind");
  // Second refresh succeeds
  H.enqueue(async () => H.jsonResponse([conv("C0", "C0"), conv("C1", "C1")], 200,
    { "X-Total-Count": "2" }));
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  const okStatus = H.registry["conversations-status"].textContent;
  return {
    ok: true, scenario: "refresh-failure-then-success",
    errStatus, errKind, okStatus,
    firstShowsError: errKind === "error" && /could not/i.test(errStatus),
    secondCleared: okStatus === "" || !/could not/i.test(okStatus),
  };
}

// --- 17. Confirmed 404 for selected conversation clears selection --------
async function scenario404ClearsSelection() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  // Trigger a reload that returns 404 (total fetch 404)
  H.enqueue(async () => H.jsonResponse({ detail: "The conversation does not exist." }, 404, {}));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  const sel = selectedId();
  const title = H.registry["conversation-current-title"].textContent;
  const msgs = H.textOf(H.registry["conversation-messages"]);
  const statusText = H.registry["conversation-messages-status"].textContent;
  const mode = H.registry["composer-mode"].textContent;
  return {
    ok: true, scenario: "404-clears-selection",
    sel, title, msgs,
    statusText, mode,
    cleared: sel === null,
    titleBlank: title === "",
    msgsEmpty: msgs.trim() === "",
    mentionsNoLongerExists: /no longer exists/i.test(statusText),
    modeIsTransient: /not be saved|transient/i.test(mode),
  };
}

// --- 18. Network failure preserves selection ----------------------------
async function scenarioNetworkErrorPreservesSelection() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  // Trigger a reload that throws
  H.enqueue(async () => { throw new Error("net boom"); });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  const sel = selectedId();
  const title = H.registry["conversation-current-title"].textContent;
  return {
    ok: true, scenario: "network-error-preserves-selection",
    sel, title,
    preserved: sel === uuidFrom("C0") && title === "Conversation 0",
  };
}

// --- 19. Stale 404 for another conversation cannot clear ----------------
async function scenarioStaleOtherConv404CannotClear() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  // Start a reload of C0 that we will resolve with 404 AFTER switching to C1.
  let resolveA;
  H.enqueue(function () {
    return new Promise((r) => { resolveA = r; });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(5);
  // Switch to C1 — normal response
  await selectViaUI(1, "C1", 0);
  // Release A's stale 404
  resolveA(H.jsonResponse({ detail: "gone" }, 404, {}));
  await H.drain(20);
  const sel = selectedId();
  return {
    ok: true, scenario: "stale-404-cannot-clear",
    sel,
    preserved: sel === uuidFrom("C1"),
  };
}


// --- 20. Refresh failure preserves pagination state ---------------------
async function scenarioRefreshFailurePreservesPage() {
  // Bootstrap with 51 conversations, go to page 2.
  await bootstrap(0, 50, 51);
  H.enqueue(async (url) => {
    if (!url.includes("offset=50")) throw new Error("expected offset=50, got " + url);
    return H.jsonResponse(pageOfConversations(1, 50, 51), 200,
      { "X-Total-Count": "51" });
  });
  H.registry["conversations-next"].click();
  await H.drain(25);
  const offsetBefore = "50"; // page 2 start
  const rowCountBefore = H.registry["conversations-list"].children.length;
  const rangeBefore = H.registry["conversations-range"].textContent;
  // Failed refresh
  H.enqueue(async () => { throw new Error("refresh boom"); });
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  const rowCountAfter = H.registry["conversations-list"].children.length;
  const rangeAfter = H.registry["conversations-range"].textContent;
  const statusText = H.registry["conversations-status"].textContent;
  const statusKind = H.registry["conversations-status"].getAttribute("data-kind");
  return {
    ok: true, scenario: "refresh-failure-preserves-page",
    rowCountBefore, rowCountAfter,
    rangeBefore, rangeAfter,
    statusKind,
    rowsPreserved: rowCountBefore === rowCountAfter,
    rangePreserved: rangeBefore === rangeAfter,
    isError: statusKind === "error",
  };
}

// --- 21. Create during in-flight list refresh (both resolve) ------------
async function scenarioCreateDuringRefresh() {
  await bootstrap(0, 50, 1);
  // Start a list refresh whose response we hold.
  let resolveList;
  H.enqueue(function () {
    return new Promise((r) => { resolveList = r; });
  });
  H.registry["conversations-refresh"].click();
  await H.drain(5);
  // While list fetch is pending, click New.
  H.enqueue(async () => H.jsonResponse(
    conv("Cnew", "New conversation"), 201, {}));
  // The create's loadConversations(0) must wait for the in-flight one.
  // After list resolves, loadConversations should issue ITS OWN fetch.
  H.enqueue(async (url) => {
    if (!url.includes("offset=0")) throw new Error("expected offset=0, got " + url);
    return H.jsonResponse([conv("Cnew", "New conversation"), conv("C0", "C0")],
      200, { "X-Total-Count": "2" });
  });
  H.registry["conversations-new"].click();
  await H.drain(10);
  // Resolve the original list refresh — its response is stale; the create
  // workflow's own fetch runs after.
  resolveList(H.jsonResponse([conv("C0", "C0")], 200, { "X-Total-Count": "1" }));
  await H.drain(30);
  const sel = selectedId();
  const title = H.registry["conversation-current-title"].textContent;
  const statusText = H.registry["conversations-status"].textContent;
  return {
    ok: true, scenario: "create-during-refresh",
    sel, title, statusText,
    selectedIsNew: sel === uuidFrom("Cnew"),
    titleIsNew: title === "New conversation",
    noFalseFailure: !/could not be refreshed/i.test(statusText),
  };
}

// --- 22. Ambiguous-404 cannot silently save to another conversation -----
async function scenarioAmbiguous404BlocksRepost() {
  await bootstrap(0, 50, 2);  // two conversations A and B
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const ambBefore = isAmbiguous(uuidFrom("C0"));
  // Attempt reload; return 404.
  H.enqueue(async () => H.jsonResponse({ detail: "not found" }, 404, {}));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(25);
  const selAfter404 = selectedId();
  const ambAfter404 = isAmbiguous(uuidFrom("C0"));
  // Attempt to submit now — the composer is transient (no conversation
  // selected), so the request must go out WITHOUT conversation_id, never
  // silently attached to another conversation.
  H.registry["message"].value = "hi";
  const fetchLogBeforeSubmit = H.fetchLog.length;
  H.enqueue(async () => H.jsonResponse({ status: "success", message: "ok" }, 200, {}));
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(20);
  // Find the POST made by the submit.
  let postBody = null;
  let postCount = 0;
  for (let i = fetchLogBeforeSubmit; i < H.fetchLog.length; i++) {
    if (H.fetchLog[i].method === "POST") {
      postCount++;
      if (H.fetchLog[i].body) {
        try { postBody = JSON.parse(H.fetchLog[i].body); } catch (e) { postBody = null; }
      }
    }
  }
  const hasConversationId = postBody !== null &&
    Object.prototype.hasOwnProperty.call(postBody, "conversation_id");
  return {
    ok: true, scenario: "ambiguous-404-blocks-repost",
    ambBefore,
    selAfter404,
    ambAfter404,
    postCount,
    postBody,
    hasConversationId,
    selectionCleared: selAfter404 === null,
    ambiguityCleared: ambAfter404 === false,
    submissionIsTransient: postCount === 1 && !hasConversationId,
  };
}

// --- 23. Malformed latest-page response keeps ambiguity -----------------
async function scenarioRecoveryMalformedPage() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  // Total fetch OK.
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "400" });
  });
  // Page fetch returns non-array body (structurally invalid).
  H.enqueue(async () => H.jsonResponse({ not: "an array" }, 200,
    { "X-Total-Count": "400" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  const amb = isAmbiguous(uuidFrom("C0"));
  return {
    ok: true, scenario: "recovery-malformed-page",
    amb, kept: amb === true,
  };
}


// --- 24. Malformed message records keep ambiguity -----------------------
async function scenarioRecoveryMalformedRecords() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  // Total fetch OK
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "400" });
  });
  // Page fetch returns array containing a malformed record (missing id).
  H.enqueue(async () => {
    const bad = pageOfMessages("C0", 200, 200, 400);
    bad[0] = { id: null, conversation_id: "C0", role: "user",
               content: "x", sequence: 200, created_at: "x" };
    return H.jsonResponse(bad, 200, { "X-Total-Count": "400" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-malformed-records",
    amb: isAmbiguous(uuidFrom("C0")), kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

// --- 25. Missing total header keeps ambiguity ---------------------------
async function scenarioRecoveryMissingTotal() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "400" });
  });
  // Page response has no X-Total-Count header at all.
  H.enqueue(async () => H.jsonResponse(
    pageOfMessages("C0", 200, 200, 400), 200, {}
  ));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-missing-total",
    amb: isAmbiguous(uuidFrom("C0")), kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

// --- 26. Invalid total value keeps ambiguity ---------------------------
async function scenarioRecoveryInvalidTotal() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "400" });
  });
  // Page fetch returns valid records but bogus total header.
  H.enqueue(async () => H.jsonResponse(
    pageOfMessages("C0", 200, 200, 400), 200, { "X-Total-Count": "not-a-number" }
  ));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-invalid-total",
    amb: isAmbiguous(uuidFrom("C0")), kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

// --- 27. Empty page with non-zero total keeps ambiguity ----------------
async function scenarioRecoveryEmptyInconsistent() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "400" });
  });
  // Empty array but header total is still 400 — inconsistent.
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "400" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-empty-inconsistent",
    amb: isAmbiguous(uuidFrom("C0")), kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

// --- 28. Legitimate empty conversation recovers ------------------------
async function scenarioRecoveryEmptyLegitimate() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);  // 0 messages
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const ambBefore = isAmbiguous(uuidFrom("C0"));
  // Reload: total 0, page empty with header 0.
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "0" });
  });
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-empty-legitimate",
    ambBefore,
    ambAfter: isAmbiguous(uuidFrom("C0")),
    cleared: ambBefore === true && isAmbiguous(uuidFrom("C0")) === false,
  };
}

// --- 29. List request serialization ------------------------------------
async function scenarioListSerialization() {
  await bootstrap(0, 50, 51);
  const fetchCountAfterBootstrap = H.fetchLog.length;
  // Hold three list responses via resolvers.
  let r1, r2, r3;
  H.enqueue(function () { return new Promise((res) => { r1 = res; }); });
  H.enqueue(function () { return new Promise((res) => { r2 = res; }); });
  H.enqueue(function () { return new Promise((res) => { r3 = res; }); });
  // Fire three refresh clicks.
  H.registry["conversations-refresh"].click();
  H.registry["conversations-refresh"].click();
  H.registry["conversations-refresh"].click();
  await H.drain(20);
  const fetchesWhilePending = H.fetchLog.length - fetchCountAfterBootstrap;

  // Resolve the first response; only one more fetch should start.
  r1(H.jsonResponse(pageOfConversations(0, 50, 51), 200, { "X-Total-Count": "51" }));
  await H.drain(25);
  const fetchesAfterFirst = H.fetchLog.length - fetchCountAfterBootstrap;

  // Resolve the second; one more.
  r2(H.jsonResponse(pageOfConversations(0, 50, 51), 200, { "X-Total-Count": "51" }));
  await H.drain(25);
  const fetchesAfterSecond = H.fetchLog.length - fetchCountAfterBootstrap;

  // Resolve the third.
  r3(H.jsonResponse(pageOfConversations(0, 50, 51), 200, { "X-Total-Count": "51" }));
  await H.drain(25);
  const fetchesFinal = H.fetchLog.length - fetchCountAfterBootstrap;

  return {
    ok: true, scenario: "list-serialization",
    fetchesWhilePending,
    fetchesAfterFirst,
    fetchesAfterSecond,
    fetchesFinal,
    // Serialised: only one request in flight at a time. While pending only
    // the first fetch should have started.
    oneAtATime: fetchesWhilePending === 1 &&
                fetchesAfterFirst === 2 &&
                fetchesAfterSecond === 3 &&
                fetchesFinal === 3,
  };
}


// --- 30. Invalid message UUID keeps ambiguity ---------------------------
async function scenarioRecoveryInvalidMessageUuid() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "400" });
  });
  H.enqueue(async () => {
    const bad = pageOfMessages("C0", 200, 200, 400);
    bad[0].id = "not-a-uuid";  // invalid id format
    return H.jsonResponse(bad, 200, { "X-Total-Count": "400" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-invalid-message-uuid",
    amb: isAmbiguous(uuidFrom("C0")),
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

// --- 31. Invalid message timestamp keeps ambiguity ----------------------
async function scenarioRecoveryInvalidTimestamp() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "400" });
  });
  H.enqueue(async () => {
    const bad = pageOfMessages("C0", 200, 200, 400);
    bad[0].created_at = "not-a-date";  // invalid timestamp
    return H.jsonResponse(bad, 200, { "X-Total-Count": "400" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-invalid-timestamp",
    amb: isAmbiguous(uuidFrom("C0")),
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

// --- 32. Fractional fresh-total keeps ambiguity ------------------------
async function scenarioRecoveryFractionalFreshTotal() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  // Fresh-total fetch returns a fractional header.
  H.enqueue(async (url) => {
    if (!url.includes("limit=1")) throw new Error("expected limit=1, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "400.5" });
  });
  // No second fetch is expected — reloadLatest should abort after the
  // invalid fresh total. If a second fetch does run, this queue handler
  // ensures we catch it and mark the test as failing.
  H.enqueue(async () => {
    throw new Error("unexpected second fetch after invalid fresh total");
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-fractional-fresh-total",
    amb: isAmbiguous(uuidFrom("C0")),
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

// --- 33. Malformed conversation record preserves committed state ------
async function scenarioRefreshMalformedRecord() {
  await bootstrap(0, 50, 51);
  const rowCountBefore = H.registry["conversations-list"].children.length;
  const rangeBefore = H.registry["conversations-range"].textContent;
  // Refresh returns an array with one malformed record.
  H.enqueue(async () => {
    const good = pageOfConversations(0, 50, 51);
    good[0].id = "not-a-uuid";
    return H.jsonResponse(good, 200, { "X-Total-Count": "51" });
  });
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  const rowCountAfter = H.registry["conversations-list"].children.length;
  const rangeAfter = H.registry["conversations-range"].textContent;
  const statusKind = H.registry["conversations-status"].getAttribute("data-kind");
  return {
    ok: true, scenario: "refresh-malformed-record",
    rowCountBefore, rowCountAfter, rangeBefore, rangeAfter,
    rowsPreserved: rowCountBefore === rowCountAfter,
    rangePreserved: rangeBefore === rangeAfter,
    isError: statusKind === "error",
  };
}

// --- 34. Invalid list-total preserves committed state ------------------
async function scenarioRefreshInvalidListTotal() {
  await bootstrap(0, 50, 51);
  const rowCountBefore = H.registry["conversations-list"].children.length;
  // Refresh: valid records but header is fractional.
  H.enqueue(async () => H.jsonResponse(
    pageOfConversations(0, 50, 51), 200, { "X-Total-Count": "51.5" }
  ));
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  const rowCountAfter = H.registry["conversations-list"].children.length;
  const statusKind = H.registry["conversations-status"].getAttribute("data-kind");
  return {
    ok: true, scenario: "refresh-invalid-list-total",
    rowCountBefore, rowCountAfter,
    rowsPreserved: rowCountBefore === rowCountAfter,
    isError: statusKind === "error",
  };
}

// --- 35. Malformed refresh then valid recovery succeeds ---------------
async function scenarioRefreshMalformedThenValid() {
  await bootstrap(0, 50, 51);
  // First refresh fails: malformed record.
  H.enqueue(async () => {
    const good = pageOfConversations(0, 50, 51);
    good[0].id = "bad";
    return H.jsonResponse(good, 200, { "X-Total-Count": "51" });
  });
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  const afterFail = H.registry["conversations-status"].getAttribute("data-kind");
  // Second refresh succeeds.
  H.enqueue(async () => H.jsonResponse(
    pageOfConversations(0, 50, 51), 200, { "X-Total-Count": "51" }
  ));
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  const afterOK = H.registry["conversations-status"].getAttribute("data-kind");
  const statusText = H.registry["conversations-status"].textContent;
  return {
    ok: true, scenario: "refresh-malformed-then-valid",
    failed: afterFail === "error",
    recovered: afterOK !== "error" && statusText === "",
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
  "refresh-button-preserves-selection": scenarioRefreshButtonPreservesSelection,
  "refresh-failure-then-success": scenarioRefreshFailureThenSuccess,
  "404-clears-selection": scenario404ClearsSelection,
  "network-error-preserves-selection": scenarioNetworkErrorPreservesSelection,
  "stale-404-cannot-clear": scenarioStaleOtherConv404CannotClear,
  "refresh-failure-preserves-page": scenarioRefreshFailurePreservesPage,
  "create-during-refresh": scenarioCreateDuringRefresh,
  "ambiguous-404-blocks-repost": scenarioAmbiguous404BlocksRepost,
  "recovery-malformed-page": scenarioRecoveryMalformedPage,
  "recovery-malformed-records": scenarioRecoveryMalformedRecords,
  "recovery-missing-total": scenarioRecoveryMissingTotal,
  "recovery-invalid-total": scenarioRecoveryInvalidTotal,
  "recovery-empty-inconsistent": scenarioRecoveryEmptyInconsistent,
  "recovery-empty-legitimate": scenarioRecoveryEmptyLegitimate,
  "list-serialization": scenarioListSerialization,
  "recovery-invalid-message-uuid": scenarioRecoveryInvalidMessageUuid,
  "recovery-invalid-timestamp": scenarioRecoveryInvalidTimestamp,
  "recovery-fractional-fresh-total": scenarioRecoveryFractionalFreshTotal,
  "refresh-malformed-record": scenarioRefreshMalformedRecord,
  "refresh-invalid-list-total": scenarioRefreshInvalidListTotal,
  "refresh-malformed-then-valid": scenarioRefreshMalformedThenValid,
  "recovery-impossible-date": scenarioRecoveryImpossibleDate,
  "recovery-invalid-offset": scenarioRecoveryInvalidOffset,
  "recovery-valid-offset": scenarioRecoveryValidOffset,
  "recovery-wrong-conversation": scenarioRecoveryWrongConversation,
  "recovery-missing-list-total": scenarioRecoveryMissingListTotal,
  "recovery-impossible-date-in-list": scenarioRecoveryImpossibleDateInList,
  "recovery-201-to-200-race": scenarioRecovery201to200Race,
  "recovery-201-to-200-race-guard-held": scenarioRecovery201to200RaceGuardHeld,
};

// --- Correction 8. Strict datetime and 201-to-200 race recovery ---

async function scenarioRecoveryImpossibleDate() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "1" }));
  H.enqueue(async () => {
    const m = msg("m0", "C0", "user", 0, "hello");
    m.created_at = "2026-02-31T00:00:00Z";
    return H.jsonResponse([m], 200, { "X-Total-Count": "1" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-impossible-date",
    amb: isAmbiguous(uuidFrom("C0")),
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

async function scenarioRecoveryInvalidOffset() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "1" }));
  H.enqueue(async () => {
    const m = msg("m0", "C0", "user", 0, "hello");
    m.created_at = "2026-01-01T00:00:00+99:00";
    return H.jsonResponse([m], 200, { "X-Total-Count": "1" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-invalid-offset",
    amb: isAmbiguous(uuidFrom("C0")),
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

async function scenarioRecoveryValidOffset() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const ambBefore = isAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "1" }));
  H.enqueue(async () => {
    const m = msg("m0", "C0", "user", 0, "hello");
    m.created_at = "2026-01-01T00:00:00+05:30";
    return H.jsonResponse([m], 200, { "X-Total-Count": "1" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-valid-offset",
    ambBefore,
    ambAfter: isAmbiguous(uuidFrom("C0")),
    cleared: ambBefore === true && isAmbiguous(uuidFrom("C0")) === false,
  };
}

async function scenarioRecoveryWrongConversation() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "1" }));
  H.enqueue(async () => {
    const m = msg("m0", "C1", "user", 0, "hello");
    return H.jsonResponse([m], 200, { "X-Total-Count": "1" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-wrong-conversation",
    amb: isAmbiguous(uuidFrom("C0")),
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

async function scenarioRecoveryMissingListTotal() {
  await bootstrap(0, 50, 51);
  await selectViaUI(0, "C0", 0);
  const rowsBefore = H.registry["conversations-list"].children.length;
  const rangeBefore = H.registry["conversations-range"].textContent;
  const selBefore = selectedId();
  H.enqueue(async () => H.jsonResponse(pageOfConversations(0, 50, 51), 200, {}));
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  return {
    ok: true, scenario: "recovery-missing-list-total",
    rowsPreserved: H.registry["conversations-list"].children.length === rowsBefore,
    rangePreserved: H.registry["conversations-range"].textContent === rangeBefore,
    selectionPreserved: selectedId() === selBefore,
    statusKind: H.registry["conversations-status"].getAttribute("data-kind"),
    statusText: H.registry["conversations-status"].textContent,
  };
}

async function scenarioRecoveryImpossibleDateInList() {
  await bootstrap(0, 50, 51);
  await selectViaUI(0, "C0", 0);
  const rowsBefore = H.registry["conversations-list"].children.length;
  const rangeBefore = H.registry["conversations-range"].textContent;
  const selBefore = selectedId();
  H.enqueue(async () => {
    const bad = pageOfConversations(0, 50, 51);
    bad[0].created_at = "2026-02-31T00:00:00Z";
    return H.jsonResponse(bad, 200, { "X-Total-Count": "51" });
  });
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  return {
    ok: true, scenario: "recovery-impossible-date-in-list",
    rowsPreserved: H.registry["conversations-list"].children.length === rowsBefore,
    rangePreserved: H.registry["conversations-range"].textContent === rangeBefore,
    selectionPreserved: selectedId() === selBefore,
    statusKind: H.registry["conversations-status"].getAttribute("data-kind"),
    statusText: H.registry["conversations-status"].textContent,
  };
}

async function scenarioRecovery201to200Race() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const ambBefore = isAmbiguous(uuidFrom("C0"));
  const logStart = H.fetchLog.length;
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "201" }));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "200" }));
  H.enqueue(async () => H.jsonResponse(
    pageOfMessages("C0", 0, 200, 200), 200, { "X-Total-Count": "200" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(40);
  const urls = H.fetchLog.slice(logStart).map((x) => x.url);
  return {
    ok: true, scenario: "recovery-201-to-200-race",
    ambBefore,
    ambAfter: isAmbiguous(uuidFrom("C0")),
    clearedAfterRetry: ambBefore === true && isAmbiguous(uuidFrom("C0")) === false,
    fetchUrls: urls,
    emptyAt200ThenRetryAt0:
      urls.length >= 3 &&
      /offset=200\b/.test(urls[1]) &&
      /limit=200&offset=0\b/.test(urls[2]),
  };
}

async function scenarioRecovery201to200RaceGuardHeld() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const ambBefore = isAmbiguous(uuidFrom("C0"));
  const logStart = H.fetchLog.length;
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "201" }));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "200" }));
  let releaseRetry;
  const retryGate = new Promise((r) => { releaseRetry = r; });
  H.enqueue(async () => {
    await retryGate;
    return H.jsonResponse([], 200, { "X-Total-Count": "200" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(40);
  const urlsDuring = H.fetchLog.slice(logStart).map((x) => x.url);
  const ambDuring = isAmbiguous(uuidFrom("C0"));
  releaseRetry();
  await H.drain(40);
  const urlsAfter = H.fetchLog.slice(logStart).map((x) => x.url);
  return {
    ok: true, scenario: "recovery-201-to-200-race-guard-held",
    ambBefore,
    ambDuring,
    ambAfter: isAmbiguous(uuidFrom("C0")),
    guardHeldDuring: ambDuring === true,
    keptAfterInvalidRetry: isAmbiguous(uuidFrom("C0")) === true,
    fetchCountDuringRetry: urlsDuring.length,
    fetchCountAfterFailedRetry: urlsAfter.length,
    noBlindResubmission: urlsAfter.length === urlsDuring.length,
  };
}

Object.assign(SCENARIOS, {
  "recovery-year-zero": scenarioRecoveryYearZero,
  "recovery-year-one": scenarioRecoveryYearOne,
  "recovery-hour-24": scenarioRecoveryHour24,
  "recovery-valid-leap-day": scenarioRecoveryValidLeapDay,
  "recovery-year-zero-in-list": scenarioRecoveryYearZeroInList,
  "recovery-201-to-200-race-no-bad-commit": scenarioRecovery201to200NoBadCommit,
});

async function scenarioRecoveryYearZero() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "1" }));
  H.enqueue(async () => {
    const m = msg("m0", "C0", "user", 0, "hello");
    m.created_at = "0000-02-29T00:00:00Z";
    return H.jsonResponse([m], 200, { "X-Total-Count": "1" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-year-zero",
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

async function scenarioRecoveryYearOne() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const ambBefore = isAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "1" }));
  H.enqueue(async () => {
    const m = msg("m0", "C0", "user", 0, "hello");
    m.created_at = "0001-01-01T00:00:00Z";
    return H.jsonResponse([m], 200, { "X-Total-Count": "1" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-year-one",
    ambBefore,
    cleared: ambBefore === true && isAmbiguous(uuidFrom("C0")) === false,
  };
}

async function scenarioRecoveryHour24() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "1" }));
  H.enqueue(async () => {
    const m = msg("m0", "C0", "user", 0, "hello");
    m.created_at = "2026-01-01T24:00:00Z";
    return H.jsonResponse([m], 200, { "X-Total-Count": "1" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-hour-24",
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

async function scenarioRecoveryValidLeapDay() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const ambBefore = isAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "1" }));
  H.enqueue(async () => {
    const m = msg("m0", "C0", "user", 0, "hello");
    m.created_at = "2024-02-29T00:00:00Z";
    return H.jsonResponse([m], 200, { "X-Total-Count": "1" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-valid-leap-day",
    ambBefore,
    cleared: ambBefore === true && isAmbiguous(uuidFrom("C0")) === false,
  };
}

async function scenarioRecoveryYearZeroInList() {
  await bootstrap(0, 50, 51);
  await selectViaUI(0, "C0", 0);
  const rowsBefore = H.registry["conversations-list"].children.length;
  const rangeBefore = H.registry["conversations-range"].textContent;
  const selBefore = selectedId();
  H.enqueue(async () => {
    const bad = pageOfConversations(0, 50, 51);
    bad[0].created_at = "0000-02-29T00:00:00Z";
    return H.jsonResponse(bad, 200, { "X-Total-Count": "51" });
  });
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  return {
    ok: true, scenario: "recovery-year-zero-in-list",
    rowsPreserved: H.registry["conversations-list"].children.length === rowsBefore,
    rangePreserved: H.registry["conversations-range"].textContent === rangeBefore,
    selectionPreserved: selectedId() === selBefore,
    statusKind: H.registry["conversations-status"].getAttribute("data-kind"),
  };
}

async function scenarioRecovery201to200NoBadCommit() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 400, (off) => pageOfMessages("C0", off, 200, 400));
  const stateBefore = global.window.__mickyConversations.messagesState();
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const ambBefore = isAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "201" }));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "200" }));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "200" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(40);
  const state = global.window.__mickyConversations.messagesState();
  const impossibleRange =
    state.rendered === 0 &&
    state.total !== null &&
    state.total > 0 &&
    state.offset === state.total;
  const stateUnverified = state.total === null && state.rendered === 0;
  return {
    ok: true, scenario: "recovery-201-to-200-race-no-bad-commit",
    ambBefore,
    ambAfter: isAmbiguous(uuidFrom("C0")),
    kept: isAmbiguous(uuidFrom("C0")) === true,
    stateBefore, state,
    impossibleRange,
    stateUnverified,
    stateCoherent: !impossibleRange,
  };
}

Object.assign(SCENARIOS, {
  "recovery-fractional-precision": scenarioRecoveryFractionalPrecision,
  "recovery-fractional-precision-in-list": scenarioRecoveryFractionalPrecisionInList,
  "switch-failure-rendered-count-coherent": scenarioSwitchFailureRenderedCountCoherent,
});

async function scenarioRecoveryFractionalPrecision() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "1" }));
  H.enqueue(async () => {
    const m = msg("m0", "C0", "user", 0, "hello");
    m.created_at = "2026-01-01T00:00:00.1234567Z";
    return H.jsonResponse([m], 200, { "X-Total-Count": "1" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-fractional-precision",
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

async function scenarioRecoveryFractionalPrecisionInList() {
  await bootstrap(0, 50, 51);
  await selectViaUI(0, "C0", 0);
  const rowsBefore = H.registry["conversations-list"].children.length;
  const rangeBefore = H.registry["conversations-range"].textContent;
  const selBefore = selectedId();
  H.enqueue(async () => {
    const bad = pageOfConversations(0, 50, 51);
    bad[0].created_at = "2026-01-01T00:00:00.1234567Z";
    return H.jsonResponse(bad, 200, { "X-Total-Count": "51" });
  });
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  return {
    ok: true, scenario: "recovery-fractional-precision-in-list",
    rowsPreserved: H.registry["conversations-list"].children.length === rowsBefore,
    rangePreserved: H.registry["conversations-range"].textContent === rangeBefore,
    selectionPreserved: selectedId() === selBefore,
    statusKind: H.registry["conversations-status"].getAttribute("data-kind"),
  };
}

async function scenarioSwitchFailureRenderedCountCoherent() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  const stateBefore = global.window.__mickyConversations.messagesState();
  H.enqueue(async () => H.jsonResponse([], 500, {}));
  H.enqueue(async () => H.jsonResponse([], 500, {}));
  H.registry["conversations-list"].children[1].children[0].click();
  await H.drain(30);
  const state = global.window.__mickyConversations.messagesState();
  const messagesList = H.registry["messages-list"];
  const domCount = messagesList ? messagesList.children.length : 0;
  return {
    ok: true, scenario: "switch-failure-rendered-count-coherent",
    stateBefore, state, domCount,
    renderedMatchesDom: state.rendered === domCount,
    totalUnverified: state.total === null,
  };
}

Object.assign(SCENARIOS, {
  "delete-stale-response-cannot-repopulate": scenarioDeleteStaleResponseCannotRepopulate,
  "delete-resets-pagination-state": scenarioDeleteResetsPaginationState,
});

async function scenarioDeleteStaleResponseCannotRepopulate() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 5, (off) => pageOfMessages("C0", off, 200, 5));
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const ambBefore = isAmbiguous(uuidFrom("C0"));

  // Start a fresh reload that BLOCKS on the page fetch.
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "5" }));
  let releasePage;
  const pageGate = new Promise((r) => { releasePage = r; });
  H.enqueue(async () => {
    await pageGate;
    return H.jsonResponse(pageOfMessages("C0", 0, 200, 5), 200,
      { "X-Total-Count": "5" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(20);

  // While the reload's page fetch is pending, delete the conversation.
  H.confirmQueue.push(true);
  H.enqueue(async () => H.jsonResponse({}, 204, {}));
  H.registry["conversation-delete"].click();
  await H.drain(30);

  const stateAfterDelete = global.window.__mickyConversations.messagesState();
  const ambAfterDelete = isAmbiguous(uuidFrom("C0"));
  const selectedAfterDelete = selectedId();

  // Now release the stale page response.
  releasePage();
  await H.drain(40);

  const stateAfterStale = global.window.__mickyConversations.messagesState();
  const msgsEl = H.registry["messages-list"];
  const domAfterStale = msgsEl ? msgsEl.children.length : 0;
  const ambAfterStale = isAmbiguous(uuidFrom("C0"));

  return {
    ok: true, scenario: "delete-stale-response-cannot-repopulate",
    ambBefore,
    stateAfterDelete,
    ambAfterDelete,
    selectedAfterDelete,
    stateAfterStale,
    domAfterStale,
    ambAfterStale,
    clearedOnDelete:
      stateAfterDelete.offset === 0 &&
      stateAfterDelete.total === null &&
      stateAfterDelete.rendered === 0,
    staleBlocked:
      stateAfterStale.offset === 0 &&
      stateAfterStale.total === null &&
      stateAfterStale.rendered === 0 &&
      domAfterStale === 0,
    ambiguityCleared: ambBefore === true && ambAfterDelete === false &&
      ambAfterStale === false,
    selectionCleared: selectedAfterDelete === null,
  };
}

async function scenarioDeleteResetsPaginationState() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 5, (off) => pageOfMessages("C0", off, 200, 5));
  const before = global.window.__mickyConversations.messagesState();
  H.confirmQueue.push(true);
  H.enqueue(async () => H.jsonResponse({}, 204, {}));
  H.registry["conversation-delete"].click();
  await H.drain(30);
  const after = global.window.__mickyConversations.messagesState();
  return {
    ok: true, scenario: "delete-resets-pagination-state",
    before, after,
    offsetReset: after.offset === 0,
    totalReset: after.total === null,
    renderedReset: after.rendered === 0,
    selectedCleared: selectedId() === null,
  };
}

Object.assign(SCENARIOS, {
  "create-response-malformed": scenarioCreateResponseMalformed,
  "create-response-naive-timestamp": scenarioCreateResponseNaiveTimestamp,
  "create-network-fail-blocks-retry": scenarioCreateNetworkFailBlocksRetry,
  "create-reconcile-via-refresh": scenarioCreateReconcileViaRefresh,
  "recovery-naive-timestamp": scenarioRecoveryNaiveTimestamp,
});

async function scenarioCreateResponseMalformed() {
  await bootstrap(0, 50, 0);
  // POST returns only {id, title}; missing created_at / updated_at means
  // the response fails isValidConversationRecord and must not be treated
  // as a valid selection.
  H.enqueue(async () => H.jsonResponse(
    { id: uuidFrom("Cnew"), title: "New conversation" }, 201, {}));
  H.registry["conversations-new"].click();
  await H.drain(25);
  const state = global.window.__mickyConversations.createState();
  return {
    ok: true, scenario: "create-response-malformed",
    ambiguous: state.ambiguous,
    selected: selectedId(),
  };
}

async function scenarioCreateResponseNaiveTimestamp() {
  await bootstrap(0, 50, 0);
  H.enqueue(async () => {
    const c = conv("Cnew", "New conversation");
    c.created_at = "2026-01-01T00:00:00";
    return H.jsonResponse(c, 201, {});
  });
  H.registry["conversations-new"].click();
  await H.drain(25);
  const state = global.window.__mickyConversations.createState();
  return {
    ok: true, scenario: "create-response-naive-timestamp",
    ambiguous: state.ambiguous,
    selected: selectedId(),
  };
}

async function scenarioCreateNetworkFailBlocksRetry() {
  await bootstrap(0, 50, 0);
  H.enqueue(async () => { throw new Error("network boom"); });
  H.registry["conversations-new"].click();
  await H.drain(20);
  const fetchCountAfterFirst = H.fetchLog.length;
  const stateAfterFirst = global.window.__mickyConversations.createState();
  // A second click must NOT issue another POST while the guard is set.
  H.registry["conversations-new"].click();
  await H.drain(20);
  const fetchCountAfterSecond = H.fetchLog.length;
  return {
    ok: true, scenario: "create-network-fail-blocks-retry",
    ambiguousAfterFail: stateAfterFirst.ambiguous,
    fetchCountAfterFirst,
    fetchCountAfterSecond,
    noSecondPost: fetchCountAfterSecond === fetchCountAfterFirst,
  };
}

async function scenarioCreateReconcileViaRefresh() {
  await bootstrap(0, 50, 0);
  // First create attempt: network failure sets the guard.
  H.enqueue(async () => { throw new Error("network boom"); });
  H.registry["conversations-new"].click();
  await H.drain(20);
  const ambiguousAfterFail = global.window.__mickyConversations.createState().ambiguous;
  // Reconcile via refresh: list fetch succeeds, guard clears.
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  const ambiguousAfterRefresh = global.window.__mickyConversations.createState().ambiguous;
  // Now New must fire a second POST.
  const fetchCountBeforeSecondClick = H.fetchLog.length;
  H.enqueue(async () => { throw new Error("second POST attempted"); });
  H.registry["conversations-new"].click();
  await H.drain(20);
  const fetchCountAfterSecondClick = H.fetchLog.length;
  return {
    ok: true, scenario: "create-reconcile-via-refresh",
    ambiguousAfterFail,
    ambiguousAfterRefresh,
    secondPostAttempted: fetchCountAfterSecondClick > fetchCountBeforeSecondClick,
  };
}

async function scenarioRecoveryNaiveTimestamp() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "1" }));
  H.enqueue(async () => {
    const m = msg("m0", "C0", "user", 0, "hello");
    m.created_at = "2026-01-01T00:00:00";
    return H.jsonResponse([m], 200, { "X-Total-Count": "1" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-naive-timestamp",
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

Object.assign(SCENARIOS, {
  "create-stale-response-cannot-repopulate": scenarioCreateStaleResponseCannotRepopulate,
  "rename-a-then-switch-to-b": scenarioRenameThenSwitchToB,
});

async function scenarioCreateStaleResponseCannotRepopulate() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 5, (off) => pageOfMessages("C0", off, 200, 5));
  // Start a reload of C0 whose page fetch is held.
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "5" }));
  let releasePage;
  const pageGate = new Promise((r) => { releasePage = r; });
  H.enqueue(async () => {
    await pageGate;
    return H.jsonResponse(pageOfMessages("C0", 0, 200, 5), 200,
      { "X-Total-Count": "5" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(20);
  // Create new conversation with a valid response; list refresh fails fast.
  H.enqueue(async () => H.jsonResponse(conv("Cnew", "New conversation"), 201, {}));
  H.enqueue(async () => { throw new Error("list boom"); });
  H.registry["conversations-new"].click();
  await H.drain(30);
  const stateAfterCreate = global.window.__mickyConversations.messagesState();
  const selAfterCreate = selectedId();
  const domAfterCreate = H.registry["conversation-messages"].children.length;
  // Release the stale C0 page response.
  releasePage();
  await H.drain(30);
  const stateAfterStale = global.window.__mickyConversations.messagesState();
  const domAfterStale = H.registry["conversation-messages"].children.length;
  return {
    ok: true, scenario: "create-stale-response-cannot-repopulate",
    stateAfterCreate, stateAfterStale,
    selAfterCreate, domAfterCreate, domAfterStale,
    selectedIsNew: selAfterCreate === uuidFrom("Cnew"),
    clearedOnCreate:
      stateAfterCreate.offset === 0 &&
      stateAfterCreate.total === null &&
      stateAfterCreate.rendered === 0,
    staleBlocked:
      stateAfterStale.offset === 0 &&
      stateAfterStale.total === null &&
      stateAfterStale.rendered === 0,
    domStillEmpty: domAfterCreate === 0 && domAfterStale === 0,
  };
}

async function scenarioRenameThenSwitchToB() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  // Set rename input and fire PATCH; hold the response.
  H.registry["conversation-rename-input"].value = "Renamed A";
  let releaseRename;
  const renameGate = new Promise((r) => { releaseRename = r; });
  H.enqueue(async () => {
    await renameGate;
    return H.jsonResponse({
      id: uuidFrom("C0"),
      title: "Renamed A",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
    }, 200, {});
  });
  H.registry["conversation-rename"].click();
  await H.drain(10);
  // While rename pending, switch to C1.
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-list"].children[1].children[0].click();
  await H.drain(20);
  const selAfterSwitch = selectedId();
  const titleAfterSwitch = H.registry["conversation-current-title"].textContent;
  // Release rename response.
  releaseRename();
  await H.drain(30);
  const selAfter = selectedId();
  const titleAfter = H.registry["conversation-current-title"].textContent;
  const convs = global.window.__mickyConversations.conversationsState();
  const c0 = convs.find((c) => c.id === uuidFrom("C0"));
  const c1 = convs.find((c) => c.id === uuidFrom("C1"));
  return {
    ok: true, scenario: "rename-a-then-switch-to-b",
    selAfterSwitch, titleAfterSwitch, selAfter, titleAfter,
    c0Title: c0 ? c0.title : null,
    c1Title: c1 ? c1.title : null,
    bStillSelected: selAfter === uuidFrom("C1"),
    bTitleUnchanged: titleAfter === "Conversation 1",
    aTitleUpdated: c0 !== undefined && c0.title === "Renamed A",
  };
}

Object.assign(SCENARIOS, {
  "send-pending-switch-to-b": scenarioSendPendingSwitchToB,
  "send-during-reload-blocked": scenarioSendDuringReloadBlocked,
  "delete-invalidated-load-not-stuck": scenarioDeleteInvalidatedLoadNotStuck,
});

async function scenarioSendPendingSwitchToB() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  // Submit a send; hold its POST response.
  H.registry["message"].value = "hello A";
  let releaseSend;
  const sendGate = new Promise((r) => { releaseSend = r; });
  H.enqueue(async () => {
    await sendGate;
    return H.jsonResponse({ status: "success", message: "ok" }, 200, {});
  });
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(15);
  // Switch to B while the send is in flight.
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-list"].children[1].children[0].click();
  await H.drain(25);
  const selAfterSwitch = selectedId();
  const fetchCountAfterSwitch = H.fetchLog.length;
  // Release the send response: A's success must NOT trigger a fetch for B.
  releaseSend();
  await H.drain(30);
  const fetchCountAfterSend = H.fetchLog.length;
  return {
    ok: true, scenario: "send-pending-switch-to-b",
    selAfterSwitch,
    finalSelected: selectedId(),
    bStillSelected:
      selAfterSwitch === uuidFrom("C1") && selectedId() === uuidFrom("C1"),
    noRefreshForA: fetchCountAfterSend === fetchCountAfterSwitch,
    fetchCountAfterSwitch, fetchCountAfterSend,
  };
}

async function scenarioSendDuringReloadBlocked() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  // Start a reload; hold its total-fetch response.
  let releaseTotal;
  const totalGate = new Promise((r) => { releaseTotal = r; });
  H.enqueue(async () => {
    await totalGate;
    return H.jsonResponse([], 200, { "X-Total-Count": "0" });
  });
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(10);
  const loadingDuringFetch = global.window.__mickyConversations.isLoadingMessages();
  // Try to submit while the total fetch is pending.
  H.registry["message"].value = "hello";
  const fetchCountBeforeSend = H.fetchLog.length;
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(10);
  const fetchCountAfterSend = H.fetchLog.length;
  // Release the total fetch and let the reload finish.
  releaseTotal();
  await H.drain(25);
  return {
    ok: true, scenario: "send-during-reload-blocked",
    loadingDuringFetch,
    fetchCountBeforeSend,
    fetchCountAfterSend,
    sendBlocked: fetchCountAfterSend === fetchCountBeforeSend,
    loadingCoversWholeOperation: loadingDuringFetch === true,
  };
}

async function scenarioDeleteInvalidatedLoadNotStuck() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 5, (off) => pageOfMessages("C0", off, 200, 5));
  // Start a reload; hold its page fetch.
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "5" }));
  let releasePage;
  const pageGate = new Promise((r) => { releasePage = r; });
  H.enqueue(async () => {
    await pageGate;
    return H.jsonResponse(pageOfMessages("C0", 0, 200, 5), 200,
      { "X-Total-Count": "5" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(15);
  const midLoad = global.window.__mickyConversations.isLoadingMessages();
  // Delete C0: invalidates token, must clear the in-flight flag.
  H.confirmQueue.push(true);
  H.enqueue(async () => H.jsonResponse({}, 204, {}));
  H.registry["conversation-delete"].click();
  await H.drain(25);
  const afterDelete = global.window.__mickyConversations.isLoadingMessages();
  const selAfterDelete = selectedId();
  // Release the stale page response.
  releasePage();
  await H.drain(30);
  const afterStale = global.window.__mickyConversations.isLoadingMessages();
  return {
    ok: true, scenario: "delete-invalidated-load-not-stuck",
    midLoad, afterDelete, afterStale, selAfterDelete,
    flagClearedOnDelete: midLoad === true && afterDelete === false,
    stillClearAfterStale: afterStale === false,
    selectionCleared: selAfterDelete === null,
  };
}

Object.assign(SCENARIOS, {
  "delete-last-item-on-last-page": scenarioDeleteLastItemOnLastPage,
  "delete-one-item-updates-total": scenarioDeleteOneItemUpdatesTotal,
  "list-in-flight-does-not-reintroduce-deleted": scenarioListInFlightDoesNotReintroduceDeleted,
  "list-rejects-oversize-page": scenarioListRejectsOversizePage,
  "list-rejects-empty-at-nonzero-offset": scenarioListRejectsEmptyAtNonzeroOffset,
});

async function scenarioDeleteLastItemOnLastPage() {
  await bootstrap(0, 50, 51);
  // Go to page 2 (offset 50, 1 item = C50)
  H.enqueue(async (url) => {
    if (!url.includes("offset=50")) throw new Error("expected offset=50, got " + url);
    return H.jsonResponse(pageOfConversations(1, 50, 51), 200,
      { "X-Total-Count": "51" });
  });
  H.registry["conversations-next"].click();
  await H.drain(25);
  // Select C50 (the only item on this page)
  await selectViaUI(0, "C50", 0);
  const selBeforeDelete = selectedId();
  const fetchCountBeforeDelete = H.fetchLog.length;
  // Delete C50
  H.confirmQueue.push(true);
  H.enqueue(async () => H.jsonResponse({}, 204, {}));
  // Post-delete loadConversations must fetch from the recovered offset (0)
  H.enqueue(async (url) => {
    if (!url.includes("offset=0")) throw new Error("expected recovered offset=0, got " + url);
    return H.jsonResponse(pageOfConversations(0, 50, 50), 200,
      { "X-Total-Count": "50" });
  });
  H.registry["conversation-delete"].click();
  await H.drain(40);
  const rowsAfter = H.registry["conversations-list"].children.length;
  const rangeAfter = H.registry["conversations-range"].textContent;
  const urlsAfter = H.fetchLog.slice(fetchCountBeforeDelete).map((x) => x.url);
  const fetchedOffset0 = urlsAfter.some((u) => /offset=0(?:\D|$)/.test(u) && !/limit=1/.test(u));
  return {
    ok: true, scenario: "delete-last-item-on-last-page",
    rowsAfter, rangeAfter,
    fetchedOffset0,
    selBeforeDelete,
    selectedAfter: selectedId(),
    offsetRecovered: fetchedOffset0,
    rowsCoherent: rowsAfter === 50,
    rangeCoherent: rangeAfter === "Showing 1\u201350 of 50",
  };
}

async function scenarioDeleteOneItemUpdatesTotal() {
  await bootstrap(0, 50, 51);
  await selectViaUI(0, "C0", 0);
  const rangeBefore = H.registry["conversations-range"].textContent;
  // Delete C0
  H.confirmQueue.push(true);
  H.enqueue(async () => H.jsonResponse({}, 204, {}));
  H.enqueue(async (url) => {
    if (!url.includes("offset=0")) throw new Error("expected offset=0, got " + url);
    return H.jsonResponse(pageOfConversations(0, 50, 50), 200,
      { "X-Total-Count": "50" });
  });
  H.registry["conversation-delete"].click();
  await H.drain(40);
  const rangeAfter = H.registry["conversations-range"].textContent;
  const rowsAfter = H.registry["conversations-list"].children.length;
  return {
    ok: true, scenario: "delete-one-item-updates-total",
    rangeBefore, rangeAfter, rowsAfter,
    rangeUpdated: rangeAfter === "Showing 1\u201350 of 50",
    rowsCoherent: rowsAfter === 50,
  };
}

async function scenarioListInFlightDoesNotReintroduceDeleted() {
  await bootstrap(0, 50, 51);
  await selectViaUI(0, "C0", 0);
  // Start a list refresh; hold its response (still contains C0 -- this is
  // the STALE pre-delete response that must NOT be committed after delete).
  let releaseRefresh;
  const refreshGate = new Promise((r) => { releaseRefresh = r; });
  H.enqueue(async () => {
    await refreshGate;
    return H.jsonResponse(pageOfConversations(0, 50, 51), 200,
      { "X-Total-Count": "51" });
  });
  H.registry["conversations-refresh"].click();
  await H.drain(5);
  // Delete C0 while refresh is pending.
  H.confirmQueue.push(true);
  H.enqueue(async () => H.jsonResponse({}, 204, {}));
  // After delete: accurate server state is C1..C50 (50 rows, total 50).
  // Build this explicitly -- pageOfConversations(0, 50, 50) would return
  // C0..C49, i.e. re-introduce the deleted row via the fixture itself.
  H.enqueue(async () => {
    const remaining = [];
    for (let i = 1; i <= 50; i++) {
      remaining.push(conv("C" + i, "Conversation " + i));
    }
    return H.jsonResponse(remaining, 200, { "X-Total-Count": "50" });
  });
  H.registry["conversation-delete"].click();
  await H.drain(15);
  // Release stale refresh response (would reintroduce C0 if not rejected
  // by the listLoadToken guard).
  releaseRefresh();
  await H.drain(40);
  // Read rendered titles via the .conv-title button textContent -- renderList
  // does not set a data-id attribute, so dataset lookup is unreliable.
  const rows = H.registry["conversations-list"].children;
  const titles = rows.map(function (li) {
    for (let i = 0; i < li.children.length; i++) {
      if (li.children[i].textContent) return li.children[i].textContent;
    }
    return "";
  });
  const hasC0 = titles.indexOf("Conversation 0") !== -1;
  return {
    ok: true, scenario: "list-in-flight-does-not-reintroduce-deleted",
    rowCount: rows.length,
    titles: titles.slice(0, 3),
    hasC0,
    deletedNotReintroduced: hasC0 === false,
    rowCountCoherent: rows.length === 50,
  };
}

async function scenarioListRejectsOversizePage() {
  await bootstrap(0, 50, 51);
  const rowsBefore = H.registry["conversations-list"].children.length;
  const rangeBefore = H.registry["conversations-range"].textContent;
  // 51 rows when LIST_LIMIT is 50 is impossible.
  H.enqueue(async () => {
    const oversize = pageOfConversations(0, 50, 51);
    oversize.push(conv("C1000", "Extra"));
    return H.jsonResponse(oversize, 200, { "X-Total-Count": "51" });
  });
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  const rowsAfter = H.registry["conversations-list"].children.length;
  const rangeAfter = H.registry["conversations-range"].textContent;
  const statusKind = H.registry["conversations-status"].getAttribute("data-kind");
  return {
    ok: true, scenario: "list-rejects-oversize-page",
    rowsBefore, rowsAfter, rangeBefore, rangeAfter,
    rowsPreserved: rowsBefore === rowsAfter,
    rangePreserved: rangeBefore === rangeAfter,
    isError: statusKind === "error",
  };
}

async function scenarioListRejectsEmptyAtNonzeroOffset() {
  await bootstrap(0, 50, 51);
  const rowsBefore = H.registry["conversations-list"].children.length;
  const rangeBefore = H.registry["conversations-range"].textContent;
  // Click next: server responds with an impossible empty page at offset 50.
  H.enqueue(async (url) => {
    if (!url.includes("offset=50")) throw new Error("expected offset=50, got " + url);
    return H.jsonResponse([], 200, { "X-Total-Count": "51" });
  });
  H.registry["conversations-next"].click();
  await H.drain(25);
  const rowsAfter = H.registry["conversations-list"].children.length;
  const rangeAfter = H.registry["conversations-range"].textContent;
  const statusKind = H.registry["conversations-status"].getAttribute("data-kind");
  return {
    ok: true, scenario: "list-rejects-empty-at-nonzero-offset",
    rowsBefore, rowsAfter, rangeBefore, rangeAfter,
    rowsPreserved: rowsBefore === rowsAfter,
    rangePreserved: rangeBefore === rangeAfter,
    isError: statusKind === "error",
  };
}

Object.assign(SCENARIOS, {
  "switch-while-delete-pending": scenarioSwitchWhileDeletePending,
  "stale-invalidated-resolves-after-new-fail": scenarioStaleInvalidatedResolvesAfterNewFail,
  "recovery-rejects-out-of-order-sequence": scenarioRecoveryRejectsOutOfOrderSequence,
});

async function scenarioSwitchWhileDeletePending() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  // Mark C0 ambiguous so we can observe its marker being cleared on delete.
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  const ambC0BeforeDelete = isAmbiguous(uuidFrom("C0"));
  // Start DELETE for C0; hold response on a gate.
  H.confirmQueue.push(true);
  let releaseDelete;
  const deleteGate = new Promise((r) => { releaseDelete = r; });
  H.enqueue(async () => { await deleteGate; return H.jsonResponse({}, 204, {}); });
  H.registry["conversation-delete"].click();
  await H.drain(10);
  // Switch to C1 while DELETE is pending.
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-list"].children[1].children[0].click();
  await H.drain(25);
  const selAfterSwitch = selectedId();
  // C0 must still be marked ambiguous while its DELETE is unresolved.
  const ambC0WhilePending = isAmbiguous(uuidFrom("C0"));
  // Delete resolves -- post-delete list reconciliation returns ONLY C1
  // (accurate server state: C0 was actually deleted).
  H.enqueue(async () => H.jsonResponse(
    [conv("C1", "Conversation 1")], 200, { "X-Total-Count": "1" }));
  releaseDelete();
  await H.drain(35);
  // Aftermath: C0 absent from list; marker cleared; status honest.
  const rows = H.registry["conversations-list"].children;
  const titles = rows.map(function (li) {
    var btn = li.querySelector ? li.querySelector(".conv-title") : null;
    if (btn) return btn.textContent;
    for (var i = 0; i < li.children.length; i++) {
      if (li.children[i].textContent) return li.children[i].textContent;
    }
    return "";
  });
  const hasC0 = titles.indexOf("Conversation 0") !== -1;
  const statusText = H.registry["conversation-messages-status"].textContent;
  return {
    ok: true, scenario: "switch-while-delete-pending",
    selAfterSwitch,
    finalSelected: selectedId(),
    state: global.window.__mickyConversations.messagesState(),
    ambC0BeforeDelete,
    ambC0WhilePending,
    ambC0AfterDelete: isAmbiguous(uuidFrom("C0")),
    bStillSelected:
      selAfterSwitch === uuidFrom("C1") && selectedId() === uuidFrom("C1"),
    bStateIntact:
      global.window.__mickyConversations.messagesState().offset === 0 &&
      global.window.__mickyConversations.messagesState().total === 0,
    hasC0,
    c0Absent: hasC0 === false,
    markerCleared: isAmbiguous(uuidFrom("C0")) === false,
    statusHonest:
      !/no conversation is selected/i.test(statusText) &&
      !/no conversation is selected/i.test(
        H.registry["conversations-status"].textContent),
  };
}

async function scenarioStaleInvalidatedResolvesAfterNewFail() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  // Start a reload of C0; hold its page fetch.
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "3" }));
  let releasePage;
  const pageGate = new Promise((r) => { releasePage = r; });
  H.enqueue(async () => {
    await pageGate;
    return H.jsonResponse(pageOfMessages("C0", 0, 200, 3), 200,
      { "X-Total-Count": "3" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(15);
  // Switch to C1, whose reload fails.
  H.enqueue(async () => H.jsonResponse({ detail: "err" }, 500, {}));
  H.enqueue(async () => H.jsonResponse({ detail: "err" }, 500, {}));
  H.registry["conversations-list"].children[1].children[0].click();
  await H.drain(25);
  const selAfterSwitch = selectedId();
  // Release C0's stale page response.
  releasePage();
  await H.drain(35);
  return {
    ok: true, scenario: "stale-invalidated-resolves-after-new-fail",
    selAfterSwitch,
    finalSelected: selectedId(),
    state: global.window.__mickyConversations.messagesState(),
    bStillSelected:
      selAfterSwitch === uuidFrom("C1") && selectedId() === uuidFrom("C1"),
    noCorruption:
      global.window.__mickyConversations.messagesState().offset === 0 &&
      global.window.__mickyConversations.messagesState().rendered === 0,
  };
}

async function scenarioRecoveryRejectsOutOfOrderSequence() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "3" }));
  H.enqueue(async () => {
    // Valid records individually, but sequences 0, 5, 2 -- not ascending.
    const bad = pageOfMessages("C0", 0, 200, 3);
    bad[1].sequence = 5;
    bad[2].sequence = 2;
    return H.jsonResponse(bad, 200, { "X-Total-Count": "3" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-rejects-out-of-order-sequence",
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

Object.assign(SCENARIOS, {
  // F1b: creation reconciliation scoped
  "create-ambiguous-old-response-does-not-clear": scenarioCreateAmbiguousOldResponseDoesNotClear,
  "create-ambiguous-nonzero-offset-does-not-clear": scenarioCreateAmbiguousNonzeroOffsetDoesNotClear,
  // F2: strict slice validation
  "recovery-rejects-oversize-message-page": scenarioRecoveryRejectsOversizeMessagePage,
  "recovery-rejects-wrong-slice-position": scenarioRecoveryRejectsWrongSlicePosition,
  // F3: rename reconciliation
  "rename-network-loss-reconciles-via-list": scenarioRenameNetworkLossReconcilesViaList,
  "rename-404-clears-selection": scenarioRename404ClearsSelection,
  "rename-404-preserves-other-selection": scenarioRename404PreservesOtherSelection,
  // F6: strict decimal total header
  "list-rejects-hex-total": scenarioListRejectsHexTotal,
  "list-rejects-exponent-total": scenarioListRejectsExponentTotal,
  // F7: send response validation
  "send-unknown-status-marks-ambiguous": scenarioSendUnknownStatusMarksAmbiguous,
  "send-missing-message-marks-ambiguous": scenarioSendMissingMessageMarksAmbiguous,
  "send-invalid-challenge-marks-ambiguous": scenarioSendInvalidChallengeMarksAmbiguous,
});

// ---- F1b: creation reconciliation is scoped to fresh offset-0 refreshes ----

async function scenarioCreateAmbiguousOldResponseDoesNotClear() {
  await bootstrap(0, 50, 0);
  // Start a list refresh whose response we hold.
  let releaseRefresh;
  const refreshGate = new Promise((r) => { releaseRefresh = r; });
  H.enqueue(async () => {
    await refreshGate;
    return H.jsonResponse([], 200, { "X-Total-Count": "0" });
  });
  H.registry["conversations-refresh"].click();
  await H.drain(5);
  // Trigger creation network failure: sets ambiguity + captures the
  // current listLoadToken (which is the token of the pending refresh).
  H.enqueue(async () => { throw new Error("create network boom"); });
  H.registry["conversations-new"].click();
  await H.drain(15);
  const ambiguousAfterFail = global.window.__mickyConversations.createState().ambiguous;
  // Release the OLD refresh: it must NOT clear the guard.
  releaseRefresh();
  await H.drain(30);
  return {
    ok: true, scenario: "create-ambiguous-old-response-does-not-clear",
    ambiguousAfterFail,
    ambiguousAfterOldRefresh: global.window.__mickyConversations.createState().ambiguous,
    guardHeldAfterStaleResponse:
      ambiguousAfterFail === true &&
      global.window.__mickyConversations.createState().ambiguous === true,
  };
}

async function scenarioCreateAmbiguousNonzeroOffsetDoesNotClear() {
  await bootstrap(0, 50, 51);
  // Trigger creation network failure.
  H.enqueue(async () => { throw new Error("create network boom"); });
  H.registry["conversations-new"].click();
  await H.drain(15);
  const ambiguousAfterFail = global.window.__mickyConversations.createState().ambiguous;
  // Now do a NONZERO-offset list fetch -- this must NOT reconcile.
  H.enqueue(async (url) => {
    if (!url.includes("offset=50")) throw new Error("expected offset=50, got " + url);
    return H.jsonResponse(pageOfConversations(1, 50, 51), 200,
      { "X-Total-Count": "51" });
  });
  H.registry["conversations-next"].click();
  await H.drain(30);
  return {
    ok: true, scenario: "create-ambiguous-nonzero-offset-does-not-clear",
    ambiguousAfterFail,
    ambiguousAfterPagination: global.window.__mickyConversations.createState().ambiguous,
    guardHeldAfterPagination:
      ambiguousAfterFail === true &&
      global.window.__mickyConversations.createState().ambiguous === true,
  };
}

// ---- F2: strict slice validation ----

async function scenarioRecoveryRejectsOversizeMessagePage() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "201" }));
  H.enqueue(async () => {
    // Build 201 records at offset 0. Exceeds MESSAGES_LIMIT (200).
    const oversized = [];
    for (let i = 0; i < 201; i++) {
      oversized.push(msg("m" + i, "C0", i % 2 === 0 ? "user" : "assistant",
                         i, "msg " + i));
    }
    return H.jsonResponse(oversized, 200, { "X-Total-Count": "201" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-rejects-oversize-message-page",
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

async function scenarioRecoveryRejectsWrongSlicePosition() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  global.window.__mickyConversations.markAmbiguous(uuidFrom("C0"));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "3" }));
  H.enqueue(async () => {
    // Ordered, unique, individually valid -- but sequences 100,101,102
    // at offset 0 (must be 0,1,2 for a valid slice).
    const wrongSlice = [];
    for (let i = 0; i < 3; i++) {
      wrongSlice.push(msg("m" + i, "C0", i % 2 === 0 ? "user" : "assistant",
                          100 + i, "msg " + i));
    }
    return H.jsonResponse(wrongSlice, 200, { "X-Total-Count": "3" });
  });
  H.registry["conversations-list"].children[0].children[0].click();
  await H.drain(30);
  return {
    ok: true, scenario: "recovery-rejects-wrong-slice-position",
    kept: isAmbiguous(uuidFrom("C0")) === true,
  };
}

// ---- F3: rename reconciliation ----

async function scenarioRenameNetworkLossReconcilesViaList() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.registry["conversation-rename-input"].value = "Renamed";
  H.enqueue(async (url, opts) => {
    if (opts.method !== "PATCH") throw new Error("expected PATCH, got " + opts.method);
    throw new Error("patch network boom");
  });
  H.enqueue(async (url, opts) => {
    if (opts.method !== "GET" || !url.endsWith("/" + uuidFrom("C0"))) {
      throw new Error("expected target GET reconciliation, got " + opts.method + " " + url);
    }
    return H.jsonResponse(conv("C0", "Renamed"), 200, {});
  });
  H.registry["conversation-rename"].click();
  await H.drain(40);
  const convs = global.window.__mickyConversations.conversationsState();
  const c0 = convs.find((c) => c.id === uuidFrom("C0"));
  return {
    ok: true, scenario: "rename-network-loss-reconciles-via-list",
    c0Title: c0 ? c0.title : null,
    reconciled: c0 !== undefined && c0.title === "Renamed",
    renameButtonEnabled: H.registry["conversation-rename"].disabled === false,
  };
}

async function scenarioRename404ClearsSelection() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.registry["conversation-rename-input"].value = "Renamed";
  H.enqueue(async () => H.jsonResponse({ detail: "not found" }, 404, {}));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversation-rename"].click();
  await H.drain(40);
  const rows = H.registry["conversations-list"].children;
  const list = global.window.__mickyConversations.listState();
  return {
    ok: true, scenario: "rename-404-clears-selection",
    selected: selectedId(),
    rowCount: rows.length,
    selectionCleared: selectedId() === null,
    rowRemoved: rows.length === 0,
    totalIsZero: list.total === 0,
    offsetIsZero: list.offset === 0,
    pagerHidden: list.paginationHidden === true,
    rangeCoherent: list.range === "Showing 0 of 0",
    renameButtonEnabled: H.registry["conversation-rename"].disabled === false,
  };
}

async function scenarioRename404PreservesOtherSelection() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  H.registry["conversation-rename-input"].value = "Renamed";
  // Hold PATCH response on a gate.
  let releasePatch;
  const patchGate = new Promise((r) => { releasePatch = r; });
  H.enqueue(async () => {
    await patchGate;
    return H.jsonResponse({ detail: "not found" }, 404, {});
  });
  H.registry["conversation-rename"].click();
  await H.drain(10);
  // Switch to C1 while PATCH pending.
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.enqueue(async () => H.jsonResponse([], 200, { "X-Total-Count": "0" }));
  H.registry["conversations-list"].children[1].children[0].click();
  await H.drain(25);
  const selAfterSwitch = selectedId();
  // The follow-up list reconciliation must preserve B and remove A.
  H.enqueue(async () => H.jsonResponse(
    [conv("C1", "Conversation 1")], 200, { "X-Total-Count": "1" }));
  // Release the PATCH 404.
  releasePatch();
  await H.drain(30);
  const convs = global.window.__mickyConversations.conversationsState();
  const c0 = convs.find((c) => c.id === uuidFrom("C0"));
  return {
    ok: true, scenario: "rename-404-preserves-other-selection",
    selAfterSwitch,
    finalSelected: selectedId(),
    c0Removed: c0 === undefined,
    bPreserved:
      selAfterSwitch === uuidFrom("C1") && selectedId() === uuidFrom("C1"),
    renameButtonEnabled: H.registry["conversation-rename"].disabled === false,
  };
}

// ---- F6: strict decimal total header ----

async function scenarioListRejectsHexTotal() {
  await bootstrap(0, 50, 51);
  const rowCountBefore = H.registry["conversations-list"].children.length;
  H.enqueue(async () => H.jsonResponse(
    pageOfConversations(0, 50, 51), 200, { "X-Total-Count": "0x10" }));
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  return {
    ok: true, scenario: "list-rejects-hex-total",
    rowsPreserved: H.registry["conversations-list"].children.length === rowCountBefore,
    isError: H.registry["conversations-status"].getAttribute("data-kind") === "error",
  };
}

async function scenarioListRejectsExponentTotal() {
  await bootstrap(0, 50, 51);
  const rowCountBefore = H.registry["conversations-list"].children.length;
  H.enqueue(async () => H.jsonResponse(
    pageOfConversations(0, 50, 51), 200, { "X-Total-Count": "1e2" }));
  H.registry["conversations-refresh"].click();
  await H.drain(25);
  return {
    ok: true, scenario: "list-rejects-exponent-total",
    rowsPreserved: H.registry["conversations-list"].children.length === rowCountBefore,
    isError: H.registry["conversations-status"].getAttribute("data-kind") === "error",
  };
}

// ---- F7: send response validation ----

async function scenarioSendUnknownStatusMarksAmbiguous() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.registry["message"].value = "hello";
  H.enqueue(async () => H.jsonResponse(
    { status: "totally-unknown", message: "x" }, 200, {}));
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(25);
  return {
    ok: true, scenario: "send-unknown-status-marks-ambiguous",
    ambiguous: isAmbiguous(uuidFrom("C0")),
    markedAmbiguous: isAmbiguous(uuidFrom("C0")) === true,
  };
}

async function scenarioSendMissingMessageMarksAmbiguous() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.registry["message"].value = "hello";
  H.enqueue(async () => H.jsonResponse({ status: "success" }, 200, {}));
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(25);
  return {
    ok: true, scenario: "send-missing-message-marks-ambiguous",
    ambiguous: isAmbiguous(uuidFrom("C0")),
    markedAmbiguous: isAmbiguous(uuidFrom("C0")) === true,
  };
}

async function scenarioSendInvalidChallengeMarksAmbiguous() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.registry["message"].value = "hello";
  H.enqueue(async () => H.jsonResponse({
    status: "confirmation-required",
    message: "Please confirm",
    challenge: { challenge_id: "short" },
  }, 200, {}));
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
  await H.drain(25);
  return {
    ok: true, scenario: "send-invalid-challenge-marks-ambiguous",
    ambiguous: isAmbiguous(uuidFrom("C0")),
    markedAmbiguous: isAmbiguous(uuidFrom("C0")) === true,
  };
}

function countAssistantPosts() {
  return H.fetchLog.filter((entry) =>
    entry.url === "/api/assistant/requests" && entry.method === "POST"
  ).length;
}
function submitMessage(value) {
  H.registry["message"].value = value;
  H.registry["request-form"]._listeners["submit"][0]({ preventDefault() {} });
}
function conversationTitle(id, title) {
  return conv(id, title);
}

Object.assign(SCENARIOS, {
  "rename-controls-reset-after-success": scenarioRenameControlsResetAfterSuccess,
  "rename-unknown-outcome-blocks-retry": scenarioRenameUnknownOutcomeBlocksRetry,
  "send-unsupported-capability-valid": scenarioSendUnsupportedCapabilityValid,
  "confirmation-required-no-challenge-valid": scenarioConfirmationRequiredNoChallengeValid,
  "confirmation-required-valid-challenge-shown": scenarioConfirmationRequiredValidChallengeShown,
  "ambiguous-request-blocks-after-switch": scenarioAmbiguousRequestBlocksAfterSwitch,
  "ambiguous-transient-request-blocks-retry": scenarioAmbiguousTransientRequestBlocksRetry,
  "persisted-ambiguous-guard-blocks-request": scenarioPersistedAmbiguousGuardBlocksRequest,
});

async function scenarioRenameControlsResetAfterSuccess() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.enqueue(async () => H.jsonResponse(conversationTitle("C0", "Renamed"), 200, {}));
  H.registry["conversation-rename-input"].value = "Renamed";
  H.registry["conversation-rename"].click();
  await H.drain(30);
  const enabledAfterFirst = H.registry["conversation-rename"].disabled === false;
  H.enqueue(async () => H.jsonResponse(conversationTitle("C0", "Renamed Again"), 200, {}));
  H.registry["conversation-rename-input"].value = "Renamed Again";
  H.registry["conversation-rename"].click();
  await H.drain(30);
  const patches = H.fetchLog.filter((entry) =>
    entry.method === "PATCH" && entry.url.endsWith("/" + uuidFrom("C0"))
  ).length;
  const rows = global.window.__mickyConversations.conversationsState();
  const c0 = rows.find((c) => c.id === uuidFrom("C0"));
  return {
    ok: true, scenario: "rename-controls-reset-after-success",
    enabledAfterFirst,
    enabledAfterSecond: H.registry["conversation-rename"].disabled === false,
    patchCount: patches,
    secondRenameSent: patches === 2,
    secondTitleApplied: !!c0 && c0.title === "Renamed Again",
  };
}

async function scenarioRenameUnknownOutcomeBlocksRetry() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.enqueue(async () => { throw new Error("PATCH network failure"); });
  H.enqueue(async () => { throw new Error("GET reconciliation failure"); });
  H.registry["conversation-rename-input"].value = "Uncertain";
  H.registry["conversation-rename"].click();
  await H.drain(35);
  const firstPatchCount = H.fetchLog.filter((entry) => entry.method === "PATCH").length;
  H.enqueue(async () => H.jsonResponse(conversationTitle("C0", "Should not apply"), 200, {}));
  H.registry["conversation-rename-input"].value = "Should not apply";
  H.registry["conversation-rename"].click();
  await H.drain(20);
  const patchCount = H.fetchLog.filter((entry) => entry.method === "PATCH").length;
  return {
    ok: true, scenario: "rename-unknown-outcome-blocks-retry",
    firstPatchCount,
    patchCount,
    retryBlocked: firstPatchCount === 1 && patchCount === 1,
    buttonReenabled: H.registry["conversation-rename"].disabled === false,
    statusWarns: /unverified|reload/i.test(H.registry["conversation-messages-status"].textContent),
  };
}

async function scenarioSendUnsupportedCapabilityValid() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.enqueue(async () => H.jsonResponse({
    status: "unsupported-capability",
    message: "No matching capability. This request was not executed and was not saved.",
  }, 200, {}));
  submitMessage("unsupported request");
  await H.drain(25);
  return {
    ok: true, scenario: "send-unsupported-capability-valid",
    ambiguous: isAmbiguous(uuidFrom("C0")),
    postCount: countAssistantPosts(),
    noAmbiguity: isAmbiguous(uuidFrom("C0")) === false,
    responseNotRetried: countAssistantPosts() === 1,
    cardHidden: H.registry["confirmation-card"].hidden === true,
  };
}

async function scenarioConfirmationRequiredNoChallengeValid() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.enqueue(async () => H.jsonResponse({
    status: "confirmation-required",
    message: "Confirmation is required, but no challenge was issued in this build. Nothing was run.",
  }, 200, {}));
  submitMessage("consequential request");
  await H.drain(25);
  return {
    ok: true, scenario: "confirmation-required-no-challenge-valid",
    ambiguous: isAmbiguous(uuidFrom("C0")),
    postCount: countAssistantPosts(),
    noAmbiguity: isAmbiguous(uuidFrom("C0")) === false,
    noUsableChallengeCard: H.registry["confirmation-card"].hidden === true,
    serverMessageShown: H.registry["status"].textContent.indexOf("no challenge was issued") !== -1,
  };
}

async function scenarioConfirmationRequiredValidChallengeShown() {
  await bootstrap(0, 50, 1);
  await selectViaUI(0, "C0", 0);
  H.enqueue(async () => H.jsonResponse({
    status: "confirmation-required",
    message: "Please confirm this exact action.",
    challenge: {
      challenge_id: "0123456789abcdef",
      summary: "Example action",
      display_code: "K42AB",
      expires_at: "2027-01-01T00:00:00Z",
    },
  }, 200, {}));
  submitMessage("consequential request");
  await H.drain(25);
  return {
    ok: true, scenario: "confirmation-required-valid-challenge-shown",
    cardShown: H.registry["confirmation-card"].hidden === false,
    postCount: countAssistantPosts(),
    exactlyOnePost: countAssistantPosts() === 1,
  };
}

async function scenarioAmbiguousRequestBlocksAfterSwitch() {
  await bootstrap(0, 50, 2);
  await selectViaUI(0, "C0", 0);
  H.enqueue(async () => H.jsonResponse({
    status: "confirmation-required",
    message: "Please confirm",
    challenge: { challenge_id: "short" },
  }, 200, {}));
  submitMessage("possible confirmation request");
  await H.drain(25);
  const flagAfterFirstPost = global.window.sessionStorage.getItem(
    "micky.ai.request-outcome-unresolved.v1"
  );
  await selectViaUI(1, "C1", 0);
  H.confirmQueue.push(false);
  submitMessage("must not be sent");
  await H.drain(20);
  return {
    ok: true, scenario: "ambiguous-request-blocks-after-switch",
    selectedIsB: selectedId() === uuidFrom("C1"),
    flagPersisted: flagAfterFirstPost === "1",
    postCount: countAssistantPosts(),
    secondPostBlocked: countAssistantPosts() === 1,
  };
}

async function scenarioAmbiguousTransientRequestBlocksRetry() {
  await bootstrap(0, 50, 0);
  H.enqueue(async () => { throw new Error("network lost after POST"); });
  submitMessage("transient request");
  await H.drain(20);
  const first = H.fetchLog.filter((entry) =>
    entry.url === "/api/assistant/requests" && entry.method === "POST"
  )[0];
  const firstBody = first ? JSON.parse(first.body) : {};
  H.confirmQueue.push(false);
  submitMessage("do not retry transient request");
  await H.drain(20);
  return {
    ok: true, scenario: "ambiguous-transient-request-blocks-retry",
    noConversationId: !Object.prototype.hasOwnProperty.call(firstBody, "conversation_id"),
    flagPersisted: global.window.sessionStorage.getItem(
      "micky.ai.request-outcome-unresolved.v1"
    ) === "1",
    postCount: countAssistantPosts(),
    secondPostBlocked: countAssistantPosts() === 1,
  };
}

async function scenarioPersistedAmbiguousGuardBlocksRequest() {
  global.window.sessionStorage.setItem("micky.ai.request-outcome-unresolved.v1", "1");
  await bootstrap(0, 50, 0);
  H.confirmQueue.push(false);
  submitMessage("must remain blocked after reload");
  await H.drain(20);
  return {
    ok: true, scenario: "persisted-ambiguous-guard-blocks-request",
    postCount: countAssistantPosts(),
    noNewPost: countAssistantPosts() === 0,
    flagStillPresent: global.window.sessionStorage.getItem(
      "micky.ai.request-outcome-unresolved.v1"
    ) === "1",
  };
}

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