// Каталог видов (gf#354): страница получает разделы и виды с сервера и рисует их как есть —
// состава, подписей и картинок она не знает. Картинка — SVG тем же render/, что лист.

import { $, el } from "/static/dom.js";
import { refusedFrom } from "/static/refusal.js";
import { topbar } from "/static/shell.js";

topbar(document.getElementById("topbar"), "catalog");

const TEXT = {
  words: "В тексте:", shared: "Также называет общий вид:", source: "Источник", sectionWords: "Элемент в тексте:",
  none: "В конфиге нет видов", noImage: "Не нарисовать",
};

async function missing(box, url) {
  const res = await fetch(url);
  const why = res.ok ? TEXT.noImage : (await refusedFrom(res)).message;
  box.replaceChildren(el("div", { className: "miss" }, `${TEXT.noImage}: ${why}`));
}

function image(item) {
  const box = el("div", { className: "cat-image" });
  const img = el("img", { src: item.image, alt: item.title, loading: "lazy" });
  img.addEventListener("error", () => missing(box, item.image));
  box.append(img);
  return box;
}

function words(label, list, cls = "") {
  if (!list.length) return null;
  const box = el("div", { className: `cat-words ${cls}` }, label);
  for (const w of list) box.append(el("code", {}, w));
  return box;
}

function facts(list) {
  if (!list.length) return null;
  const dl = el("dl", { className: "cat-facts" });
  for (const f of list) dl.append(el("dt", {}, f.label), el("dd", {}, f.value));
  return dl;
}

function source(text) {
  if (!text) return null;
  const box = el("details", { className: "cat-source" });
  box.append(el("summary", {}, TEXT.source), el("p", {}, text));
  return box;
}

function card(item) {
  const node = el("article", { className: "cat-card" });
  node.dataset.search = [item.name, item.title, ...item.words, ...item.shared, ...item.facts.map((f) => f.value)]
    .join(" ").toLowerCase();
  node.append(image(item), el("h3", {}, item.title));
  const parts = [facts(item.facts), words(TEXT.words, item.words), words(TEXT.shared, item.shared, "shared"),
    source(item.source)];
  node.append(...parts.filter(Boolean));
  return node;
}

function grid(items) {
  const box = el("div", { className: "cat-grid" });
  box.append(...items.map(card));
  return box;
}

// Виды с группой (рисунок полотна двери, остекление) — под своими подзаголовками, в порядке сервера.
function groups(items) {
  const out = [];
  for (const item of items) {
    const last = out.at(-1);
    if (last && last.group === item.group) last.items.push(item);
    else out.push({ group: item.group, items: [item] });
  }
  return out;
}

function section(s) {
  const node = el("section", { className: "cat-section", id: s.id });
  const head = el("h2", {}, s.title);
  head.append(el("span", { className: "n" }, String(s.count)));
  node.append(head);
  if (s.note) node.append(el("p", { className: "cat-note" }, s.note));
  const w = words(TEXT.sectionWords, s.words);
  if (w) node.append(w);
  if (!s.items.length) node.append(el("p", { className: "cat-note" }, TEXT.none));
  for (const g of groups(s.items)) {
    if (g.group) node.append(el("div", { className: "cat-group" }, g.group));
    node.append(grid(g.items));
  }
  return node;
}

function nav(sections) {
  const box = $("nav");
  for (const s of sections) {
    const link = el("a", { href: `#${s.id}` }, s.title);
    link.append(el("span", { className: "n" }, String(s.count)));
    box.append(link);
  }
}

function filter() {
  const q = $("filter").value.trim().toLowerCase();
  for (const c of document.querySelectorAll(".cat-card")) c.hidden = !!q && !c.dataset.search.includes(q);
}

async function main() {
  const res = await fetch("/api/catalog");
  if (!res.ok) return ($("status").textContent = (await refusedFrom(res)).message);
  const { sections } = await res.json();
  nav(sections);
  $("catalog").replaceChildren(...sections.map(section));
  $("filter").addEventListener("input", filter);
  if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
}

main();
