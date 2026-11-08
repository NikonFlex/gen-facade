// Рамки страницы правки (static/markup_geom.js, gf#348): сдвиг, растяжение, касание, удаление.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  boxAt, isTap, moveBox, pick, removeElement, resizeBox, setClass,
} from "../../genfacade/viewer/static/markup_geom.js";

test("сдвиг переносит рамку целиком", () => {
  assert.deepEqual(moveBox([10, 20, 50, 80], 5, -10), [15, 10, 55, 70]);
});

test("ручка se двигает правый и нижний край, остальные стоят", () => {
  assert.deepEqual(resizeBox([10, 20, 50, 80], "se", 5, 7), [10, 20, 55, 87]);
});

test("ручка w двигает только левый край", () => {
  assert.deepEqual(resizeBox([10, 20, 50, 80], "w", -4, 99), [6, 20, 50, 80]);
});

test("протянутая через противоположный край рамка переворачивается", () => {
  assert.deepEqual(resizeBox([10, 20, 50, 80], "e", -60, 0), [-10, 20, 10, 80]);
});

test("рамка от касания стоит центром в точке и в метрах вида", () => {
  assert.deepEqual(boxAt([100, 200], [1.2, 1.4], 100), [40, 130, 160, 270]);
});

test("касание — рамка меньше порога по обеим сторонам", () => {
  assert.equal(isTap([5, 5, 7, 7], 10), true);
  assert.equal(isTap([5, 5, 7, 50], 10), false);
});

test("удаление сдвигает родителей и обнуляет потерянного", () => {
  const list = [
    { cls: "window", box: [0, 0, 1, 1], parent: null },
    { cls: "blind", box: [0, 0, 1, 1], parent: 0 },
    { cls: "window", box: [0, 0, 1, 1], parent: null },
    { cls: "sill", box: [0, 0, 1, 1], parent: 2 },
  ];
  const got = removeElement(list, 0);
  assert.deepEqual(got.map((e) => e.parent), [null, null, 1]);
});

test("смена класса сбрасывает вид, тот же класс — нет", () => {
  const door = { cls: "door", box: [0, 0, 1, 1], variant: { kind: "glazed" } };
  assert.equal(setClass(door, "door"), door);
  assert.equal(setClass(door, "window").variant, null);
});

test("под точкой выбирается меньшая из рамок", () => {
  const list = [{ box: [0, 0, 100, 100] }, { box: [40, 40, 60, 60] }];
  assert.equal(pick(list, [50, 50]), 1);
  assert.equal(pick(list, [10, 10]), 0);
  assert.equal(pick(list, [200, 200]), -1);
});
