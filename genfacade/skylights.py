"""Мансардные окна в плоскости ската (gf#456, `facade: Мансардное окно`): ряд окон на каждом скате
главной части дома, ничего не выступает над кровлей.

Окно — прямоугольник в плоскости ската: `width_m` вдоль карниза и `length_m` по скату. Его ставит
код по числу `HouseSpec.skylights`, а не модель шага 4: окно не в стене, класса элемента у него нет
и в условие модели оно не входит. Углы лежат на грани ската (низ кровельной плиты — так её отдаёт
`roof.faces`); лист, 3D и IFC поднимают их на верх кровли (`raised`).
"""

import math
from typing import NamedTuple

import shapely

from genfacade import roof
from genfacade.config import SkylightLook
from genfacade.roof import Point3
from genfacade.schema import EPS, FacadeSheet, Point, Polygon


class Skylight(NamedTuple):
    """Окно: наружный контур (рама) и внутренний (стекло), по четыре вершины (x, y плана, высота)
    в порядке: низ слева, низ справа, верх справа, верх слева; slope — номер ската в `Roofline`,
    inward — нормаль его стены внутрь дома (в плане): куда скат падает, туда окно и смотрит."""

    slope: int
    inward: Point
    outer: list[Point3]
    inner: list[Point3]


def raised(item: Skylight, dz: float) -> Skylight:
    """Окно, поднятое по вертикали на dz — с грани ската на верх кровли."""
    def up(ring: list[Point3]) -> list[Point3]:
        return [(x, y, z + dz) for x, y, z in ring]
    return item._replace(outer=up(item.outer), inner=up(item.inner))


def on_view(items: list[Skylight], left: Point, u: Point, roof_view: list[Polygon]
            ) -> list[tuple[Polygon, Polygon]]:
    """Окна на виде стены (начало left, направление u): проекции рамки и стекла окон, обращённых
    к зрителю, в пределах видимой кровли roof_view. Окно на скате, что виден с ребра (фронтон),
    не рисуется: оно в плоскости ската и ничего не выступает, на ребре его нет."""
    toward = (u[1], -u[0])  # наружная нормаль стены — к зрителю
    seen = shapely.union_all([shapely.Polygon(p) for p in roof_view]) if roof_view else None
    out = []
    for item in items:
        if -(item.inward[0] * toward[0] + item.inward[1] * toward[1]) <= EPS or seen is None:
            continue
        frame, glass = (_clip(ring, left, u, seen) for ring in (item.outer, item.inner))
        if frame and glass:
            out.append((frame, glass))
    return out


def _clip(ring: list[Point3], left: Point, u: Point, seen: shapely.Geometry) -> Polygon | None:
    """Проекция кольца на вид, обрезанная по видимой кровле seen; ничего не осталось — None."""
    flat = shapely.Polygon([((x - left[0]) * u[0] + (y - left[1]) * u[1], z)
                            for x, y, z in ring]).intersection(seen)
    shapes = roof.polygons(flat)
    return shapes[0] if shapes else None


def find(sheet: FacadeSheet, look: SkylightLook) -> list[Skylight]:
    """Окна дома: на каждом скате главной части не больше `HouseSpec.skylights` в ряд, сколько
    помещается; плоская крыша, уклон меньше `min_pitch_deg` или окон 0 — пусто. У ската,
    разрезанного кровлей другой части на куски, берётся самый большой."""
    main = roof.main_faces(sheet)
    if sheet.spec.skylights == 0 or main is None:
        return []
    line, faces = main
    if not line.slopes or math.degrees(math.atan(line.rise)) < look.min_pitch_deg - EPS:
        return []
    out = []
    for number, slope in enumerate(line.slopes):
        pieces = [face for s, face in faces if s is slope]
        if pieces:
            big = max(pieces, key=lambda f: shapely.Polygon([(x, y) for x, y, _ in f]).area)
            out += _row(line, number, big, sheet.spec.skylights, look)
    return out


def _row(line: roof.Roofline, number: int, face: list[Point3], count: int, look: SkylightLook
         ) -> list[Skylight]:
    """Ряд окон на скате number по грани face: по центру доступной ширины вдоль карниза."""
    slope = line.slopes[number]
    u = (-slope.inward[1], slope.inward[0])
    local = shapely.Polygon([((x - slope.at[0]) * u[0] + (y - slope.at[1]) * u[1],
                              slope.depth((x, y))) for x, y, _ in face])
    cos = math.cos(math.atan(line.rise))
    d0 = look.sill_m / line.rise
    d1 = d0 + look.length_m * cos
    span = _free(local, d0, d1 + look.ridge_margin_m * cos)  # выше окна — запас до конька
    if span is None:
        return []
    lo, hi = span[0] + look.end_margin_m, span[1] - look.end_margin_m
    n = min(count, int((hi - lo + look.gap_m + EPS) // (look.width_m + look.gap_m)))
    step = look.width_m + look.gap_m
    start = (lo + hi - (n * step - look.gap_m)) / 2

    def window(t0: float) -> Skylight:
        rings = [_ring(line, number, u, (t0 + inset, t0 + look.width_m - inset),
                       (d0 + inset * cos, d1 - inset * cos)) for inset in (0.0, look.frame_m)]
        return Skylight(number, slope.inward, *rings)

    return [window(start + i * step) for i in range(n)]


def _free(local: shapely.Polygon, d0: float, d1: float) -> tuple[float, float] | None:
    """Отрезок вдоль карниза, где грань есть на всех глубинах от d0 до d1 (по краям полосы — у
    выпуклой грани этого хватает; невыпуклая, где полоса не вся внутри, — None)."""
    edges = [local.intersection(shapely.LineString([(-roof.FAR, d), (roof.FAR, d)]))
             for d in (d0, d1)]
    if any(e.is_empty for e in edges):
        return None
    lo, hi = max(e.bounds[0] for e in edges), min(e.bounds[2] for e in edges)
    strip = shapely.box(lo, d0, hi, d1)
    return (lo, hi) if hi > lo and local.buffer(EPS).contains(strip) else None


def _ring(line: roof.Roofline, number: int, u: Point, t: tuple[float, float],
          d: tuple[float, float]) -> list[Point3]:
    """Прямоугольник t × d (вдоль карниза × вглубь от кромки ската) на плоскости ската."""
    slope = line.slopes[number]

    def at(tt: float, dd: float) -> Point3:
        return (slope.at[0] + u[0] * tt + slope.inward[0] * dd,
                slope.at[1] + u[1] * tt + slope.inward[1] * dd, line.eaves + line.rise * dd)

    return [at(t[0], d[0]), at(t[1], d[0]), at(t[1], d[1]), at(t[0], d[1])]
