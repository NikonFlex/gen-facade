// Смотрелка прогонов. Два экрана: главная (дома, свой JSON, история прогонов) и прогон
// на весь экран (шаги конвейера, чертёж). Открытый прогон — в адресе (#run=…&step=…):
// перезагрузка и ссылка его сохраняют, «назад» в браузере возвращает на главную.

import { SvgStage, metres } from "/static/stage.js";

const ROOF = { flat: "плоская", gable: "двускатная", hip: "вальмовая", shed: "односкатная" };
const LAYERS = {
  zones: "Зоны отделки", elements: "Элементы", mullions: "Створки",
  roof: "Крыша", annotations: "Подписи",
};
const STEP_LAYERS = { 3: ["roof", "annotations"], 6: ["zones", "elements", "mullions", "roof", "annotations"] };
const THEMES = ["auto", "light", "dark"];
const ICON = {
  back: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3 5 8l5 5"/></svg>',
  play: '<svg viewBox="0 0 16 16"><path d="M4 2.5v11l9-5.5z" fill="currentColor"/></svg>',
  plus: '<svg viewBox="0 0 16 16"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  minus: '<svg viewBox="0 0 16 16"><path d="M3 8h10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  fit: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4"/></svg>',
  file: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M4 1.5h5l3 3v10H4z"/><path d="M9 1.5v3h3"/></svg>',
  redo: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M13 3v4H9"/><path d="M13 7a5 5 0 1 0-1.4 4"/></svg>',
  upload: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M10 13V3M6 7l4-4 4 4M3 13v3h14v-3"/></svg>',
  auto: '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M8 2.5a5.5 5.5 0 0 1 0 11z" fill="currentColor"/></svg>',
  light: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"><circle cx="8" cy="8" r="3"/><path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M3 13l1-1M12 4l1-1"/></svg>',
  dark: '<svg viewBox="0 0 16 16"><path d="M13.5 10A6 6 0 0 1 6 2.5a6 6 0 1 0 7.5 7.5z" fill="currentColor"/></svg>',
};

const $ = (id) => document.getElementById(id);
const state = { runs: [], meta: null, runId: null, step: null, stage: null, nav: 0 };

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
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(errorText(data.detail)), { detail: data.detail });
  return data;
}

function errorText(detail) {
  if (!Array.isArray(detail)) return detail ?? "ошибка сервера";
  // «Value error, …» — служебная приставка pydantic, человеку она ничего не говорит.
  return detail.map((d) => `${d.loc.filter((p) => p !== "body" && p !== "sheet").join(".")}: ${d.msg.replace(/^Value error, /, "")}`).join("\n");
}

const runName = (id) => id.replace(/^\d{8}-\d{6}-/, "").replace(/-\d+$/, "");
const fmtDate = (iso) => new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function ago(iso) {
  const sec = (new Date(iso) - Date.now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat("ru", { numeric: "auto" });
  for (const [unit, size] of [["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (Math.abs(sec) >= size) return rtf.format(Math.round(sec / size), unit);
  }
  return "только что";
}

// ——— тема ———

const systemDark = matchMedia("(prefers-color-scheme: dark)");

function applyTheme(theme) {
  const dark = theme === "dark" || (theme === "auto" && systemDark.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  $("theme-btn").innerHTML = ICON[theme];
  store.set("theme", theme);
}

// ——— дома и прогоны ———

async function loadHouses() {
  const houses = await api("/api/houses");
  $("houses-count").textContent = houses.length;
  $("houses").replaceChildren(...houses.map(houseCard));
}

function houseCard(h) {
  const size = h.size_m.length ? ` · ${h.size_m.map((v) => v.toLocaleString("ru-RU")).join(" × ")} м` : "";
  const floors = `${h.floors} ${h.floors === 1 ? "этаж" : "этажа"}`;
  const btn = el("button", { className: "house", title: `Запустить конвейер: ${h.name}` },
    `<span class="house-name">${h.name}</span>
     <span class="house-meta">${floors} · ${ROOF[h.roof] ?? h.roof}${size}</span>
     <span class="swatches">${h.palette.map((c) => `<span class="swatch" style="background:${c}"></span>`).join("")}</span>
     <span class="house-go">${ICON.play}</span>`);
  btn.addEventListener("click", () => startRun({ house: h.name }, btn));
  return listItem(btn);
}

async function loadRuns() {
  state.runs = await api("/api/runs");
  $("runs-count").textContent = state.runs.length || "";
  const items = state.runs.map(runCard);
  $("runs").replaceChildren(...(items.length ? items : [el("li", { className: "empty-note", textContent: "Пока пусто — запустите дом выше." })]));
}

function runCard(r) {
  const thumb = r.preview ? `<img class="run-thumb" src="/files/${r.id}/${r.preview}" alt="" loading="lazy">` : '<span class="run-thumb"></span>';
  const btn = el("button", { className: "run-card", title: r.id },
    `${thumb}<span class="run-info"><span class="run-name">${runName(r.id)}</span><span class="run-when">${ago(r.date)} · ${fmtDate(r.date)}</span></span>`);
  btn.addEventListener("click", () => goToRun(r.id));
  return listItem(btn);
}

async function startRun(body, busyEl, { quiet = false } = {}) {
  busyEl?.classList.add("busy");
  const t0 = performance.now();
  try {
    const { id } = await api("/api/runs", body);
    await goToRun(id, state.step === "input" ? "input" : null);
    toast(`Готово за ${Math.round(performance.now() - t0)} мс`);
  } catch (err) {
    if (!quiet) toast(err.message, "error");
    throw err;
  } finally {
    busyEl?.classList.remove("busy");
  }
}

// ——— переходы между экранами ———

async function goToRun(id, step = null) {
  // С главной — новая запись в истории: «назад» в браузере вернёт на главную.
  // Из прогона в прогон (перезапуск) — замена, чтобы история не копила промежуточные.
  const url = `#run=${encodeURIComponent(id)}`;
  if ($("run").hidden) history.pushState({ fromHome: true }, "", url);
  else history.replaceState(history.state, "", url);
  await openRun(id, step);
}

function goHome() {
  if (history.state?.fromHome) return history.back();
  history.replaceState(null, "", location.pathname);
  return showHome();
}

function showHome() {
  state.nav += 1; // загрузка прогона, начатая до ухода на главную, не откроет его поверх
  Object.assign(state, { meta: null, runId: null, step: null, stage: null });
  $("run").hidden = true;
  $("run-bar").hidden = true;
  $("home").hidden = false;
  $("brand-sub").hidden = false;
  $("run-actions").replaceChildren();
  $("tooltip").hidden = true;
  document.title = "GenFacade · смотрелка";
  return loadRuns();
}

async function route() {
  const hash = new URLSearchParams(location.hash.slice(1));
  if (!hash.get("run")) return showHome();
  return openRun(hash.get("run"), hash.get("step")).catch(() => {
    toast("Прогон из ссылки не найден", "error");
    return showHome();
  });
}

// ——— открытый прогон ———

async function openRun(id, step = null) {
  const nav = ++state.nav;
  const meta = await api(`/api/runs/${encodeURIComponent(id)}`);
  if (nav !== state.nav) return; // пока грузили, пользователь ушёл — не перехватываем экран
  state.meta = meta;
  state.runId = id;
  $("home").hidden = true;
  $("brand-sub").hidden = true;
  $("run").hidden = false;
  $("run-bar").hidden = false;
  renderHead();
  const done = state.meta.steps.filter((s) => s.file);
  showStep(step ?? state.step ?? String(done.at(-1)?.n ?? "input"));
}

function renderHead() {
  const m = state.meta, id = state.runId, file = (f) => `/files/${id}/${f}`;
  $("run-title").textContent = runName(id);
  document.title = `${runName(id)} · GenFacade`;
  $("run-chips").innerHTML = [
    `<span class="chip">${fmtDate(m.date)}</span>`,
    m.git_sha ? `<span class="chip">коммит <code>${m.git_sha.slice(0, 7)}</code></span>` : "",
    `<span class="chip" title="${m.source}">${m.source.split("/").at(-1)}</span>`,
  ].join("");
  const sheet = m.steps.find((s) => s.n === 6)?.file;
  const links = [[sheet, "SVG"], [m.sheet_json, "JSON"], [m.preview, "PNG"]].filter(([f]) => f)
    .map(([f, label]) => `<a class="btn" href="${file(f)}" target="_blank" rel="noopener" title="Открыть ${label}">${ICON.file}<span>${label}</span></a>`);
  $("run-actions").innerHTML = `${links.join("")}<button class="btn" id="rerun" title="Прогнать тот же вход ещё раз">${ICON.redo}<span>Прогнать заново</span></button>`;
  $("rerun").addEventListener("click", rerun);
}

async function rerun() {
  const sheet = await (await fetch(`/files/${state.runId}/${state.meta.input}`)).json();
  await startRun({ sheet, name: runName(state.runId) }, $("rerun")).catch(() => {});
}

function renderStepper() {
  const steps = [{ key: "input", n: "", title: "Вход", file: state.meta.input }]
    .concat(state.meta.steps.map((s) => ({ ...s, key: String(s.n) })));
  const nodes = steps.flatMap((s, i) => {
    const btn = el("button", {
      className: `step${s.key === state.step ? " active" : ""}`, disabled: !s.file,
      title: s.file ? "" : "Шаг ещё не написан — появится на следующих этапах",
    }, `<span class="step-n">${s.n || "⌂"}</span>${s.title}`);
    btn.dataset.key = s.key;
    btn.addEventListener("click", () => showStep(s.key));
    return i ? [el("span", { className: "step-link" }), btn] : [btn];
  });
  $("stepper").replaceChildren(...nodes);
}

function showStep(key) {
  state.step = key;
  history.replaceState(history.state, "", `#run=${encodeURIComponent(state.runId)}&step=${key}`);
  renderStepper();
  if (key === "input") return renderInput();
  const step = state.meta.steps.find((s) => String(s.n) === key);
  return step?.file ? renderSvgStep(step) : renderInput();
}

// ——— шаг с чертежом ———

async function renderSvgStep(step) {
  const zoomVal = el("span", { className: "zoom-val" });
  const wrap = el("div", { className: "canvas-wrap" });
  $("stage").replaceChildren(toolbar(step.n, zoomVal), wrap);
  state.stage = new SvgStage(wrap, { tooltip: $("tooltip"), onZoom: (p) => { zoomVal.textContent = `${p}%`; } });
  await state.stage.load(`/files/${state.runId}/${step.file}`);
  applyLayers(step.n);
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
  const text = await (await fetch(`/files/${state.runId}/${state.meta.input}`)).text();
  const view = el("div", { className: "input-view" }, `
    <div class="editor-pane">
      <div class="pane-head">
        <h2>Дом, JSON</h2><span class="pane-note">правка → новый прогон</span>
        <span class="pane-actions"><button class="btn" id="reset">Сбросить</button><button class="btn primary" id="go">${ICON.play}Прогнать</button></span>
      </div>
      <textarea class="editor" id="editor" spellcheck="false"></textarea>
      <ul class="errors" id="errors" hidden></ul>
    </div>
    <div class="summary" id="summary"></div>`);
  $("stage").replaceChildren(view);
  const editor = $("editor");
  editor.value = text;
  renderSummary(JSON.parse(text));
  editor.addEventListener("keydown", indentOnTab);
  $("reset").addEventListener("click", () => { editor.value = text; showErrors([]); });
  $("go").addEventListener("click", () => runEdited(editor.value));
}

function indentOnTab(e) {
  if (e.key !== "Tab") return;
  e.preventDefault();
  e.target.setRangeText("  ", e.target.selectionStart, e.target.selectionEnd, "end");
}

async function runEdited(text) {
  let sheet;
  try { sheet = JSON.parse(text); } catch (err) { return showErrors([`JSON: ${err.message}`]); }
  try {
    // Ошибки показываем под редактором, рядом с тем, что их вызвало, — без всплывашки.
    await startRun({ sheet, name: runName(state.runId) }, $("go"), { quiet: true });
  } catch (err) {
    showErrors(err.message.split("\n"));
  }
}

function showErrors(lines) {
  const box = $("errors");
  box.hidden = !lines.length;
  box.replaceChildren(...lines.map((line) => el("li", { textContent: line })));
}

function renderSummary(house) {
  const s = house.spec, sides = house.facades.map((f) => f.side.length_m);
  const facts = [
    ["Тип", s.building_type === "cottage" ? "коттедж" : "многоквартирный"],
    ["Стиль", s.style || "—"],
    ["Этажи", `${s.floors}: ${s.floor_heights_m.map(metres).join(", ")}`],
    ["Цоколь", metres(s.plinth_m)],
    ["Карниз", metres(s.eaves_m)],
    ["Крыша", `${ROOF[s.roof.kind]}${s.roof.kind === "flat" ? "" : `, ${s.roof.pitch_deg}°, свес ${metres(s.roof.overhang_m)}`}`],
    ["Стороны", sides.map((v) => v.toLocaleString("ru-RU")).join(" · ") + " м"],
    ["Элементов", house.facades.reduce((n, f) => n + (f.elements?.length ?? 0), 0)],
  ];
  const palette = s.materials.map((m) => `<div class="palette-row"><span class="swatch" style="background:${m.color ?? "transparent"}"></span>${m.id}<code>${m.kind}</code></div>`);
  $("summary").innerHTML = `<h2>Параметры дома</h2>
    <dl class="facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
    <h2>Палитра</h2><div class="palette">${palette.join("")}</div>`;
}

// ——— свой файл, клавиши, запуск ———

function bindDropzone() {
  const zone = $("dropzone"), input = $("file-input");
  $("dropzone").querySelector(".dropzone-icon").innerHTML = ICON.upload;
  const send = async (file) => {
    try {
      await startRun({ sheet: JSON.parse(await file.text()), name: file.name.replace(/\.json$/i, "") }, zone);
    } catch { /* ошибка уже показана */ }
  };
  input.addEventListener("change", () => input.files[0] && send(input.files[0]));
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("over");
    if (e.dataTransfer.files[0]) send(e.dataTransfer.files[0]);
  });
}

function onKey(e) {
  if (e.target.closest("textarea, input") || !state.meta) return;
  if (e.key === "Escape") return goHome();
  const keys = [...document.querySelectorAll(".step:not(:disabled)")].map((b) => b.dataset.key);
  const i = keys.indexOf(state.step);
  if (e.key === "ArrowRight" && i < keys.length - 1) showStep(keys[i + 1]);
  else if (e.key === "ArrowLeft" && i > 0) showStep(keys[i - 1]);
  else if (state.stage && (e.key === "f" || e.key === "а" || e.key === "0")) state.stage.fit();
  else if (state.stage && (e.key === "+" || e.key === "=")) state.stage.zoomBy(0.8);
  else if (state.stage && e.key === "-") state.stage.zoomBy(1.25);
}

async function init() {
  applyTheme(store.get("theme", "auto"));
  $("theme-btn").addEventListener("click", () => {
    const cur = store.get("theme", "auto");
    applyTheme(THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length]);
  });
  systemDark.addEventListener("change", () => applyTheme(store.get("theme", "auto")));
  bindDropzone();
  $("back-btn").innerHTML = `${ICON.back}<span>Все прогоны</span>`;
  $("back-btn").addEventListener("click", goHome);
  $("home-link").addEventListener("click", (e) => { e.preventDefault(); goHome(); });
  window.addEventListener("popstate", route);
  document.addEventListener("keydown", onKey);
  await loadHouses();
  await route();
}

init().catch((err) => toast(err.message, "error"));
