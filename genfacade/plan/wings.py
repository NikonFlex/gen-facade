"""Шаг 2: контур плана → прямоугольные крылья (gf#322, `facade: Части дома`).

Часть дома — прямоугольное крыло контура, у него своя этажность и высота. Контур ортогональный:
режем его по линии через вогнутый угол, пока не останутся прямоугольники. Г-образный контур режется
двумя способами; берём разрез, после которого самое большое из итоговых крыльев (после дальнейшего
разбиения) больше (как в Г-образной синтетике, `datasets/synthetic/shapes.py`: основной объём —
целый; у Т с пристройкой посреди стены — блок целиком, а не полоса сбоку); при равенстве —
горизонтальный, потом по порядку углов, чтобы разбиение не менялось от запуска к запуску.
"""

import math
from itertools import islice, product

import shapely
from shapely import ops

from genfacade.schema import EPS, Point, Polygon, Rect

SNAP = 9  # знаков после запятой, до которых округляется контур, метры
MAX_CANDIDATES = 400  # разбиений контура, что перебирает `candidates`; у реальных домов — до сотни
FAR = 1e6  # длина разрезающей линии, метров: больше любого дома


def wings(outline: Polygon) -> list[Rect]:
    """Крылья контура; у прямоугольника — пустой список (дом из одной части)."""
    found = candidates(outline)
    return found[0] if found else []


def candidates(outline: Polygon) -> list[list[Rect]]:
    """Все разбиения контура на крылья (по разным разрезам Г-образных кусков), первое — то, что
    даёт `wings`; дальше — с меньшим числом крыльев, потом по порядку разрезов. Нужны сборщику
    разметки: отметки карниза лежат не на любом разбиении (gf#322) — берётся первое, на котором
    у каждого крыла одна отметка. Не больше `MAX_CANDIDATES`; у прямоугольника — пусто."""
    # Контур из разметки ортогонален с точностью до хвостов float (1e-15): без округления линия
    # разреза не попадает в соседний угол, и разрез не делит контур.
    shape = shapely.Polygon([(round(x, SNAP), round(y, SNAP)) for x, y in outline]).simplify(0)
    if _is_rect(shape):
        return []
    found = [[_rect(p) for p in pieces] for pieces in _splits(shape)]
    unique = {tuple(sorted(tuple(r.model_dump().items()) for r in rects)): rects
              for rects in found}
    rest = [r for r in unique.values() if r != found[0]]
    return [found[0], *sorted(rest, key=len)]  # sorted устойчива: порядок разрезов сохраняется


def _is_rect(shape: shapely.Polygon) -> bool:
    x0, y0, x1, y1 = shape.bounds
    return abs(shape.area - (x1 - x0) * (y1 - y0)) <= EPS


def _rect(shape: shapely.Polygon) -> Rect:
    x0, y0, x1, y1 = shape.bounds
    return Rect(x0_m=x0, y0_m=y0, x1_m=x1, y1_m=y1)


def _splits(shape: shapely.Polygon) -> list[list[shapely.Polygon]]:
    """Итоговые крылья по каждому способу разбиения; первое — лучшее (самое большое крыло, при
    равенстве — первое по порядку разрезов), остальные — по порядку разрезов. Куски разреза
    разбиваются независимо; перебор ограничен `MAX_CANDIDATES`."""
    if _is_rect(shape):
        return [[shape]]
    cuts = [c for v, horizontal in product(_reflex(shape), (True, False))
            if len(c := _cut(shape, v, horizontal)) > 1]
    results: list[list[shapely.Polygon]] = []
    for c in cuts:
        for combo in islice(product(*(_splits(piece) for piece in c)), MAX_CANDIDATES):
            results.append([r for rects in combo for r in rects])
    best = max(results, key=lambda rects: max(_size(r) for r in rects))  # первый из равных
    return [best, *(r for r in results if r is not best)][:MAX_CANDIDATES]


def _size(shape: shapely.Polygon) -> float:
    """Площадь для сравнения кусков: до мм², чтобы шум float у равных по площади кусков не менял
    разбиение — оно одно для контура в любом сдвиге (план и углы развёртки, gf#322)."""
    return round(shape.area, 6)


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
    return sorted(pieces, key=lambda p: (-_size(p), p.bounds))


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
