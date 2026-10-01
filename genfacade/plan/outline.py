"""Наружный контур плана: объединение стен и заполненных разрывов (plan-input.md, правило 4).

Стены — осевые прямоугольники, поэтому контур ортогональный. Разная толщина кусков
одной стены (16 и 17 px) даёт на контуре ступеньки в пиксель — их выпрямляем, иначе
у дома появились бы лишние стороны.
"""

import math

from shapely import MultiPolygon, box, unary_union

from genfacade.config import Outline
from genfacade.plan.genplan_svg import Box, PlanError
from genfacade.schema import EPS, Point, Polygon, signed_area


def outline(pieces: list[Box], cfg: Outline) -> Polygon:
    """Контур по часовой стрелке (оси с y вверх) без ступенек короче cfg.jog_px."""
    if not pieces:
        raise PlanError("в плане нет ни одной стены")
    shape = unary_union([box(b.x0, b.y0, b.x1, b.y1) for b in pieces])
    if isinstance(shape, MultiPolygon):
        parts = sorted(shape.geoms, key=lambda g: g.area, reverse=True)
        if parts[1].area > cfg.stray_area * parts[0].area:
            raise PlanError(f"стены не связаны: {len(parts)} отдельных частей")
        shape = parts[0]
    if not shape.interiors:
        raise PlanError("контур не замкнулся: стены не окружают ни одного помещения")
    ring = straighten(list(shape.exterior.coords)[:-1], cfg.jog_px)
    return ring if signed_area(ring) < 0 else ring[::-1]


def straighten(ring: Polygon, jog_px: float) -> Polygon:
    """Убрать точки на прямой и схлопнуть короткие рёбра ортогонального контура."""
    ring = _drop_collinear(ring)
    while len(ring) > 4:
        short = next((i for i in range(len(ring)) if _edge_len(ring, i) < jog_px), None)
        if short is None:
            break
        ring = _drop_collinear(_collapse(ring, short))
    return ring


def _edge_len(ring: Polygon, i: int) -> float:
    return math.dist(ring[i], ring[(i + 1) % len(ring)])


def _collapse(ring: Polygon, i: int) -> Polygon:
    """Короткое ребро i → i+1: соседние рёбра параллельны, ставим их на линию более длинного."""
    n = len(ring)
    prev, a, b, nxt = (i - 1) % n, i, (i + 1) % n, (i + 2) % n
    horizontal = abs(ring[a][0] - ring[b][0]) >= abs(ring[a][1] - ring[b][1])
    k = 0 if horizontal else 1  # координата, которую выравниваем
    keep = ring[a][k] if _edge_len(ring, prev) >= _edge_len(ring, b) else ring[b][k]
    out = list(ring)
    for j in (prev, a, b, nxt):
        p = list(out[j])
        p[k] = keep
        out[j] = (p[0], p[1])
    return out


def _drop_collinear(ring: Polygon) -> Polygon:
    """Убрать повторы и точки посреди прямой — точно, без допуска в пиксель."""
    out: Polygon = []
    for p in ring:
        if not out or math.dist(out[-1], p) > EPS:
            out.append(p)
    if len(out) > 1 and math.dist(out[0], out[-1]) <= EPS:
        out.pop()
    n = len(out)
    return [out[i] for i in range(n) if not _is_straight(out[i - 1], out[i], out[(i + 1) % n])]


def _is_straight(a: Point, b: Point, c: Point) -> bool:
    """Точка b на прямой ac — точно: ступеньки в пиксель убирает _collapse, а не допуск."""
    cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
    return abs(cross) <= EPS * max(math.dist(a, b), math.dist(b, c))
