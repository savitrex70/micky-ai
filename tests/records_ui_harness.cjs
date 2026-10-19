"use strict";

// Behavioural harness for the confirmation-records UI.
//
// Runs the real src/rop/web/static/app.js inside a minimal dependency-free
// DOM/fetch mock, drives the actual click handlers, and prints a JSON summary
// on stdout. Exits non-zero on any internal assertion failure.
//
// Usage: node records_ui_harness.cjs <app.js path> <mode>
//   mode = "delete-refresh" | "duplicate-click"

const fs = require("fs");
const appPath = process.argv[2];
const mode = process.argv[3] || "delete-refresh";
if (!appPath) {
    console.error("usage: node records_ui_harness.cjs <app.js path> <mode>");
    process.exit(2);
}
const src = fs.readFileSync(appPath, "utf8").replace(/^\uFEFF/, "");

// ---------- minimal DOM ----------
function makeEl(id) {
    const listeners = {};
    const attrs = {};
    const el = {
        id: id,
        tagName: "DIV",
        className: "",
        _text: "",
        value: "",
        disabled: false,
        hidden: false,
        checked: false,
        type: "text",
        colSpan: 1,
        children: [],
        parentNode: null,
        setAttribute: function (k, v) { attrs[k] = String(v); },
        getAttribute: function (k) { return attrs[k]; },
        removeAttribute: function (k) { delete attrs[k]; },
        appendChild: function (child) {
            this.children.push(child);
            child.parentNode = this;
            return child;
        },
        removeChild: function (child) {
            const i = this.children.indexOf(child);
            if (i >= 0) this.children.splice(i, 1);
            child.parentNode = null;
            return child;
        },
        insertBefore: function (child, ref) {
            if (ref == null) return this.appendChild(child);
            const i = this.children.indexOf(ref);
            if (i < 0) return this.appendChild(child);
            this.children.splice(i, 0, child);
            child.parentNode = this;
            return child;
        },
        addEventListener: function (evt, cb) {
            (listeners[evt] = listeners[evt] || []).push(cb);
        },
        removeEventListener: function (evt, cb) {
            const l = listeners[evt];
            if (l) {
                const i = l.indexOf(cb);
                if (i >= 0) l.splice(i, 1);
            }
        },
        focus: function () {},
        click: function () {
            const l = listeners["click"] || [];
            for (const cb of l) cb({ preventDefault: function () {}, target: this });
        },
        dispatchChange: function () {
            const l = listeners["change"] || [];
            for (const cb of l) cb({ target: this });
        },
        _listeners: listeners,
        _attrs: attrs,
    };
    Object.defineProperty(el, "textContent", {
        get: function () { return this._text; },
        set: function (v) { this._text = String(v); this.children = []; },
    });
    Object.defineProperty(el, "firstChild", {
        get: function () { return this.children[0] || null; },
    });
    return el;
}

function textOf(el) {
    if (!el) return "";
    let s = el._text || "";
    for (const c of el.children) s += textOf(c);
    return s;
}

const ids = [
    "request-form", "message", "submit", "status", "history",
    "confirmation-card", "confirmation-summary", "confirmation-display-code",
    "confirmation-expiry", "confirmation-code-input",
    "confirmation-confirm", "confirmation-cancel",
    "records-load", "records-export", "records-delete", "records-status",
    "records-pagination", "records-prev", "records-next", "records-range",
    "records-table", "records-tbody",
];
const registry = {};
for (const id of ids) registry[id] = makeEl(id);
const body = makeEl("body");
const documentMock = {
    getElementById: function (id) { return registry[id] || null; },
    createElement: function (tag) {
        const e = makeEl(null);
        e.tagName = String(tag).toUpperCase();
        return e;
    },
    body: body,
};

// ---------- fetch mock ----------
const queue = [];
const fetchLog = [];
function enqueue(handler) { queue.push(handler); }
async function fetchMock(url, opts) {
    fetchLog.push({
        url: url,
        method: (opts && opts.method) || "GET",
        body: opts && opts.body,
    });
    const h = queue.shift();
    if (!h) throw new Error("unexpected fetch: " + url);
    return h(url, opts);
}
function jsonResponse(payload, status) {
    status = status || 200;
    return {
        ok: status >= 200 && status < 300,
        status: status,
        headers: { get: function () { return null; } },
        json: async function () { return payload; },
        text: async function () { return JSON.stringify(payload); },
    };
}

const confirmQueue = [];
const windowMock = {
    confirm: function () { return confirmQueue.shift(); },
};
const URLMock = {
    createObjectURL: function () { return "blob:x"; },
    revokeObjectURL: function () {},
};
const BlobMock = function (parts, opts) { this.parts = parts; this.opts = opts; };
function setTimeoutImmediate(fn) { fn(); return 0; }

// ---------- run real app.js ----------
const runApp = new Function(
    "document", "window", "fetch", "URL", "Blob", "setTimeout", src
);
runApp(documentMock, windowMock, fetchMock, URLMock, BlobMock, setTimeoutImmediate);

// ---------- fixtures ----------
const recA = {
    id: "11111111-1111-1111-1111-111111111111",
    operation_id: "op-a",
    status: "PENDING",
    required_risk: "CONSEQUENTIAL",
    required_reason: "AUTHORIZATION_REQUIRED",
    outcome: null,
    material_state: "ABSENT",
    created_at: "2026-01-01T00:00:00Z",
    terminal_at: null,
};
const recB = {
    id: "22222222-2222-2222-2222-222222222222",
    operation_id: "op-b",
    status: "CONSUMED",
    required_risk: "CONSEQUENTIAL",
    required_reason: "AUTHORIZATION_REQUIRED",
    outcome: "SUCCEEDED",
    material_state: "ABSENT",
    created_at: "2026-01-02T00:00:00Z",
    terminal_at: "2026-01-02T00:05:00Z",
};

function pageResponse(records) {
    return {
        format: "rop.assistant-confirmation-records",
        version: "1",
        generated_at: "2026-01-01T00:00:00Z",
        retention_days: 30,
        total_record_count: records.length,
        record_count: records.length,
        offset: 0,
        limit: 50,
        has_more: false,
        next_offset: null,
        is_complete: true,
        records: records,
        notes: [],
    };
}

function drainAll(n) {
    let p = Promise.resolve();
    for (let i = 0; i < n; i++) p = p.then(function () {
        return new Promise(function (r) { setImmediate(r); });
    });
    return p;
}

function selectFirstRowCheckbox() {
    const tbody = registry["records-tbody"];
    const firstRow = tbody.children[0];
    const cb = firstRow.children[0].children[0];
    cb.checked = true;
    cb.dispatchChange();
    return cb;
}

async function scenarioDeleteRefresh() {
    const tbody = registry["records-tbody"];

    enqueue(async function () { return jsonResponse(pageResponse([recA, recB])); });
    registry["records-load"].click();
    await drainAll(5);

    const initial = textOf(tbody);
    if (initial.indexOf("op-a") < 0 || initial.indexOf("op-b") < 0) {
        throw new Error("initial render missing rows: " + JSON.stringify(initial));
    }

    selectFirstRowCheckbox();
    confirmQueue.push(true);

    enqueue(async function (url, opts) {
        if (opts.method !== "POST") {
            throw new Error("expected POST, got " + opts.method);
        }
        const parsed = JSON.parse(opts.body);
        if (!Array.isArray(parsed.record_ids) || parsed.record_ids.length !== 1) {
            throw new Error("expected one record id, got: " + opts.body);
        }
        if (parsed.record_ids[0] !== recA.id) {
            throw new Error("wrong id: " + parsed.record_ids[0]);
        }
        return jsonResponse({ deleted_count: 1 });
    });
    enqueue(async function (url) {
        if (url.indexOf("confirmation-records?limit") < 0) {
            throw new Error("unexpected refresh url: " + url);
        }
        return jsonResponse(pageResponse([recB]));
    });

    registry["records-delete"].click();
    await drainAll(12);

    const finalText = textOf(tbody);
    const statusText = registry["records-status"].textContent;

    return {
        ok: true,
        scenario: "delete-refresh",
        initialContainsA: initial.indexOf("op-a") >= 0,
        initialContainsB: initial.indexOf("op-b") >= 0,
        finalContainsA: finalText.indexOf("op-a") >= 0,
        finalContainsB: finalText.indexOf("op-b") >= 0,
        statusMentionsDeleted: statusText.indexOf("Deleted 1 record") >= 0,
        statusText: statusText,
        finalText: finalText,
    };
}

async function scenarioDuplicateClick() {
    enqueue(async function () { return jsonResponse(pageResponse([recA, recB])); });
    registry["records-load"].click();
    await drainAll(5);

    selectFirstRowCheckbox();
    confirmQueue.push(true);

    let resolvePost;
    enqueue(function () {
        return new Promise(function (resolve) {
            resolvePost = function () { resolve(jsonResponse({ deleted_count: 1 })); };
        });
    });
    enqueue(async function () { return jsonResponse(pageResponse([recB])); });

    registry["records-delete"].click();
    // Second click while first is in flight — must be blocked by inFlight.
    registry["records-delete"].click();
    await drainAll(3);

    const postCalls = fetchLog.filter(function (f) { return f.method === "POST"; }).length;

    // Release the pending POST so the flow completes cleanly.
    resolvePost();
    await drainAll(12);

    return {
        ok: true,
        scenario: "duplicate-click",
        postCalls: postCalls,
    };
}

(async function main() {
    try {
        let out;
        if (mode === "duplicate-click") {
            out = await scenarioDuplicateClick();
        } else {
            out = await scenarioDeleteRefresh();
        }
        process.stdout.write(JSON.stringify(out) + "\n");
        process.exit(0);
    } catch (err) {
        console.error("SCENARIO FAILURE:", err.message);
        process.exit(1);
    }
})();
