// Слепая проверка листов глазами (gf#268). Дом за домом: настоящий лист и листы строк на местах
// A, B, C… — чья строка на каком месте, страница не знает (сервер её не отдаёт). Отметка
// сохраняется сразу; открытый дом — в адресе (#i=…), перезагрузка его сохраняет.

const $ = (id) => document.getElementById(id);
const LETTERS = "ABCDEFGH";
const state = { items: [], at: 0, modes: {} };

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

async function sheetInto(box, url) {
  const res = await fetch(url);
  if (res.ok) {
    box.replaceChildren(el("img", { src: url, alt: "" }));
    return;
  }
  const detail = (await res.json()).detail ?? res.statusText;
  box.replaceChildren(el("div", { className: "review-refusal" }, `Нет листа: ${detail}`));
}

async function save(item, slot, mark) {
  const res = await fetch(`${base(item)}/${slot}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(mark),
  });
  if (!res.ok) return toast(`Не сохранено: ${(await res.json()).detail}`, "error");
  item.marks[slot] = mark;
  progress();
}

function slotPanel(item, slot) {
  const panel = el("section", { className: "review-slot" });
  const box = el("div", { className: "review-sheet" });
  const why = el("input", { placeholder: "почему не годен (необязательно)", value: item.marks[slot]?.why ?? "" });
  const ok = el("button", { className: "btn", type: "button" }, "Годен");
  const bad = el("button", { className: "btn", type: "button" }, "Не годен");
  const paint = () => {
    const mark = item.marks[slot];
    panel.classList.toggle("ok", mark?.ok === true);
    panel.classList.toggle("bad", mark?.ok === false);
    ok.classList.toggle("on-ok", mark?.ok === true);
    bad.classList.toggle("on-bad", mark?.ok === false);
  };
  const put = (value) => save(item, slot, { ok: value, why: why.value }).then(paint);
  ok.addEventListener("click", () => put(true));
  bad.addEventListener("click", () => put(false));
  why.addEventListener("change", () => { if (item.marks[slot]) put(item.marks[slot].ok); });
  const row = el("div", { className: "review-mark" });
  row.append(ok, bad, why);
  panel.append(el("h3", {}, `Вариант ${LETTERS[slot]}`), box, row);
  paint();
  sheetInto(box, `${base(item)}/${slot}/sheet.svg`);
  return panel;
}

function show(at) {
  if (!state.items.length) return;
  state.at = (at + state.items.length) % state.items.length;
  history.replaceState(null, "", `#i=${state.at}`);
  const item = state.items[state.at];
  $("title").textContent = `${item.house} · ${state.modes[item.mode] ?? item.mode}`;
  sheetInto($("ref"), `${base(item)}/ref/sheet.svg`);
  $("slots").replaceChildren(...Array.from({ length: item.slots }, (_, s) => slotPanel(item, s)));
  progress();
  window.scrollTo(0, 0);
}

function progress() {
  const full = state.items.filter(done).length;
  $("progress").textContent = `дом ${state.at + 1} из ${state.items.length} · отмечено полностью ${full}`;
}

function nextOpen() {
  const n = state.items.length;
  const found = Array.from({ length: n }, (_, k) => (state.at + 1 + k) % n).find((i) => !done(state.items[i]));
  if (found === undefined) return toast("Всё отмечено — спасибо!");
  show(found);
}

async function start() {
  const [data, options] = await Promise.all([
    fetch("/api/review").then((r) => r.json()), fetch("/api/options").then((r) => r.json()),
  ]);
  state.modes = Object.fromEntries(options.modes.map((m) => [m.value, m.title]));
  if (!data.folder) {
    $("title").textContent = "Проверка не включена: genfacade serve --review <папка realtest>";
    return;
  }
  state.items = data.items;
  const at = Number(new URLSearchParams(location.hash.slice(1)).get("i") ?? 0);
  show(Number.isFinite(at) ? at : 0);
}

$("prev").addEventListener("click", () => show(state.at - 1));
$("next").addEventListener("click", () => show(state.at + 1));
$("next-open").addEventListener("click", nextOpen);
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "ArrowLeft") show(state.at - 1);
  if (e.key === "ArrowRight") show(state.at + 1);
});
start();
