// Рамки разметки на странице правки (gf#348): чистые функции без DOM — двигать, тянуть,
// ставить касанием, удалять с перенумерацией родителей. Только pt листа; метры, этажи и цоколь
// считает сервер (datasets/markup_edit.py). Тесты — tests/js/markup_geom.test.mjs.

// Ручки рамки: имя — стороны света, по которым она двигает края.
export const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

export const normalize = ([x0, y0, x1, y1]) =>
  [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];

export const moveBox = ([x0, y0, x1, y1], dx, dy) => [x0 + dx, y0 + dy, x1 + dx, y1 + dy];

// Тянем ручку handle на (dx, dy): края, на которые она указывает, едут за пальцем. Протянутая
// через противоположный край рамка переворачивается, а не пропадает.
export function resizeBox(box, handle, dx, dy) {
  const [x0, y0, x1, y1] = box;
  return normalize([
    handle.includes("w") ? x0 + dx : x0, handle.includes("n") ? y0 + dy : y0,
    handle.includes("e") ? x1 + dx : x1, handle.includes("s") ? y1 + dy : y1,
  ]);
}

// Точки ручек рамки — по ним страница рисует и ловит касание.
export function handlePoints([x0, y0, x1, y1]) {
  const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
  return { nw: [x0, y0], n: [mx, y0], ne: [x1, y0], e: [x1, my],
           se: [x1, y1], s: [mx, y1], sw: [x0, y1], w: [x0, my] };
}

// Рамка от касания в точке: sizeM = [ширина, высота] в метрах, pxPerM — pt листа на метр вида.
// Центр рамки в точке касания.
export function boxAt([x, y], sizeM, pxPerM) {
  const w = sizeM[0] * pxPerM, h = sizeM[1] * pxPerM;
  return [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
}

// Протащенная рамка меньше порога по обеим сторонам — это было касание.
export function isTap(box, minPt) {
  const [x0, y0, x1, y1] = normalize(box);
  return x1 - x0 < minPt && y1 - y0 < minPt;
}

// Рамка от жеста: протянули — края жеста, коснулись — размер по умолчанию sizeM (м) с центром в
// точке; координаты — в pt листа, до 0,1.
export function boxFrom(start, end, sizeM, pxPerM, minPt) {
  const box = isTap([...start, ...end], minPt)
    ? boxAt(start, sizeM, pxPerM) : normalize([...start, ...end]);
  return box.map(round1);
}

// Удалить элемент i: родитель, которого не стало, обнуляется, номера после него сдвигаются
// (`parent` в разметке — номер в списке стороны).
export function removeElement(elements, i) {
  return elements.filter((_, k) => k !== i).map((e) => {
    if (e.parent == null) return e;
    if (e.parent === i) return { ...e, parent: null };
    return e.parent > i ? { ...e, parent: e.parent - 1 } : e;
  });
}

// Сменить класс: вид окна (деление рамы) и вид двери разные, поэтому вид не переносится.
export const setClass = (element, cls) =>
  element.cls === cls ? element : { ...element, cls, variant: null };

// Верхний элемент под точкой: последний в списке рисуется сверху; из совпавших — самый малый
// (окно внутри большой зоны выбирается раньше зоны).
export function pick(elements, [x, y]) {
  const hit = elements.map((e, i) => ({ i, b: normalize(e.box) }))
    .filter(({ b }) => x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3]);
  if (!hit.length) return -1;
  const area = ({ b }) => (b[2] - b[0]) * (b[3] - b[1]);
  return hit.reduce((best, h) => (area(h) <= area(best) ? h : best)).i;
}

export const round1 = (v) => Math.round(v * 10) / 10;

// ——— отметки и зоны на виде (gf#470): труба, мансардное и слуховое окна, крыльцо под кровлей ———
// Форму отметки задаёт сервер (`options.marks[вид].shape`): касание, отрезок по x или рамка.
export const SHAPE = { POINT: "point", SPAN: "span", BOX: "box" };

// Отметка от жеста: касание-точка кладёт x, отрезок — края по x, рамка — ещё и y. Касание
// (жест короче minPt) для отрезка и рамки — размер по умолчанию sizeM с центром в точке. Поля,
// которые жестом не задать (вид кровли, столбы), — из defaults.
export function markFrom(shape, start, end, { sizeM, pxPerM, minPt, defaults }) {
  if (shape === SHAPE.POINT) return { x: round1(start[0]), ...defaults };
  const [x0, y0, x1, y1] = boxFrom(start, end, sizeM, pxPerM, minPt);
  return shape === SHAPE.SPAN ? { x: [x0, x1], ...defaults } : { x: [x0, x1], y: [y0, y1], ...defaults };
}

// Отметки всех сторон одним списком вида: у каждой — номер её стороны (`side`), как в разметке.
export const flattenMarks = (sides, kind) =>
  sides.flatMap((s, k) => s.marks[kind].map((m) => ({ ...m, side: k })));

// Удалить отметку или зону по номеру в списке стороны.
export const removeAt = (list, i) => list.filter((_, k) => k !== i);
