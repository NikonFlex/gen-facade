// Общее для страниц смотрелки: узел с атрибутами и всплывающая подсказка.
export const $ = (id) => document.getElementById(id);

export function el(tag, attrs = {}, text = "") {
  const node = Object.assign(document.createElement(tag), attrs);
  if (text) node.textContent = text;
  return node;
}

export function toast(text, kind = "") {
  const node = el("div", { className: `toast ${kind}` }, text);
  $("toasts").append(node);
  setTimeout(() => node.remove(), kind === "error" ? 7000 : 2000);
}
