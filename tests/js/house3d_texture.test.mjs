// Размеры и развёртка текстур дома объёмом (static/house3d_texture.js, gf#353).
import assert from "node:assert/strict";
import { test } from "node:test";

import { faceUV, pixels, wallScale, worldUV } from "../../genfacade/viewer/static/house3d_texture.js";

const HOUSE = [[10, 3.25], [5, 3.25], [10, 3.25], [5, 3.25]];

test("wallScale: простой дом идёт желаемым шагом, пока влезает", () => {
  assert.equal(wallScale(HOUSE, 200, 4096, 8e6), 200);
});

test("wallScale: длинная стена не шире MAX_TEXTURE_SIZE", () => {
  const scale = wallScale([[30, 3], [10, 3]], 200, 4096, 1e9);
  assert.ok(30 * scale <= 4096 + 1e-9);
  assert.ok(Math.abs(30 * scale - 4096) < 1e-6);
});

test("wallScale: все стены вместе укладываются в бюджет пикселей", () => {
  const walls = [[16, 7], [16, 7], [12, 7], [12, 7]];
  const scale = wallScale(walls, 200, 8192, 8e6);
  const total = walls.reduce((s, [l, h]) => s + pixels(l, scale) * pixels(h, scale), 0);
  assert.ok(total <= 8e6 * 1.01, `${total} px`);
  assert.ok(scale < 200);
});

test("pixels: целое число, не меньше одного", () => {
  assert.equal(pixels(0.095, 200), 19);
  assert.equal(pixels(0.001, 200), 1);
});

test("worldUV: передняя грань — (x, y), верх — (x, z), торец — (z, y), в метрах", () => {
  // Три грани, по треугольнику: z = 2 (лицо), y = 3 (верх), x = 5 (торец)
  const tri = [
    1, 1, 2, 4, 1, 2, 1, 3, 2,
    1, 3, 1, 4, 3, 1, 1, 3, 4,
    5, 1, 1, 5, 1, 3, 5, 4, 1,
  ];
  assert.deepEqual([...worldUV(new Float32Array(tri))], [
    1, 1, 4, 1, 1, 3,
    1, 1, 4, 1, 1, 4,
    1, 1, 3, 1, 1, 4,
  ]);
});

test("faceUV: скат 45° — v растёт вверх по скату в метрах ячейки, u — вдоль карниза", () => {
  // Скат над стороной z = 0: низ карниза y = 0, конёк y = 2 на z = −2 (дом уходит в −z). Длина по скату √8.
  const points = [[0, 0, 0], [4, 0, 0], [4, 2, -2], [0, 2, -2]];
  const uv = faceUV(points, [2, 0, -2], [2, 1]);
  const along = Math.hypot(2, 2);
  assert.ok(Math.abs(uv[3][1] - along) < 1e-9);
  assert.ok(Math.abs(uv[1][0] - 2) < 1e-9 && uv[0][0] === 0 && uv[0][1] === 0);
});

test("faceUV: u идёт вправо, если смотреть на грань снаружи — для двух противоположных скатов", () => {
  const front = faceUV([[0, 0, 0], [4, 0, 0], [4, 2, -2], [0, 2, -2]], [2, 0, -2], [1, 1]);
  const back = faceUV([[4, 0, -4], [0, 0, -4], [0, 2, -2], [4, 2, -2]], [2, 0, -2], [1, 1]);
  assert.ok(front[1][0] > front[0][0], "передний скат: вправо — к +x");
  assert.ok(back[1][0] > back[0][0], "задний скат: вправо — к −x, вершины идут туда же");
});

test("faceUV: вертикальная грань над карнизом — v это высота", () => {
  const uv = faceUV([[0, 3, 0], [4, 3, 0], [2, 5, 0]], [2, 0, -3], [1, 0.5]);
  assert.ok(Math.abs(uv[2][1] - 4) < 1e-9);
});
