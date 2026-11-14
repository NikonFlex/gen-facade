// Панель «что строит модуль» на странице правки (gf#470): лист фасадов и 3D дома, собранные
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
    this.sheetUrl = null;
    this.sheet = el("div", { className: "mk-sheet" });
    this.house = el("div", { className: "mk-stage" });
    root.style.setProperty("--build-h", `${options.build_height_px}px`);
    const { build_sheet: sheet, build_house: house } = options.labels;
    root.replaceChildren(this._titled(sheet, this.sheet), this._titled(house, this.house));
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
    this.sheetUrl = URL.createObjectURL(new Blob([built.sheet], { type: "image/svg+xml" }));
    this.sheet.replaceChildren(el("img", { src: this.sheetUrl, alt: "" }));
    this.stage = new HouseStage(this.house, this.options.house3d);
    await this.stage.show(built.house3d, view);
  }

  refuse(text) {
    this._drop();
    for (const box of [this.sheet, this.house]) {
      box.replaceChildren(el("p", { className: "empty-note" }, text));
    }
  }

  _drop() {
    this.stage?.dispose();
    if (this.sheetUrl) URL.revokeObjectURL(this.sheetUrl);
    this.stage = this.sheetUrl = null;
  }
}
