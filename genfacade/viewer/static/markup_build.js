// Панель «что строит модуль» на странице правки (gf#470): лист фасадов, 3D и входной план дома, собранные
// сервером из разметки с несохранёнными правками (POST /api/markup/<дом>/build). Сборку страница
// не считает — рисует ответ; отказ сборщика показывает его текстом на месте листа и 3D.

import { el } from "/static/dom.js";
import { HouseStage } from "/static/house3d.js";

export class BuildPanel {
  // options — ответ /api/markup: подписи, высота панели и вид сцены (house3d) из viewer.toml.
  constructor(root, options) {
    this.root = root;
    this.options = options;
    this.stage = null;
    this.urls = [];
    this.sheet = el("div", { className: "mk-sheet" });
    this.house = el("div", { className: "mk-stage" });
    this.plan = el("div", { className: "mk-plan" });
    this.source = el("div", { className: "mk-plan-source" });
    root.style.setProperty("--build-h", `${options.build_height_px}px`);
    const { build_sheet: sheet, build_house: house, build_plan: plan } = options.labels;
    const planBox = el("div", { className: "mk-plans" }, "");
    planBox.append(this.plan, this.source);
    root.replaceChildren(this._titled(sheet, this.sheet), this._titled(house, this.house),
      this._titled(plan, planBox));
    this.wait();
  }

  _titled(title, box) {
    const part = el("section", { className: "mk-build-part" }, "");
    part.append(el("h3", {}, title), box);
    return part;
  }

  wait() {
    this.refuse(this.options.labels.build_wait);
  }

  async show(built) {
    const view = this.stage?.view;
    this._drop();
    this.urls = [built.sheet, built.plan].map((svg) =>
      URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" })));
    this.sheet.replaceChildren(el("img", { src: this.urls[0], alt: "" }));
    this.plan.replaceChildren(el("img", { src: this.urls[1], alt: "" }));
    this.source.replaceChildren(el("img", { src: built.source_plan, alt: "" }),
      el("small", {}, this.options.labels.build_source_plan));
    this.stage = new HouseStage(this.house, this.options.house3d);
    await this.stage.show(built.house3d, view);
  }

  refuse(text) {
    this._drop();
    for (const box of [this.sheet, this.house, this.plan]) {
      box.replaceChildren(el("p", { className: "empty-note" }, text));
    }
  }

  _drop() {
    this.stage?.dispose();
    this.urls.forEach((u) => URL.revokeObjectURL(u));
    this.stage = null;
    this.urls = [];
    this.source.replaceChildren();
  }
}
