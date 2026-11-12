"""Дымовая труба и водосток (gf#454, `facade: Дымовая труба`, `facade: Водосток`): то, что стоит на
кровле и по её краю. Считает код по параметрам дома (`HouseSpec.chimney`, `HouseSpec.gutters`) и
скатам (`roof.py`); модель шага 4 их не ставит и не видит. Лист, дом объёмом и IFC берут отсюда.

Труба — квадрат `chimney_m` в плане на коньке главной части (`ridge`): конёк — отрезок, где скаты
сходятся на высшей отметке, начало конька — его конец, ближний к углу 0 контура части. Верх —
конёк плюс `chimney_over_m` (СНиП 41-01-2003 п. 6.6.12), низ — по самой низкой точке кровли под
трубой, то есть внутри кровли. У односкатной крыши конёк — высокая кромка у стены, труба сдвинута
от стены внутрь на полсечения: иначе она стояла бы наружу. У плоской крыши трубы нет.

Водосток — желоб по краю свеса каждой карнизной стороны части (от угла до угла контура кровли)
на высоте низа кровли у края и водосточные трубы по стене у каждого конца желоба, от желоба до
земли. Дом из частей: по карнизным сторонам каждой части, но желоб не идёт там, где край свеса
под кровлей или у стены другой части, и не дублирует желоб, что уже лёг на ту же линию; у конца,
что упёрся в соседнюю часть, труба стоит у этого конца.
"""

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple

import shapely

from genfacade import roof
from genfacade.config import RoofItemsLook
from genfacade.roof import HouseRoof, Roofline
from genfacade.schema import EPS, FacadeSheet, Point, Polygon

Point3 = tuple[float, float, float]
KEEP_MIN_M = 10 * EPS  # желоба короче этого — крошка после вычитания, не желоб


class ItemKind(StrEnum):
    """Что нарисовано на виде стены."""

    CHIMNEY = "chimney"
    GUTTER = "gutter"
    PIPE = "pipe"


@dataclass(frozen=True)
class Chimney:
    """Труба: четыре угла в плане, низ и верх."""

    footprint: list[Point]
    z0: float
    z1: float


@dataclass(frozen=True)
class Gutter:
    """Желоб: ось в плане от a к b, верх z, сечение size × size, сторона части и её наружная
    нормаль."""

    a: Point
    b: Point
    z: float
    size: float
    wall: tuple[Point, Point]
    normal: Point


@dataclass(frozen=True)
class Pipe:
    """Водосточная труба: ось на стене (план), верх z_top и низ 0; отвод — горизонтально от
    конца желоба `elbow` к трубе."""

    center: Point
    elbow: Point
    z_top: float
    diameter: float
    wall: tuple[Point, Point]
    normal: Point


@dataclass(frozen=True)
class Items:
    chimney: Chimney | None
    gutters: list[Gutter]
    pipes: list[Pipe]


def roof_items(sheet: FacadeSheet, cfg: RoofItemsLook) -> Items:
    """Труба и водосток дома по параметрам; крыша плоская или скатов нет — ничего."""
    house = roof.roofs(sheet)
    if house is None:
        return Items(None, [], [])
    return of_house(house, sheet.spec.chimney, sheet.spec.gutters, cfg)


def of_house(house: HouseRoof, chimney: float | None, gutters: bool, cfg: RoofItemsLook) -> Items:
    """Труба в доле `chimney` конька главной части (None — нет) и водосток (gutters)."""
    order = roof.own_parts(house)
    found = None if chimney is None else _chimney(house.parts[order[0]], chimney, cfg)
    made, pipes = _gutters(house, order, cfg) if gutters else ([], [])
    return Items(found, made, pipes)


# ——— труба ———

def ridge(line: Roofline) -> tuple[Point, Point, float] | None:
    """Конёк части: концы и высота. Начало — конец, ближний к углу 0 контура части. Скатов нет
    (плоская крыша) — None. Вальмовая пирамида — отрезок нулевой длины."""
    if not line.slopes:
        return None
    verts = [v for _, face in roof.faces(line, shapely.Polygon(line.corners)) for v in face]
    top = max(z for _, _, z in verts)
    high = {(round(x, 6), round(y, 6)) for x, y, z in verts if z >= top - EPS}
    a, b = max(((p, q) for p in high for q in high), key=lambda pq: math.dist(*pq))
    if math.dist(b, line.corners[0]) < math.dist(a, line.corners[0]) - EPS:
        a, b = b, a
    return a, b, top


def _chimney(line: Roofline, at: float, cfg: RoofItemsLook) -> Chimney | None:
    found = ridge(line)
    if found is None:
        return None
    a, b, top = found
    cx, cy = a[0] + at * (b[0] - a[0]), a[1] + at * (b[1] - a[1])
    if len(line.slopes) == 1:  # односкатная: конёк — кромка у стены, труба — внутрь от неё
        inward = line.slopes[0].inward
        cx, cy = cx - inward[0] * cfg.chimney_m / 2, cy - inward[1] * cfg.chimney_m / 2
    length = math.dist(a, b)
    u = ((b[0] - a[0]) / length, (b[1] - a[1]) / length) if length > EPS else (1.0, 0.0)
    h = cfg.chimney_m / 2
    ring = [(cx + sx * h * u[0] - sy * h * u[1], cy + sx * h * u[1] + sy * h * u[0])
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return Chimney(ring, min(line.height(p) for p in ring), top + cfg.chimney_over_m)


# ——— водосток ———

def _gutters(house: HouseRoof, order: list[int], cfg: RoofItemsLook
             ) -> tuple[list[Gutter], list[Pipe]]:
    gutters: list[Gutter] = []
    pipes: list[Pipe] = []
    for number in order:
        line = house.parts[number]
        cut = Cut(_others(house, order, number), gutters, cfg)
        for k in _eave_sides(line):
            for g, ends in _pieces(line, k, cut):
                gutters.append(g)
                pipes += [_pipe(g, end, cfg) for end in ends]
    return gutters, pipes


class Cut(NamedTuple):
    """Где желоб части не идёт (`_others`), что уже построено (желоба, у которых нет трубы на
    стыке) и настройки."""

    others: shapely.Geometry
    done: list[Gutter]
    cfg: RoofItemsLook


def _eave_sides(line: Roofline) -> list[int]:
    """Стороны части со скатом — карнизные (низ ската на стене)."""
    return [k for k, c in enumerate(line.corners)
            if any(math.dist(s.at, c) <= EPS for s in line.slopes)]


def _others(house: HouseRoof, order: list[int], number: int) -> shapely.Geometry:
    """Где желоб части не идёт: стены других частей и кровля главнее неё (под ней край свеса)."""
    mine, out = order.index(number), []
    for rank, j in enumerate(order):
        if j == number:
            continue
        line = house.parts[j]
        out.append(shapely.Polygon(line.corners).buffer(-EPS))
        if rank < mine:
            out.append(line.outline().buffer(-EPS))
    return shapely.union_all(out) if out else shapely.Polygon()


def _frame(line: Roofline, k: int) -> tuple[Point, Point, Point, float]:
    """Сторона k части: начало (угол k), направление к углу k+1, наружная нормаль и длина."""
    a, b = line.corners[k], line.corners[(k + 1) % len(line.corners)]
    length = math.dist(a, b)
    t = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
    sign = 1.0 if shapely.is_ccw(shapely.Polygon(line.corners).exterior) else -1.0
    return a, t, (sign * t[1], -sign * t[0]), length


def _edge(line: Roofline, k: int) -> shapely.LineString:
    """Край кровли над стороной k от угла до угла контура кровли (`Roofline.outline`): сторона,
    вынесенная на свес, продолженная на свесы соседних сторон."""
    over, n = line.side_overhangs(), len(line.corners)
    a, t, out, length = _frame(line, k)
    d, before, after = over[k], over[(k - 1) % n], over[(k + 1) % n]
    return shapely.LineString([
        (a[0] + out[0] * d - t[0] * before, a[1] + out[1] * d - t[1] * before),
        (a[0] + t[0] * (length + after) + out[0] * d, a[1] + t[1] * (length + after) + out[1] * d)])


def _lines(geometry: shapely.Geometry) -> list[shapely.LineString]:
    return [g for g in getattr(geometry, "geoms", [geometry])
            if isinstance(g, shapely.LineString) and g.length > KEEP_MIN_M]


def _ends(piece: shapely.LineString) -> tuple[Point, Point]:
    return piece.coords[0], piece.coords[-1]


def _pieces(line: Roofline, k: int, cut: Cut) -> list[tuple[Gutter, list[tuple[Point, bool]]]]:
    """Желоба на стороне k: свободные куски края свеса. Каждый — с концами, где нужна труба:
    (конец, внутри ли стороны). Кусок, что лёг на уже построенный желоб на той же высоте, у
    этого стыка трубы не получает."""
    a, t, out, _ = _frame(line, k)
    d = line.side_overhangs()[k]
    z = line.eaves - line.rise * d
    cfg = cut.cfg
    half = cfg.gutter_m / 2
    wall = (a, line.corners[(k + 1) % len(line.corners)])
    over = shapely.union_all([shapely.LineString([_edge_of(g, half)[0], _edge_of(g, half)[1]])
                              .buffer(EPS) for g in cut.done if abs(g.z - z) <= EPS]
                             or [shapely.Polygon()])
    result = []
    for free in _lines(_edge(line, k).difference(cut.others)):
        for piece in _lines(free.difference(over)):
            p, q = _ends(piece)
            if (q[0] - p[0]) * t[0] + (q[1] - p[1]) * t[1] < 0:
                p, q = q, p
            walled = [e for e in (p, q) if any(math.dist(e, f) <= 10 * EPS for f in _ends(free))]
            centre = [(x + out[0] * half, y + out[1] * half) for x, y in (p, q)]
            result.append((Gutter(centre[0], centre[1], z, cfg.gutter_m, wall, out),
                           [(e, e is p) for e in walled]))
    return result


def _edge_of(g: Gutter, half: float) -> tuple[Point, Point]:
    """Край свеса под осью желоба: ось сдвинута от него наружу на полсечения."""
    return tuple((x - g.normal[0] * half, y - g.normal[1] * half) for x, y in (g.a, g.b))


def _pipe(g: Gutter, end: tuple[Point, bool], cfg: RoofItemsLook) -> Pipe:
    """Труба у конца желоба: на стене в `pipe_inset_m` от угла (от конца желоба, если он упёрся в
    соседнюю часть), ось — на полдиаметра от стены наружу."""
    (x, y), first = end
    a, b = g.wall
    length = math.dist(a, b)
    t, out = ((b[0] - a[0]) / length, (b[1] - a[1]) / length), g.normal
    s = (x - a[0]) * t[0] + (y - a[1]) * t[1]
    s = max(s, 0.0) + cfg.pipe_inset_m if first else min(s, length) - cfg.pipe_inset_m
    r = cfg.pipe_m / 2
    centre = (a[0] + t[0] * s + out[0] * r, a[1] + t[1] * s + out[1] * r)
    elbow = (x + out[0] * cfg.gutter_m / 2, y + out[1] * cfg.gutter_m / 2)
    return Pipe(centre, elbow, g.z - cfg.gutter_m / 2, cfg.pipe_m, g.wall, g.normal)


# ——— на виде стены ———

def view(items: Items, corners: list[Point], k: int) -> list[tuple[ItemKind, Polygon]]:
    """Труба, желоба и трубы на виде стены k (x вдоль стены слева направо, y — высота): труба — вся;
    желоба и трубы — те, что на самой стене (у неё общая линия и наружная нормаль), и те, что
    смотрят на зрителя торцом (перпендикулярны стене) в передней половине дома: задние за домом.
    Порядок — как рисовать."""
    left, u, _ = roof.axis(corners, k)
    toward = (u[1], -u[0])

    def at(p: Point) -> tuple[float, float]:  # x вдоль стены, расстояние к зрителю от стены
        return (p[0] - left[0]) * u[0] + (p[1] - left[1]) * u[1], (
            (p[0] - left[0]) * toward[0] + (p[1] - left[1]) * toward[1])

    depth = [at(c)[1] for c in corners]
    front = (max(depth) + min(depth)) / 2
    out: list[tuple[ItemKind, Polygon]] = []
    if items.chimney is not None:
        xs = [at(p)[0] for p in items.chimney.footprint]
        out.append((ItemKind.CHIMNEY, _rect(min(xs), items.chimney.z0, max(xs), items.chimney.z1)))
    for g in items.gutters:
        (xa, da), (xb, db) = at(g.a), at(g.b)
        if _on_wall(g.wall, g.normal, at, toward):
            out.append((ItemKind.GUTTER, _rect(min(xa, xb), g.z - g.size, max(xa, xb), g.z)))
        elif abs(xa - xb) <= EPS and max(da, db) >= front:  # торцом: стена по длине желоба
            out.append((ItemKind.GUTTER,
                        _rect(xa - g.size / 2, g.z - g.size, xa + g.size / 2, g.z)))
    for p in items.pipes:
        x, d = at(p.center)
        if _on_wall(p.wall, p.normal, at, toward) or (
                abs(p.normal[0] * toward[0] + p.normal[1] * toward[1]) <= EPS and d >= front):
            out.append((ItemKind.PIPE, _rect(x - p.diameter / 2, 0.0, x + p.diameter / 2, p.z_top)))
    return out


def _on_wall(wall: tuple[Point, Point], normal: Point, at, toward: Point) -> bool:
    """Сторона части — на линии стены вида и смотрит туда же."""
    return (normal[0] * toward[0] + normal[1] * toward[1] > 1 - EPS
            and all(abs(at(p)[1]) <= EPS for p in wall))


def _rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def height(items: Items) -> float:
    """Высота верха трубы — для рамки листа; трубы нет — 0."""
    return items.chimney.z1 if items.chimney else 0.0
