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
Контур не из четырёх сторон — скатов нет (крыша пока плоская), валидатор предупреждает
(`Rule.ROOF_FLAT`): нижняя огибающая скатов от всех стен верна только для выпуклого контура, а
для Г-, Т-образного нужен прямой скелет.
"""

import math
from dataclasses import dataclass
from itertools import combinations

import shapely

from genfacade.plan.genplan_svg import PlanError
from genfacade.schema import EPS, FacadeSheet, Point, Polygon, RoofKind, Side
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
        return self.eaves + self.rise * min(s.depth(p) for s in self.slopes)


def roofline(sheet: FacadeSheet) -> Roofline | None:
    """Скаты дома; крыша плоская или контур не прямоугольник — None."""
    sides = [f.side for f in sheet.facades]
    roof = sheet.spec.roof
    if not builds(sheet):
        return None
    corners = plan_corners(sides)
    slopes = [Slope(corners[k], (-s.orientation[0], -s.orientation[1]))
              for k, s in enumerate(sides) if k in _eave_sides(sides, roof.kind)]
    rise = math.tan(math.radians(roof.pitch_deg))
    return Roofline(corners, slopes, sheet.spec.eaves_m, rise, roof.overhang_m)


def builds(sheet: FacadeSheet) -> bool:
    """Скаты строятся: контур — прямоугольник, и у вида крыши есть стены со скатами."""
    sides = [f.side for f in sheet.facades]
    return len(sides) == RECT_SIDES and bool(_eave_sides(sides, sheet.spec.roof.kind))


def eave_walls(sheet: FacadeSheet) -> set[int]:
    """Стены с карнизом — под нижним краем ската (`facade: Карниз под скатом`): у щипцовой стены
    и высокой стены односкатной крыши края ската нет, свес идёт по скату или торцом. Скатов нет
    (крыша плоская или контур не прямоугольник) — край крыши над всеми стенами."""
    sides = [f.side for f in sheet.facades]
    if not builds(sheet):
        return set(range(len(sides)))
    return _eave_sides(sides, sheet.spec.roof.kind)


def _eave_sides(sides: list[Side], kind: RoofKind) -> set[int]:
    """Стены прямоугольника, от которых идут скаты, по виду крыши; стороны 0, 2 и 1, 3 — пары
    напротив. Односкатная: низ — у длинной стены со входом, иначе у первой из длинных."""
    first = 0 if sides[0].length_m >= sides[1].length_m - EPS else 1  # пара длинных стен
    long = (first, first + 2)
    low = next((k for k in long if sides[k].has_entrance), first)
    return {RoofKind.FLAT: set(), RoofKind.HIP: set(range(RECT_SIDES)), RoofKind.GABLE: set(long),
            RoofKind.SHED: {low}}[kind]


def wall_axis(line: Roofline, k: int) -> tuple[Point, Point, float]:
    """Вид стены k: начало в плане (её левый край снаружи — угол k+1), единичное направление
    слева направо и длина."""
    n = len(line.corners)
    left, right = line.corners[(k + 1) % n], line.corners[k]
    length = math.dist(left, right)
    return left, ((right[0] - left[0]) / length, (right[1] - left[1]) / length), length


def above_eaves(line: Roofline, k: int) -> Polygon | None:
    """Стена k выше карниза — по высоте крыши над линией стены; не выше карниза — None."""
    left, u, length = wall_axis(line, k)

    def at(x: float) -> Point:
        return left[0] + u[0] * x, left[1] + u[1] * x

    xs = {0.0, length}
    for a, b in combinations(line.slopes, 2):  # где над стеной сменяется скат — излом верха
        gap0 = a.depth(at(0.0)) - b.depth(at(0.0))
        gap1 = a.depth(at(length)) - b.depth(at(length))
        if abs(gap1 - gap0) > EPS and EPS < (x := gap0 / (gap0 - gap1) * length) < length - EPS:
            xs.add(x)
    top = [(x, line.height(at(x))) for x in sorted(xs)]
    ring = [(0.0, line.eaves), *top, (length, line.eaves)]
    if max(y for _, y in top) - line.eaves <= EPS:
        return None
    return [p for p, q in zip(ring, ring[1:] + ring[:1], strict=True) if math.dist(p, q) > EPS]


def faces(line: Roofline) -> list[tuple[Slope, list[Point3]]]:
    """Скаты в объёме: у каждого — часть плана со свесом, где он ниже остальных; вершины —
    (x, y плана, высота)."""
    out = []
    for s in line.slopes:
        area = shapely.Polygon(line.corners).buffer(line.overhang, join_style="mitre")
        for other in (o for o in line.slopes if o is not s):
            area = area.intersection(_not_above(s, other))
        if area.area > EPS:
            ring = list(shapely.Polygon(area).exterior.coords)[:-1]
            out.append((s, [(x, y, line.eaves + line.rise * s.depth((x, y))) for x, y in ring]))
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
    toward = (u[1], -u[0])  # наружная нормаль стены k — к зрителю

    def project(p: Point3) -> Point:
        return (p[0] - left[0]) * u[0] + (p[1] - left[1]) * u[1], p[2]

    def facing(n: Point) -> bool:
        return n[0] * toward[0] + n[1] * toward[1] > EPS

    pieces = []
    for slope, face in faces(line):
        if facing((-slope.inward[0], -slope.inward[1])):
            pieces.append([(x, y, z + thickness) for x, y, z in face])
        pieces += [[a, b, (*b[:2], b[2] + thickness), (*a[:2], a[2] + thickness)]
                   for a, b in _edges(face) if facing(_outward(a, b, face))]
    flat = [shapely.Polygon([project(p) for p in piece]) for piece in pieces]
    shape = shapely.union_all([p.buffer(0) for p in flat if p.area > EPS])
    return [list(g.exterior.coords)[:-1] for g in getattr(shape, "geoms", [shape]) if g.area > EPS]


def _edges(face: list[Point3]) -> list[tuple[Point3, Point3]]:
    return list(zip(face, face[1:] + face[:1], strict=True))


def _outward(a: Point3, b: Point3, face: list[Point3]) -> Point:
    """Нормаль кромки ската ab в плане — наружу от ската."""
    area = sum(p[0] * q[1] - q[0] * p[1] for p, q in _edges(face))  # > 0 — обход против часовой
    dx, dy = b[0] - a[0], b[1] - a[1]
    return (dy, -dx) if area > 0 else (-dy, dx)


# ——— фронтон: стена выше карниза как место окон (gf#321) ———

def gables(sheet: FacadeSheet) -> list[Polygon | None]:
    """Стена выше карниза у каждой стороны листа — зона фронтона, где бывают окна этажа под
    скатом; скаты не строятся, контур не обходится или у стены нет части выше карниза — None
    (контур отклоняет развёртка, валидатор и метрики листа на нём не падают)."""
    try:
        line = roofline(sheet)
    except PlanError:
        line = None
    return [None if line is None else above_eaves(line, k) for k in range(len(sheet.facades))]


def peaks(above: Polygon, eaves: float) -> list[Point]:
    """Вершины верха стены выше карниза слева направо: у щипца двускатной — конёк; с ними и длиной
    стены зона фронтона восстанавливается (низ — карниз от края до края)."""
    return [p for p in above if p[1] > eaves + EPS]


def slopes(above: Polygon, eaves: float) -> list[tuple[Point, Point]]:
    """Кромки ската на стене: стороны зоны фронтона, кроме низа по карнизу и вертикальных краёв
    стены."""
    pairs = zip(above, above[1:] + above[:1], strict=True)
    return [(a, b) for a, b in pairs
            if abs(a[0] - b[0]) > EPS
            and not (abs(a[1] - eaves) <= EPS and abs(b[1] - eaves) <= EPS)]


def wall_shape(length: float, eaves: float, above: Polygon | None) -> shapely.Geometry:
    """Стена целиком: прямоугольник до карниза и зона фронтона над ним."""
    wall = shapely.box(0.0, 0.0, length, eaves)
    return wall if above is None else wall.union(shapely.Polygon(above))


def room(length: float, eaves: float, above: Polygon | None, offset: float) -> shapely.Geometry:
    """Где может стоять окно: стена целиком без полосы шириной offset вдоль ската."""
    wall = wall_shape(length, eaves, above)
    if above is None or offset <= 0:
        return wall
    band = shapely.union_all([shapely.LineString(e).buffer(offset, cap_style="flat")
                              for e in slopes(above, eaves)])
    return wall.difference(band)
