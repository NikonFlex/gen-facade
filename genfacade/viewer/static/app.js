// Смотрелка прогонов. Два экрана: главная (дома, свой JSON, история прогонов) и прогон
// на весь экран (шаги конвейера, чертёж). Открытый прогон — в адресе (#run=…&step=…):
// перезагрузка и ссылка его сохраняют, «назад» в браузере возвращает на главную.

import { SvgStage, metres } from "/static/stage.js";

const ROOF = { flat: "плоская" };  // пока только плоская (хозяин 01.10)
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
const state = { runs: [], meta: null, runId: null, step: null, stage: null, nav: 0, options: null };

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

// ——— план и описание ———

const planState = { svg: null, name: null };

async function loadPlans() {
  const plans = await api("/api/plans");
  $("plan-select").replaceChildren(...plans.map((p) => el("option", { value: p.name, textContent: p.name })));
  const last = store.get("plan.name", null);
  if (plans.some((p) => p.name === last)) $("plan-select").value = last;
  showPlanThumb(`/api/plans/${encodeURIComponent($("plan-select").value)}`);
}

function showPlanThumb(src) {
  $("plan-thumb").replaceChildren(el("img", { src, alt: "План" }));
}

function bindPlanForm() {
  const form = $("plan-form");
  $("plan-go").innerHTML = `${ICON.play}<span>Построить фасады</span>`;
  $("plan-text").value = store.get("plan.text", "A simple one-storey house with a flat roof.");
  const { modes, default_mode: fallback } = state.options;
  $("mode-group").replaceChildren(...modes.map((m) => el("label", { title: m.hint },
    `<input type="radio" name="mode" value="${m.value}"><span>${m.title}</span>`)));
  const saved = store.get("plan.mode", fallback);
  const mode = modes.some((m) => m.value === saved) ? saved : fallback;
  form.querySelector(`input[name=mode][value=${mode}]`).checked = true;
  $("plan-select").addEventListener("change", () => {
    Object.assign(planState, { svg: null, name: null });
    showPlanThumb(`/api/plans/${encodeURIComponent($("plan-select").value)}`);
  });
  $("plan-file").addEventListener("change", async () => {
    const file = $("plan-file").files[0];
    if (!file) return;
    Object.assign(planState, { svg: await file.text(), name: file.name.replace(/\.svg$/i, "") });
    showPlanThumb(URL.createObjectURL(file));
    $("plan-select").replaceChildren(el("option", { textContent: `свой: ${file.name}` }), ...$("plan-select").children);
    $("plan-select").selectedIndex = 0;
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); submitPlan().catch(() => {}); });
}

async function submitPlan() {
  const form = $("plan-form");
  const run = {
    plan: planState.name ?? $("plan-select").value,
    text: $("plan-text").value.trim(),
    mode: form.querySelector("input[name=mode]:checked").value,
  };
  store.set("plan.text", run.text);
  store.set("plan.mode", run.mode);
  if (!planState.svg) store.set("plan.name", run.plan);
  await startRun({ plan_run: run, svg: planState.svg }, $("plan-go"));
}

// ——— дома и прогоны ———

async function loadRuns() {
  state.runs = await api("/api/runs");
  $("runs-count").textContent = state.runs.length || "";
  const items = state.runs.map(runCard);
  $("runs").replaceChildren(...(items.length ? items : [el("li", { className: "empty-note", textContent: "Пока пусто — постройте фасады по плану выше." })]));
}

function runCard(r) {
  const thumb = r.preview ? `<img class="run-thumb" src="/files/${r.id}/${r.preview}" alt="" loading="lazy">` : '<span class="run-thumb"></span>';
  const btn = el("button", { className: "run-card", title: r.id },
    `${thumb}<span class="run-info"><span class="run-name">${runName(r.id)}</span><span class="run-when">${ago(r.date)} · ${fmtDate(r.date)}</span></span>`);
  btn.addEventListener("click", () => goToRun(r.id));
  return listItem(btn);
}

// ——— датасеты ———

async function loadSamples() {
  const sources = await api("/api/samples");
  const blocks = sources.flatMap(sourceBlock);
  $("samples").replaceChildren(...(blocks.length ? blocks : [el("p", { className: "empty-note", textContent: "Примеров пока нет — появятся после сборки датасета." })]));
}

// Источник: заголовок, опись числами и дома карточками; всё — из ответа сервера.
function sourceBlock(s) {
  const counts = (obj, label) => Object.entries(obj).map(([k, n]) => `<span class="chip">${label(k)} <b>${n}</b></span>`).join("");
  const head = el("div", { className: "section-head" },
    `<h2>${s.source}</h2>
     <span class="section-note">опись на ${fmtDate(s.date)}${s.samples > s.ids.length ? ` · показаны первые ${s.ids.length}` : ""}</span>`);
  const stats = el("div", { className: "dataset-stats" },
    `<span class="chip">домов <b>${s.samples}</b></span><span class="chip">стен <b>${s.walls}</b></span><span class="chip">из них глухих <b>${s.blind_walls}</b></span>
     ${s.generator ? `<span class="chip" title="дома с ошибкой валидатора в датасет не пишутся">отброшено <b>${Object.keys(s.generator.rejected).length}</b></span>` : ""}
     ${counts(s.splits, (k) => k)}${counts(s.elements, (k) => state.options.cls[k].toLowerCase())}`);
  const grid = el("ul", { className: "run-grid" });
  grid.append(...s.ids.map((id) => sampleCard(s.source, id)));
  return [head, stats, grid];
}

function sampleCard(source, id) {
  const url = `/api/samples/${source}/${encodeURIComponent(id)}`;
  const btn = el("button", { className: "run-card", title: `${source}/${id}` },
    `<img class="run-thumb" src="${url}/sheet.svg" alt="" loading="lazy"><span class="run-info"><span class="run-name">${id}</span></span>`);
  btn.addEventListener("click", () => openSample(url, btn).catch((err) => toast(err.message, "error")));
  return listItem(btn);
}

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
  busyEl?.classList.add("busy");
  const t0 = performance.now(), nav = state.nav;
  try {
    const { id } = await api("/api/runs", body);
    const ms = Math.round(performance.now() - t0);
    if (nav !== state.nav) { // пока считали, пользователь ушёл — не выдёргиваем его обратно
      toast(`Прогон ${runName(id)} готов за ${ms} мс — он в списке`);
      if (!$("home").hidden) await loadRuns();
      return;
    }
    await goToRun(id, state.step === "input" ? "input" : null);
    toast(`Готово за ${ms} мс`);
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

// Вкладки главной: что показать, чем заполнить и какой у вкладки адрес.
const TABS = {
  home: { load: loadRuns, url: () => location.pathname },
  datasets: { load: loadSamples, url: () => "#datasets" },
};
// Пример датасета открыт со вкладки «Датасеты» — туда же и возвращаемся.
const tabOfRun = () => (state.meta?.sample ? "datasets" : "home");

function goHome() {
  if (history.state?.fromHome) return history.back();
  const tab = tabOfRun();
  history.replaceState(null, "", TABS[tab].url());
  return showTab(tab);
}

function goToTab(tab) {
  history.pushState(null, "", TABS[tab].url());
  return showTab(tab);
}

function showTab(tab) {
  state.nav += 1; // загрузка прогона, начатая до ухода на вкладку, не откроет его поверх
  Object.assign(state, { meta: null, runId: null, step: null, stage: null });
  $("run").hidden = true;
  $("run-bar").hidden = true;
  $("tabs").hidden = false;
  for (const name of Object.keys(TABS)) $(name).hidden = name !== tab;
  for (const link of $("tabs").children) link.classList.toggle("active", link.dataset.tab === tab);
  $("run-actions").replaceChildren();
  $("tooltip").hidden = true;
  document.title = "GenFacade · смотрелка";
  return TABS[tab].load();
}

async function route() {
  const hash = new URLSearchParams(location.hash.slice(1));
  const tab = Object.keys(TABS).find((name) => hash.has(name)) ?? "home";
  if (!hash.get("run")) return showTab(tab);
  return openRun(hash.get("run"), hash.get("step")).catch(() => {
    toast("Прогон из ссылки не найден", "error");
    return showTab("home");
  });
}

// ——— открытый прогон ———

async function openRun(id, step = null) {
  const nav = ++state.nav;
  const meta = await api(`/api/runs/${encodeURIComponent(id)}`);
  if (nav !== state.nav) return; // пока грузили, пользователь ушёл — не перехватываем экран
  state.meta = meta;
  state.runId = id;
  for (const name of Object.keys(TABS)) $(name).hidden = true;
  $("tabs").hidden = true;
  $("run").hidden = false;
  $("run-bar").hidden = false;
  renderHead();
  const done = state.meta.steps.filter((s) => s.file);
  showStep(step ?? state.step ?? String(done.at(-1)?.n ?? "input"));
}

function renderHead() {
  const m = state.meta, id = state.runId, file = (f) => `/files/${id}/${f}`;
  $("back-btn").innerHTML = `${ICON.back}<span>${$("tabs").querySelector(`[data-tab=${tabOfRun()}]`).textContent}</span>`;
  // У примера датасета имя — его id: в нём номер, который runName принял бы за суффикс прогона.
  const title = m.sample ? m.sample.id : runName(id);
  $("run-title").textContent = title;
  document.title = `${title} · GenFacade`;
  $("run-chips").innerHTML = [
    `<span class="chip">${fmtDate(m.date)}</span>`,
    m.git_sha ? `<span class="chip">коммит <code>${m.git_sha.slice(0, 7)}</code></span>` : "",
    m.sample ? `<span class="chip">${m.sample.source} · ${m.sample.split}</span>`
      : `<span class="chip" title="${m.source}">${m.source.split("/").at(-1)}</span>`,
  ].join("");
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
  const steps = input.concat(state.meta.steps.map((s) => ({ ...s, key: String(s.n) })));
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

function showStep(wanted) {
  const done = state.meta.steps.filter((s) => s.file);
  // Нет такого шага — «Вход»; у примера датасета входа нет — его последний шаг.
  const step = done.find((s) => String(s.n) === wanted) ?? (state.meta.input ? null : done.at(-1));
  const key = step ? String(step.n) : "input";
  state.step = key;
  history.replaceState(history.state, "", `#run=${encodeURIComponent(state.runId)}&step=${key}`);
  renderStepper();
  if (!step) return renderInput();
  if (step.file === state.meta.tokens) return renderTokensStep(step);
  return step.file.endsWith(".json") ? renderJsonStep(step) : renderSvgStep(step);
}

// ——— шаг-JSON: параметры дома ———

async function renderJsonStep(step) {
  state.stage = null;
  const data = await (await fetch(`/files/${state.runId}/${step.file}`)).json();
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

async function renderTokensStep(step) {
  state.stage = null;
  const data = await (await fetch(`/files/${state.runId}/${step.file}`)).json();
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
  state.stage = new SvgStage(wrap, { tooltip: $("tooltip"), labels: state.options, onZoom: (p) => { zoomVal.textContent = `${p}%`; } });
  await state.stage.load(`/files/${state.runId}/${step.file}`);
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
  const text = await (await fetch(`/files/${state.runId}/${state.meta.input}`)).text();
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
  try {
    // Ошибки показываем под редактором, рядом с тем, что их вызвало, — без всплывашки.
    await startRun(await runBody(input), $("go"), { quiet: true });
  } catch (err) {
    showErrors(err.message.split("\n"));
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
    ["Крыша", ROOF[s.roof.kind] ?? s.roof.kind],
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
  else if (state.stage && (e.key === "+" || e.key === "=")) state.stage.zoomBy(0.8);
  else if (state.stage && e.key === "-") state.stage.zoomBy(1.25);
}

async function init() {
  $("back-btn").addEventListener("click", goHome);
  $("home-link").addEventListener("click", (e) => { e.preventDefault(); goHome(); });
  for (const link of $("tabs").children) link.addEventListener("click", (e) => { e.preventDefault(); goToTab(link.dataset.tab); });
  window.addEventListener("popstate", route);
  document.addEventListener("keydown", onKey);
  state.options = await api("/api/options");
  bindPlanForm();
  await loadPlans();
  await route();
}

init().catch((err) => toast(err.message, "error"));
