// Страница правки автоматической разметки (gf#348): дом за домом, рамки поверх листов фасадов.
// «Хорошо» — одно нажатие; поправил рамки мышью или пальцем — «Сохранить правку»; «Негоден» —
// причина из списка. Что за дом дальше, какое у дома состояние, сколько этажей в метрах и сколько
// секунд ушло — решает сервер (viewer/markup.py): страница рисует его ответы и пересчётов не держит.
// Открытый дом — в адресе (#h=<id>); без адреса — первый непроверенный.

import {
  HANDLES, boxAt, handlePoints, isTap, moveBox, normalize, pick, removeElement, resizeBox, round1,
  setClass,
} from "/static/markup_geom.js";
import { $, el, toast } from "/static/dom.js";
import { refusedFrom } from "/static/refusal.js";
import { serial } from "/static/serial.js";

const NS = "http://www.w3.org/2000/svg";
const LEVEL_PAD_M = 1.0; // поле вокруг стены на кадре, как в tools/markup.py overlay
const state = {
  options: null, queue: null, house: null, initial: "", selected: null, adding: null,
  drag: null, levels: [], busy: false, openedAt: 0,
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
    })),
    levels: state.levels,
  };
}

const isDirty = () => JSON.stringify(editBody()) !== state.initial;

function refreshButtons() {
  $("good").textContent = isDirty() ? "Сохранить правку" : "Хорошо";
  for (const id of ["good", "reject", "prev", "next", "list-open"]) $(id).disabled = state.busy;
  const chosen = selectedElement();
  $("pick-tools").hidden = !chosen;
  if (chosen) {
    $("cls").value = chosen.cls;
    const g = sides()[state.selected.k].geometry;
    const [x0, y0, x1, y1] = normalize(chosen.box);
    $("size").textContent = `${((x1 - x0) / g.px_per_m).toFixed(2)} × ${((y1 - y0) / g.px_per_m).toFixed(2)} м`;
  }
  document.querySelectorAll("[data-add]").forEach((b) =>
    b.classList.toggle("on", b.dataset.add === state.adding));
}

const selectedElement = () =>
  state.selected ? sides()[state.selected.k].elements[state.selected.i] : null;

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
  for (const z of side.zones) {
    const [x0, y0, x1, y1] = z.box;
    sv("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, stroke: c.zone, class: "zone" }, side.svg);
  }
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
  if (state.selected?.k !== k) return;
  const box = side.elements[state.selected.i].box;
  const [x0, y0, x1, y1] = normalize(box), r = handlePx() / scale;
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
  drawLevels(side, side.geometry, scale);
  drawElements(side, k, scale);
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
  if (t.role === "handle") {
    const orig = [...side.elements[state.selected.i].box];
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
  select(k, i);
  if (i >= 0) state.drag = { kind: "move", k, start, orig: [...side.elements[i].box] };
}

function onMove(k, ev) {
  const d = state.drag;
  if (!d || d.k !== k) return;
  const side = sides()[k], p = toPt(side, ev), dx = p[0] - d.start[0], dy = p[1] - d.start[1];
  if (d.kind === "move") side.elements[state.selected.i].box = moveBox(d.orig, dx, dy);
  if (d.kind === "resize") side.elements[state.selected.i].box = resizeBox(d.orig, d.h, dx, dy);
  if (d.kind === "create") d.box = [...d.start, ...p];
  if (d.kind === "wall") side.wall[d.w] = d.orig + dx;
  if (d.kind === "level") setLine(side.geometry, d, d.orig + dy);
  draw(k);
  if (d.kind === "create") drawGhost(side, d.box);
}

function setLine(g, d, y) {
  if (d.level === "top") g.tops[d.index] = y;
  else g[d.level] = y;
}

function drawGhost(side, box) {
  const [x0, y0, x1, y1] = normalize(box);
  sv("rect", { x: x0, y: y0, width: x1 - x0, height: y1 - y0, class: "box",
    stroke: colorOf(state.adding), fill: "none", "stroke-dasharray": "4 3" }, side.svg);
}

function onUp(k, ev) {
  const d = state.drag;
  state.drag = null;
  if (!d || d.k !== k) return;
  const side = sides()[k];
  if (d.kind === "create") addElement(side, k, d, toPt(side, ev));
  if (d.kind === "move" || d.kind === "resize") {
    const e = side.elements[state.selected.i];
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
  const minPt = o.min_box_m * g.px_per_m;
  const box = isTap([...d.start, ...end], minPt)
    ? boxAt(d.start, o.default_size_m[cls], g.px_per_m) : normalize([...d.start, ...end]);
  side.elements.push({ cls, box: box.map(round1), parent: null, variant: null });
  state.adding = null;
  select(k, side.elements.length - 1);
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
      drawAll();
    } catch (err) {
      toast(`Линии не пересчитаны: ${err.message}`, "error");
    }
    refreshButtons();
  });
}

// ——— действия над выбранной рамкой ———

function removeSelected() {
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
  const chosen = selectedElement();
  if (!chosen) return;
  chosen.box = moveBox(chosen.box, dx, dy);
  draw(state.selected.k);
  refreshButtons();
}

function onKey(ev) {
  if (ev.target.matches("input, select, textarea") || document.querySelector("dialog[open]")) return;
  const step = ev.shiftKey ? 10 : 1;
  const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  if (moves[ev.key] && state.selected) { ev.preventDefault(); nudge(...moves[ev.key]); }
  if (ev.key === "Delete" || ev.key === "Backspace") removeSelected();
  if (ev.key === "Escape") { state.adding = null; select(0, -1); }
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
  }
  Object.assign(state, { house, selected: null, adding: null, drag: null, levels: [] });
  state.openedAt = performance.now();
  $("house").textContent = house.id;
  const chip = $("chip");
  chip.textContent = state.options.labels.state[house.state];
  chip.className = `mk-chip ${house.state}`;
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

function buildTools() {
  const o = state.options, add = $("add-tools");
  add.replaceChildren(...o.add_classes.map((cls) => {
    const b = el("button", { type: "button", className: "btn" }, `+ ${o.labels.cls[cls]}`);
    b.dataset.add = cls;
    b.addEventListener("click", () => { state.adding = state.adding === cls ? null : cls; refreshButtons(); });
    return b;
  }));
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
  document.addEventListener("keydown", onKey);
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", () => state.house && drawAll());
  setInterval(() => {
    if (state.house) $("timer").textContent = `${Math.round((performance.now() - state.openedAt) / 1000)} с`;
  }, 1000);
  route();
}

boot().catch((err) => toast(err.message, "error"));
