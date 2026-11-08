// Размеры и развёртка текстур дома объёмом (gf#353): чистые функции без three.js и DOM — тесты
// tests/js/house3d_texture.test.mjs. Рисунок материала — тот же, что на листе: размеры швов в
// метрах лежат в [patterns] конфига библиотеки, сюда они приходят уже в SVG-ячейке.

const FLAT = 1e-6;  // |n.y| меньше — грань вертикальная: у стены над карнизом нет «вверх по скату»

// Пикселей на метр у текстур стен: желаемые px_per_m, но чтобы длинная стена влезла в
// `maxSide` (MAX_TEXTURE_SIZE у телефона бывает 4096, а [house3d] ещё и ставит свой потолок) и
// все стены вместе — в `budgetPx` (память: 4 байта на пиксель). Один шаг на все стены — плотность
// рисунка на всех сторонах дома одна.
export function wallScale(walls, pxPerM, maxSide, budgetPx) {
  const longest = Math.max(...walls.map(([length, height]) => Math.max(length, height)));
  const area = walls.reduce((sum, [length, height]) => sum + length * height, 0);
  return Math.min(pxPerM, maxSide / longest, Math.sqrt(budgetPx / area));
}

// Размер текстуры в пикселях: целый, не меньше одного.
export function pixels(sizeM, pxPerM) {
  return Math.max(1, Math.round(sizeM * pxPerM));
}

// UV по метрам для граней выступов: каждый треугольник кладётся в плоскость, к которой он ближе
// всего (по нормали): передние и задние — (x, y), верх и низ — (x, z), торцы — (z, y); единица UV —
// метр, поэтому рисунок идёт тем же шагом, что на стене, на любой грани. `positions` —
// плоский массив xyz, треугольник — три подряд идущие вершины (индексы развернуты заранее).
export function worldUV(positions) {
  const uv = new Float32Array((positions.length / 3) * 2);
  for (let t = 0; t + 8 < positions.length; t += 9) {
    const e1 = [0, 1, 2].map((k) => positions[t + 3 + k] - positions[t + k]);
    const e2 = [0, 1, 2].map((k) => positions[t + 6 + k] - positions[t + k]);
    const n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
      .map(Math.abs);
    const [a, b] = n[2] >= n[0] && n[2] >= n[1] ? [0, 1] : n[1] >= n[0] ? [0, 2] : [2, 1];
    for (let v = 0; v < 3; v++) {
      uv[(t / 3 + v) * 2] = positions[t + v * 3 + a];
      uv[(t / 3 + v) * 2 + 1] = positions[t + v * 3 + b];
    }
  }
  return uv;
}

const sub = (p, q) => p.map((x, i) => x - q[i]);
const dot = (p, q) => p.reduce((s, x, i) => s + x * q[i], 0);
const cross = (p, q) => [p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0]];
const unit = (p) => p.map((x) => x / Math.hypot(...p));

// Нормаль грани наружу. Скат смотрит вверх; вертикальная грань (стена над карнизом) — от центра дома.
function outward(points, center) {
  let n = [0, 0, 0];
  points.forEach((p, i) => {
    const q = points[(i + 1) % points.length];
    n = [n[0] + (p[1] - q[1]) * (p[2] + q[2]), n[1] + (p[2] - q[2]) * (p[0] + q[0]),
      n[2] + (p[0] - q[0]) * (p[1] + q[1])];
  });
  n = unit(n);
  const mid = points[0].map((_, k) => points.reduce((s, p) => s + p[k], 0) / points.length);
  const away = Math.abs(n[1]) > FLAT ? n[1] : dot(n, sub(mid, center));
  return away < 0 ? n.map((x) => -x) : n;
}

// UV граней ската и стены над карнизом: v идёт вверх по грани, u — вправо, если смотреть на неё
// снаружи, как ряды на стене листа; единица — размер ячейки рисунка (метры), начало — у нижнего
// левого угла грани. points — вершины в осях сцены (x, y вверх, z).
export function faceUV(points, center, [tileW, tileH]) {
  const n = outward(points, center);
  const up = [0, 1, 0];
  const d = unit(sub(up, n.map((x) => x * dot(up, n))));
  const right = cross(d, n);
  const u = points.map((p) => dot(p, right)), v = points.map((p) => dot(p, d));
  const u0 = Math.min(...u), v0 = Math.min(...v);
  return points.map((_, i) => [(u[i] - u0) / tileW, (v[i] - v0) / tileH]);
}
