// Слепая проверка листов глазами (gf#268). Дом за домом: настоящий дом и дома строк на местах
// A, B, C… — чья строка на каком месте, страница не знает (сервер её не отдаёт). По умолчанию —
// 3D-модели (хозяин 03.11), переключатель «Фасады» — чертежи. Отметка сохраняется сразу;
// открытый дом — в адресе (#i=…), вид — в localStorage.

import { HouseStage } from "/static/house3d.js";

const $ = (id) => document.getElementById(id);
const LETTERS = "ABCDEFGH";
const VIEW_KEY = "review.view";
const state = { items: [], at: 0, modes: {}, look: null, view: "3d", stages: [] };

function el(tag, attrs = {}, text = "") {
  const node = Object.assign(document.createElement(tag), attrs);
  if (text) node.textContent = text;
  return node;
}

function toast(text, kind = "") {
  const node = el("div", { className: `toast ${kind}` }, text);
  $("toasts").append(node);
  setTimeout(() => node.remove(), kind === "error" ? 7000 : 2000);
}

const base = (item) => `/api/review/${item.mode}/${encodeURIComponent(item.house)}`;
const marked = (item) => Object.values(item.marks).filter(Boolean).length;
const done = (item) => marked(item) === item.slots;
const refusal = (text) => el("div", { className: "review-refusal" }, text);

async function sheetInto(box, url) {
  const res = await fetch(url);
  if (res.ok) return box.replaceChildren(el("img", { src: url, alt: "" }));
  box.replaceChildren(refusal(`Нет листа: ${(await res.json()).detail ?? res.statusText}`));
}

async function houseInto(box, url) {
  const stage = new HouseStage(box, state.look);
  state.stages.push(stage);
  try {
    await stage.load(url);
  } catch (err) {
    box.replaceChildren(refusal(`Нет дома: ${err.message}`));
  }
}

function viewOf(item, slot) {
  const box = el("div", { className: `review-view ${state.view === "3d" ? "" : "sheet"}` });
  const url = `${base(item)}/${slot}/${state.view === "3d" ? "house3d" : "sheet.svg"}`;
  // 3D — после вставки в страницу: размер холста берётся из размера блока
  requestAnimationFrame(() => (state.view === "3d" ? houseInto(box, url) : sheetInto(box, url)));
  return box;
}

async function save(item, slot, mark) {
  const res = await fetch(`${base(item)}/${slot}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(mark),
  });
  if (!res.ok) return toast(`Не сохранено: ${(await res.json()).detail}`, "error");
  item.marks[slot] = mark;
  progress();
}

function slotCard(item, slot) {
  const card = el("section", { className: "review-card" });
  const why = el("input", { placeholder: "почему не годен", value: item.marks[slot]?.why ?? "" });
  const ok = el("button", { className: "btn", type: "button" }, "Годен");
  const bad = el("button", { className: "btn", type: "button" }, "Не годен");
  const paint = () => {
    const mark = item.marks[slot];
    card.classList.toggle("ok", mark?.ok === true);
    card.classList.toggle("bad", mark?.ok === false);
    ok.classList.toggle("on-ok", mark?.ok === true);
    bad.classList.toggle("on-bad", mark?.ok === false);
  };
  const put = (value) => save(item, slot, { ok: value, why: why.value }).then(paint);
  ok.addEventListener("click", () => put(true));
  bad.addEventListener("click", () => put(false));
  why.addEventListener("change", () => { if (item.marks[slot]) put(item.marks[slot].ok); });
  const row = el("div", { className: "review-mark" });
  row.append(ok, bad, why);
  card.append(el("h3", {}, `Вариант ${LETTERS[slot]}`), viewOf(item, slot), row);
  paint();
  return card;
}

function refCard(item) {
  const card = el("section", { className: "review-card ref" });
  card.append(el("h3", {}, "Настоящий дом"), viewOf(item, "ref"));
  return card;
}

function show(at) {
  if (!state.items.length) return;
  state.at = (at + state.items.length) % state.items.length;
  history.replaceState(null, "", `#i=${state.at}`);
  for (const stage of state.stages.splice(0)) stage.dispose();
  const item = state.items[state.at];
  $("title").textContent = `${item.house} · ${state.modes[item.mode] ?? item.mode}`;
  $("grid").replaceChildren(refCard(item),
    ...Array.from({ length: item.slots }, (_, s) => slotCard(item, s)));
  progress();
  window.scrollTo(0, 0);
}

function progress() {
  const full = state.items.filter(done).length;
  $("progress").textContent = `дом ${state.at + 1} из ${state.items.length} · отмечено ${full}`;
}

function nextOpen() {
  const n = state.items.length;
  const found = Array.from({ length: n }, (_, k) => (state.at + 1 + k) % n).find((i) => !done(state.items[i]));
  if (found === undefined) return toast("Всё отмечено — спасибо!");
  show(found);
}

function setView(view) {
  state.view = view;
  try { localStorage.setItem(VIEW_KEY, view); } catch { /* приватный режим */ }
  for (const b of document.querySelectorAll("[data-view]")) b.classList.toggle("active", b.dataset.view === view);
  show(state.at);
}

async function start() {
  const [data, options] = await Promise.all([
    fetch("/api/review").then((r) => r.json()), fetch("/api/options").then((r) => r.json()),
  ]);
  state.modes = Object.fromEntries(options.modes.map((m) => [m.value, m.title]));
  state.look = options.house3d;
  if (!data.folder) {
    $("title").textContent = "Проверка не включена: genfacade serve --review <папка realtest>";
    return;
  }
  state.items = data.items;
  const at = Number(new URLSearchParams(location.hash.slice(1)).get("i") ?? 0);
  state.at = Number.isFinite(at) ? at : 0;
  let saved = null;
  try { saved = localStorage.getItem(VIEW_KEY); } catch { /* приватный режим */ }
  setView(saved === "sheet" ? "sheet" : "3d");
}

$("prev").addEventListener("click", () => show(state.at - 1));
$("next").addEventListener("click", () => show(state.at + 1));
$("next-open").addEventListener("click", nextOpen);
for (const b of document.querySelectorAll("[data-view]")) b.addEventListener("click", () => setView(b.dataset.view));
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "ArrowLeft") show(state.at - 1);
  if (e.key === "ArrowRight") show(state.at + 1);
});
start();
