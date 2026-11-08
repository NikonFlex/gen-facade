// Страница «Данные» (gf#356): на каком датасете учим. Числа, доли и подписи считает сервер
// (GET /api/data); страница рисует наборы по порядку обучения и открывает пример листом и 3D.

import { $, el } from "/static/dom.js";

const TEXT = {
  title: "Данные", sub: "датасет, на котором учим и проверяем",
  houses: "домов", walls: "стен", blindWalls: "из них глухих", sample: "доли по выборке из {n} домов",
  rejected: "Почему дома не вошли в набор", origins: "Дома по источникам разметки",
  source: "Источник", marked: "Размечено", built: "Собрано", waiting: "Ждут",
  examples: "Примеры", empty: "Примеров пока нет — появятся после сборки датасета.",
  date: "опись на", elements: "Элементов на стенах",
};
const PERCENT = new Intl.NumberFormat("ru-RU", { style: "percent", maximumFractionDigits: 0 });
const DATE = (iso) => new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short" });

export async function showData({ api, options, openSample }) {
  const data = await api("/api/data");
  const root = $("samples");
  const head = el("div", { className: "page-head" });
  head.append(el("h1", {}, TEXT.title), el("span", { className: "count" }, TEXT.sub));
  root.replaceChildren(head, ...(data.sets.length ? data.sets.map((s) => dataset(s, data.attrs, options, openSample)) : [el("p", { className: "empty-note" }, TEXT.empty)]));
}

function dataset(s, attrs, options, openSample) {
  const box = el("section", { className: "panel data-set" });
  const title = el("h2", { id: `data-${s.source}` }, s.title);
  box.setAttribute("aria-labelledby", title.id);
  const head = el("div", { className: "panel-head" });
  head.append(title, el("span", { className: "chip" }, `${TEXT.date} ${DATE(s.date)}`));
  const body = el("div", { className: "panel-body" });
  body.append(el("p", { className: "data-note" }, s.note), stats(s));
  if (s.shares) body.append(shares(s.shares, attrs));
  if (s.rejected) body.append(table(TEXT.rejected, [["", "Причина"], ["num", "Домов"]], Object.entries(s.rejected).map(([k, n]) => [k, n])));
  if (s.origins) body.append(table(TEXT.origins, [["", TEXT.source], ["num", TEXT.marked], ["num", TEXT.built], ["num", TEXT.waiting]], s.origins.map((o) => [o.name, o.marked, o.built, o.waiting])));
  body.append(el("h3", { className: "eyebrow" }, TEXT.examples), examples(s, options, openSample));
  box.append(head, body);
  return box;
}

function stats(s) {
  const tiles = [[TEXT.houses, s.samples], [TEXT.walls, s.walls], [TEXT.blindWalls, s.blind_walls],
    ...Object.entries(s.splits).map(([k, n]) => [k, n])];
  const box = el("div", { className: "stats" });
  box.append(...tiles.map(([label, value]) => {
    const tile = el("div", { className: "stat" });
    tile.append(el("div", { className: "label" }, label), el("div", { className: "value" }, value.toLocaleString("ru-RU")));
    return tile;
  }));
  return box;
}

function shares(found, attrs) {
  const box = el("div", { className: "shares" });
  box.append(el("p", { className: "data-note" }, TEXT.sample.replace("{n}", found.of)));
  const grid = el("div", { className: "share-grid" });
  grid.append(...Object.entries(found.attrs).map(([attr, rows]) => {
    const card = el("section", { className: "share" });
    card.append(el("h3", {}, attrs[attr]));
    const list = el("ul", { className: "bars" });
    list.append(...rows.map((r) => {
      const li = el("li");
      const bar = el("span", { className: "bar" });
      bar.style.setProperty("--share", `${(r.share * 100).toFixed(1)}%`);
      li.append(el("span", { className: "bar-label" }, r.label), bar, el("span", { className: "bar-n" }, PERCENT.format(r.share)));
      return li;
    }));
    card.append(list);
    return card;
  }));
  box.append(grid);
  return box;
}

function table(title, columns, rows) {
  const wrap = el("div", { className: "data-table" });
  const t = el("table", { className: "table" });
  const caption = el("caption", { className: "eyebrow" }, title);
  const head = el("tr");
  head.append(...columns.map(([cls, text]) => el("th", { scope: "col", className: cls }, text)));
  const thead = el("thead"), tbody = el("tbody");
  thead.append(head);
  tbody.append(...rows.map((row) => {
    const tr = el("tr");
    tr.append(...row.map((cell, i) => el("td", { className: columns[i][0] }, String(cell))));
    return tr;
  }));
  t.append(caption, thead, tbody);
  wrap.append(t);
  return wrap;
}

function examples(s, options, openSample) {
  const grid = el("ul", { className: "cards" });
  grid.append(...s.examples.map((id) => {
    const url = `/api/samples/${s.source}/${encodeURIComponent(id)}`;
    const li = el("li"), btn = el("button", { type: "button", className: "card", title: `${s.source}/${id}` });
    const thumb = el("div", { className: "card-thumb" });
    thumb.append(el("img", { src: `${url}/sheet.svg`, alt: "" }));
    const body = el("div", { className: "card-body" }), titleRow = el("div", { className: "card-title" });
    titleRow.append(el("h3", {}, id));
    body.append(titleRow);
    btn.append(thumb, body);
    btn.addEventListener("click", () => openSample(url, btn));
    li.append(btn);
    return li;
  }));
  return grid;
}
