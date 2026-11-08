// Страница «Новый дом» (gf#356): план, параметры дома, необязательное описание — и запуск прогона.
// Модуль принимает только план, текст и режим, поэтому параметры уходят в него текстом: сервер
// собирает описание словами конфига и читает его обратно стабом шага 1 (POST /api/spec/text,
// /api/spec). Что можно выбрать — ответ GET /api/newhouse; списков значений здесь нет.

import { $, el, toast } from "/static/dom.js";

const SAVED = "newhouse.v1";
const AUTO = "";                 // «не названо»: решает стаб
const YES = "yes", NO = "no";    // элемент есть / «без …»
const SOURCES = [
  { key: "ready", title: "Готовый план" },
  { key: "random", title: "Случайный план" },
  { key: "own", title: "Свой SVG" },
];
const TEXT = {
  auto: "авто", sheet: "Построить фасады", sheets: "Построить варианты", slope: "Уклон ската по виду крыши",
  readTitle: "Что прочтёт шаг 1", noText: "Описание пустое — шаг 1 возьмёт заготовку дома",
};

const mem = {
  get(fallback) {
    try { return { ...fallback, ...JSON.parse(localStorage.getItem(SAVED)) }; } catch { return fallback; }
  },
  set(value) {
    try { localStorage.setItem(SAVED, JSON.stringify(value)); } catch { /* приватный режим */ }
  },
};

const blank = () => ({ floors: null, wing_floors: null, style: null, walls: null, wall_color: null, roof: null, roof_color: null, trims: {} });

export async function mountNewHouse({ api, options, startRun, goHome }) {
  const { choices, shapes } = await api("/api/newhouse");
  const plans = await api("/api/plans");
  const saved = mem.get({ source: "ready", plan: plans[0]?.name, shape: shapes[0], variant: 0, mode: options.default_mode, count: 3, form: blank(), text: "" });
  const ui = { ...saved, form: { ...blank(), ...saved.form }, own: null, ownUrl: null, read: 0 };
  if (!SOURCES.some((s) => s.key === ui.source)) ui.source = "ready";
  if (!plans.some((p) => p.name === ui.plan)) ui.plan = plans[0]?.name;
  if (!options.modes.some((m) => m.value === ui.mode)) ui.mode = options.default_mode;
  if (!shapes.includes(ui.shape)) ui.shape = shapes[0];

  const save = () => mem.set({ source: ui.source, plan: ui.plan, shape: ui.shape, variant: ui.variant, mode: ui.mode, count: ui.count, form: ui.form, text: ui.text });

  const form = $("nh");

  // ——— план ———

  function buildPlan() {
    $("nh-source").replaceChildren(...SOURCES.map((s) => radio("nh-source", s.key, s.title)));
    $("nh-source").addEventListener("change", (e) => { ui.source = e.target.value; syncPlan(); save(); });
    const select = $("nh-plan");
    select.replaceChildren(...plans.map((p) => el("option", { value: p.name }, p.name)));
    select.addEventListener("change", () => { ui.plan = select.value; syncPlan(); save(); });
    const shape = $("nh-shape");
    shape.replaceChildren(...shapes.map((s) => el("option", { value: s }, options.shape[s])));
    shape.addEventListener("change", () => { ui.shape = shape.value; ui.variant = 0; syncPlan(); save(); });
    $("nh-variant").addEventListener("click", () => { ui.variant += 1; syncPlan(); save(); });
    $("nh-file").addEventListener("change", async () => {
      const file = $("nh-file").files[0];
      if (!file) return;
      if (ui.ownUrl) URL.revokeObjectURL(ui.ownUrl);
      ui.own = { name: file.name.replace(/\.svg$/i, ""), svg: await file.text() };
      ui.ownUrl = URL.createObjectURL(file);
      syncPlan();
    });
    $("nh-mode").replaceChildren(...options.modes.map((m) => radio("nh-mode", m.value, m.title, m.hint)));
    $("nh-mode").addEventListener("change", (e) => { ui.mode = e.target.value; save(); });
  }

  const planUrl = () => ({
    ready: `/api/plans/${encodeURIComponent(ui.plan)}`,
    random: `/api/plans/random/${ui.shape}/${ui.variant}.svg`,
    own: ui.ownUrl,
  })[ui.source];

  function syncPlan() {
    check("nh-source", ui.source);
    check("nh-mode", ui.mode);
    $("nh-plan").value = ui.plan;
    $("nh-shape").value = ui.shape;
    $("nh-variant-n").textContent = `вариант ${ui.variant + 1}`;
    for (const key of SOURCES.map((s) => s.key)) $(`nh-pick-${key}`).hidden = key !== ui.source;
    $("nh-count-field").hidden = ui.source !== "random";
    const src = planUrl();
    $("nh-thumb").replaceChildren(src ? el("img", { src, alt: "План дома" }) : el("p", { className: "empty-note" }, "Выберите файл SVG плана GenPlan"));
    $("nh-go").querySelector("span").textContent = ui.source === "random" && ui.count > 1 ? TEXT.sheets : TEXT.sheet;
  }

  // ——— параметры ———

  function buildFields() {
    const f = $("nh-fields");
    f.replaceChildren(
      group("Этажей", "floors", [[AUTO, TEXT.auto], ...choices.floors.map((n) => [String(n), String(n)])]),
      group("Нижнее крыло, этажей", "wing_floors", [[AUTO, TEXT.auto], ...choices.wing_floors.map((n) => [String(n), String(n)])]),
      selectField("Стиль", "style", choices.styles.map((s) => [s, options.style[s]])),
      tiles(),
      swatchGroup("Цвет стен", "wall_color", "nh-wall-colors"),
      group("Крыша", "roof", [[AUTO, TEXT.auto], ...choices.roofs.map((r) => [r, options.roof[r]])]),
      el("p", { className: "hint-line", id: "nh-pitch" }),
      swatchGroup("Цвет крыши", "roof_color", "nh-roof-colors"),
      trims(),
    );
    f.addEventListener("change", onField);
  }

  function group(title, name, items) {
    const box = el("div", { className: "nh-field", role: "radiogroup" });
    box.setAttribute("aria-label", title);
    const seg = el("div", { className: "segmented" });
    seg.append(...items.map(([v, label]) => radio(`f-${name}`, v, label)));
    box.append(el("span", { className: "nh-label" }, title), seg);
    return box;
  }

  function selectField(title, name, items) {
    const label = el("label", { className: "field nh-field" });
    const select = el("select", { className: "select", name: `f-${name}` });
    select.append(el("option", { value: AUTO }, TEXT.auto), ...items.map(([v, t]) => el("option", { value: v }, t)));
    label.append(el("span", {}, title), select);
    return label;
  }

  function tiles() {
    const box = el("fieldset", { className: "nh-field nh-tiles" });
    box.append(el("legend", { className: "nh-label" }, "Стены"));
    const auto = el("label", { className: "tile tile-auto" });
    auto.append(Object.assign(el("input", { type: "radio", name: "f-walls", value: AUTO })), el("span", {}, TEXT.auto));
    box.append(auto, ...choices.walls.map((kind) => {
      const tile = el("label", { className: "tile" });
      const img = el("img", { src: `/api/catalog/walls/${kind}/image.svg`, alt: "", loading: "lazy" });
      tile.append(el("input", { type: "radio", name: "f-walls", value: kind }), el("span", { className: "tile-pic" }), el("span", {}, options.kind[kind]));
      tile.querySelector(".tile-pic").append(img);
      return tile;
    }));
    return box;
  }

  function swatchGroup(title, name, id) {
    const box = el("fieldset", { className: "nh-field", id });
    box.dataset.name = name;
    box.append(el("legend", { className: "nh-label" }, title));
    box.append(el("div", { className: "swatches" }));
    return box;
  }

  function fillSwatches(id, colors, current) {
    const name = $(id).dataset.name, list = $(id).querySelector(".swatches");
    const auto = el("label", { className: "sw" });
    auto.append(el("input", { type: "radio", name: `f-${name}`, value: AUTO }), el("span", {}, TEXT.auto));
    list.replaceChildren(auto, ...colors.map((c) => {
      const label = el("label", { className: "sw" });
      const dot = el("span", { className: "swatch" });
      dot.style.background = c.hex;
      label.append(el("input", { type: "radio", name: `f-${name}`, value: c.name }), dot, el("span", {}, options.color[c.name] ?? c.name));
      return label;
    }));
    check(`f-${name}`, current);
  }

  function trims() {
    const box = el("fieldset", { className: "nh-field nh-trims-box" });
    box.append(el("legend", { className: "nh-label" }, "Элементы"));
    const rows = el("div", { className: "nh-trims" });
    for (const t of choices.trims) {
      const row = el("div", { className: "nh-trim", role: "radiogroup" });
      row.setAttribute("aria-label", options.trim[t]);
      const seg = el("div", { className: "segmented" });
      seg.append(radio(`t-${t}`, AUTO, TEXT.auto), radio(`t-${t}`, YES, "есть"), radio(`t-${t}`, NO, "нет"));
      row.append(el("span", {}, options.trim[t]), seg);
      rows.append(row);
    }
    box.append(rows);
    return box;
  }

  const wallColors = () => ui.form.walls
    ? choices.wall_colors[ui.form.walls]
    : [...new Map(Object.values(choices.wall_colors).flat().map((c) => [c.name, c])).values()];

  async function onField(e) {
    const { name, value } = e.target;
    if (name.startsWith("t-")) {
      const t = name.slice(2);
      if (value === AUTO) delete ui.form.trims[t]; else ui.form.trims[t] = value === YES;
    } else if (name.startsWith("f-")) {
      const key = name.slice(2);
      ui.form[key] = value === AUTO ? null : (key === "floors" || key === "wing_floors" ? Number(value) : value);
      if (key === "walls" && ui.form.wall_color && !wallColors().some((c) => c.name === ui.form.wall_color)) ui.form.wall_color = null;
    } else return;
    syncFields();
    await textFromForm();
  }

  function syncFields() {
    const f = ui.form;
    for (const key of ["floors", "wing_floors", "walls", "roof"]) check(`f-${key}`, f[key]);
    $("nh-fields").querySelector("select[name=f-style]").value = f.style ?? AUTO;
    fillSwatches("nh-wall-colors", wallColors(), f.wall_color);
    fillSwatches("nh-roof-colors", choices.roof_colors, f.roof_color);
    for (const t of choices.trims) check(`t-${t}`, t in f.trims ? (f.trims[t] ? YES : NO) : AUTO);
    const pitch = f.roof ? choices.pitch_deg[f.roof] ?? 0 : null;
    $("nh-pitch").textContent = pitch === null ? "" : `${TEXT.slope}: ${pitch}°`;
    save();
  }

  // ——— описание ———

  function buildText() {
    $("nh-text").addEventListener("input", () => { ui.text = $("nh-text").value; save(); readBack(); });
    $("nh-parse").addEventListener("click", async () => {
      const got = await api("/api/spec", { text: ui.text });
      ui.form = { ...blank(), ...got.form, trims: Object.fromEntries(Object.entries(got.form.trims)) };
      syncFields();
      showRead(got);
      toast("Параметры выставлены по тому, что прочитал шаг 1");
    });
    $("nh-reset").addEventListener("click", async () => { ui.form = blank(); syncFields(); await textFromForm(); });
  }

  async function textFromForm() {
    ui.text = (await api("/api/spec/text", ui.form)).text;
    $("nh-text").value = ui.text;
    save();
    await readBack();
  }

  async function readBack() {
    const mine = ++ui.read;
    const got = await api("/api/spec", { text: ui.text });
    if (mine === ui.read) showRead(got);
  }

  function showRead({ form: read, colors }) {
    const swatch = (hex) => `<span class="swatch" style="background:${hex}"></span>`;
    const on = Object.entries(read.trims).filter(([, v]) => v).map(([t]) => options.trim[t]);
    const rows = [
      ["Этажей", read.floors + (read.wing_floors ? `, нижнее крыло — ${read.wing_floors}` : "")],
      ["Стиль", options.style[read.style]],
      ["Стены", `${swatch(colors.main)} ${options.kind[read.walls] ?? read.walls}`],
      ["Крыша", `${swatch(colors.roof)} ${options.roof[read.roof]}`],
      ["Отделка", `${swatch(colors.trim)} ${on.length ? on.join(", ") : "без элементов"}`],
    ];
    $("nh-read").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  }

  // ——— запуск ———

  function buildActions() {
    $("nh-count").value = ui.count;
    $("nh-count").addEventListener("change", () => {
      ui.count = Math.min(Math.max(Number($("nh-count").value) || 1, 1), Number($("nh-count").max));
      $("nh-count").value = ui.count;
      syncPlan(); save();
    });
    form.addEventListener("submit", (e) => { e.preventDefault(); build().catch(() => {}); });
  }

  async function planFor(variant) {
    if (ui.source === "ready") return { plan: ui.plan, svg: null };
    if (ui.source === "own") return { plan: ui.own.name, svg: ui.own.svg };
    const res = await fetch(`/api/plans/random/${ui.shape}/${variant}.svg`);
    return { plan: `random-${ui.shape}-${variant + 1}`, svg: await res.text() };
  }

  async function build() {
    if (ui.source === "own" && !ui.own) { toast("Сначала выберите файл плана", "error"); return; }
    const many = ui.source === "random" && ui.count > 1;
    const run = async (variant) => {
      const { plan, svg } = await planFor(variant);
      return { plan_run: { plan, text: ui.text.trim(), mode: ui.mode }, svg };
    };
    if (!many) return startRun(await run(ui.variant), $("nh-go"));
    const button = $("nh-go");
    button.disabled = true;
    button.classList.add("busy");
    let built = 0;
    try {
      for (let i = 0; i < ui.count; i += 1) {
        try { await api("/api/runs", await run(ui.variant + i)); built += 1; } catch (err) { toast(`Вариант ${i + 1}: ${err.message}`, "error"); }
      }
    } finally {
      button.disabled = false;
      button.classList.remove("busy");
    }
    toast(`Построено ${built} из ${ui.count}`);
    if (built) goHome();
  }

  function syncAll() {
    $("nh-text").value = ui.text;
    syncPlan();
    syncFields();
    readBack();
  }

  buildPlan();
  buildFields();
  buildText();
  buildActions();
  syncAll();
  form.inert = false;
}

// ——— радио в `.segmented` ———

function radio(name, value, title, hint = "") {
  const label = el("label", { title: hint });
  label.append(el("input", { type: "radio", name, value }), el("span", {}, title));
  return label;
}

function check(name, value) {
  const wanted = value === null || value === undefined ? AUTO : String(value);
  for (const input of document.querySelectorAll(`input[name="${name}"]`)) input.checked = input.value === wanted;
}
