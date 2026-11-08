"""Шаг 2: контур плана → прямоугольные крылья (gf#322, `facade: Части дома`).

Часть дома — прямоугольное крыло контура, у него своя этажность и высота. Контур ортогональный:
режем его по линии через вогнутый угол, пока не останутся прямоугольники. Г-образный контур режется
двумя способами; берём разрез, после которого самое большое крыло больше (как в Г-образной
синтетике, `datasets/synthetic/shapes.py`: основной объём — целый); при равенстве — горизонтальный,
потом по порядку углов, чтобы разбиение не менялось от запуска к запуску.
"""

import math
from itertools import product

import shapely
from shapely import ops

from genfacade.schema import EPS, Point, Polygon, Rect

SNAP = 9  # знаков после запятой, до которых округляется контур, метры
FAR = 1e6  # длина разрезающей линии, метров: больше любого дома


def wings(outline: Polygon) -> list[Rect]:
    """Крылья контура; у прямоугольника — пустой список (дом из одной части)."""
    # Контур из разметки ортогонален с точностью до хвостов float (1e-15): без округления линия
    # разреза не попадает в соседний угол, и разрез не делит контур.
    shape = shapely.Polygon([(round(x, SNAP), round(y, SNAP)) for x, y in outline]).simplify(0)
    if _is_rect(shape):
        return []
    return [_rect(p) for p in _split(shape)]


def _is_rect(shape: shapely.Polygon) -> bool:
    x0, y0, x1, y1 = shape.bounds
    return abs(shape.area - (x1 - x0) * (y1 - y0)) <= EPS


def _rect(shape: shapely.Polygon) -> Rect:
    x0, y0, x1, y1 = shape.bounds
    return Rect(x0_m=x0, y0_m=y0, x1_m=x1, y1_m=y1)


def _split(shape: shapely.Polygon) -> list[shapely.Polygon]:
    if _is_rect(shape):
        return [shape]
    cuts = [c for v, horizontal in product(_reflex(shape), (True, False))
            if len(c := _cut(shape, v, horizontal)) > 1]
    best = max(cuts, key=lambda pieces: max(p.area for p in pieces))  # max берёт первый из равных
    return [r for piece in best for r in _split(piece)]


def _reflex(shape: shapely.Polygon) -> list[Point]:
    """Вогнутые углы контура в порядке обхода."""
    ring = list(shape.exterior.coords)[:-1]
    sign = 1 if shape.exterior.is_ccw else -1
    out = []
    for prev, cur, nxt in zip(ring[-1:] + ring[:-1], ring, ring[1:] + ring[:1], strict=True):
        turn = (cur[0] - prev[0]) * (nxt[1] - cur[1]) - (cur[1] - prev[1]) * (nxt[0] - cur[0])
        if turn * sign < -EPS:
            out.append(cur)
    return out


def _cut(shape: shapely.Polygon, at: Point, horizontal: bool) -> list[shapely.Polygon]:
    """Куски контура после разреза линией через угол at."""
    dx, dy = (FAR, 0.0) if horizontal else (0.0, FAR)
    line = shapely.LineString([(at[0] - dx, at[1] - dy), (at[0] + dx, at[1] + dy)])
    pieces = [p.simplify(0) for p in ops.split(shape, line).geoms if p.area > EPS]
    return sorted(pieces, key=lambda p: (-p.area, p.bounds))


def edge_runs(a: Point, b: Point, wing_rects: list[Rect]) -> list[tuple[int, float, float]]:
    """Какие крылья лежат на стороне ab контура: (номер крыла, t0, t1) — расстояния от a вдоль
    стороны. Сторона ортогональна, крыло лежит на ней гранью. Участки идут по возрастанию t."""
    length = math.dist(a, b)
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    out = []
    for k, w in enumerate(wing_rects):
        ts = _along(a, (ux, uy), length, w)
        if ts is not None:
            out.append((k, *ts))
    return sorted(out, key=lambda r: r[1])


def _along(a: Point, u: Point, length: float, w: Rect) -> tuple[float, float] | None:
    """Участок стороны (a, направление u) на грани крыла w; грань не на стороне — None."""
    horizontal = abs(u[0]) > abs(u[1])
    lo, hi = (w.x0_m, w.x1_m) if horizontal else (w.y0_m, w.y1_m)  # вдоль стороны
    across = (w.y0_m, w.y1_m) if horizontal else (w.x0_m, w.x1_m)
    fixed = a[1] if horizontal else a[0]
    if min(abs(v - fixed) for v in across) > EPS:
        return None
    start, sign = (a[0], u[0]) if horizontal else (a[1], u[1])
    t0, t1 = sorted((v - start) * sign for v in (lo, hi))
    t0, t1 = max(t0, 0.0), min(t1, length)
    return (t0, t1) if t1 - t0 > EPS else None
