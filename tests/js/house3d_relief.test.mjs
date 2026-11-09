// Выступы стены в 3D (static/house3d_relief.js, gf#414): крыльцо и козырёк у края стены не
// заходят за угол; цоколь и карниз — заходят, чтобы профиль на углу не рвался.
import assert from "node:assert/strict";
import { test } from "node:test";

import { Relief } from "../../genfacade/viewer/static/house3d_relief.js";

// Без three.js: геометрия — запись того, что просили построить (границы вдоль стены).
const THREE = {
  BoxGeometry: class { constructor(w) { this.w = w; } translate(x) { this.x = x; return this; } },
};
const look = { plinth_wash_m: 0.05, slope_edge: 0.6, tread_m: 0.3, cornice_steps: [[1, 0]] };
const relief = new Relief(THREE, look, {});
relief._extrudeX = (profile, x0, x1) => ({ x0, x1 });
const wall = { length_m: 4, convex_left: true };
const at = (cls, extra) => ({ cls, x0: 0, x1: 4, y0: 0, y1: 1, depth: 0.5, steps: 2, ...extra });

for (const [cls, extra] of [["porch", {}], ["canopy", { shape: "slab" }]]) {
  test(`${cls} у левого края выпуклого угла начинается на краю стены`, () => {
    const [g] = relief.geometries(at(cls, extra), wall);
    assert.equal(g.x0, 0);
    assert.equal(g.x1, 4);
  });
}

test("цоколь у левого края выпуклого угла выходит за угол на свой вынос", () => {
  const [g] = relief.geometries({ ...at("plinth"), role: "plinth", cls: null }, wall);
  assert.equal(g.x0, -0.5);
});
