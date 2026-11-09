// Страница «Данные» (gf#356): на чём учим и проверяем. Числа, доли и подписи считает сервер
// (GET /api/data); у каждого набора плашка одной формы, несколько примеров и «Все примеры» —
// порциями по прокрутке (GET /api/data/<набор>/samples). Фильтр и поиск живут в адресе: #datasets&set=…&split=…&q=…

import { $, el } from "/static/dom.js";
import { createFeed, Phase } from "/static/feed.js";
import { query as apiQuery } from "/static/query.js";

const FEED_MARGIN = "100%"; // запас часового: подгрузка начинается за экран до конца списка

const TEXT = {
  title: "Данные", sub: "на чём учим и проверяем модель шага 4",
  houses: "Домов", walls: "Стен", blindWalls: "Глухих стен", elements: "Элементов", splits: "Разбиение",
  sample: "доли по выборке из {n} домов", none: "—",
  facts: [["note", "Что это"], ["origin", "Откуда"], ["how", "Как участвует"], ["modes", "Режимы"]],
  rejected: "Почему дома не вошли в набор", reason: "Причина", houses_n: "Домов",
  origins: "Дома по источникам разметки", source: "Источник", marked: "Размечено", built: "Собрано", waiting: "Ждут",
  examples: "Примеры", all: "Все примеры", allN: "Все примеры ({n})", back: "К данным",
  empty: "Примеров пока нет — появятся после сборки датасета.",
  date: "опись на", listSub: "{n} примеров", noMatch: "По этому фильтру примеров нет.",
  allSplits: "Все", split: "Разбиение", search: "Имя дома", searchGo: "Найти",
  allShown: "Все {n} показаны", loading: "Загружаю…", loadFailed: "Не удалось загрузить", retry: "Ещё раз",
};
const PERCENT = new Intl.NumberFormat("ru-RU", { style: "percent", maximumFractionDigits: 0 });
const NUMBER = new Intl.NumberFormat("ru-RU");
const DATE = (iso) => new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short" });
const count = (n) => (n == null ? TEXT.none : NUMBER.format(n));
const sampleUrl = (source, id) => `/api/samples/${source}/${encodeURIComponent(id)}`;

export async function showData(ctx) {
  stopFeed();
  const params = new URLSearchParams(location.hash.slice(1));
  params.delete("datasets");
  const view = params.get("set") ? await listPage(ctx, params) : await overviewPage(ctx);
  $("samples").replaceChildren(...view);
  window.scrollTo(0, 0);
}

// Адрес страницы данных: набор, разбиение и поиск; пустое не пишется. Номера порции в адресе нет: прокрутка начинается сверху.
function dataHash(fields = {}) {
  const rest = new URLSearchParams(Object.entries(fields).filter(([, value]) => value)).toString();
  return rest ? `#datasets&${rest}` : "#datasets";
}

function navigate(ctx, fields) {
  history.pushState(null, "", dataHash(fields));
  return showData(ctx);
}

function pageHead(title, sub) {
  const head = el("div", { className: "page-head" });
  head.append(el("h1", {}, title), el("span", { className: "count" }, sub));
  return head;
}

// ——— обзор: плашка набора, несколько примеров, кнопка «Все примеры» ———

async function overviewPage(ctx) {
  const data = await ctx.api("/api/data");
  const sets = data.sets.map((s) => dataset(s, data.attrs, ctx));
  return [pageHead(TEXT.title, TEXT.sub), ...(sets.length ? sets : [el("p", { className: "empty-note" }, TEXT.empty)])];
}

function dataset(s, attrs, ctx) {
  const box = el("section", { className: "panel data-set" });
  const title = el("h2", { id: `data-${s.source}` }, s.title);
  box.setAttribute("aria-labelledby", title.id);
  const head = el("div", { className: "panel-head" });
  head.append(title, el("span", { className: "chip accent" }, s.role_title), el("span", { className: "chip" }, s.date ? `${TEXT.date} ${DATE(s.date)}` : TEXT.none));
  const body = el("div", { className: "panel-body" });
  body.append(facts(s), stats(s), shares(s.shares, attrs));
  if (s.rejected) body.append(table(TEXT.rejected, [["", TEXT.reason], ["num", TEXT.houses_n]], Object.entries(s.rejected)));
  if (s.origins) body.append(table(TEXT.origins, [["", TEXT.source], ["num", TEXT.marked], ["num", TEXT.built], ["num", TEXT.waiting]], s.origins.map((o) => [o.name, o.marked, o.built, o.waiting])));
  body.append(examplesHead(s, ctx), examples(s, ctx));
  box.append(head, body);
  return box;
}

function facts(s) {
  const list = el("dl", { className: "facts" });
  for (const [key, label] of TEXT.facts) list.append(el("dt", {}, label), el("dd", {}, s[key] || TEXT.none));
  return list;
}

function stats(s) {
  const splits = Object.entries(s.splits);
  const tiles = [[TEXT.houses, count(s.samples)], [TEXT.walls, count(s.walls)], [TEXT.blindWalls, count(s.blind_walls)],
    [TEXT.elements, count(s.elements)], ...(splits.length ? splits.map(([k, n]) => [k, count(n)]) : [[TEXT.splits, TEXT.none]])];
  const box = el("div", { className: "stats" });
  box.append(...tiles.map(([label, value]) => {
    const tile = el("div", { className: "stat" });
    tile.append(el("div", { className: "label" }, label), el("div", { className: "value" }, value));
    return tile;
  }));
  return box;
}

function shares(found, attrs) {
  const box = el("div", { className: "shares" });
  box.append(el("p", { className: "data-note" }, TEXT.sample.replace("{n}", found.of)));
  const grid = el("div", { className: "share-grid" });
  grid.append(...Object.entries(attrs).map(([attr, title]) => shareCard(title, found.attrs[attr] ?? [])));
  box.append(grid);
  return box;
}

function shareCard(title, rows) {
  const card = el("section", { className: "share" });
  card.append(el("h3", {}, title));
  const list = el("ul", { className: "bars" });
  list.append(...(rows.length ? rows.map(shareRow) : [el("li", { className: "bar-none" }, TEXT.none)]));
  card.append(list);
  return card;
}

function shareRow(r) {
  const li = el("li");
  const bar = el("span", { className: "bar" });
  bar.style.setProperty("--share", `${(r.share * 100).toFixed(1)}%`);
  li.append(el("span", { className: "bar-label" }, r.label), bar, el("span", { className: "bar-n" }, PERCENT.format(r.share)));
  return li;
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

function examplesHead(s, ctx) {
  const row = el("div", { className: "data-examples-head" });
  const all = el("button", { type: "button", className: "btn" }, s.samples ? TEXT.allN.replace("{n}", count(s.samples)) : TEXT.all);
  all.addEventListener("click", () => navigate(ctx, { set: s.source }));
  row.append(el("h3", { className: "eyebrow" }, TEXT.examples), all);
  return row;
}

function examples(s, ctx) {
  const grid = el("ul", { className: "cards" });
  grid.append(...s.examples.map((id) => exampleCard(s.source, { id }, ctx)));
  return grid;
}

function exampleCard(source, item, ctx) {
  const url = sampleUrl(source, item.id);
  const li = el("li"), btn = el("button", { type: "button", className: "card", title: `${source}/${item.id}` });
  const thumb = el("div", { className: "card-thumb" });
  thumb.append(el("img", { src: `${url}/sheet.svg`, alt: "", loading: "lazy" }));
  const body = el("div", { className: "card-body" }), titleRow = el("div", { className: "card-title" });
  titleRow.append(el("h3", {}, item.id));
  if (item.split) titleRow.append(el("span", { className: "chip" }, item.split));
  body.append(titleRow);
  btn.append(thumb, body);
  btn.addEventListener("click", () => ctx.openSample(url, btn));
  li.append(btn);
  return li;
}

// ——— все примеры набора: прокруткой порциями, с фильтром по разбиению и поиском по имени ———

let stopFeed = () => {};

async function listPage(ctx, params) {
  const source = params.get("set");
  const fields = { set: source, split: params.get("split"), q: params.get("q") };
  let first = null;
  const feed = createFeed(async (page) => {
    const found = await ctx.api(`/api/data/${source}/samples?${apiQuery({ page, split: fields.split, q: fields.q })}`);
    first ??= found;
    return found;
  });
  await feed.more();
  if (feed.phase === Phase.ERROR) throw feed.error;
  const head = pageHead(first.title, TEXT.listSub.replace("{n}", count(first.total)));
  const back = el("button", { type: "button", className: "btn ghost" }, TEXT.back);
  back.addEventListener("click", () => navigate(ctx, {}));
  head.prepend(back);
  const cards = el("ul", { className: "cards data-list" }), foot = el("div", { className: "feed-foot" });
  const view = [head, listFilters(first, fields, ctx), cards, foot];
  if (!first.total) return [head, view[1], el("p", { className: "empty-note" }, TEXT.noMatch)];
  keepFeeding(feed, { cards, foot, source, total: first.total, ctx });
  return view;
}

// Карточки дописываются по мере порций; часовой внизу с запасом в экран просит следующую.
function keepFeeding(feed, { cards, foot, source, total, ctx }) {
  let shown = 0;
  const sentinel = el("div", { className: "feed-sentinel", "aria-hidden": "true" });
  const watcher = new IntersectionObserver((seen) => { if (seen.some((e) => e.isIntersecting)) feed.more(); },
    { rootMargin: `0px 0px ${FEED_MARGIN} 0px` });
  const draw = () => {
    cards.append(...feed.items.slice(shown).map((item) => exampleCard(source, item, ctx)));
    shown = feed.items.length;
    watcher.disconnect();
    if (feed.phase === Phase.DONE) foot.replaceChildren(el("p", { className: "feed-note" }, TEXT.allShown.replace("{n}", count(total))));
    else if (feed.phase === Phase.ERROR) foot.replaceChildren(feedError(feed));
    else foot.replaceChildren(...(feed.phase === Phase.LOADING ? [el("p", { className: "feed-note" }, TEXT.loading)] : []), sentinel);
    if (feed.phase === Phase.IDLE) watcher.observe(sentinel); // и когда часовой уже на экране: порция короче экрана
  };
  stopFeed();
  stopFeed = () => { watcher.disconnect(); feed.reset(); };
  feed.onChange = draw;
  draw();
}

function feedError(feed) {
  const retry = el("button", { type: "button", className: "btn" }, TEXT.retry);
  retry.addEventListener("click", () => feed.more());
  const box = el("div", { className: "feed-error", role: "alert" });
  box.append(el("span", {}, `${TEXT.loadFailed}: ${feed.error.message}`), retry);
  return box;
}

function listFilters(found, fields, ctx) {
  const box = el("div", { className: "filters data-filters", role: "group", "aria-label": TEXT.split });
  const group = el("div", { className: "filter-group" });
  const total = Object.values(found.splits).reduce((a, b) => a + b, 0);
  group.append(el("span", { className: "filter-label" }, TEXT.split), splitButton(TEXT.allSplits, total, "", fields, ctx),
    ...Object.entries(found.splits).map(([name, n]) => splitButton(name, n, name, fields, ctx)));
  box.append(group, searchForm(fields, ctx));
  return box;
}

function splitButton(label, n, value, fields, ctx) {
  const btn = el("button", { type: "button", className: "filter" }, label);
  btn.setAttribute("aria-pressed", String((fields.split || "") === value));
  btn.append(el("span", { className: "n" }, count(n)));
  btn.addEventListener("click", () => navigate(ctx, { ...fields, split: value }));
  return btn;
}

function searchForm(fields, ctx) {
  const form = el("form", { className: "data-search", role: "search" });
  const input = el("input", { type: "search", className: "input", placeholder: TEXT.search, value: fields.q || "", name: "q" });
  input.setAttribute("aria-label", TEXT.search);
  form.append(input, el("button", { type: "submit", className: "btn" }, TEXT.searchGo));
  form.addEventListener("submit", (e) => { e.preventDefault(); navigate(ctx, { ...fields, q: input.value.trim() }); });
  return form;
}
