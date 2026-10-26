"use strict";

const fs = require("fs");
const vm = require("vm");

const [scriptPath, itemsJson] = process.argv.slice(2);
if (!scriptPath || !itemsJson) {
  console.error("usage: node workspace_ui_harness.cjs <workspace.js> <items-json>");
  process.exit(2);
}

const source = fs.readFileSync(scriptPath, "utf8").replace(/^\uFEFF/, "");
const persistedItems = JSON.parse(itemsJson);
const fixedNow = Date.parse("2026-10-24T12:00:00.000Z");

class FixedDate extends Date {
  static now() {
    return fixedNow;
  }
}

function makeElement(id, tagName = "div") {
  const listeners = Object.create(null);
  const attrs = Object.create(null);
  const node = {
    id,
    tagName: String(tagName).toUpperCase(),
    className: "",
    type: "",
    value: "",
    hidden: false,
    disabled: false,
    checked: false,
    elements: [],
    children: [],
    parentNode: null,
    dataset: {},
    _text: "",
    addEventListener(event, callback) {
      (listeners[event] ||= []).push(callback);
    },
    removeEventListener(event, callback) {
      const handlers = listeners[event] || [];
      const index = handlers.indexOf(callback);
      if (index >= 0) handlers.splice(index, 1);
    },
    appendChild(child) {
      this.children.push(child);
      child.parentNode = this;
      return child;
    },
    replaceChildren(...children) {
      this.children.forEach((child) => {
        child.parentNode = null;
      });
      this.children = [];
      children.forEach((child) => this.appendChild(child));
    },
    removeChild(child) {
      const index = this.children.indexOf(child);
      if (index >= 0) this.children.splice(index, 1);
      child.parentNode = null;
      return child;
    },
    setAttribute(name, value) {
      attrs[name] = String(value);
    },
    getAttribute(name) {
      return attrs[name] ?? null;
    },
    removeAttribute(name) {
      delete attrs[name];
    },
    focus() {},
    click() {
      for (const callback of listeners.click || []) {
        callback({ preventDefault() {}, target: this });
      }
    },
    _listeners: listeners,
  };
  Object.defineProperty(node, "textContent", {
    get() {
      return this._text;
    },
    set(value) {
      this._text = value == null ? "" : String(value);
      this.children.forEach((child) => {
        child.parentNode = null;
      });
      this.children = [];
    },
  });
  Object.defineProperty(node, "firstChild", {
    get() {
      return this.children[0] || null;
    },
  });
  return node;
}

function textOf(node) {
  if (!node) return "";
  return node._text + node.children.map(textOf).join("");
}

function response(payload) {
  return {
    ok: true,
    status: 200,
    async json() {
      return payload;
    },
  };
}

async function flushPromises() {
  for (let i = 0; i < 30; i += 1) await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

async function makePage() {
  const elements = new Map();
  const intervals = [];
  const fetchLog = [];
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeElement(id));
      return elements.get(id);
    },
    createElement(tagName) {
      return makeElement("", tagName);
    },
  };
  for (const match of source.matchAll(/byId\("([^"]+)"\)/g)) {
    document.getElementById(match[1]);
  }
  document.getElementById("workspace-filter").value = "all";

  const window = {
    sessionStorage: {
      getItem() {
        return null;
      },
      setItem() {},
      removeItem() {},
    },
    setInterval(callback, milliseconds) {
      intervals.push({ callback, milliseconds });
      return intervals.length;
    },
    addEventListener() {},
    confirm() {
      return true;
    },
    prompt() {
      return null;
    },
  };

  async function fetchMock(url, options = {}) {
    const path = String(url);
    fetchLog.push({ url: path, method: options.method || "GET" });
    if (path === "/api/assistant/workspace/items") {
      return response(persistedItems);
    }
    if (path === "/api/assistant/workspace/retrieval-roots") {
      return response([]);
    }
    if (path === "/sessions?offset=0&limit=50") {
      return response([]);
    }
    throw new Error("unexpected request: " + path);
  }

  vm.runInNewContext(
    source,
    {
      document,
      window,
      fetch: fetchMock,
      Date: FixedDate,
      TextEncoder,
      console,
    },
    { filename: scriptPath }
  );
  await flushPromises();

  const summary = () => {
    const overdue = document.getElementById("workspace-overdue");
    const list = document.getElementById("workspace-items");
    return {
      overdueVisible: overdue.hidden === false,
      overdueText: textOf(overdue),
      itemCardCount: list.children.length,
      apiListRequested: fetchLog.some(
        (entry) => entry.method === "GET" && entry.url === "/api/assistant/workspace/items"
      ),
    };
  };

  const initial = summary();
  if (intervals.length !== 1 || intervals[0].milliseconds !== 60000) {
    throw new Error("expected the established 60-second in-app refresh");
  }
  await intervals[0].callback();
  await flushPromises();
  const refreshed = summary();
  return {
    initial,
    refreshed,
    intervalMilliseconds: intervals[0].milliseconds,
  };
}

(async function main() {
  try {
    const firstPage = await makePage();
    // The API's persisted item response is reused to model a clean page context
    // after an API restart; no browser-local copy is used for the item list.
    const restartedPage = await makePage();
    const output = {
      initial: firstPage.initial,
      refreshed: firstPage.refreshed,
      afterReload: restartedPage.initial,
      intervalMilliseconds: firstPage.intervalMilliseconds,
    };
    for (const phase of [output.initial, output.refreshed, output.afterReload]) {
      if (!phase.apiListRequested) throw new Error("workspace API item list was not read");
    }
    process.stdout.write(JSON.stringify(output) + "\n");
  } catch (error) {
    console.error("SCENARIO FAILURE:", error.stack || error.message);
    process.exitCode = 1;
  }
})();