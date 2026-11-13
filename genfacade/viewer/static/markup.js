// Страница правки автоматической разметки (gf#348): дом за домом, рамки поверх листов фасадов.
// «Хорошо» — одно нажатие; поправил рамки мышью или пальцем — «Сохранить правку»; «Негоден» —
// причина из списка. Что за дом дальше, какое у дома состояние, сколько этажей в метрах и сколько
// секунд ушло — решает сервер (viewer/markup.py): страница рисует его ответы и пересчётов не держит.
// Открытый дом — в адресе (#h=<id>); без адреса — первый непроверенный.

import {
  SHAPE, boxFrom, flattenMarks, handlePoints, markFrom, moveBox, normalize, pick,
  removeAt, removeElement, resizeBox, round1, setClass,
} from "/static/markup_geom.js";
import { topbar } from "/static/shell.js";
import { $, el, toast } from "/static/dom.js";
import { refusedFrom } from "/static/refusal.js";
import { serial } from "/static/serial.js";

topbar(document.getElementById("topbar"), "markup");

const NS = "http://www.w3.org/2000/svg";
const LEVEL_PAD_M = 1.0; // поле вокруг стены на кадре, как в tools/markup.py overlay
const MARK_PX = 12; // толщина отметки-полоски (трубы, слухового окна) на экране, px
const state = {
  options: null, queue: null, house: null, initial: "", selected: null, adding: null,
  addingMark: null, addingZone: false, zone: null, mark: null, drag: null, levels: [], busy: false,
  openedAt: 0,
};
const ordered = serial(); // предпросмотр линий — по очереди: последний ответ принадлежит последней правке

function sv(tag, attrs, parent) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  parent.append(node);
  return node;
}

async function call(url, body) {
  const res = await fetch(url, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) throw await refusedFrom(res);
  return res.json();
}

const handlePx = () =>
  parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--handle"));
const sides = () => state.house.sides;
const colorOf = (cls) => state.options.colors.cls[cls];

// ——— правка, которую уносим на сервер ———

function editBody() {
  return {
    sides: sides().map((s) => ({
      wall: s.wall, pt_per_unit: s.scale,
      elements: s.elements.map((e) => ({
        cls: e.cls, box: e.box.map(round1), parent: e.parent ?? null, variant: e.variant ?? null,
      })),
      zones: s.zones.map((z) => ({ role: z.role, material: z.material, box: z.box.map(round1) })),
    })),
    levels: state.levels,
    house: state.house.fields,
    ...Object.fromEntries(Object.entries(state.options.marks).map(([kind, style]) =>
      [style.field, flattenMarks(sides(), kind)])),
  };
}

const isDirty = () => JSON.stringify(editBody()) !== state.initial;

function refreshButtons() {
  $("good").textContent = isDirty() ? "Сохранить правку" : "Хорошо";
  for (const id of ["good", "reject", "prev", "next", "list-open"]) $(id).disabled = state.busy;
  const chosen = selectedElement();
  $("pick-tools").hidden = !chosen;
  $("zone-tools").hidden = !state.zone;
  refreshMarkTools();
  if (chosen) {
    $("cls").value = chosen.cls;
    const g = sides()[state.selected.k].geometry;
    const [x0, y0, x1, y1] = normalize(chosen.box);
    $("size").textContent = `${((x1 - x0) / g.px_per_m).toFixed(2)} × ${((y1 - y0) / g.px_per_m).toFixed(2)} м`;
  }
  document.querySelectorAll("[data-add]").forEach((b) =>
    b.classList.toggle("on", b.dataset.add === state.adding));
  document.querySelectorAll("[data-mark]").forEach((b) =>
    b.classList.toggle("on", b.dataset.mark === state.addingMark));
  document.querySelectorAll("[data-zone]").forEach((b) => b.classList.toggle("on", state.addingZone));
}

// ——— отметки на виде ———

const markAt = (ref) => sides()[ref.k].marks[ref.kind][ref.i];
const sameMark = (a, b) => a && b && a.k === b.k && a.kind === b.kind && a.i === b.i;

// У выбранной отметки с видом кровли (слуховое окно, крыльцо) — список видов: у слухового окна
// `roof`, у крыльца `kind`; сами варианты приходят с сервера.
function refreshMarkTools() {
  $("mark-tools").hidden = !state.mark;
  if (!state.mark) return;
  const m = markAt(state.mark), field = "roof" in m ? "roof" : "kind" in m ? "kind" : null;
  const choices = state.options.choices[field === "roof" ? "dormer_roof" : "roof_kind"];
  const kinds = $("mark-kind");
  kinds.hidden = !field;
  if (field) {
    kinds.replaceChildren(...choices.map((c) => el("option", { value: c }, c)));
    kinds.value = m[field];
  }
}

function selectMark(ref) {
  state.mark = ref;
  state.selected = null;
  state.zone = null;
  drawAll();
  refreshButtons();
}

function drawMarks(side, k, scale) {
  const o = state.options, top = side.geometry.tops.at(-1), bar = MARK_PX / scale;
  for (const [kind, marks] of Object.entries(side.marks)) {
    marks.forEach((m, i) => {
      const chosen = sameMark(state.mark, { k, kind, i });
      const style = o.marks[kind], color = chosen ? o.colors.selected : style.color;
      const [x0, x1] = Array.isArray(m.x) ? m.x : [m.x - bar / 2, m.x + bar / 2];
      const [y0, y1] = m.y ?? (style.shape === SHAPE.POINT
        ? [side.view[1], side.view[1] + side.view[3]] : [top - bar, top]);
      const rect = sv("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, class: "box",
        stroke: color, fill: style.color, "fill-opacity": chosen ? 0.35 : 0.2 }, side.svg);
      Object.assign(rect.dataset, { role: "mark", kind, i });
      sv("text", { x: x0 + 3, y: Math.max(y0, side.view[1]) + 15 / scale, fill: style.color,
        "font-size": 13 / scale }, side.svg).textContent = `${style.label} ${i}`;
    });
  }
}

const selectedElement = () =>
  state.selected ? sides()[state.selected.k].elements[state.selected.i] : null;
const selectedZone = () => (state.zone ? sides()[state.zone.k].zones[state.zone.i] : null);
// Рамка, которую двигают и тянут: выбранная зона или выбранный элемент.
const target = () => selectedZone() ?? selectedElement();
const targetSide = () => (state.zone ?? state.selected)?.k;

function selectZone(ref) {
  state.zone = ref;
  state.selected = null;
  state.mark = null;
  drawAll();
  refreshButtons();
}

// ——— рисование ———

function fit(side) {
  const g = side.geometry, pad = LEVEL_PAD_M * g.px_per_m;
  const ys = [g.ground, g.floor, ...g.tops, ...side.elements.map((e) => e.box[1]),
              ...side.outline.map((p) => p[1]), ...side.roof.flat().map((p) => p[1]),
              ...side.eaves.map((e) => e.y)];
  const x0 = Math.max(0, side.wall[0] - pad), x1 = Math.min(side.size[0], side.wall[1] + pad);
  const y0 = Math.max(0, Math.min(...ys) - pad), y1 = Math.min(side.size[1], g.ground + pad);
  return [x0, y0, x1 - x0, y1 - y0];
}

function line(parent, [x0, y0, x1, y1], color, role) {
  const horizontal = y0 === y1;
  const hit = sv("line", { x1: x0, y1: y0, x2: x1, y2: y1, class: `hit ${horizontal ? "h" : "v"}` }, parent);
  Object.assign(hit.dataset, role);
  sv("line", { x1: x0, y1: y0, x2: x1, y2: y1, class: "line", stroke: color }, parent)
    .style.pointerEvents = "none";
}

function drawLevels(side, g, scale) {
  const color = state.options.colors.levels, names = state.options.labels.level;
  const [left, right] = side.wall, bottom = g.tops.at(-1);
  const rows = [["ground", 0, g.ground], ["floor", 0, g.floor],
                ...g.tops.map((y, i) => ["top", i, y])];
  for (const [kind, index, y] of rows) {
    line(side.svg, [left, y, right, y], color, { role: "level", kind, index });
    sv("text", { x: side.view[0] + 4, y: y - 3 / scale, fill: color, "font-size": 13 / scale },
      side.svg).textContent = names[kind];
  }
  [left, right].forEach((x, w) =>
    line(side.svg, [x, bottom, x, g.ground], color, { role: "wall", w }));
}

function drawShapes(side) {
  const c = state.options.colors;
  const poly = (pts, color) => sv("polygon", {
    points: pts.map((p) => p.join(",")).join(" "), stroke: color, class: "shape" }, side.svg);
  if (side.outline.length) poly(side.outline, c.outline);
  side.roof.forEach((r) => poly(r, c.roof));
  side.eaves.forEach((e) => sv("line", { x1: e.x[0], y1: e.y, x2: e.x[1], y2: e.y,
    stroke: c.levels, "stroke-width": 4, class: "shape" }, side.svg));
}

function drawZones(side, k) {
  const c = state.options.colors;
  side.zones.forEach((z, i) => {
    const [x0, y0, x1, y1] = normalize(z.box), chosen = state.zone?.k === k && state.zone.i === i;
    sv("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, class: "zone",
      stroke: chosen ? c.selected : c.zone, fill: c.zone, "fill-opacity": chosen ? 0.3 : 0.12 }, side.svg);
  });
}

function drawElements(side, k, scale) {
  side.elements.forEach((e, i) => {
    const [x0, y0, x1, y1] = normalize(e.box), color = colorOf(e.cls);
    const chosen = state.selected?.k === k && state.selected.i === i;
    sv("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, class: "box",
      stroke: chosen ? state.options.colors.selected : color, fill: color, "fill-opacity": chosen ? 0.25 : 0.1 }, side.svg);
    sv("text", { x: x0 + 3, y: y0 + 15 / scale, fill: color, "font-size": 13 / scale }, side.svg).textContent = i;
  });
}

function drawHandles(side, k, scale) {
  if (targetSide() !== k) return;
  const [x0, y0, x1, y1] = normalize(target().box), r = handlePx() / scale;
  const small = Math.min(x1 - x0, y1 - y0) * scale < handlePx() * 4; // на мелкой рамке — только углы
  for (const [name, [x, y]] of Object.entries(handlePoints([x0, y0, x1, y1]))) {
    if (small && name.length === 1) continue;
    const grip = sv("circle", { cx: x, cy: y, r, fill: state.options.colors.selected, class: "grip" }, side.svg);
    Object.assign(grip.dataset, { role: "handle", h: name });
  }
}

function draw(k) {
  const side = sides()[k];
  const scale = side.svg.getBoundingClientRect().width / side.view[2];
  side.svg.replaceChildren();
  sv("image", { href: side.image, x: 0, y: 0, width: side.size[0], height: side.size[1] }, side.svg)
    .style.pointerEvents = "none";
  drawShapes(side);
  drawZones(side, k);
  drawLevels(side, side.geometry, scale);
  drawElements(side, k, scale);
  drawMarks(side, k, scale);
  drawHandles(side, k, scale);
}

const drawAll = () => sides().forEach((_, k) => draw(k));

function buildSide(side, k) {
  const card = el("section", { className: "mk-card" });
  const scale = el("input", { type: "number", step: "0.1", min: "1", value: side.scale });
  scale.addEventListener("change", () => setScale(k, Number(scale.value)));
  const title = el("h3", {}, side.view);
  const label = el("label", { className: "mk-scale" }, `масштаб, pt/${state.house.unit}`);
  label.append(scale);
  title.append(label);
  side.view = fit(side);
  side.svg = document.createElementNS(NS, "svg");
  side.svg.setAttribute("viewBox", side.view.join(" "));
  side.svg.setAttribute("class", "mk-view");
  side.svg.addEventListener("pointerdown", (ev) => onDown(k, ev));
  side.svg.addEventListener("pointermove", (ev) => onMove(k, ev));
  side.svg.addEventListener("pointerup", (ev) => onUp(k, ev));
  side.svg.addEventListener("pointercancel", () => { state.drag = null; drawAll(); });
  card.append(title, side.svg);
  return card;
}

// ——— касание и мышь ———

function toPt(side, ev) {
  const p = side.svg.createSVGPoint();
  p.x = ev.clientX;
  p.y = ev.clientY;
  const q = p.matrixTransform(side.svg.getScreenCTM().inverse());
  return [q.x, q.y];
}

function select(k, i) {
  state.mark = null;
  state.zone = null;
  state.selected = i < 0 ? null : { k, i };
  drawAll();
  refreshButtons();
}

function onDown(k, ev) {
  if (state.busy) return;
  ev.preventDefault();
  const side = sides()[k], start = toPt(side, ev), t = ev.target.dataset;
  side.svg.setPointerCapture(ev.pointerId);
  if (state.adding) return void (state.drag = { kind: "create", k, start, box: [...start, ...start] });
  if (state.addingMark) return void (state.drag = { kind: "mark", k, start, box: [...start, ...start] });
  if (state.addingZone) return void (state.drag = { kind: "zone", k, start, box: [...start, ...start] });
  if (t.role === "mark") return selectMark({ k, kind: t.kind, i: Number(t.i) });
  if (t.role === "handle") {
    const orig = [...target().box];
    return void (state.drag = { kind: "resize", k, h: t.h, start, orig });
  }
  if (t.role === "level") {
    const index = Number(t.index), g = side.geometry;
    const orig = t.kind === "top" ? g.tops[index] : g[t.kind];
    return void (state.drag = { kind: "level", k, level: t.kind, index, start, orig });
  }
  if (t.role === "wall") {
    return void (state.drag = { kind: "wall", k, w: Number(t.w), start, orig: side.wall[Number(t.w)] });
  }
  const i = pick(side.elements, start);
  if (i < 0 && pickZone(side, k, start)) return;
  select(k, i);
  if (i >= 0) state.drag = { kind: "move", k, start, orig: [...side.elements[i].box] };
}

// Под точкой нет элемента — берём зону отделки: она лежит под элементами.
function pickZone(side, k, start) {
  const i = pick(side.zones, start);
  if (i < 0) return false;
  selectZone({ k, i });
  state.drag = { kind: "move", k, start, orig: [...side.zones[i].box] };
  return true;
}

function onMove(k, ev) {
  const d = state.drag;
  if (!d || d.k !== k) return;
  const side = sides()[k], p = toPt(side, ev), dx = p[0] - d.start[0], dy = p[1] - d.start[1];
  if (d.kind === "move") target().box = moveBox(d.orig, dx, dy);
  if (d.kind === "resize") target().box = resizeBox(d.orig, d.h, dx, dy);
  if (CREATING.has(d.kind)) d.box = [...d.start, ...p];
  if (d.kind === "wall") side.wall[d.w] = d.orig + dx;
  if (d.kind === "level") setLine(side.geometry, d, d.orig + dy);
  draw(k);
  if (d.kind === "create") drawGhost(side, d.box, colorOf(state.adding));
  if (d.kind === "zone") drawGhost(side, d.box, state.options.colors.zone);
  if (d.kind === "mark" && state.options.marks[state.addingMark].shape !== SHAPE.POINT) {
    drawGhost(side, d.box, state.options.marks[state.addingMark].color);
  }
}

const CREATING = new Set(["create", "mark", "zone"]); // жесты, что тянут новую рамку

function setLine(g, d, y) {
  if (d.level === "top") g.tops[d.index] = y;
  else g[d.level] = y;
}

function drawGhost(side, box, color) {
  const [x0, y0, x1, y1] = normalize(box);
  sv("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, class: "box",
    stroke: color, fill: "none", "stroke-dasharray": "4 3" }, side.svg);
}

function onUp(k, ev) {
  const d = state.drag;
  state.drag = null;
  if (!d || d.k !== k) return;
  const side = sides()[k];
  if (d.kind === "create") addElement(side, k, d, toPt(side, ev));
  if (d.kind === "mark") addMark(side, k, d, toPt(side, ev));
  if (d.kind === "zone") addZone(side, k, d, toPt(side, ev));
  if (d.kind === "move" || d.kind === "resize") {
    const e = target();
    e.box = normalize(e.box).map(round1);
  }
  if (d.kind === "level") {
    const y = d.level === "top" ? side.geometry.tops[d.index] : side.geometry[d.level];
    pushLevel({ side: k, kind: d.level, index: d.index, y });
  }
  draw(k);
  refreshButtons();
}

function addElement(side, k, d, end) {
  const o = state.options, g = side.geometry, cls = state.adding;
  const box = boxFrom(d.start, end, o.default_size_m[cls], g.px_per_m, o.min_box_m * g.px_per_m);
  side.elements.push({ cls, box, parent: null, variant: null });
  state.adding = null;
  select(k, side.elements.length - 1);
}

// Вид второй отделки один на дом: у дома без неё берём первый из списка — поле дома его покажет.
function addZone(side, k, d, end) {
  const o = state.options, g = side.geometry, fields = state.house.fields;
  fields.second_material ??= o.house_form.find((r) => r.name === "second_material").choices[0];
  const box = boxFrom(d.start, end, o.zone.size_m, g.px_per_m, o.min_box_m * g.px_per_m);
  side.zones.push({ role: "accent", material: fields.second_material, box });
  state.addingZone = false;
  buildHouseForm();
  selectZone({ k, i: side.zones.length - 1 });
  return preview();
}

function addMark(side, k, d, end) {
  const kind = state.addingMark, style = state.options.marks[kind], g = side.geometry;
  const made = markFrom(style.shape, d.start, end, {
    sizeM: style.size_m, pxPerM: g.px_per_m, minPt: state.options.min_box_m * g.px_per_m,
    defaults: style.defaults });
  side.marks[kind].push(made);
  state.addingMark = null;
  selectMark({ k, kind, i: side.marks[kind].length - 1 });
}

// ——— линии, масштаб: пересчёт — на сервере ———

function pushLevel(level) {
  state.levels = state.levels.filter((v) =>
    !(v.side === level.side && v.kind === level.kind && v.index === level.index));
  state.levels.push(level);
  preview();
}

function setScale(k, value) {
  if (!(value > 0)) return;
  sides()[k].scale = value;
  refreshButtons();
  preview();
}

function preview() {
  return ordered("preview", async () => {
    try {
      const got = await call(`/api/markup/${state.house.id}/preview`, editBody());
      got.geometry.forEach((g, k) => { sides()[k].geometry = g; });
      setRoles(got.roles);
      drawAll();
    } catch (err) {
      toast(`Линии не пересчитаны: ${err.message}`, "error");
    }
    refreshButtons();
  });
}

// ——— действия над выбранной рамкой ———

function removeMarked() {
  const { k, kind, i } = state.mark, side = sides()[k];
  side.marks[kind] = removeAt(side.marks[kind], i);
  selectMark(null);
}

function removeZone() {
  const { k, i } = state.zone, side = sides()[k];
  side.zones = removeAt(side.zones, i);
  selectZone(null);
  return preview();
}

function removeSelected() {
  if (state.mark) return removeMarked();
  if (state.zone) return removeZone();
  if (!state.selected) return;
  const { k, i } = state.selected, side = sides()[k];
  side.elements = removeElement(side.elements, i);
  select(k, -1);
}

function duplicateSelected() {
  const chosen = selectedElement();
  if (!chosen) return;
  const { k } = state.selected, side = sides()[k];
  const [x0, , x1] = normalize(chosen.box), shift = x1 - x0 + 8;
  side.elements.push({ ...chosen, box: moveBox(chosen.box, shift, 0), parent: null });
  select(k, side.elements.length - 1);
}

function nudge(dx, dy) {
  const chosen = target();
  if (!chosen) return;
  chosen.box = moveBox(chosen.box, dx, dy);
  draw(targetSide());
  refreshButtons();
}

function onKey(ev) {
  if (ev.target.matches("input, select, textarea") || document.querySelector("dialog[open]")) return;
  const step = ev.shiftKey ? 10 : 1;
  const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  if (moves[ev.key] && target()) { ev.preventDefault(); nudge(...moves[ev.key]); }
  if (ev.key === "Delete" || ev.key === "Backspace") removeSelected();
  if (ev.key === "Escape") {
    Object.assign(state, { adding: null, addingMark: null, addingZone: false });
    select(0, -1);
  }
  if (ev.key === "Enter" && !state.busy) $("good").click();
}

// ——— решение о доме и очередь ———

async function decide(body) {
  state.busy = true;
  refreshButtons();
  try {
    const got = await call(`/api/markup/${state.house.id}/decision`, body);
    if (!got.assembly.ok) toast(`Разметка не собирается: ${got.assembly.detail}`, "error");
    else toast(`${state.options.labels.state[got.state]} · ${got.seconds} с`);
    state.queue = await call("/api/markup");
    state.busy = false;
    got.next ? go(got.next) : showList();
  } catch (err) {
    state.busy = false;
    toast(`Не сохранено: ${err.message}`, "error");
    refreshButtons();
  }
}

function go(id) {
  if (location.hash === `#h=${id}`) return route();
  location.hash = `h=${id}`;
}

function step(delta) {
  const ids = state.queue.items.map((i) => i.id), at = ids.indexOf(state.house.id);
  const to = ids[at + delta];
  if (to && (!isDirty() || confirm("Правка не сохранена. Уйти?"))) go(to);
}

function progress() {
  const c = state.queue.counts, median = c.median_seconds === null ? "" : ` · медиана ${c.median_seconds} с`;
  $("progress").textContent = `проверено ${c.checked} · осталось ${c.left}${median}`;
}

function showList() {
  const body = $("list-body"), labels = state.options.labels;
  body.replaceChildren(...state.queue.items.map((i) => {
    const row = el("button", { type: "button", className: i.id === state.house?.id ? "cur" : "" });
    const why = i.reason ? ` · ${labels.reason[i.reason]}` : "";
    const time = i.seconds === null ? "" : ` · ${i.seconds} с`;
    row.append(el("span", {}, i.id), el("span", { className: "mk-progress" }, `${labels.state[i.state]}${why}${time}`));
    row.addEventListener("click", () => { $("list").close(); go(i.id); });
    return row;
  }));
  progress();
  $("list").showModal();
}

function showReasons() {
  const list = $("reason-list");
  list.replaceChildren(...Object.entries(state.options.labels.reason).map(([code, text]) => {
    const b = el("button", { type: "button", className: "btn" }, text);
    b.addEventListener("click", () => {
      $("reasons").close();
      decide({ good: false, reason: code, note: $("note").value });
    });
    return b;
  }));
  $("note").value = state.house.note;
  $("reasons").showModal();
}

async function openHouse(id) {
  const house = await call(`/api/markup/${encodeURIComponent(id)}/open`, null);
  for (const s of house.sides) {
    s.scale = s.geometry.pt_per_unit;
    s.elements = s.elements.map((e) => ({ ...e, box: [...e.box] }));
    s.zones = s.zones.map((z) => ({ ...z, box: [...z.box] }));
  }
  house.fields = structuredClone(house.house);
  Object.assign(state, { house, selected: null, adding: null, addingMark: null, addingZone: false,
    zone: null, mark: null, drag: null, levels: [] });
  state.openedAt = performance.now();
  $("house").textContent = house.id;
  const chip = $("chip");
  chip.textContent = state.options.labels.state[house.state];
  chip.className = `mk-chip ${house.state}`;
  buildHouseForm();
  buildColors();
  $("sides").replaceChildren(...house.sides.map(buildSide));
  drawAll();
  state.initial = JSON.stringify(editBody());
  state.queue = await call("/api/markup");
  progress();
  refreshButtons();
  window.scrollTo(0, 0);
}

async function route() {
  const id = new URLSearchParams(location.hash.slice(1)).get("h") ?? state.queue.next;
  if (!id) return showList();
  try {
    await openHouse(id);
  } catch (err) {
    toast(err.message, "error");
  }
}

// ——— поля дома: панель строится по `options.house_form` ———

const pathOf = (name) => name.split(".");
const fieldGet = (name) => pathOf(name).reduce((o, k) => o[k], state.house.fields);
function fieldSet(name, value) {
  const path = pathOf(name), last = path.pop();
  path.reduce((o, k) => o[k], state.house.fields)[last] = value;
}

// Значение поля из элемента: пустой список или число — null (поле не записано), флажок — bool.
function fieldValue(row, input) {
  if (row.type === "flag") return input.checked;
  if (row.type === "number") return input.value === "" ? null : Number(input.value);
  return input.value === "" ? null : input.value;
}

function fieldInput(row) {
  if (row.type === "flag") return el("input", { type: "checkbox", checked: fieldGet(row.name) });
  if (row.type === "number") {
    return el("input", { type: "number", step: row.step, min: "0", value: fieldGet(row.name) ?? "" });
  }
  const choices = row.empty ? [["", state.options.labels.empty_kind]] : [];
  const select = el("select");
  select.append(...[...choices, ...row.choices.map((c) => [c, c])]
    .map(([value, text]) => el("option", { value }, text)));
  select.value = fieldGet(row.name) ?? "";
  return select;
}

// Поля дома, от которых зависит, какие роли есть в палитре: после правки сервер пересчитывает роли.
const ROLE_FIELDS = new Set(["material", "plinth_material", "trim_material", "roof_material",
  "second_material"]);

// ——— цвета ролей палитры: поле на каждую роль, что есть у дома ———

function setRoles(roles) {
  const colors = state.house.fields.colors;
  for (const role of Object.keys(colors)) if (!roles.includes(role)) delete colors[role];
  state.house.roles = roles;
  buildColors();
}

function colorRow(role) {
  const names = state.options.labels, colors = state.house.fields.colors;
  const input = el("input", { type: "color", value: colors[role] ?? "#808080" });
  const clear = el("button", { type: "button", className: "btn" }, names.no_color);
  const sync = () => {
    clear.disabled = !(role in colors);
    input.classList.toggle("unset", !(role in colors));
  };
  input.addEventListener("input", () => { colors[role] = input.value; sync(); refreshButtons(); });
  clear.addEventListener("click", () => { delete colors[role]; sync(); refreshButtons(); });
  sync();
  const label = el("label", { className: "mk-field" }, names.role[role]);
  label.append(input, clear);
  return label;
}

function buildColors() {
  $("color-fields").replaceChildren(...state.house.roles.map(colorRow));
}

function buildHouseForm() {
  $("house-fields").replaceChildren(...state.options.house_form.map((row) => {
    const input = fieldInput(row);
    input.addEventListener("change", () => {
      fieldSet(row.name, fieldValue(row, input));
      refreshButtons();
      if (ROLE_FIELDS.has(row.name)) preview();
    });
    const label = el("label", { className: "mk-field" }, row.label);
    label.append(input);
    return label;
  }));
}

function buildTools() {
  const o = state.options, add = $("add-tools");
  add.replaceChildren(...o.add_classes.map((cls) => {
    const b = el("button", { type: "button", className: "btn" }, `+ ${o.labels.cls[cls]}`);
    b.dataset.add = cls;
    b.addEventListener("click", () => {
      state.adding = state.adding === cls ? null : cls;
      state.addingMark = null;
      state.addingZone = false;
      refreshButtons();
    });
    return b;
  }));
  add.append(...Object.entries(o.marks).map(([kind, style]) => {
    const b = el("button", { type: "button", className: "btn" }, `+ ${style.label}`);
    b.dataset.mark = kind;
    b.addEventListener("click", () => {
      state.addingMark = state.addingMark === kind ? null : kind;
      state.adding = null;
      state.addingZone = false;
      refreshButtons();
    });
    return b;
  }));
  const zone = el("button", { type: "button", className: "btn" }, `+ ${o.zone.label}`);
  zone.dataset.zone = "";
  zone.addEventListener("click", () => {
    state.addingZone = !state.addingZone;
    state.adding = null;
    state.addingMark = null;
    refreshButtons();
  });
  add.append(zone);
  $("mark-del").textContent = o.labels.delete_mark;
  $("zone-del").textContent = o.labels.delete_zone;
  $("mark-kind").addEventListener("change", () => {
    const m = markAt(state.mark);
    m["roof" in m ? "roof" : "kind"] = $("mark-kind").value;
    refreshButtons();
  });
  $("cls").replaceChildren(...Object.entries(o.labels.cls).map(([cls, text]) => el("option", { value: cls }, text)));
  $("cls").addEventListener("change", () => {
    const { k, i } = state.selected, side = sides()[k];
    side.elements[i] = setClass(side.elements[i], $("cls").value);
    draw(k);
    refreshButtons();
  });
}

async function boot() {
  state.queue = await call("/api/markup");
  state.options = state.queue.options;
  buildTools();
  $("good").addEventListener("click", () => decide({ good: true, edit: isDirty() ? editBody() : null }));
  $("reject").addEventListener("click", showReasons);
  $("reasons-close").addEventListener("click", () => $("reasons").close());
  $("list-close").addEventListener("click", () => $("list").close());
  $("list-open").addEventListener("click", showList);
  $("prev").addEventListener("click", () => step(-1));
  $("next").addEventListener("click", () => step(1));
  $("del").addEventListener("click", removeSelected);
  $("dup").addEventListener("click", duplicateSelected);
  $("mark-del").addEventListener("click", removeSelected);
  $("zone-del").addEventListener("click", removeSelected);
  document.addEventListener("keydown", onKey);
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", () => state.house && drawAll());
  setInterval(() => {
    if (state.house) $("timer").textContent = `${Math.round((performance.now() - state.openedAt) / 1000)} с`;
  }, 1000);
  route();
}

boot().catch((err) => toast(err.message, "error"));
