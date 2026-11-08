// Смотрелка прогонов. Вкладки страницы — Дома (прогоны карточками), Новый дом (план и описание),
// Данные (примеры датасета) — и экран дома (шаги конвейера, чертёж, 3D). Открытый прогон — в адресе
// (#run=…&step=…): перезагрузка и ссылка его сохраняют, «назад» в браузере возвращает к списку.

import { HouseStage } from "/static/house3d.js";
import { refusalText, refusedFrom } from "/static/refusal.js";
import { NAV, markCurrent, topbar } from "/static/shell.js";
import { SvgStage, metres } from "/static/stage.js";
import { showData } from "/static/datapage.js";
import { mountNewHouse } from "/static/newhouse.js";

const LAYERS = {
  zones: "Зоны отделки", elements: "Элементы", mullions: "Створки",
  annotations: "Подписи", forbidden: "Запретные зоны", violations: "Нарушения",
};
const SHEET_LAYERS = ["zones", "elements", "mullions", "annotations"];
// Шаги 3–5 — стены без крыши и оформления (хозяин 30.09): у них только слои элементов.
const WALL_LAYERS = ["zones", "elements", "mullions"];
const STEP_LAYERS = {
  4: [...WALL_LAYERS, "forbidden"], 5: [...WALL_LAYERS, "forbidden", "violations"], 6: SHEET_LAYERS,
};
// После листа — дом объёмом по нему же: не шаг конвейера, а другой взгляд на шаг 6.
const HOUSE_STEP = { key: "3d", n: "3D", title: "Дом в 3D" };
const ICON = {
  back: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3 5 8l5 5"/></svg>',
  play: '<svg viewBox="0 0 16 16"><path d="M4 2.5v11l9-5.5z" fill="currentColor"/></svg>',
  plus: '<svg viewBox="0 0 16 16"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  minus: '<svg viewBox="0 0 16 16"><path d="M3 8h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  fit: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"/></svg>',
  file: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M4 1.5h5l3 3v10H4z"/><path d="M9 1.5v3h3"/></svg>',
  redo: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M13 3v4H9"/><path d="M13 7a5 5 0 1 0-1.4 4"/></svg>',
};

const $ = (id) => document.getElementById(id);
const state = { runs: [], meta: null, runId: null, step: null, stage: null, nav: 0, shown: 0, options: null, filters: {}, query: "" };
// Ответ шага, с которого уже ушли, экран не трогает: показан последний выбранный шаг (C13, gf#293).
const stale = (shown) => shown !== state.shown;

// ——— мелочи ———

const store = {
  get(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* приватный режим */ }
  },
};

function el(tag, attrs = {}, html = "") {
  const node = Object.assign(document.createElement(tag), attrs);
  if (html) node.innerHTML = html;
  return node;
}

function listItem(child) {
  const li = el("li");
  li.append(child);
  return li;
}

function toast(text, kind = "") {
  const node = el("div", { className: `toast ${kind}`, textContent: text });
  $("toasts").append(node);
  setTimeout(() => node.remove(), kind === "error" ? 7000 : 3000);
}

async function api(path, body) {
  const init = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const res = await fetch(path, init);
  if (!res.ok) throw await refusedFrom(res);
  return res.json();
}

const runName = (id) => id.replace(/^\d{8}-\d{6}-/, "").replace(/-\d+$/, "");
// Число со словом по-русски: 1 этаж, 2 этажа, 5 этажей.
const RU_PLURAL = new Intl.PluralRules("ru");
const counted = (n, forms) => `${n} ${forms[RU_PLURAL.select(n)] ?? forms.many}`;
const FLOORS = { one: "этаж", few: "этажа", many: "этажей" };
const SIDES = { one: "сторона", few: "стороны", many: "сторон" };
const RUNS = { one: "прогон", few: "прогона", many: "прогонов" };
const fmtDate = (iso) => new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function ago(iso) {
  const sec = (new Date(iso) - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat("ru", { numeric: "auto" });
  for (const [unit, size] of [["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (Math.abs(sec) >= size) return rtf.format(Math.round(sec / size), unit);
  }
  return "только что";
}

// ——— дома и прогоны ———

async function loadRuns() {
  state.runs = await api("/api/runs");
  $("runs-count").textContent = counted(state.runs.length, RUNS);
  renderFilters();
  renderRuns();
}

// Фильтры — по полям карточки, которые посчитал сервер (viewer/houses.py); значения — те, что
// есть в списке, подписи — из /api/options. Фильтр только сужает показ, ничего не решает.
const FILTERS = [
  { key: "outcome", title: "Итог", value: (r) => r.outcome, label: (v) => state.options.outcome[v].title },
  { key: "mode", title: "Режим", value: (r) => r.mode, label: (v) => modeTitle(v) },
  { key: "sides", title: "Форма", value: (r) => r.house?.sides, label: (v) => counted(v, SIDES) },
  { key: "roof", title: "Крыша", value: (r) => r.house?.roof, label: (v) => state.options.roof[v] },
  { key: "model", title: "Модель", value: (r) => r.model, label: (v) => v },
];
const modeTitle = (v) => state.options.modes.find((m) => m.value === v).title;

function renderFilters() {
  const groups = FILTERS.map((f) => {
    const counts = new Map();
    for (const r of state.runs) {
      const v = f.value(r);
      if (v != null) counts.set(v, (counts.get(v) ?? 0) + 1);
    }
    if (counts.size < 2) return null; // одно значение на все дома — фильтровать нечем
    const group = el("div", { className: "filter-group", role: "group", ariaLabel: f.title },
      `<span class="filter-label">${f.title}</span>`);
    group.append(filterButton(f.key, null, "все"),
      ...[...counts].sort().map(([v, n]) => filterButton(f.key, v, `${f.label(v)}<span class="n">${n}</span>`)));
    return group;
  }).filter(Boolean);
  $("runs-filters").replaceChildren(...groups);
}

function filterButton(key, value, html) {
  const btn = el("button", { type: "button", className: "filter" }, html);
  btn.setAttribute("aria-pressed", String((state.filters[key] ?? null) === value));
  btn.addEventListener("click", () => {
    state.filters[key] = value;
    for (const b of btn.parentElement.querySelectorAll(".filter")) b.setAttribute("aria-pressed", String(b === btn));
    renderRuns();
  });
  return btn;
}

function shownRuns() {
  const q = state.query.toLowerCase();
  return state.runs.filter((r) => FILTERS.every((f) => state.filters[f.key] == null || f.value(r) === state.filters[f.key])
    && (!q || [r.id, r.text, r.source, r.model, r.house?.walls].some((t) => t?.toLowerCase().includes(q))));
}

function renderRuns() {
  const shown = shownRuns();
  const note = state.runs.length ? "Под фильтр ничего не подошло." : "Пока пусто — постройте дом на вкладке «Новый дом».";
  $("runs").replaceChildren(...(shown.length ? shown.map(runCard) : [el("li", { className: "empty-note", textContent: note })]));
}

// Карточка дома: лист на «бумаге», название, модель, параметры дома и итог проверки.
function runCard(r) {
  const h = r.house, tone = state.options.outcome[r.outcome];
  const thumb = r.thumb ? `<img src="${r.thumb}" alt="" loading="lazy">`
    : '<svg class="house-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-5h4v5"/></svg>';
  const facts = h ? [`<span class="swatch" style="background:${h.color}"></span>${h.walls}`, state.options.roof[h.roof],
    counted(h.floors, FLOORS), h.sides ? counted(h.sides, SIDES) : null].filter(Boolean) : [];
  const warn = r.warnings ? `<span class="status warn">· ${r.warnings} предупр.</span>` : "";
  const link = el("a", { className: "card", href: `#run=${encodeURIComponent(r.id)}`, title: r.text ?? r.source }, `
    <div class="card-thumb">${thumb}</div>
    <div class="card-body">
      <div class="card-title"><h3>${runName(r.id)}</h3>${r.model ? `<span class="chip accent">${r.model}</span>` : ""}</div>
      <div class="card-meta">${facts.join('<span class="sep">·</span>')}</div>
      <div class="card-foot"><span class="status ${tone.tone}"><span class="dot"></span>${tone.title}</span>${warn}${r.mode ? `<span>· ${modeTitle(r.mode)}</span>` : ""}<span class="when">${ago(r.date)}</span></div>
    </div>`);
  link.addEventListener("click", (e) => { e.preventDefault(); goToRun(r.id); });
  return listItem(link);
}

// ——— примеры датасета ———

async function openSample(url, busyEl) {
  busyEl.classList.add("busy");
  try {
    const run = await api(url, {});
    await goToRun(run.id);
  } finally {
    busyEl.classList.remove("busy");
  }
}

async function startRun(body, busyEl, { quiet = false } = {}) {
  // Кнопка выключена до ответа: второй щелчок запустил бы второй прогон.
  busyEl?.classList.add("busy");
  if (busyEl) busyEl.disabled = true;
  const t0 = performance.now(), nav = state.nav;
  try {
    const { id } = await api("/api/runs", body);
    const ms = Math.round(performance.now() - t0);
    if (nav !== state.nav) { // пока считали, пользователь ушёл — не выдёргиваем его обратно
      toast(`Прогон ${runName(id)} готов за ${ms} мс — он в списке`);
      if (!$("houses").hidden) await loadRuns();
      return;
    }
    await goToRun(id, state.step === "input" ? "input" : null);
    toast(`Готово за ${ms} мс`);
  } catch (err) {
    if (!quiet) toast(err.message, "error");
    throw err;
  } finally {
    busyEl?.classList.remove("busy");
    if (busyEl) busyEl.disabled = false;
  }
}

// ——— переходы между экранами ———

async function goToRun(id, step = null) {
  // Со списка — новая запись в истории: «назад» в браузере вернёт к нему.
  // Из прогона в прогон (перезапуск) — замена, чтобы история не копила промежуточные.
  const url = `#run=${encodeURIComponent(id)}`;
  if ($("run").hidden) history.pushState({ fromHome: true }, "", url);
  else history.replaceState(history.state, "", url);
  await openRun(id, step);
}

// Вкладки страницы: раздел шапки (shell.js), секция в index.html, чем заполнить, адрес.
const TABS = {
  houses: { section: "houses", load: loadRuns, hash: "" },
  new: { section: "new", load: async () => {}, hash: "new" },
  data: { section: "datasets", load: () => showData({ api, options: state.options, openSample: (url, btn) => openSample(url, btn).catch((err) => toast(err.message, "error")) }), hash: "datasets" },
};
const tabUrl = (tab) => (TABS[tab].hash ? `#${TABS[tab].hash}` : location.pathname);
// Пример датасета открыт со вкладки «Данные» — туда же и возвращаемся.
const tabOfRun = () => (state.meta?.sample ? "data" : "houses");

function goHome() {
  if (history.state?.fromHome) return history.back();
  const tab = tabOfRun();
  history.replaceState(null, "", tabUrl(tab));
  return showTab(tab);
}

function goToTab(tab) {
  history.pushState(null, "", tabUrl(tab));
  return showTab(tab);
}

function showTab(tab) {
  state.nav += 1; // загрузка прогона, начатая до ухода на вкладку, не откроет его поверх
  Object.assign(state, { meta: null, runId: null, step: null, stage: null });
  $("run").hidden = true;
  for (const [name, t] of Object.entries(TABS)) $(t.section).hidden = name !== tab;
  markCurrent($("topbar"), tab);
  $("run-actions").replaceChildren();
  $("tooltip").hidden = true;
  document.title = "GenFacade · смотрелка";
  return TABS[tab].load();
}

async function route() {
  const hash = new URLSearchParams(location.hash.slice(1));
  const tab = Object.keys(TABS).find((name) => TABS[name].hash && hash.has(TABS[name].hash)) ?? "houses";
  if (!hash.get("run")) return showTab(tab);
  return openRun(hash.get("run"), hash.get("step")).catch((err) => {
    toast(`Прогон из ссылки не открыт — ${err.message}`, "error");
    return showTab("houses");
  });
}

// ——— открытый прогон ———

async function openRun(id, step = null) {
  const nav = ++state.nav;
  const meta = await api(`/api/runs/${encodeURIComponent(id)}`);
  if (nav !== state.nav) return; // пока грузили, пользователь ушёл — не перехватываем экран
  state.meta = meta;
  state.runId = id;
  for (const t of Object.values(TABS)) $(t.section).hidden = true;
  $("run").hidden = false;
  markCurrent($("topbar"), tabOfRun());
  renderHead();
  const done = state.meta.steps.filter((s) => s.file);
  showStep(step ?? state.step ?? String(done.at(-1)?.n ?? "input"));
}

function renderHead() {
  const m = state.meta, id = state.runId, file = (f) => `/files/${id}/${f}`;
  $("back-btn").innerHTML = `${ICON.back}<span>${NAV.find((n) => n.page === tabOfRun()).title}</span>`;
  // У примера датасета имя — его id: в нём номер, который runName принял бы за суффикс прогона.
  const title = m.sample ? m.sample.id : runName(id);
  $("run-title").textContent = title;
  document.title = `${title} · GenFacade`;
  $("run-chips").innerHTML = [
    m.request ? `<span class="chip accent">${modeTitle(m.request.mode)}</span>` : "",
    `<span class="chip">${fmtDate(m.date)}</span>`,
    m.git_sha ? `<span class="chip">коммит <code>${m.git_sha.slice(0, 7)}</code></span>` : "",
    m.sample ? `<span class="chip">${m.sample.source} · ${m.sample.split}</span>`
      : `<span class="chip" title="${m.source}">${m.source.split("/").at(-1)}</span>`,
  ].join("");
  // Причина отказа — текстом, не разметкой: в ней бывают имена тегов SVG.
  if (m.refusal) {
    const text = refusalText(m.refusal);
    $("run-chips").append(el("span", { className: "chip refusal", title: text, textContent: text }));
  }
  const sheet = m.steps.find((s) => s.n === 6)?.file;
  const links = [[sheet, "SVG"], [m.sheet_json, "JSON"], [m.preview, "PNG"]].filter(([f]) => f)
    .map(([f, label]) => `<a class="btn" href="${file(f)}" target="_blank" rel="noopener" title="Открыть ${label}">${ICON.file}<span>${label}</span></a>`);
  // У примера датасета входа нет: перезапускать нечего.
  const redo = m.input ? `<button class="btn" id="rerun" title="Прогнать тот же вход ещё раз">${ICON.redo}<span>Прогнать заново</span></button>` : "";
  $("run-actions").innerHTML = links.join("") + redo;
  $("rerun")?.addEventListener("click", rerun);
}

async function rerun() {
  const input = await (await fetch(`/files/${state.runId}/${state.meta.input}`)).json();
  await startRun(await runBody(input), $("rerun")).catch(() => {});
}

// Тело запуска из входа прогона: у прогона по плану — запрос и тот же SVG-план.
async function runBody(input) {
  const svg = await (await fetch(`/files/${state.runId}/${state.meta.plan_input}`)).text();
  return { plan_run: input, svg };
}

function renderStepper() {
  const input = state.meta.input ? [{ key: "input", n: "", title: "Вход", file: state.meta.input }] : [];
  const house = state.meta.sheet_json ? [{ ...HOUSE_STEP, file: state.meta.sheet_json }] : [];
  const steps = input.concat(state.meta.steps.map((s) => ({ ...s, key: String(s.n) })), house);
  const nodes = steps.flatMap((s, i) => {
    const btn = el("button", {
      className: `step${s.key === state.step ? " active" : ""}`, disabled: !s.file,
      title: s.file ? "" : state.meta.refusal ? `Прогон остановлен раньше — ${refusalText(state.meta.refusal)}`
        : "Шаг ещё не написан — появится на следующих этапах",
    }, `<span class="step-n">${s.n || "⌂"}</span>${s.title}`);
    btn.dataset.key = s.key;
    btn.addEventListener("click", () => showStep(s.key));
    return i ? [el("span", { className: "step-link" }), btn] : [btn];
  });
  $("stepper").replaceChildren(...nodes);
}

function showStep(wanted) {
  state.shown += 1;
  if (wanted === HOUSE_STEP.key && state.meta.sheet_json) return showHouse();
  const done = state.meta.steps.filter((s) => s.file);
  // Нет такого шага — «Вход»; у примера датасета входа нет — его последний шаг.
  const step = done.find((s) => String(s.n) === wanted) ?? (state.meta.input ? null : done.at(-1));
  const key = step ? String(step.n) : "input";
  state.step = key;
  history.replaceState(history.state, "", `#run=${encodeURIComponent(state.runId)}&step=${key}`);
  renderStepper();
  if (!step) return renderInput();
  if (step.file === state.meta.tokens) return withData(step, renderTokensStep);
  return step.file.endsWith(".json") ? withData(step, renderJsonStep) : renderSvgStep(step);
}

function showHouse() {
  state.step = HOUSE_STEP.key;
  history.replaceState(history.state, "", `#run=${encodeURIComponent(state.runId)}&step=${HOUSE_STEP.key}`);
  renderStepper();
  return renderHouse();
}

async function renderHouse() {
  const wrap = el("div", { className: "canvas-wrap house-wrap" });
  const fit = el("button", { className: "icon-btn", title: "Вписать (F)", ariaLabel: "Вписать" }, ICON.fit);
  const bar = el("div", { className: "toolbar" });
  bar.append(el("div", { className: "tool-group" }), el("span", { className: "hint" },
    "тянуть — повернуть · колесо — ближе/дальше · двойной щелчок или <kbd>F</kbd> — вписать"));
  bar.firstChild.append(fit);
  $("stage").replaceChildren(bar, wrap);
  state.stage = new HouseStage(wrap, state.options.house3d);
  fit.addEventListener("click", () => state.stage.fit());
  try {
    await state.stage.load(`/api/runs/${encodeURIComponent(state.runId)}/house3d`);
  } catch (err) {
    wrap.replaceChildren(el("p", { className: "empty-note", textContent: err.message }));
    state.stage = null;
  }
}

// JSON шага без чертежа: холста у такого шага нет.
// Данные шага — в отрисовку; пока грузили, ушли на другой шаг — не рисуем.
async function withData(step, render) {
  state.stage = null;
  const shown = state.shown, data = await (await fetch(`/files/${state.runId}/${step.file}`)).json();
  if (!stale(shown)) render(step, data);
}

// ——— шаг-JSON: параметры дома ———

function renderJsonStep(step, data) {
  const view = el("div", { className: "input-view" }, `
    <div class="editor-pane">
      <div class="pane-head"><h2>${step.file}</h2><span class="pane-note">шаг ${step.n}: ${step.title}</span></div>
      <pre class="json-view"></pre>
    </div>
    <div class="summary" id="summary"></div>`);
  view.querySelector(".json-view").textContent = JSON.stringify(data, null, 2);
  $("stage").replaceChildren(view);
  renderSummary(data.spec, data.colors);
}

// ——— шаг «Токены»: что модель шага 4 получает и что пишет, по режимам ———

function renderTokensStep(step, data) {
  const view = el("div", { className: "tokens-view" });
  for (const mode of state.options.modes.filter((m) => data[m.value])) {
    const column = el("div", { className: "editor-pane" });
    column.append(el("div", { className: "pane-head" }, `<h2>${mode.title}</h2><span class="pane-note">${mode.hint}</span>`));
    for (const part of data[mode.value]) {
      column.append(el("div", { className: "pane-head" }, `<h2>${part.title}</h2><span class="pane-note">токенов: ${part.count}</span>`));
      column.append(el("pre", { className: "json-view", textContent: part.lines.join("\n") }));
    }
    view.append(column);
  }
  $("stage").replaceChildren(view);
}

// ——— шаг с чертежом ———

async function renderSvgStep(step) {
  const zoomVal = el("span", { className: "zoom-val" });
  const wrap = el("div", { className: "canvas-wrap" });
  $("stage").replaceChildren(toolbar(step.n, zoomVal), wrap);
  const shown = state.shown;
  state.stage = new SvgStage(wrap, { tooltip: $("tooltip"), labels: state.options, onZoom: (p) => { zoomVal.textContent = `${p}%`; } });
  await state.stage.load(`/files/${state.runId}/${step.file}`);
  if (stale(shown)) return;
  applyLayers(step.n);
  if (step.n === 5 && state.meta.violations) await violationsChip($("stage").querySelector(".toolbar"));
}

async function violationsChip(bar) {
  const list = await (await fetch(`/files/${state.runId}/${state.meta.violations}`)).json();
  const bad = state.meta.errors;
  const chip = el("span", {
    className: `chip violations-chip${bad ? " bad" : ""}`,
    title: list.map((v) => `сторона ${v.side ?? "—"}: ${v.message}`).join("\n") || "валидатор ничего не нашёл",
    textContent: list.length ? `нарушений: ${list.length}, ошибок: ${bad}` : "нарушений нет",
  });
  bar.insertBefore(chip, bar.querySelector(".hint"));
}

function toolbar(n, zoomVal) {
  const zoom = el("div", { className: "tool-group" });
  for (const [icon, title, act] of [["minus", "Мельче (−)", () => state.stage.zoomBy(1.25)],
    ["plus", "Крупнее (+)", () => state.stage.zoomBy(0.8)], ["fit", "Вписать (F)", () => state.stage.fit()]]) {
    const b = el("button", { className: "icon-btn", title, ariaLabel: title }, ICON[icon]);
    b.addEventListener("click", act);
    zoom.append(b);
  }
  zoom.insertBefore(zoomVal, zoom.children[1]);
  const layers = el("div", { className: "tool-group" });
  for (const name of STEP_LAYERS[n] ?? []) {
    const label = el("label", { className: "layer" }, `<input type="checkbox">${LAYERS[name]}`);
    const box = label.querySelector("input");
    box.checked = store.get(`layer.${name}`, true);
    box.addEventListener("change", () => { store.set(`layer.${name}`, box.checked); applyLayers(n); });
    layers.append(label);
  }
  const bar = el("div", { className: "toolbar" });
  bar.append(zoom);
  if (layers.children.length) bar.append(layers);
  bar.append(el("span", { className: "hint" },
    "колесо — масштаб · тянуть — сдвиг · <kbd>F</kbd> вписать · <kbd>←</kbd><kbd>→</kbd> шаги"));
  return bar;
}

function applyLayers(n) {
  for (const name of STEP_LAYERS[n] ?? []) state.stage.setLayer(name, store.get(`layer.${name}`, true));
}

// ——— шаг «Вход» ———

async function renderInput() {
  state.stage = null;
  const shown = state.shown;
  const text = await (await fetch(`/files/${state.runId}/${state.meta.input}`)).text();
  if (stale(shown)) return;
  const view = el("div", { className: "input-view" }, `
    <div class="editor-pane">
      <div class="pane-head">
        <h2>Запрос, JSON</h2><span class="pane-note">правка → новый прогон</span>
        <span class="pane-actions"><button class="btn" id="reset">Сбросить</button><button class="btn primary" id="go">${ICON.play}Прогнать</button></span>
      </div>
      <textarea class="editor" id="editor" spellcheck="false"></textarea>
      <ul class="errors" id="errors" hidden></ul>
    </div>
    <div class="summary" id="summary"></div>`);
  $("stage").replaceChildren(view);
  const editor = $("editor");
  editor.value = text;
  renderPlanSummary();
  editor.addEventListener("keydown", indentOnTab);
  $("reset").addEventListener("click", () => { editor.value = text; showErrors([]); });
  $("go").addEventListener("click", () => runEdited(editor.value));
}

function indentOnTab(e) {
  if (e.key !== "Tab") return;
  e.preventDefault();
  e.target.setRangeText("  ", e.target.selectionStart, e.target.selectionEnd, "end");
}

function renderPlanSummary() {
  const m = state.meta;
  $("summary").innerHTML = `<h2>План</h2>
    <img class="plan-picture" src="/files/${state.runId}/${m.plan_input}" alt="План">
    <h2>Проверка</h2><dl class="facts"><dt>Ошибок</dt><dd>${m.errors ?? "—"}</dd><dt>Предупреждений</dt><dd>${m.warnings ?? "—"}</dd></dl>`;
}

async function runEdited(text) {
  let input;
  try { input = JSON.parse(text); } catch (err) { return showErrors([`JSON: ${err.message}`]); }
  // Пока прогон считается, редактор только для чтения: после ответа он перерисуется из
  // request.json нового прогона, и набранное за это время пропало бы (C13, gf#293).
  const editor = $("editor"), reset = $("reset");
  editor.readOnly = reset.disabled = true;
  try {
    // Ошибки показываем под редактором, рядом с тем, что их вызвало, — без всплывашки.
    await startRun(await runBody(input), $("go"), { quiet: true });
  } catch (err) {
    showErrors(err.message.split("\n"));
  } finally {
    editor.readOnly = reset.disabled = false;
  }
}

function showErrors(lines) {
  const box = $("errors");
  box.hidden = !lines.length;
  box.replaceChildren(...lines.map((line) => el("li", { textContent: line })));
}

// Сводка шага 1: параметры дома и палитра; colors — цвета видов из библиотеки.
function renderSummary(s, colors) {
  const facts = [
    ["Тип", s.building_type === "cottage" ? "коттедж" : "многоквартирный"],
    ["Стиль", s.style || "—"],
    ["Этажи", `${s.floors}: ${s.floor_heights_m.map(metres).join(", ")}`],
    ["Цоколь", metres(s.plinth_m)],
    ["Карниз", metres(s.eaves_m)],
    ["Крыша", state.options.roof[s.roof.kind]],
  ];
  const color = (m) => m.color ?? colors?.[m.id] ?? "transparent";
  const palette = s.materials.map((m) => `<div class="palette-row"><span class="swatch" style="background:${color(m)}"></span>${m.id}<code>${m.kind}</code></div>`);
  $("summary").innerHTML = `<h2>Параметры дома</h2>
    <dl class="facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
    <h2>Палитра</h2><div class="palette">${palette.join("")}</div>`;
}

// ——— свой файл, клавиши, запуск ———

function onKey(e) {
  if (e.target.closest("textarea, input") || !state.meta) return;
  if (e.key === "Escape") return goHome();
  const keys = [...document.querySelectorAll(".step:not(:disabled)")].map((b) => b.dataset.key);
  const i = keys.indexOf(state.step);
  if (e.key === "ArrowRight" && i < keys.length - 1) showStep(keys[i + 1]);
  else if (e.key === "ArrowLeft" && i > 0) showStep(keys[i - 1]);
  else if (state.stage && (e.key === "f" || e.key === "а" || e.key === "0")) state.stage.fit();
  else if (state.stage?.zoomBy && (e.key === "+" || e.key === "=")) state.stage.zoomBy(0.8);
  else if (state.stage?.zoomBy && e.key === "-") state.stage.zoomBy(1.25);
}

async function init() {
  topbar($("topbar"), "houses");
  $("back-btn").addEventListener("click", goHome);
  // Разделы этой страницы — без перезагрузки; остальные ссылки шапки ведут на свои страницы.
  for (const link of $("topbar").querySelectorAll("[data-page]")) {
    if (TABS[link.dataset.page]) link.addEventListener("click", (e) => { e.preventDefault(); goToTab(link.dataset.page); });
  }
  $("runs-search").addEventListener("input", (e) => { state.query = e.target.value.trim(); renderRuns(); });
  window.addEventListener("popstate", route);
  document.addEventListener("keydown", onKey);
  state.options = await api("/api/options");
  // Форма неактивна (inert в index.html), пока её не заполнили ответы: иначе набранное до ответа
  // перезаписали бы список планов и сохранённый текст (C13, gf#293).
  await mountNewHouse({ api, options: state.options, startRun, goHome: () => goToTab("houses") });
  await route();
}

init().catch((err) => toast(err.message, "error"));
