// Шапка всех страниц смотрелки (gf#356): марка, вкладки разделов и «Новый дом». Список разделов —
// только здесь; страница вызывает topbar(узел, раздел) и не держит своей копии навигации.
// Вкладки одной страницы (Дома, Новый дом и Данные — index.html) она перехватывает сама по data-page.

const HOUSE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/></svg>';
const PLUS_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

export const NAV = [
  { page: "houses", href: "/", title: "Дома" },
  { page: "catalog", href: "/catalog", title: "Каталог" },
  { page: "data", href: "/#datasets", title: "Данные" },
  { page: "markup", href: "/markup", title: "Разметка" },
  { page: "review", href: "/review", title: "Проверка" },
];
export const NEW_HOUSE = { page: "new", href: "/#new", title: "Новый дом" };

export function topbar(node, current) {
  node.classList.add("topbar");
  node.innerHTML = `
    <a class="brand" href="/" data-page="houses" aria-label="GenFacade — все дома">
      <span class="brand-mark">${HOUSE_ICON}</span><span class="brand-name">GenFacade</span>
    </a>
    <nav class="tabs" aria-label="Разделы">
      ${NAV.map((n) => `<a href="${n.href}" data-page="${n.page}">${n.title}</a>`).join("")}
    </nav>
    <div class="topbar-end">
      <a class="btn primary" href="${NEW_HOUSE.href}" data-page="${NEW_HOUSE.page}">${PLUS_ICON}<span class="label">${NEW_HOUSE.title}</span></a>
    </div>`;
  markCurrent(node, current);
}

// Текущий раздел — aria-current: его видит и экранный диктор, и тема (.tabs a[aria-current]).
export function markCurrent(node, current) {
  for (const link of node.querySelectorAll("[data-page]")) {
    if (link.dataset.page === current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}
