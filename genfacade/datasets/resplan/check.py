"""Сверка сторон с исходником ResPlan: каждое окно и каждая дверь ResPlan у наружного контура
должны найтись на своей стороне с тем же x и шириной.

Считается прямо по многоугольникам ResPlan, мимо SVG и поиска разрывов препроцессора, —
поэтому ловит ошибки перевода: потерянный проём, сдвиг, дверь, ставшую окном.
"""

import math
from dataclasses import dataclass, field

import numpy
import shapely

from genfacade.config import ResPlan
from genfacade.datasets.resplan.convert import DOOR, FRONT_DOOR, WINDOW, Drawing, m_per_px
from genfacade.schema import Opening, OpeningKind, Plan, Point

SOURCE_KIND = {WINDOW: OpeningKind.WINDOW, DOOR: OpeningKind.DOOR, FRONT_DOOR: OpeningKind.DOOR}


@dataclass
class Match:
    """Итог сверки одного дома."""

    on_contour: int = 0       # проёмов ResPlan у наружного контура
    found: int = 0            # из них нашлись на своей стороне
    kind_differs: int = 0     # нашлись, но окно стало дверью или наоборот
    extracted: int = 0        # проёмов на сторонах всего
    entrance_is_front_door: bool = False  # вход по правилу GenPlan — входная дверь ResPlan
    errors_m: list[float] = field(default_factory=list)  # |Δx| и |Δширины| найденных

    @property
    def clean(self) -> bool:
        """Все проёмы ResPlan у контура нашлись, с тем же видом, и лишних нет."""
        return self.found == self.on_contour == self.extracted and not self.kind_differs


@dataclass(frozen=True)
class _Edge:
    p: Point
    d: Point   # направление обхода
    n: Point   # наружная нормаль
    length: float

    def t(self, c: Point) -> float:
        return (c[0] - self.p[0]) * self.d[0] + (c[1] - self.p[1]) * self.d[1]

    def depth(self, c: Point) -> float:
        """Насколько точка внутри дома от линии стороны."""
        return -((c[0] - self.p[0]) * self.n[0] + (c[1] - self.p[1]) * self.n[1])


def against_source(plan: dict, drawing: Drawing, ours: Plan, rules: ResPlan) -> Match:
    """Проёмы ResPlan у контура против проёмов сторон плана `ours` (метры, y вверх)."""
    edges = _edges(ours)
    reach = plan["wall_depth"] * m_per_px(plan) + rules.match_tol_m
    match = Match(extracted=sum(len(s.openings) for s in ours.sides))
    for key, kind in SOURCE_KIND.items():
        for poly in shapely.get_parts(drawing.in_plan_m(plan.get(key), ours.scale_m_per_px)):
            located = _locate(poly, edges, reach)
            if located is None:
                continue
            i, x, w = located
            match.on_contour += 1
            near = _nearest(ours.sides[i].openings, x + w / 2)
            if near is None or abs(near.x_m + near.width_m / 2 - x - w / 2) > rules.match_tol_m:
                continue
            match.found += 1
            match.entrance_is_front_door |= key == FRONT_DOOR and near.kind is OpeningKind.ENTRANCE
            match.kind_differs += _family(near.kind) is not kind
            match.errors_m += [abs(near.x_m - x), abs(near.width_m - w)]
    return match


def total(matches: list[Match]) -> dict:
    """Сверка по всем домам: доли найденных и точность x и ширины."""
    on = sum(m.on_contour for m in matches)
    found = sum(m.found for m in matches)
    errors = numpy.array([e for m in matches for e in m.errors_m] or [0.0])
    return {
        "source_openings_on_contour": on,
        "found_on_side": found,
        "found_share": round(found / max(on, 1), 4),
        "kind_differs": sum(m.kind_differs for m in matches),
        "extracted_openings": sum(m.extracted for m in matches),
        "houses_all_found": sum(m.found == m.on_contour for m in matches),
        "entrance_is_front_door": sum(m.entrance_is_front_door for m in matches),
        "error_m": {"median": round(float(numpy.median(errors)), 4),
                    "p95": round(float(numpy.percentile(errors, 95)), 4),
                    "max": round(float(errors.max()), 4),
                    "share_within_5cm": round(float((errors <= 0.05).mean()), 4)},
    }


def _edges(ours: Plan) -> list[_Edge]:
    ring, out = ours.outline, []
    for i, side in enumerate(ours.sides):
        p, q = ring[i], ring[(i + 1) % len(ring)]
        length = math.dist(p, q)
        out.append(_Edge(p, ((q[0] - p[0]) / length, (q[1] - p[1]) / length),
                         side.orientation, length))
    return out


def _locate(poly, edges: list[_Edge], reach: float) -> tuple[int, float, float] | None:
    """Сторона, у которой лежит проём, и его x и ширина на фасаде (x — от конца стороны)."""
    c = poly.centroid.coords[0]
    near = [(abs(e.depth(c)), i) for i, e in enumerate(edges)
            if -reach <= e.depth(c) <= reach and 0 <= e.t(c) <= e.length]
    if not near:
        return None
    i = min(near)[1]
    corners = shapely.get_coordinates(poly.envelope)
    ts, ds = [edges[i].t(xy) for xy in corners], [edges[i].depth(xy) for xy in corners]
    if max(ts) - min(ts) < max(ds) - min(ds):
        return None  # проём поперёк стороны — во внутренней стене, упёршейся в наружную
    t0, t1 = max(min(ts), 0.0), min(max(ts), edges[i].length)
    return i, edges[i].length - t1, t1 - t0


def _nearest(openings: list[Opening], center: float) -> Opening | None:
    return min(openings, key=lambda o: abs(o.x_m + o.width_m / 2 - center), default=None)


def _family(kind: OpeningKind) -> OpeningKind:
    """Вход — тоже дверь: у ResPlan дверь и входная дверь — разные слои, у плана — вид."""
    return OpeningKind.DOOR if kind is OpeningKind.ENTRANCE else kind
