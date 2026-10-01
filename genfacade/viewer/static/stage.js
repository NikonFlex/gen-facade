// Сцена с чертежом: SVG в shadow DOM (стили листа не смешиваются со страницей),
// масштаб колесом к курсору, сдвиг перетаскиванием, слои, карточка элемента.

const ZOOM_MIN = 0.5, ZOOM_MAX = 40; // относительно «вписать»

let stageCss = null;

export const metres = (v) =>
  `${Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} м`;

export class SvgStage {
  // labels — подписи к классам, ролям и типам окон с сервера (/api/options).
  constructor(container, { tooltip, onZoom, labels }) {
    this.labels = labels;
    this.host = document.createElement("div");
    this.host.className = "canvas";
    container.append(this.host);
    this.root = this.host.attachShadow({ mode: "open" });
    this.tooltip = tooltip;
    this.onZoom = onZoom;
    this._bindPointer();
  }

  async load(url) {
    stageCss ??= await (await fetch("/static/stage.css")).text();
    const text = await (await fetch(url)).text();
    this.root.innerHTML = `<style>${stageCss}</style>${text}`;
    this.svg = this.root.querySelector("svg");
    this.svg.removeAttribute("width");
    this.svg.removeAttribute("height");
    const [x, y, w, h] = this.svg.getAttribute("viewBox").split(/\s+/).map(Number);
    this.home = { x, y, w, h };
    this.fit();
  }

  fit() {
    this.vb = { ...this.home };
    this._apply();
  }

  zoomBy(factor, clientX, clientY) {
    const rect = this.host.getBoundingClientRect();
    const p = this._toSvg(clientX ?? rect.left + rect.width / 2, clientY ?? rect.top + rect.height / 2);
    const scale = this.home.w / (this.vb.w * factor);
    if (scale < ZOOM_MIN || scale > ZOOM_MAX) return;
    this.vb = {
      x: p.x - (p.x - this.vb.x) * factor, y: p.y - (p.y - this.vb.y) * factor,
      w: this.vb.w * factor, h: this.vb.h * factor,
    };
    this._apply();
  }

  setLayer(name, visible) {
    this.host.classList.toggle(`no-${name}`, !visible);
  }

  _apply() {
    const { x, y, w, h } = this.vb;
    this.svg.setAttribute("viewBox", `${x} ${y} ${w} ${h}`);
    this.onZoom?.(Math.round((this.home.w / w) * 100));
  }

  _toSvg(clientX, clientY) {
    const pt = this.svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    return pt.matrixTransform(this.svg.getScreenCTM().inverse());
  }

  _bindPointer() {
    this.host.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.zoomBy(Math.exp(e.deltaY * 0.0015), e.clientX, e.clientY);
    }, { passive: false });
    this.host.addEventListener("dblclick", () => this.fit());
    this.host.addEventListener("pointerdown", (e) => this._dragStart(e));
    this.root.addEventListener("pointermove", (e) => this._hover(e));
    this.root.addEventListener("pointerleave", () => this._hover(null));
  }

  _dragStart(e) {
    if (e.button !== 0 || !this.svg) return;
    const start = { x: e.clientX, y: e.clientY, vb: { ...this.vb }, k: this.svg.getScreenCTM().a };
    this.host.setPointerCapture(e.pointerId);
    this.host.classList.add("dragging");
    const move = (ev) => {
      this.vb = { ...start.vb, x: start.vb.x - (ev.clientX - start.x) / start.k,
                  y: start.vb.y - (ev.clientY - start.y) / start.k };
      this._apply();
    };
    const up = () => {
      this.host.classList.remove("dragging");
      this.host.removeEventListener("pointermove", move);
    };
    this.host.addEventListener("pointermove", move);
    this.host.addEventListener("pointerup", up, { once: true });
  }

  _hover(e) {
    const target = e && !this.host.classList.contains("dragging")
      ? e.target.closest?.("[data-cls],[data-role]") : null;
    if (target !== this.current) {
      this.current?.classList.remove("hl");
      target?.classList.add("hl");
      this.current = target;
    }
    if (!target) { this.tooltip.hidden = true; return; }
    this.tooltip.innerHTML = (target.dataset.cls ? elementCard : zoneCard)(target, this.labels);
    this.tooltip.hidden = false;
    placeTooltip(this.tooltip, e.clientX, e.clientY);
  }
}

function row(label, value) {
  return value == null ? "" : `<div class="tt-row"><span>${label}</span><b>${value}</b></div>`;
}

function swatch(color) {
  return color ? `<span class="swatch" style="background:${color}"></span>` : "";
}

function elementCard(el, labels) {
  const d = el.dataset;
  const [kind, cols, rows] = (d.variant ?? "").split(":");
  // Свой stroke лист пишет только окну с материалом: рама — цвет материала, заливка — стекло.
  const color = el.getAttribute("stroke") ?? el.getAttribute("fill");
  return `<div class="tt-title">${swatch(color)}${labels.cls[d.cls] ?? d.cls}<span class="tt-id">${d.id}</span></div>`
    + row("Размер", `${metres(el.getAttribute("width"))} × ${metres(el.getAttribute("height"))}`)
    + row("Слева · снизу", `${metres(el.getAttribute("x"))} · ${metres(el.getAttribute("y"))}`)
    + row("Этаж", d.floor)
    + row("Тип", kind ? `${labels.variant[kind] ?? kind}${cols > 1 || rows > 1 ? `, ${cols}×${rows}` : ""}` : null)
    + row("Материал", d.material)
    + row("Внутри", d.parent)
    + row("Задано планом", d.fixed);
}

function zoneCard(el, labels) {
  const d = el.dataset;
  return `<div class="tt-title">${swatch(el.getAttribute("fill"))}${labels.role[d.role] ?? d.role}</div>`
    + row("Материал", d.material);
}

function placeTooltip(tip, x, y) {
  const pad = 14, { innerWidth: W, innerHeight: H } = window;
  const r = tip.getBoundingClientRect();
  tip.style.left = `${Math.min(x + pad, W - r.width - 8)}px`;
  tip.style.top = `${y + pad + r.height > H ? y - r.height - pad : y + pad}px`;
}
