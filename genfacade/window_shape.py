"""Контур окна по его виду (gf#319, `docs/decisions.md`, 08.11): форма окна — вид проёма
(`VariantKind`), рамка остаётся прямоугольником во всём модуле, контур считает этот модуль — для
листа, дома объёмом и проверки ската.

- `arch` — полукруглый верх: полуэллипс шириной рамки и высотой не больше половины ширины над
  прямоугольником (при высоте рамки в половину ширины — полукруглое окно);
- `oval` — эллипс, вписанный в рамку (круг при равных сторонах);
- `slope` — верх по скату (gf#470): рамка, срезанная скатами, сдвинутыми параллельно вниз до
  касания верха рамки (не ближе отступа `slope_offset_m`) — верх параллелен скату через верхний
  угол рамки (трапеция без полки; под коньком — пятиугольник с острым коньком); рамка, что
  не ближе отступа к скату, и окно не во фронтоне — рамка;
- остальные виды — рамка.
"""

import math
from typing import NamedTuple

import shapely

from genfacade import roof
from genfacade.schema import EPS, Element, Point, Polygon, VariantKind

ARC_POINTS = 12  # точек на полуокружность: на листе 1:100 дуга без изломов


class Gable(NamedTuple):
    """Фронтон стены для окон: room — место окна (стена без полосы `offset` у ската), slopes —
    кромки ската, offset — отступ от ската."""

    room: shapely.Geometry
    slopes: list[tuple[Point, Point]]
    offset: float


def kind(e: Element) -> VariantKind:
    return e.variant.kind if e.variant is not None else VariantKind.REGULAR


def outline(e: Element, gable: Gable | None = None) -> Polygon:
    """Контур окна в метрах стены; gable — фронтон стены (`gable_room`) или None."""
    x0, y0, x1, y1 = e.x_m, e.y_m, e.x_m + e.w_m, e.y_m + e.h_m
    box = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    match kind(e):
        case VariantKind.ARCH:
            r = min(e.h_m, e.w_m / 2)
            return [(x0, y0), (x1, y0), *_arc((x0 + x1) / 2, y1 - r, e.w_m / 2, r, 0, math.pi)]
        case VariantKind.OVAL:
            return _arc((x0 + x1) / 2, (y0 + y1) / 2, e.w_m / 2, e.h_m / 2, 0, 2 * math.pi)[:-1]
        case VariantKind.SLOPE if gable is not None:
            return _slope_cut(e, gable) or box
    return box


def reach(room: shapely.Geometry, x: float, y: float, w: float, h: float) -> float:
    """Доля рамки x y w h, что остаётся в месте окна во фронтоне (`room`), если срез — один
    многоугольник, иначе 0. Одна формула стража (в шагах сетки: доля от масштаба не зависит),
    валидатора и синтетики: окно `slope` годно, когда доля не меньше `checks.slope_share`."""
    if w <= 0 or h <= 0:
        return 0.0
    cut = room.intersection(shapely.box(x, y, x + w, y + h))
    return cut.area / (w * h) if cut.geom_type == "Polygon" else 0.0


def casing(w: Element, m: Element, gable: Gable | None = None) -> Polygon:
    """Контур наличника окна w не прямоугольником (gf#319): контур окна, расширенный на ширину
    наличника, в пределах прямоугольника наличника m (его низ — низ окна). Прямоугольник m остаётся
    записью и рамкой разбора; рисунок и проверка стены берут этот контур. Окно — прямоугольник:
    сам m."""
    box = [(m.x_m, m.y_m), (m.x_m + m.w_m, m.y_m), (m.x_m + m.w_m, m.y_m + m.h_m),
           (m.x_m, m.y_m + m.h_m)]
    shape = outline(w, gable)
    if shapely.Polygon(shape).equals(shapely.box(w.x_m, w.y_m, w.x_m + w.w_m, w.y_m + w.h_m)):
        return box
    ring = shapely.Polygon(shape).buffer(w.x_m - m.x_m, join_style="mitre")
    cut = ring.intersection(shapely.box(m.x_m, w.y_m, m.x_m + m.w_m, m.y_m + m.h_m))
    return _largest(cut) or box


def gable_room(length: float, eaves: float, above: Polygon | None,
               offset: float) -> Gable | None:
    """Фронтон стены для окон или None, если фронтона нет."""
    if above is None:
        return None
    return Gable(roof.room(length, eaves, above, offset), roof.slopes(above, eaves), offset)


def _line(s: tuple[Point, Point]) -> tuple[float, float, float]:
    """Прямая ската: единичная нормаль вверх (nx, ny) и c, где n·p = c — точки ската."""
    (ax, ay), (bx, by) = s
    size = math.hypot(bx - ax, by - ay)
    nx, ny = (ay - by) / size, (bx - ax) / size
    if ny < 0:
        nx, ny = -nx, -ny
    return nx, ny, nx * ax + ny * ay


def _gap(line: tuple[float, float, float], x: float, y: float) -> float:
    """Расстояние от точки (x, y) до прямой ската вниз по нормали; над скатом — отрицательное."""
    return line[2] - line[0] * x - line[1] * y


def _top_gap(lines: list[tuple[float, float, float]], x0: float, x1: float, y: float) -> float:
    """Наибольший отступ от скатов, который есть у точки верха рамки: она ближе всего к скатам
    на краю верха или там, где расстояния до двух скатов равны (конёк)."""
    xs = [x0, x1]
    for i, a in enumerate(lines):
        for b in lines[i + 1:]:
            dx = a[0] - b[0]
            if abs(dx) > EPS and x0 < (x := ((a[2] - b[2]) - (a[1] - b[1]) * y) / dx) < x1:
                xs.append(x)
    return max(min(_gap(line, x, y) for line in lines) for x in xs)


def _slope_cut(e: Element, gable: Gable) -> Polygon | None:
    """Контур окна `slope`: рамка под скатами, сдвинутыми вниз на отступ до верха рамки, но не
    меньше `offset`. Скат не ближе отступа ни к одному углу рамки — рамка (None)."""
    x0, y0, x1, y1 = e.x_m, e.y_m, e.x_m + e.w_m, e.y_m + e.h_m
    lines = [_line(s) for s in gable.slopes if min(s[0][0], s[1][0]) < x1
             and max(s[0][0], s[1][0]) > x0]
    corners = [(x, y) for x in (x0, x1) for y in (y0, y1)]
    if not lines or min(_gap(line, *c) for line in lines for c in corners) >= gable.offset - EPS:
        return None
    shift = max(gable.offset, _top_gap(lines, x0, x1, y1))
    cut = shapely.box(x0, y0, x1, y1)
    for nx, ny, c in lines:
        cut = cut.intersection(roof.halfplane((nx, ny), c - shift))
    return _largest(cut.simplify(EPS))


def _largest(cut: shapely.Geometry) -> Polygon | None:
    """Вершины самого большого многоугольника среза; пусто — None."""
    parts = getattr(cut, "geoms", [cut])
    best = max((g for g in parts if g.geom_type == "Polygon"), key=lambda g: g.area, default=None)
    return None if best is None or best.area <= 0 else list(best.exterior.coords)[:-1]


def _arc(cx: float, cy: float, rx: float, ry: float, start: float, end: float) -> Polygon:
    steps = max(2, round(ARC_POINTS * abs(end - start) / math.pi))
    return [(cx + rx * math.cos(start + (end - start) * i / steps),
             cy + ry * math.sin(start + (end - start) * i / steps)) for i in range(steps + 1)]
