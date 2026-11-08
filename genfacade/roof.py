"""Крыша дома (gf#320): скаты над прямоугольным контуром — для листа (шаг 6) и дома объёмом.

Скат — плоскость, которая поднимается от карнизной кромки (линии стены на высоте карниза) внутрь
дома с уклоном крыши; за стену она продолжается свесом и опускается. Крыша — нижняя огибающая
скатов: высота над точкой плана — меньшая из высот всех скатов. Вид крыши задаёт, от каких стен
идут скаты: двускатная — от двух длинных, вальмовая — от всех, односкатная — от одной длинной.
Так фронтоны, вальмы и конёк получаются сами, а соседние фасады сходятся на углу по построению:
высота над углом одна для обеих стен (`facade: Общие параметры дома`).

Модель шага 4 крыши не касается: её стена — силуэт до карниза. Отсюда только то, что рисуется
выше: стена над карнизом (фронтон, верх стены под односкатной крышей) и кровля на виде. В JSON
листа их нет: их однозначно задают крыша дома (HouseSpec) и план, лист и дом объёмом считают здесь.
Контур не из четырёх сторон и без частей — скатов нет (крыша плоская), валидатор предупреждает
(`Rule.ROOF_FLAT`): нижняя огибающая скатов от всех стен верна только для выпуклого контура, а
для Г-, Т-образного нужен прямой скелет.

Дом из частей разной высоты (gf#322, `facade: Части дома`): у каждого крыла контура своя крыша
вида дома, как у отдельного прямоугольного дома, с карнизом части. Крыша части обрывается на
стене соседа: её площадь — крыло со свесом без других крыльев (`_area`). Стена более высокой
части над крышей нижней — `joints`: на листе её видно со стороны нижней части, линия примыкания —
по кровле нижней.
"""

import math
from dataclasses import dataclass
from itertools import combinations
from typing import NamedTuple

import shapely

from genfacade.parts import stepped
from genfacade.plan.wings import wings
from genfacade.schema import EPS, FacadeSheet, OpeningKind, Point, Polygon, RoofKind
from genfacade.unfold import plan_corners

RECT_SIDES = 4
FAR = 1e4  # полуплоскость отсечения — полоса такой длины, метров: больше любого дома

Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class Slope:
    """Скат от стены: кромка проходит через угол `at`, `inward` — нормаль стены внутрь дома."""

    at: Point
    inward: Point

    def depth(self, p: Point) -> float:
        """Насколько точка плана глубже кромки внутрь дома (за стеной — меньше нуля)."""
        return (p[0] - self.at[0]) * self.inward[0] + (p[1] - self.at[1]) * self.inward[1]


@dataclass(frozen=True)
class Roofline:
    """Скаты дома: углы контура в плане, карниз, рост высоты на метр глубины, свес."""

    corners: list[Point]
    slopes: list[Slope]
    eaves: float
    rise: float
    overhang: float

    def height(self, p: Point) -> float:
        return self.eaves + self.rise * min((s.depth(p) for s in self.slopes), default=0.0)


def roofline(sheet: FacadeSheet) -> Roofline | None:
    """Скаты прямоугольного дома; крыша плоская, контур не прямоугольник или дом из частей — None
    (дом из частей — `roofs`)."""
    sides = [f.side for f in sheet.facades]
    roof = sheet.spec.roof
    if stepped(sheet) or not builds(sheet):
        return None
    corners = plan_corners(sides)
    eaves = _eave_sides([s.length_m for s in sides], [s.has_entrance for s in sides], roof.kind)
    slopes = [Slope(corners[k], (-s.orientation[0], -s.orientation[1]))
              for k, s in enumerate(sides) if k in eaves]
    rise = math.tan(math.radians(roof.pitch_deg))
    return Roofline(corners, slopes, sheet.spec.eaves_m, rise, roof.overhang_m)


def builds(sheet: FacadeSheet) -> bool:
    """Скаты строятся: вид крыши скатный и контур — прямоугольник или дом из частей."""
    kind = sheet.spec.roof.kind
    if stepped(sheet):
        return kind is not RoofKind.FLAT
    sides = [f.side for f in sheet.facades]
    return len(sides) == RECT_SIDES and bool(_eave_sides(
        [s.length_m for s in sides], [s.has_entrance for s in sides], kind))


def eave_walls(sheet: FacadeSheet) -> set[int]:
    """Стены с карнизом — под нижним краем ската (`facade: Карниз под скатом`): у щипцовой стены
    и высокой стены односкатной крыши края ската нет, свес идёт по скату или торцом. Скатов нет
    (крыша плоская или контур не прямоугольник) — край крыши над всеми стенами. У дома из частей
    стена с карнизом, если у любой её части скат идёт от этой стены."""
    sides = [f.side for f in sheet.facades]
    if not builds(sheet):
        return set(range(len(sides)))
    if stepped(sheet):
        house = roofs(sheet)
        return {k for k, f in enumerate(sheet.facades) if any(
            math.dist(s.inward, (-f.side.orientation[0], -f.side.orientation[1])) <= EPS
            for span in house.spans[k] for s in house.parts[span.part].slopes)}
    return _eave_sides([s.length_m for s in sides], [s.has_entrance for s in sides],
                       sheet.spec.roof.kind)


def _eave_sides(lengths: list[float], entrances: list[bool], kind: RoofKind) -> set[int]:
    """Стены прямоугольника, от которых идут скаты, по виду крыши; стороны 0, 2 и 1, 3 — пары
    напротив. Односкатная: низ — у длинной стены со входом, иначе у первой из длинных."""
    first = 0 if lengths[0] >= lengths[1] - EPS else 1  # пара длинных стен
    long = (first, first + 2)
    low = next((k for k in long if entrances[k]), first)
    return {RoofKind.FLAT: set(), RoofKind.HIP: set(range(RECT_SIDES)), RoofKind.GABLE: set(long),
            RoofKind.SHED: {low}}[kind]


def wall_axis(line: Roofline, k: int) -> tuple[Point, Point, float]:
    """Вид стены k: начало в плане (её левый край снаружи — угол k+1), единичное направление
    слева направо и длина."""
    return axis(line.corners, k)


def axis(corners: list[Point], k: int) -> tuple[Point, Point, float]:
    n = len(corners)
    left, right = corners[(k + 1) % n], corners[k]
    length = math.dist(left, right)
    return left, ((right[0] - left[0]) / length, (right[1] - left[1]) / length), length


def above_eaves(line: Roofline, k: int) -> Polygon | None:
    """Стена k выше карниза — по высоте крыши над линией стены; не выше карниза — None."""
    left, u, length = wall_axis(line, k)
    return _above(line, left, u, 0.0, length)


def _breaks(line: Roofline, at, x0: float, x1: float) -> list[float]:
    """Где на отрезке [x0, x1] линии at(x) над домом сменяется скат — излом верха; с концами."""
    xs = {x0, x1}
    for a, b in combinations(line.slopes, 2):
        gap0 = a.depth(at(x0)) - b.depth(at(x0))
        gap1 = a.depth(at(x1)) - b.depth(at(x1))
        if abs(gap1 - gap0) > EPS and x0 + EPS < (
                x := x0 + gap0 / (gap0 - gap1) * (x1 - x0)) < x1 - EPS:
            xs.add(x)
    return sorted(xs)


def _above(line: Roofline, left: Point, u: Point, x0: float, x1: float) -> Polygon | None:
    """Стена над карнизом на участке [x0, x1] стены (начало left, направление u)."""
    def at(x: float) -> Point:
        return left[0] + u[0] * x, left[1] + u[1] * x

    top = [(x, line.height(at(x))) for x in _breaks(line, at, x0, x1)]
    ring = [(x0, line.eaves), *top, (x1, line.eaves)]
    if max(y for _, y in top) - line.eaves <= EPS:
        return None
    return [p for p, q in zip(ring, ring[1:] + ring[:1], strict=True) if math.dist(p, q) > EPS]


def faces(line: Roofline, base: shapely.Geometry | None = None
          ) -> list[tuple[Slope, list[Point3]]]:
    """Скаты в объёме: у каждого — часть плана со свесом, где он ниже остальных; вершины —
    (x, y плана, высота). base — площадь крыши вместо контура со свесом (дом из частей)."""
    out = []
    if base is None:
        base = shapely.Polygon(line.corners).buffer(line.overhang, join_style="mitre")
    for s in line.slopes:
        area = base
        for other in (o for o in line.slopes if o is not s):
            area = area.intersection(_not_above(s, other))
        for piece in getattr(area, "geoms", [area]):
            if isinstance(piece, shapely.Polygon) and piece.area > EPS:
                ring = list(shapely.Polygon(piece).exterior.coords)[:-1]
                out.append((s, [(x, y, line.eaves + line.rise * s.depth((x, y)))
                                for x, y in ring]))
    return out


def _not_above(s: Slope, other: Slope) -> shapely.Polygon:
    """Полуплоскость, где скат s не выше ската other: (n_s − n_o)·p ≤ n_s·a_s − n_o·a_o."""
    n = (s.inward[0] - other.inward[0], s.inward[1] - other.inward[1])
    c = s.inward[0] * s.at[0] + s.inward[1] * s.at[1] - (
        other.inward[0] * other.at[0] + other.inward[1] * other.at[1])
    size = math.hypot(*n)
    if size <= EPS:  # скаты параллельны в одну сторону — у прямоугольника не бывает
        raise ValueError("два ската от параллельных стен с одной стороны")
    unit = (n[0] / size, n[1] / size)
    on = (unit[0] * c / size, unit[1] * c / size)  # точка на границе
    along = (-unit[1] * FAR, unit[0] * FAR)
    back = (-unit[0] * FAR, -unit[1] * FAR)
    return shapely.Polygon([
        (on[0] + along[0], on[1] + along[1]), (on[0] - along[0], on[1] - along[1]),
        (on[0] - along[0] + back[0], on[1] - along[1] + back[1]),
        (on[0] + along[0] + back[0], on[1] + along[1] + back[1])])


def roof_view(line: Roofline, k: int, thickness: float) -> list[Polygon]:
    """Кровля на виде стены k: скат, обращённый к зрителю, и торцы кровли толщиной `thickness`,
    повёрнутые к нему (на фронтоне скат виден с ребра — полосой). Скат, уходящий от зрителя, —
    за стеной. Многоугольники в метрах вида: x от левого края стены, y — высота."""
    left, u, _ = wall_axis(line, k)
    return _polygons(_projected(faces(line), left, u, thickness))


def _on_view(p: Point3, left: Point, u: Point) -> Point:
    """Точка объёма на виде стены (начало left, направление u): x вдоль стены, y — высота."""
    return (p[0] - left[0]) * u[0] + (p[1] - left[1]) * u[1], p[2]


def _projected(items: list[tuple[Slope, list[Point3]]], left: Point, u: Point, thickness: float
               ) -> shapely.Geometry:
    """Кровля скатов items на виде стены (начало left, направление u): союз проекций."""
    toward = (u[1], -u[0])  # наружная нормаль стены — к зрителю

    def facing(n: Point) -> bool:
        return n[0] * toward[0] + n[1] * toward[1] > EPS

    pieces = []
    for slope, face in items:
        if facing((-slope.inward[0], -slope.inward[1])):
            pieces.append([(x, y, z + thickness) for x, y, z in face])
        pieces += [[a, b, (*b[:2], b[2] + thickness), (*a[:2], a[2] + thickness)]
                   for a, b in _edges(face) if facing(_outward(a, b, face))]
    flat = [shapely.Polygon([_on_view(p, left, u) for p in piece]) for piece in pieces]
    return shapely.union_all([p.buffer(0) for p in flat if p.area > EPS])


def _polygons(shape: shapely.Geometry) -> list[Polygon]:
    return [list(g.exterior.coords)[:-1] for g in getattr(shape, "geoms", [shape])
            if isinstance(g, shapely.Polygon) and g.area > EPS]


def _edges(face: list[Point3]) -> list[tuple[Point3, Point3]]:
    return list(zip(face, face[1:] + face[:1], strict=True))


def _outward(a: Point3, b: Point3, face: list[Point3]) -> Point:
    """Нормаль кромки ската ab в плане — наружу от ската."""
    area = sum(p[0] * q[1] - q[0] * p[1] for p, q in _edges(face))  # > 0 — обход против часовой
    dx, dy = b[0] - a[0], b[1] - a[1]
    return (dy, -dx) if area > 0 else (-dy, dx)


# ——— Дом из частей разной высоты (gf#322) ———


class Span(NamedTuple):
    """Участок стены: [x0, x1] вдоль стены от левого края, номер части."""

    x0: float
    x1: float
    part: int


@dataclass(frozen=True)
class HouseRoof:
    """Крыша дома: контур, скаты каждой части (прямоугольный дом — одна часть) и участки сторон."""

    corners: list[Point]
    parts: list[Roofline]
    spans: list[list[Span]]


def roofs(sheet: FacadeSheet) -> HouseRoof | None:
    """Скаты дома — прямоугольного и из частей; крыша плоская или скатов не построить — None."""
    if (line := roofline(sheet)) is not None:
        return HouseRoof(line.corners, [line], [
            [Span(0.0, wall_axis(line, k)[2], 0)] for k in range(RECT_SIDES)])
    if not (stepped(sheet) and builds(sheet)):
        return None
    sides = [f.side for f in sheet.facades]
    corners = plan_corners(sides)
    spec = sheet.spec
    rise = math.tan(math.radians(spec.roof.pitch_deg))
    eaves = {r.part: r.eaves_m for f in sheet.facades for r in f.runs}
    rects = wings(corners)
    lines = [_part_line(sheet, k, w, eaves[k], rise,
                        [r for j, r in enumerate(rects) if eaves[j] > eaves[k] + EPS])
             for k, w in enumerate(rects)]
    return HouseRoof(corners, lines, [[Span(r.x0_m, r.x1_m, r.part) for r in f.runs]
                                      for f in sheet.facades])


def _part_line(sheet: FacadeSheet, part: int, w, eaves: float, rise: float,
               taller: list) -> Roofline:
    """Скаты крыла w как отдельного прямоугольного дома: углы по часовой, сторона k идёт от
    угла k к k+1; вход на стороне — если он на участке этой части с такой наружной нормалью.
    Скат не идёт от стены, на которую крыло опирается более высокая часть (taller): кровля
    поднимается к этой стене и примыкает к ней выше карниза (пристройка «в один скат»); если
    скатов не осталось — вид крыши как есть."""
    corners = [(w.x0_m, w.y1_m), (w.x1_m, w.y1_m), (w.x1_m, w.y0_m), (w.x0_m, w.y0_m)]
    normals = [(0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0)]
    entrance = [any(_entrance_on(f, part) for f in sheet.facades
                    if math.dist(f.side.orientation, n) <= EPS) for n in normals]
    lengths = [w.x1_m - w.x0_m, w.y1_m - w.y0_m] * 2
    on = _eave_sides(lengths, entrance, sheet.spec.roof.kind)
    butts = {k for k in on if any(shapely.LineString([corners[k], corners[(k + 1) % 4]])
                                  .intersection(shapely.box(r.x0_m, r.y0_m, r.x1_m, r.y1_m)
                                                ).length > EPS for r in taller)}
    on = on - butts or on
    slopes = [Slope(corners[k], (-n[0], -n[1])) for k, n in enumerate(normals) if k in on]
    if min(lengths[:2]) <= sheet.spec.roof.overhang_m:  # уже собственного свеса — уступ контура
        slopes = []  # (у разметки — шум в сантиметры): крыши у него нет, он под соседними
    return Roofline(corners, slopes, eaves, rise, sheet.spec.roof.overhang_m)


def _entrance_on(facade, part: int) -> bool:
    return any(o.kind is OpeningKind.ENTRANCE and r.x0_m - EPS <= o.x_m
               and o.x_m + o.width_m <= r.x1_m + EPS
               for r in facade.runs if r.part == part for o in facade.side.openings)


def _area(house: HouseRoof, k: int) -> shapely.Geometry:
    """Площадь крыши части k: крыло со свесом без других крыльев — крыша обрывается на их стенах;
    свес не лежит под свесом более высокой части (при равных — части с меньшим номером)."""
    me = house.parts[k]
    rect = shapely.Polygon(me.corners)
    area = rect.buffer(me.overhang, join_style="mitre")
    for j, other in enumerate(house.parts):
        if j != k:
            area = area.difference(shapely.Polygon(other.corners))
    for j, other in enumerate(house.parts):
        if j != k and (other.eaves, -j) > (me.eaves, -k):
            area = area.difference(shapely.Polygon(other.corners).buffer(
                other.overhang, join_style="mitre"))
    return area.union(rect)


def house_above(house: HouseRoof, k: int) -> list[Polygon]:
    """Стена k выше карниза: по участку каждой части — фронтон или верх стены под односкатной."""
    left, u, _ = axis(house.corners, k)
    shapes = (_above(house.parts[s.part], left, u, s.x0, s.x1) for s in house.spans[k])
    return [shape for shape in shapes if shape is not None]


def house_faces(house: HouseRoof) -> list[list[Point3]]:
    """Скаты всех частей в объёме."""
    if len(house.parts) == 1:
        return [face for _, face in faces(house.parts[0])]
    return [face for k, line in enumerate(house.parts) for _, face in faces(line, _area(house, k))]


def house_view(house: HouseRoof, k: int, thickness: float) -> list[Polygon]:
    """Кровля на виде стены k: частей, что стоят на ней, и более высоких частей за примыканиями,
    видимыми с неё. Часть, которую заслоняет стена более близкой части, не видна ниже её карниза;
    видна кровля лишь в пределах стены и свеса (за ним лист не рисуется)."""
    if len(house.parts) == 1:
        return roof_view(house.parts[0], k, thickness)
    left, u, length = axis(house.corners, k)
    toward = (u[1], -u[0])

    def front(line: Roofline) -> float:
        return max(c[0] * toward[0] + c[1] * toward[1] for c in line.corners)

    window = shapely.box(-house.parts[0].overhang, -1.0, length + house.parts[0].overhang, FAR)
    shapes = []
    shown = {s.part for s in house.spans[k]} | {
        j.high for j in joints(house) if j.normal[0] * toward[0] + j.normal[1] * toward[1] > EPS}
    for p, line in ((p, line) for p, line in enumerate(house.parts) if p in shown):
        shape = _projected(faces(line, _area(house, p)), left, u, thickness)
        for q in (q for q in house.parts if front(q) > front(line) + EPS):
            xs = [(c[0] - left[0]) * u[0] + (c[1] - left[1]) * u[1] for c in q.corners]
            shape = shape.difference(shapely.box(min(xs), -1.0, max(xs), q.eaves))
        shapes.append(shape)
    return _polygons(shapely.union_all(shapes).intersection(window))


class Joint(NamedTuple):
    """Стена более высокой части над крышей нижней: наружная нормаль стены (в сторону нижней
    части), стена в объёме кусками (x, y плана, высота) и линия примыкания кровли к ней."""

    normal: Point
    walls: list[list[Point3]]
    seam: list[Point3]
    high: int  # номер более высокой части


def joints(house: HouseRoof) -> list[Joint]:
    """Примыкания: общая стена нижней части и более высокой — от кровли нижней до верха стены
    верхней (карниз, у щипцовой стены — фронтон)."""
    out = []
    for low in house.parts:
        for h, high in ((h, p) for h, p in enumerate(house.parts) if p.eaves > low.eaves + EPS):
            shared = shapely.Polygon(low.corners).intersection(shapely.Polygon(high.corners))
            out += [_joint(low, high, h, list(seg.coords))
                    for seg in getattr(shared, "geoms", [shared])
                    if isinstance(seg, shapely.LineString) and seg.length > EPS]
    return out


def _joint(low: Roofline, high: Roofline, number: int, ends: list[Point]) -> Joint:
    (x0, y0), (x1, y1) = ends[0], ends[-1]
    length = math.dist(ends[0], ends[-1])
    u = ((x1 - x0) / length, (y1 - y0) / length)

    def at(x: float) -> Point:
        return x0 + u[0] * x, y0 + u[1] * x

    xs = sorted(set(_breaks(low, at, 0.0, length)) | set(_breaks(high, at, 0.0, length)))
    bottom = [(*at(x), min(low.height(at(x)), high.height(at(x)))) for x in xs]
    top = [(*at(x), high.height(at(x))) for x in xs]
    mid = at(length / 2)
    centre = shapely.Polygon(high.corners).centroid
    normal = (u[1], -u[0])  # от верхней части к нижней
    if (mid[0] - centre.x) * normal[0] + (mid[1] - centre.y) * normal[1] < 0:
        normal = (-normal[0], -normal[1])
    walls = [[bottom[i], bottom[i + 1], top[i + 1], top[i]] for i in range(len(xs) - 1)]
    return Joint(normal, walls, bottom, number)


def joint_view(house: HouseRoof, k: int) -> tuple[list[Polygon], list[list[Point]]]:
    """Примыкания на виде стены k: стена верхней части над крышей нижней (многоугольники) и линия
    примыкания; видны с той стороны, куда смотрит стена k, в пределах стены."""
    left, u, length = axis(house.corners, k)
    toward = (u[1], -u[0])
    window = shapely.box(0.0, -1.0, length, FAR)
    walls, seams = [], []
    for joint in joints(house):
        if joint.normal[0] * toward[0] + joint.normal[1] * toward[1] <= EPS:
            continue

        shape = shapely.union_all([shapely.Polygon([_on_view(p, left, u) for p in w]).buffer(0)
                                   for w in joint.walls]).intersection(window)
        walls += _polygons(shape)
        line = shapely.LineString([_on_view(p, left, u) for p in joint.seam]).intersection(window)
        seams += [list(g.coords) for g in getattr(line, "geoms", [line])
                  if isinstance(g, shapely.LineString) and g.length > EPS]
    return walls, seams
