// Страница «Правила» (gf#356): правило, его число, где оно держится, источник и картинки «так / не
// так». Всё — из GET /api/rules; число и картинки считает сервер (viewer/rules.py).

import { $, el } from "/static/dom.js";
import { refusedFrom } from "/static/refusal.js";
import { topbar } from "/static/shell.js";

const TEXT = {
  holds: "Держится", sources: "Источники", rule: "Правило свода",
  checked: "цитата найдена в тексте источника", count: "правил",
};
const NUMBER = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 });

function picture(rule, image) {
  const fig = el("figure", { className: image.good ? "pic is-good" : "pic is-bad" });
  fig.append(el("img", { src: image.url, alt: `${image.caption}: ${rule.title}`, loading: "lazy" }), el("figcaption", {}, image.caption));
  return fig;
}

function sources(list) {
  if (!list.length) return null;
  const box = el("details", { className: "sources" });
  box.append(el("summary", {}, `${TEXT.sources} (${list.length})`));
  const ul = el("ul");
  ul.append(...list.map((s) => {
    const li = el("li");
    li.append(el("b", {}, `${s.doc}, ${s.where}`), el("blockquote", {}, s.quote));
    return li;
  }));
  box.append(ul);
  return box;
}

function card(rule) {
  const li = el("li", { className: "panel rule" });
  const info = el("div", { className: "rule-info" });
  const head = el("div", { className: "rule-head" });
  head.append(el("h2", {}, rule.title));
  const number = el("p", { className: "rule-number" });
  number.append(el("b", {}, NUMBER.format(rule.value)), ` ${rule.unit}`);
  info.append(head, number, el("p", { className: "rule-text" }, rule.text));
  const facts = el("dl", { className: "facts" });
  facts.append(el("dt", {}, TEXT.holds), el("dd", {}, rule.holds));
  if (rule.rule) facts.append(el("dt", {}, TEXT.rule), el("dd", {}, rule.rule));
  info.append(facts);
  const src = sources(rule.sources);
  if (src) info.append(src);
  const pics = el("div", { className: "pics" });
  pics.append(...rule.images.map((image) => picture(rule, image)));
  li.append(info, pics);
  return li;
}

async function init() {
  topbar($("topbar"), "rules");
  const res = await fetch("/api/rules");
  if (!res.ok) throw await refusedFrom(res);
  const rules = await res.json();
  $("count").textContent = `${rules.length} ${TEXT.count}`;
  $("rules").replaceChildren(...rules.map(card));
}

init().catch((err) => $("rules").replaceChildren(el("li", { className: "empty-note" }, err.message)));
