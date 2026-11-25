var genfacadeBraille = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // viewer-entry.ts
  var viewer_entry_exports = {};
  __export(viewer_entry_exports, {
    registerDataSource: () => registerDataSource
  });

  // upstream/runtime/busy.ts
  var sources = /* @__PURE__ */ new Map();
  function busyOf(doc) {
    const busy = {};
    for (const [name, source] of sources) {
      const count = source();
      if (count > 0) busy[name] = count;
    }
    const animations = doc.getAnimations?.().filter((a) => a.playState === "running" && isFinite(endOf(a))).length ?? 0;
    if (animations > 0) busy.animations = animations;
    return busy;
  }
  function endOf(animation) {
    const end = animation.effect?.getComputedTiming().endTime;
    return typeof end === "number" ? end : Number.POSITIVE_INFINITY;
  }
  var dataSources = /* @__PURE__ */ new Map();
  function registerDataSource(name, source) {
    dataSources.set(name, source);
  }
  function dataOf() {
    const data = {};
    for (const [name, source] of dataSources) data[name] = source();
    return data;
  }

  // upstream/runtime/errorsLog.ts
  var MAX_ENTRIES = 200;
  function startErrorsLog(win) {
    let entries = [];
    const disposers = [];
    const push = (entry) => {
      entries.push({ ...entry, path: win.location.pathname, at: Date.now() });
      if (entries.length > MAX_ENTRIES) entries.shift();
    };
    const originalConsoleError = win.console.error;
    win.console.error = (...args) => {
      push({ kind: "console", message: args.map(stringify).join(" ").slice(0, 500) });
      originalConsoleError.apply(win.console, args);
    };
    disposers.push(() => {
      win.console.error = originalConsoleError;
    });
    const onError = (event) => push({ kind: "exception", message: String(event.message).slice(0, 500) });
    const onRejection = (event) => push({ kind: "rejection", message: stringify(event.reason).slice(0, 500) });
    win.addEventListener("error", onError);
    win.addEventListener("unhandledrejection", onRejection);
    disposers.push(() => {
      win.removeEventListener("error", onError);
      win.removeEventListener("unhandledrejection", onRejection);
    });
    if (typeof win.fetch === "function") {
      const originalFetch = win.fetch;
      win.fetch = async (...args) => {
        const method = (args[1]?.method ?? (args[0] instanceof Request ? args[0].method : "GET")).toUpperCase();
        const url = args[0] instanceof Request ? args[0].url : String(args[0]);
        try {
          const response = await originalFetch.apply(win, args);
          if (response.status >= 400) {
            const code = errorCodeOf(await response.clone().text().catch(() => ""));
            push({
              kind: "request",
              message: `${method} ${url} -> ${response.status}${code ? ` ${code}` : ""}`,
              method,
              url,
              status: response.status,
              ...code ? { code } : {}
            });
          }
          return response;
        } catch (error) {
          push({ kind: "request", message: `${method} ${url} -> ${stringify(error)}`, method, url, status: 0 });
          throw error;
        }
      };
      disposers.push(() => {
        win.fetch = originalFetch;
      });
    }
    const xhrProto = win.XMLHttpRequest?.prototype;
    if (xhrProto) {
      const originalOpen = xhrProto.open;
      const originalSend = xhrProto.send;
      xhrProto.open = function(method, url, ...rest) {
        this.__stalkerReq = { method: method.toUpperCase(), url: String(url) };
        return originalOpen.call(this, method, url, ...rest);
      };
      xhrProto.send = function(body) {
        this.addEventListener("loadend", () => {
          const req = this.__stalkerReq;
          if (!req || this.status > 0 && this.status < 400) return;
          const text = this.responseType === "" || this.responseType === "text" ? this.responseText : "";
          const code = errorCodeOf(text || (this.responseType === "json" ? stringify(this.response) : ""));
          push({
            kind: "request",
            message: `${req.method} ${req.url} -> ${this.status}${code ? ` ${code}` : ""}`,
            method: req.method,
            url: req.url,
            status: this.status,
            ...code ? { code } : {}
          });
        });
        return originalSend.call(this, body);
      };
      disposers.push(() => {
        xhrProto.open = originalOpen;
        xhrProto.send = originalSend;
      });
    }
    return {
      read: (options) => {
        const out = entries.slice();
        if (options?.clear) entries = [];
        return out;
      },
      dispose: () => disposers.reverse().forEach((d) => d())
    };
  }
  function errorCodeOf(text) {
    if (!text || text.length > 2e4) return void 0;
    try {
      const body = JSON.parse(text);
      const code = body?.detail?.code ?? body?.code;
      return typeof code === "string" && code ? code.slice(0, 80) : void 0;
    } catch {
      return void 0;
    }
  }
  function stringify(value) {
    if (value instanceof Error) return `${value.name}: ${value.message}`;
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value) ?? String(value);
    } catch {
      return String(value);
    }
  }

  // upstream/runtime/screenState.ts
  var SCREEN_TESTID_PREFIX = "screen.";
  var SCREEN_FACT_ATTR = "data-fact";
  var SCREEN_FACT_VALUE_ATTR = "data-fact-value";

  // upstream/runtime/inspect.ts
  var IMPLICIT_ROLES = {
    button: "button",
    select: "combobox",
    textarea: "textbox",
    a: "link",
    nav: "navigation",
    dialog: "dialog",
    li: "listitem",
    ul: "list",
    ol: "list",
    tr: "row",
    td: "cell",
    table: "table",
    main: "main",
    img: "img",
    progress: "progressbar",
    h1: "heading",
    h2: "heading",
    h3: "heading",
    h4: "heading",
    h5: "heading",
    h6: "heading"
  };
  var INPUT_ROLES = {
    checkbox: "checkbox",
    radio: "radio",
    range: "slider",
    button: "button",
    submit: "button",
    reset: "button",
    search: "searchbox"
  };
  function roleOf(el) {
    const explicit = el.getAttribute("role")?.trim().split(/\s+/)[0];
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return el.hasAttribute("href") ? "link" : null;
    if (tag === "input") {
      const type = (el.getAttribute("type") ?? "text").toLowerCase();
      return INPUT_ROLES[type] ?? "textbox";
    }
    return IMPLICIT_ROLES[tag] ?? null;
  }
  function squash(text) {
    return (text ?? "").replace(/\s+/g, " ").trim();
  }
  function visibleTextOf(el) {
    return squash(el.textContent);
  }
  function shownText(node) {
    if (!node) return "";
    if (node.nodeType === 3) return node.textContent ?? "";
    if (node instanceof Element && node.getAttribute("aria-hidden") === "true") return "";
    return Array.from(node.childNodes).map(shownText).join("");
  }
  function nameOf(el) {
    const doc = el.ownerDocument;
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const joined = labelledBy.split(/\s+/).map((id2) => squash(shownText(doc.getElementById(id2)))).filter(Boolean).join(" ");
      if (joined) return joined;
    }
    const aria = squash(el.getAttribute("aria-label"));
    if (aria) return aria;
    const id = el.getAttribute("id");
    if (id) {
      const label = Array.from(doc.querySelectorAll("label")).find(
        (l) => l.getAttribute("for") === id
      );
      const text = squash(shownText(label));
      if (text) return text;
    }
    const wrapping = el.closest("label");
    if (wrapping && wrapping !== el) {
      const text = squash(shownText(wrapping));
      if (text) return text;
    }
    const alt = squash(el.getAttribute("alt"));
    if (alt) return alt;
    const tag = el.tagName.toLowerCase();
    const fromContent = tag === "input" || tag === "textarea" || tag === "select" ? "" : squash(shownText(el));
    if (fromContent) return fromContent;
    return squash(el.getAttribute("title")) || squash(el.getAttribute("placeholder"));
  }
  function boolAttr(el, name) {
    const raw = el.getAttribute(name);
    if (raw == null) return void 0;
    return raw === "true";
  }
  function ariaStateOf(el) {
    const state = {};
    const busy = boolAttr(el, "aria-busy");
    if (busy !== void 0) state.busy = busy;
    const invalid = el.getAttribute("aria-invalid");
    if (invalid != null) state.invalid = invalid !== "false";
    const supportsDisabled = "disabled" in el;
    const nativeDisabled = supportsDisabled && el.disabled === true;
    const ariaDisabled = boolAttr(el, "aria-disabled");
    if (supportsDisabled || ariaDisabled !== void 0) {
      state.disabled = nativeDisabled || ariaDisabled === true || el.hasAttribute("data-disabled");
    }
    const selected = boolAttr(el, "aria-selected");
    if (selected !== void 0) state.selected = selected;
    const current = el.getAttribute("aria-current");
    if (current != null && current !== "false") state.current = current;
    const expanded = boolAttr(el, "aria-expanded");
    if (expanded !== void 0) state.expanded = expanded;
    const checked = el.getAttribute("aria-checked");
    if (checked != null) state.checked = checked === "mixed" ? "mixed" : checked === "true";
    else if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) {
      state.checked = el.checked;
    }
    const pressed = el.getAttribute("aria-pressed");
    if (pressed != null) state.pressed = pressed === "mixed" ? "mixed" : pressed === "true";
    return state;
  }
  function rectOf(el) {
    const r = el.getBoundingClientRect();
    return { x: round(r.x), y: round(r.y), w: round(r.width), h: round(r.height) };
  }
  function round(n) {
    return Math.round(n * 10) / 10;
  }
  function isInViewport(rect, win) {
    if (rect.w <= 0 || rect.h <= 0) return false;
    const vw = win?.innerWidth ?? 0;
    const vh = win?.innerHeight ?? 0;
    return rect.x < vw && rect.y < vh && rect.x + rect.w > 0 && rect.y + rect.h > 0;
  }
  function describeOccluder(el) {
    return {
      testid: el.getAttribute("data-testid"),
      role: roleOf(el),
      name: nameOf(el).slice(0, 80),
      tag: el.tagName.toLowerCase()
    };
  }
  function occludedByOf(el, rect = rectOf(el)) {
    if (rect.w <= 0 || rect.h <= 0) return [];
    const doc = el.ownerDocument;
    const inset = Math.min(1, rect.w / 2, rect.h / 2);
    const points = [
      [rect.x + rect.w / 2, rect.y + rect.h / 2],
      [rect.x + inset, rect.y + inset],
      [rect.x + rect.w - inset, rect.y + inset],
      [rect.x + inset, rect.y + rect.h - inset],
      [rect.x + rect.w - inset, rect.y + rect.h - inset]
    ];
    const found = /* @__PURE__ */ new Map();
    for (const [px, py] of points) {
      const hit = doc.elementFromPoint(px, py);
      if (!hit || hit === el || el.contains(hit) || hit.contains(el)) continue;
      if (!found.has(hit)) found.set(hit, describeOccluder(hit));
    }
    return Array.from(found.values());
  }
  function valueOf(el) {
    return el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement ? el.value : void 0;
  }
  function visualBoxOf(el) {
    if (!(el instanceof HTMLInputElement)) return el;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return el;
    const label = el.id && Array.from(el.ownerDocument.querySelectorAll("label")).find((l) => l.htmlFor === el.id) || el.closest("label");
    return label ?? el;
  }
  function describeElement(el) {
    const box = visualBoxOf(el);
    const rect = rectOf(box);
    const value = valueOf(el);
    return {
      ...value === void 0 ? {} : { value },
      domIndex: Array.prototype.indexOf.call(el.ownerDocument.querySelectorAll("*"), el),
      testid: el.getAttribute("data-testid"),
      role: roleOf(el),
      name: nameOf(el),
      text: visibleTextOf(el).slice(0, 200),
      aria: ariaStateOf(el),
      rect,
      inViewport: isInViewport(rect, el.ownerDocument.defaultView),
      occludedBy: occludedByOf(box, rect),
      clipped: el.scrollWidth > el.clientWidth
    };
  }
  function matchesTestid(actual, wanted) {
    if (actual == null) return false;
    return wanted.endsWith("*") ? actual.startsWith(wanted.slice(0, -1)) : actual === wanted;
  }
  var norm = (s) => s.toLowerCase();
  function matchesQuery(el, query) {
    if (query.testid !== void 0 && !matchesTestid(el.getAttribute("data-testid"), query.testid)) {
      return false;
    }
    if (query.role !== void 0 && roleOf(el) !== query.role) return false;
    if (query.name !== void 0 && !norm(nameOf(el)).includes(norm(query.name))) return false;
    if (query.text !== void 0 && !norm(visibleTextOf(el)).includes(norm(query.text))) {
      return false;
    }
    return true;
  }
  function isRendered(el) {
    const win = el.ownerDocument.defaultView;
    if (!win) return true;
    const style = win.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden";
  }
  var ELEMENT_SELECTOR = [
    "[data-testid]",
    "button",
    "a[href]",
    "input",
    "textarea",
    "select",
    '[role="button"]',
    '[role="tab"]',
    '[role="link"]',
    '[role="checkbox"]',
    '[role="menuitem"]',
    '[role="option"]',
    '[role="switch"]',
    '[role="alert"]',
    "h1",
    "h2",
    "h3"
  ].join(",");
  function queryElements(root, query) {
    if (query?.text !== void 0) {
      const matched = Array.from(root.querySelectorAll("*")).filter((el) => matchesQuery(el, query));
      const deepest = matched.filter((el) => !matched.some((other) => other !== el && el.contains(other)));
      return deepest.filter(isRendered);
    }
    const all = Array.from(root.querySelectorAll(ELEMENT_SELECTOR)).filter(isRendered);
    return query ? all.filter((el) => matchesQuery(el, query)) : all;
  }
  function findInfos(doc, query) {
    return queryElements(doc, query).map(describeElement);
  }
  function screenRootOf(doc) {
    const roots = Array.from(doc.querySelectorAll(`[data-testid^="${SCREEN_TESTID_PREFIX}"]`));
    return roots.find((root) => !roots.some((other) => other !== root && root.contains(other))) ?? null;
  }
  function screenInfoOf(doc) {
    const root = screenRootOf(doc);
    if (!root) return null;
    const scopes = [root, ...Array.from(doc.querySelectorAll('[role="dialog"]'))];
    const seen = /* @__PURE__ */ new Set();
    const elements = [];
    for (const scope of scopes) {
      for (const el of queryElements(scope)) {
        if (seen.has(el) || el === root) continue;
        seen.add(el);
        elements.push(describeElement(el));
      }
    }
    const alerts = Array.from(doc.querySelectorAll('[role="alert"]')).filter(isRendered).map(visibleTextOf).filter(Boolean);
    return {
      testid: root.getAttribute("data-testid") ?? "",
      name: (root.getAttribute("data-testid") ?? "").slice(SCREEN_TESTID_PREFIX.length),
      state: root.getAttribute("data-state"),
      url: doc.defaultView?.location.href ?? "",
      outerScreens: Array.from(doc.querySelectorAll(`[data-testid^="${SCREEN_TESTID_PREFIX}"]`)).filter((other) => other !== root && other.contains(root)).map((other) => ({
        testid: other.getAttribute("data-testid") ?? "",
        state: other.getAttribute("data-state")
      })),
      overlays: overlaysOf(doc),
      facts: factsOf(scopes),
      alerts,
      elements
    };
  }
  var OVERLAY_SELECTOR = '[role="dialog"],[role="alertdialog"],[role="listbox"],[role="menu"]';
  function overlaysOf(doc) {
    return Array.from(doc.querySelectorAll(OVERLAY_SELECTOR)).filter((el) => isRendered(el) && rectOf(el).w > 0 && rectOf(el).h > 0).map((el) => ({
      role: el.getAttribute("role") ?? "",
      name: (nameOf(el) || el.querySelector("h1,h2,h3,h4")?.textContent || "").trim().slice(0, 80),
      testid: el.getAttribute("data-testid")
    }));
  }
  function factsOf(scopes) {
    const facts = {};
    for (const scope of scopes) {
      for (const el of Array.from(scope.querySelectorAll(`[${SCREEN_FACT_ATTR}]`))) {
        if (!isRendered(el)) continue;
        facts[el.getAttribute(SCREEN_FACT_ATTR) ?? ""] = el.getAttribute(SCREEN_FACT_VALUE_ATTR) ?? "";
      }
    }
    return facts;
  }
  function computeLayout(a, b) {
    const gapX = Math.max(0, Math.max(a.x, b.x) - Math.min(a.x + a.w, b.x + b.w));
    const gapY = Math.max(0, Math.max(a.y, b.y) - Math.min(a.y + a.h, b.y + b.h));
    const overlapW = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
    const overlapH = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
    const overlaps = overlapW > 0 && overlapH > 0;
    return {
      a,
      b,
      aAbove: a.y + a.h <= b.y,
      aBelow: a.y >= b.y + b.h,
      aLeftOf: a.x + a.w <= b.x,
      aRightOf: a.x >= b.x + b.w,
      gapX: round(gapX),
      gapY: round(gapY),
      distance: round(Math.hypot(gapX, gapY)),
      overlaps,
      overlapArea: overlaps ? round(overlapW * overlapH) : 0
    };
  }
  function layoutOf(doc, a, b) {
    const ea = queryElements(doc, { testid: a })[0];
    const eb = queryElements(doc, { testid: b })[0];
    if (!ea || !eb) return null;
    return computeLayout(rectOf(ea), rectOf(eb));
  }
  function setNativeValue(el, value) {
    const proto = Object.getPrototypeOf(el);
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (setter) setter.call(el, value);
    else el.value = value;
  }
  function dispatchMouse(el, type) {
    const Ctor = el.ownerDocument.defaultView?.MouseEvent ?? MouseEvent;
    el.dispatchEvent(new Ctor(type, { bubbles: true, cancelable: true }));
  }
  function actOn(doc, testid, action, value) {
    const el = queryElements(doc, { testid })[0];
    if (!el) return { ok: false, error: "not_found" };
    const info = describeElement(el);
    if (info.aria.disabled) return { ok: false, error: "disabled" };
    if (action === "focus") {
      el.focus();
      return { ok: true };
    }
    if (action === "click") {
      if (info.occludedBy.length > 0) {
        return { ok: false, error: "occluded", occludedBy: info.occludedBy };
      }
      el.focus?.();
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup"]) {
        dispatchMouse(el, type);
      }
      el.click();
      return { ok: true };
    }
    const isField = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement;
    if (!isField) return { ok: false, error: "unsupported" };
    if (!(el instanceof HTMLSelectElement) && el.readOnly) return { ok: false, error: "unsupported" };
    if (action === "type" || action === "clear") {
      if (el instanceof HTMLSelectElement) return { ok: false, error: "unsupported" };
      el.focus();
      setNativeValue(el, action === "clear" ? "" : value ?? "");
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return { ok: true };
    }
    if (!(el instanceof HTMLSelectElement)) return { ok: false, error: "unsupported" };
    setNativeValue(el, value ?? "");
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return { ok: true };
  }

  // upstream/runtime/tools.ts
  var queryProperties = {
    testid: { type: "string", description: "Exact data-testid; `prefix*` matches by the start." },
    role: { type: "string", description: "ARIA role: button, textbox, tab, link, ..." },
    name: { type: "string", description: "Substring of the accessible name, case-insensitive." },
    text: { type: "string", description: "Substring of the visible text, case-insensitive." }
  };
  var STALKER_TOOLS = [
    {
      name: "screen",
      description: "Current screen: testid, data-state (loading|ready|empty|error), role=alert texts and interactive elements with role, name, ARIA state, bounding box, visibility, overlap and clipping.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false }
    },
    {
      name: "busy",
      description: "What on the page has not finished yet: navigation, loads without data (queries), submissions (mutations), finite animations (animations) - a count for each. An empty object means the page is at rest.",
      inputSchema: { type: "object", properties: {}, additionalProperties: false }
    },
    {
      name: "find",
      description: "Page elements by testid, role, name or text (conditions are combined with AND) with the same fields as screen().",
      inputSchema: { type: "object", properties: queryProperties, additionalProperties: false }
    },
    {
      name: "layout",
      description: "Relative position of two elements by testid: above/below/left/right, gaps, distance, intersection.",
      inputSchema: {
        type: "object",
        properties: {
          a: { type: "string", description: "data-testid of the first element." },
          b: { type: "string", description: "data-testid of the second element." }
        },
        required: ["a", "b"],
        additionalProperties: false
      }
    },
    {
      name: "errors",
      description: "Console errors, unhandled exceptions and failed requests (status 400 and above, or network) since the current screen was loaded.",
      inputSchema: {
        type: "object",
        properties: { clear: { type: "boolean", description: "Clear the buffer after reading." } },
        additionalProperties: false
      }
    },
    {
      name: "act",
      description: "Action on an element by testid through the same event path as a person. A click on a covered or disabled element is rejected, naming the covering element.",
      inputSchema: {
        type: "object",
        properties: {
          testid: { type: "string", description: "data-testid of the element." },
          action: { enum: ["click", "type", "select", "focus", "clear"] },
          value: { type: "string", description: "Text for type or value for select." }
        },
        required: ["testid", "action"],
        additionalProperties: false
      }
    }
  ];

  // upstream/runtime/install.ts
  function createStalker(win) {
    const doc = win.document;
    const log = startErrorsLog(win);
    return {
      version: "agent-braille.v2",
      screen: () => screenInfoOf(doc),
      busy: () => busyOf(doc),
      data: () => dataOf(),
      find: (query) => findInfos(doc, query ?? {}),
      layout: (a, b) => layoutOf(doc, a, b),
      errors: (options) => log.read(options),
      act: (testid, action, value) => actOn(doc, testid, action, value),
      tools: STALKER_TOOLS,
      dispose: log.dispose
    };
  }
  function callTool(api, name, input) {
    switch (name) {
      case "screen":
        return api.screen();
      case "busy":
        return api.busy();
      case "find":
        return api.find(input);
      case "layout":
        return api.layout(String(input.a), String(input.b));
      case "errors":
        return api.errors(input);
      case "act":
        return api.act(String(input.testid), input.action, input.value);
    }
  }
  function installStalker(win = window) {
    if (win.stalker) return;
    const { dispose, ...api } = createStalker(win);
    void dispose;
    win.stalker = api;
    win.__agent = api;
    const modelContext = win.navigator.modelContext;
    for (const tool of modelContext?.registerTool ? STALKER_TOOLS : []) {
      modelContext?.registerTool?.({
        ...tool,
        execute: async (input) => ({
          content: [{ type: "text", text: JSON.stringify(callTool(api, tool.name, input)) }]
        })
      });
    }
  }

  // viewer-entry.ts
  installStalker();
  return __toCommonJS(viewer_entry_exports);
})();
