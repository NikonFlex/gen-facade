"""Стороны контура: проёмы и запретные зоны вдоль каждой (plan-input.md, Side).

Сторона i идёт от угла i к углу i+1 обходом по часовой стрелке (оси с y вверх), нормаль
наружу — слева от направления обхода. Смотрящий снаружи видит начало стороны справа,
поэтому x на фасаде отсчитывается от конца стороны: x = длина − t.
"""

import math
from typing import NamedTuple

from genfacade.plan.gaps import Found
from genfacade.plan.genplan_svg import TOL_PX, Box
from genfacade.schema import ForbiddenZone, Opening, Point, Polygon, Side


class Contour(NamedTuple):
    ring: Polygon  # пиксели, по часовой стрелке
    tol_px: float  # насколько грань стены может отстоять от линии стороны после выпрямления


class Edge:
    """Сторона в пикселях: начало, направление, наружная нормаль, длина."""

    def __init__(self, ring: Polygon, i: int):
        self.p, q = ring[i], ring[(i + 1) % len(ring)]
        self.length = math.dist(self.p, q)
        self.d = ((q[0] - self.p[0]) / self.length, (q[1] - self.p[1]) / self.length)
        # Контур ортогональный: нормаль — ровно ось, без хвостов float.
        self.n = (float(round(-self.d[1])), float(round(self.d[0])))

    def t(self, pt: Point) -> float:
        """Координата точки вдоль стороны от её начала."""
        return (pt[0] - self.p[0]) * self.d[0] + (pt[1] - self.p[1]) * self.d[1]

    def depth(self, pt: Point) -> float:
        """Насколько точка внутри дома от линии стороны."""
        return -((pt[0] - self.p[0]) * self.n[0] + (pt[1] - self.p[1]) * self.n[1])

    def span(self, b: Box) -> tuple[float, float]:
        ts = [self.t(c) for c in _corners(b)]
        return max(min(ts), 0.0), min(max(ts), self.length)

    def depths(self, b: Box) -> tuple[float, float]:
        ds = [self.depth(c) for c in _corners(b)]
        return min(ds), max(ds)


def start_at(c: Contour, entrance: Box) -> Contour:
    """Повернуть обход так, чтобы сторона 0 была стороной входа."""
    i = _edge_of(c, entrance)
    return Contour(c.ring[i:] + c.ring[:i], c.tol_px)


def build(c: Contour, openings: list[Found], walls: list[Box], scale: float) -> list[Side]:
    """Стороны в метрах: проёмы (наружные, не заделанные) и запретные зоны."""
    edges = [Edge(c.ring, i) for i in range(len(c.ring))]
    inner = [w for w in walls if not any(_on_line(e, w, c.tol_px) for e in edges)]
    sides = []
    for i, e in enumerate(edges):
        own = [f for f in openings if _edge_of(c, f.gap.box) == i]
        on_line = [w for w in walls if _on_line(e, w, c.tol_px)]
        thickness = max((_depth_extent(e, w) for w in on_line), default=0.0)
        sides.append(Side(
            index=i, length_m=e.length * scale, orientation=e.n,
            openings=[_opening(e, f, scale) for f in own],
            forbidden=_forbidden(e, inner, thickness, scale),
            has_entrance=any(f.kind == "entrance" for f in own),
        ))
    return sides


def _corners(b: Box) -> list[Point]:
    return [(b.x0, b.y0), (b.x1, b.y0), (b.x1, b.y1), (b.x0, b.y1)]


def _along(e: Edge, b: Box) -> float:
    t0, t1 = e.span(b)
    return t1 - t0


def _depth_extent(e: Edge, b: Box) -> float:
    d0, d1 = e.depths(b)
    return d1 - d0


def _on_line(e: Edge, b: Box, tol: float) -> bool:
    """Прямоугольник лежит на стороне: наружная грань на её линии, и он вытянут вдоль.

    Внутренние стены GenPlan часто прорисованы насквозь до наружной грани — их грань тоже
    на линии, но они вытянуты поперёк стороны.
    """
    return abs(e.depths(b)[0]) <= tol and _along(e, b) >= _depth_extent(e, b)


def _edge_of(c: Contour, b: Box) -> int:
    """Сторона, на линии которой лежит проём."""
    for i in range(len(c.ring)):
        if _on_line(Edge(c.ring, i), b, c.tol_px):
            return i
    raise ValueError(f"проём {b} не лежит ни на одной стороне контура")


def _opening(e: Edge, f: Found, scale: float) -> Opening:
    t0, t1 = e.span(f.gap.box)
    return Opening(kind=f.kind, x_m=(e.length - t1) * scale, width_m=(t1 - t0) * scale)


def _forbidden(e: Edge, inner: list[Box], thickness: float, scale: float) -> list[ForbiddenZone]:
    """Где к стороне изнутри примыкает внутренняя стена (plan-input.md, ForbiddenZone)."""
    zones = []
    for w in inner:
        near, _ = e.depths(w)
        t0, t1 = e.span(w)
        if -TOL_PX <= near <= thickness + TOL_PX and t1 - t0 > TOL_PX:
            zones.append(((e.length - t1) * scale, (e.length - t0) * scale))
    return [ForbiddenZone(x0_m=x0, x1_m=x1) for x0, x1 in _merge(zones)]


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Слить пересекающиеся интервалы: векторизация GenPlan дублирует стены внахлёст."""
    out: list[tuple[float, float]] = []
    for x0, x1 in sorted(spans):
        if out and x0 <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], x1))
        else:
            out.append((x0, x1))
    return out
