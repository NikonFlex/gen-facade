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
стене более высокого соседа: площадь — крыло со свесом, свес не режется (`_area`). Стена более
высокой части над крышей нижней — `joints`: на листе её видно со стороны нижней части, линия
примыкания — по кровле нижней.
"""

import dataclasses
import math
from dataclasses import dataclass
from itertools import combinations
from typing import NamedTuple

import shapely

from genfacade.parts import parts_of, stepped
from genfacade.plan.genplan_svg import PlanError
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FacadeSheet,
    ForbiddenZone,
    OpeningKind,
    Point,
    Polygon,
    Roof,
    RoofKind,
    WallGable,
)
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
    eaves = _eave_sides(*_walls(sheet), roof)
    slopes = [Slope(corners[k], (-s.orientation[0], -s.orientation[1]))
              for k, s in enumerate(sides) if k in eaves]
    rise = math.tan(math.radians(roof.pitch_deg))
    return Roofline(corners, slopes, sheet.spec.eaves_m, rise, roof.overhang_m)


def builds(sheet: FacadeSheet) -> bool:
    """Скаты строятся: контур — прямоугольник со скатной крышей дома или дом из частей, у одной из
    которых крыша скатная."""
    if stepped(sheet):
        return any(r.kind is not RoofKind.FLAT for r in sheet.roofs or [sheet.spec.roof])
    return len(sheet.facades) == RECT_SIDES and bool(_eave_sides(*_walls(sheet), sheet.spec.roof))


def part_roof(sheet: FacadeSheet, part: int) -> Roof:
    """Крыша части: своя у листа, без неё — крыша дома (`facade: Крыша над частями дома`)."""
    return sheet.roofs[part] if sheet.roofs else sheet.spec.roof


def _walls(sheet: FacadeSheet) -> tuple[list[float], list[bool], list[Point]]:
    """Длины, входы и наружные нормали сторон листа — для `_eave_sides`."""
    sides = [f.side for f in sheet.facades]
    return [s.length_m for s in sides], [s.has_entrance for s in sides], [s.orientation
                                                                           for s in sides]


def eave_walls(sheet: FacadeSheet) -> set[int]:
    """Стены с карнизом — под нижним краем ската (`facade: Карниз под скатом`): у щипцовой стены
    и высокой стены односкатной крыши края ската нет, свес идёт по скату или торцом. Скатов нет
    (крыша плоская или контур не прямоугольник) — край крыши над всеми стенами. У дома из частей
    стена с карнизом, если у любой её части скат идёт от этой стены."""
    if not builds(sheet):
        return set(range(len(sheet.facades)))
    if stepped(sheet):
        house = roofs(sheet)
        return {k for k, f in enumerate(sheet.facades) if any(
            math.dist(s.inward, (-f.side.orientation[0], -f.side.orientation[1])) <= EPS
            for span in house.spans[k] for s in house.parts[span.part].slopes)}
    return _eave_sides(*_walls(sheet), sheet.spec.roof)


def _eave_sides(lengths: list[float], entrances: list[bool], normals: list[Point], roof: Roof
                ) -> set[int]:
    """Стены прямоугольника, от которых идут скаты (`facade: Направление ската`); стороны 0, 2 и
    1, 3 — пары напротив, normals — их наружные нормали. С направлением крыши низ ската — на стене,
    что смотрит в его сторону, у двускатной — и на стене напротив. Без него двускатная — от длинных
    стен, односкатная — низ у длинной стены со входом, иначе у первой из длинных."""
    if roof.down_to is not None:
        to = roof.down_to.normal
        down = max(range(RECT_SIDES), key=lambda k: normals[k][0] * to[0] + normals[k][1] * to[1])
        return {down, (down + 2) % RECT_SIDES} if roof.kind is RoofKind.GABLE else {down}
    first = 0 if lengths[0] >= lengths[1] - EPS else 1  # пара длинных стен
    long = (first, first + 2)
    low = next((k for k in long if entrances[k]), first)
    return {RoofKind.FLAT: set(), RoofKind.HIP: set(range(RECT_SIDES)), RoofKind.GABLE: set(long),
            RoofKind.SHED: {low}}[roof.kind]


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


def _walker(left: Point, u: Point):
    """Точка линии (начало left, направление u) по расстоянию x вдоль неё."""
    return lambda x: (left[0] + u[0] * x, left[1] + u[1] * x)


def _above(line: Roofline, left: Point, u: Point, x0: float, x1: float) -> Polygon | None:
    """Стена над карнизом на участке [x0, x1] стены (начало left, направление u)."""
    at = _walker(left, u)
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
    if math.hypot(*n) <= EPS:  # скаты параллельны в одну сторону — у прямоугольника не бывает
        raise ValueError("два ската от параллельных стен с одной стороны")
    return _halfplane(n, c)


def _halfplane(n: Point, c: float) -> shapely.Polygon:
    """Полуплоскость n·p ≤ c (n ненулевой) — полосой длины FAR."""
    size = math.hypot(*n)
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
    """Многоугольники фигуры; кольцо с канонической вершины — не зависит от порядка частей."""
    return [list(shapely.normalize(g).exterior.coords)[:-1]
            for g in getattr(shape, "geoms", [shape])
            if isinstance(g, shapely.Polygon) and g.area > EPS]


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
    скатом; скаты не строятся, контур не обходится, дом из частей (gf#322: в синтетике обучения
    таких нет, условие модели — как при обучении) или у стены нет части выше карниза — None
    (контур отклоняет развёртка, валидатор и метрики листа на нём не падают)."""
    try:
        line = roofline(sheet)
    except PlanError:
        line = None
    return [None if line is None else above_eaves(line, k) for k in range(len(sheet.facades))]


def under_roof(e: Element, floors: int) -> bool:
    """Элемент этажа под скатом — окно во фронтоне и его выводимые элементы — по записи: этаж
    `floors + 1` ставят сборщик разметки, синтетика и модель, по нему ведут себя привязка, уровни
    и раскладка синтетики. Проверки и метрики поле этажа не читают — им `over_eaves`."""
    return (e.floor or 1) > floors


def over_eaves(e: Element, eaves: float) -> bool:
    """Окно во фронтоне по геометрии: верх выше карниза (стену проверяет вызывающий). Так его
    видят валидатор, метрики и дом объёмом: поле этажа пишет сам метод."""
    return e.cls is ElementClass.WINDOW and e.y_m + e.h_m > eaves + EPS


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
# ——— Дом из частей разной высоты (gf#322) ———


class Span(NamedTuple):
    """Участок стены: [x0, x1] вдоль стены от левого края, номер части."""

    x0: float
    x1: float
    part: int


class Extension(NamedTuple):
    """Кровля части `part`, продолженная над соседней частью `into` (поперечный щипец, gf#431):
    zone — площадь продолжения в плане; в ней видна та из двух кровель, что выше."""

    part: int
    into: int
    zone: shapely.Polygon


@dataclass(frozen=True)
class HouseRoof:
    """Крыша дома: контур, скаты каждой части (прямоугольный дом — одна часть), участки сторон и
    продолжения кровель над соседними частями."""

    corners: list[Point]
    parts: list[Roofline]
    spans: list[list[Span]]
    extensions: tuple[Extension, ...] = ()


def roofs(sheet: FacadeSheet) -> HouseRoof | None:
    """Скаты дома — прямоугольного и из частей, со щипцами над карнизными стенами
    (`wall_gables`); крыша плоская или скатов не построить — None."""
    house = _parts_roof(sheet)
    if house is None or not sheet.wall_gables:
        return house
    lines, through = list(house.parts), list(house.extensions)
    for g in sheet.wall_gables:
        if (found := _wall_gable(house, g)) is not None:
            through.append(Extension(len(lines), found[1], found[2]))
            lines.append(found[0])
    return dataclasses.replace(house, parts=lines, extensions=tuple(through))


def _parts_roof(sheet: FacadeSheet) -> HouseRoof | None:
    """Скаты дома без щипцов над карнизными стенами."""
    if (line := roofline(sheet)) is not None:
        return HouseRoof(line.corners, [line], [
            [Span(0.0, wall_axis(line, k)[2], 0)] for k in range(RECT_SIDES)])
    if not (stepped(sheet) and builds(sheet)):
        return None
    corners = plan_corners([f.side for f in sheet.facades])
    eaves = {r.part: r.eaves_m for f in sheet.facades for r in f.runs}
    rects = parts_of(sheet, corners)
    lines = [_part_line(sheet, k, w, eaves[k],
                        [r for j, r in enumerate(rects) if eaves[j] > eaves[k] + EPS])
             for k, w in enumerate(rects)]
    return HouseRoof(corners, lines, [[Span(r.x0_m, r.x1_m, r.part) for r in f.runs]
                                      for f in sheet.facades], _extensions(lines))


def _part_line(sheet: FacadeSheet, part: int, w, eaves: float, taller: list) -> Roofline:
    """Скаты крыла w крышей части (`part_roof`) как отдельного прямоугольного дома: углы по
    часовой, сторона k идёт от угла k к k+1; вход на стороне — если он на участке этой части с
    такой наружной нормалью. Без направления крыши скат не идёт от стены, на которую крыло
    опирается более высокая часть (taller): кровля поднимается к этой стене и примыкает к ней выше
    карниза (пристройка «в один скат»); если скатов не осталось — вид крыши как есть. Заданное
    направление — как на чертеже, без поправки."""
    roof = part_roof(sheet, part)
    corners = [(w.x0_m, w.y1_m), (w.x1_m, w.y1_m), (w.x1_m, w.y0_m), (w.x0_m, w.y0_m)]
    normals = [(0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0)]
    entrance = [any(_entrance_on(f, part) for f in sheet.facades
                    if math.dist(f.side.orientation, n) <= EPS) for n in normals]
    lengths = [w.x1_m - w.x0_m, w.y1_m - w.y0_m] * 2
    on = _eave_sides(lengths, entrance, normals, roof)
    if roof.down_to is None:
        butts = {k for k in on if any(shapely.LineString([corners[k], corners[(k + 1) % 4]])
                                      .intersection(shapely.box(r.x0_m, r.y0_m, r.x1_m, r.y1_m)
                                                    ).length > EPS for r in taller)}
        on = _off_walls(on, butts, roof.kind)
    slopes = [Slope(corners[k], (-n[0], -n[1])) for k, n in enumerate(normals) if k in on]
    if min(lengths[:2]) <= roof.overhang_m:  # уже собственного свеса — уступ контура
        slopes = []  # (у разметки — шум в сантиметры): крыши у него нет, он под соседними
    return Roofline(corners, slopes, eaves, math.tan(math.radians(roof.pitch_deg)),
                    roof.overhang_m)


def _off_walls(on: set[int], butts: set[int], kind: RoofKind) -> set[int]:
    """Стены карниза без тех, на которые опирается более высокая часть. Односкатная опирается
    единственной низкой стороной на стену: низ уходит на противоположную сторону, высокая — у
    стены. Двускатная опирается длинной стеной не «в один скат» (плоскость в 1,5–2 м, что
    поднимается к стене выше карниза и читается палаткой, gf#412), а коньком от стены: скаты — от
    двух других стен, как у крыльца с щипцом наружу. У остальных видов, если опираются все
    стены, — как есть."""
    if kind is RoofKind.GABLE and on & butts:
        across = {(k + 1) % RECT_SIDES for k in on}  # другая пара стен напротив
        if not across & butts:
            return across
    free = on - butts
    if not free and kind is RoofKind.SHED:
        free = {(k + 2) % RECT_SIDES for k in on}
    return free or on


def _entrance_on(facade, part: int) -> bool:
    return any(o.kind is OpeningKind.ENTRANCE and r.x0_m - EPS <= o.x_m
               and o.x_m + o.width_m <= r.x1_m + EPS
               for r in facade.runs if r.part == part for o in facade.side.openings)


def _area(house: HouseRoof, k: int) -> shapely.Geometry:
    """Площадь крыши части k: крыло со свесом по всему контуру. Ни одна крыша не режется свесом
    другой (gf#412): свес верхней нависает над нижней крышей, а нижняя обрывается на стене более
    высокой части (её крыло не вычитается из верхней). У равных высот — часть с меньшим номером
    выше."""
    me = house.parts[k]
    rect = shapely.Polygon(me.corners)
    above = [shapely.Polygon(other.corners) for j, other in enumerate(house.parts)
             if (other.eaves, -j) > (me.eaves, -k)]
    area = rect.buffer(me.overhang, join_style="mitre")
    area = area.difference(shapely.union_all(above)).union(rect) if above else area
    zones = [e.zone for e in house.extensions if e.part == k]
    return area.union(shapely.union_all(zones)) if zones else area


# ——— Поперечный щипец: кровля части над соседней (gf#431, `facade: Поперечный щипец`) ———


class Plane(NamedTuple):
    """Плоскость ската: высота h = a·x + b·y + c над точкой плана."""

    a: float
    b: float
    c: float


def _plane(line: Roofline, s: Slope) -> Plane:
    k = line.rise
    return Plane(k * s.inward[0], k * s.inward[1],
                 line.eaves - k * (s.at[0] * s.inward[0] + s.at[1] * s.inward[1]))


def _extensions(parts: list[Roofline]) -> tuple[Extension, ...]:
    """Продолжения кровель: часть упирается в соседа не ниже её по карнизу торцом щипца, и её
    кровля над общей линией где-то выше кровли соседа — она идёт над соседом до его кровли
    (ендова), а не обрывается стенкой (`_joint`)."""
    return tuple(e for k, me in enumerate(parts) for j, other in enumerate(parts)
                 if j != k and other.eaves >= me.eaves - EPS for e in _through(k, j, parts))


def _through(k: int, j: int, parts: list[Roofline]) -> list[Extension]:
    me, other = parts[k], parts[j]
    shared = shapely.Polygon(me.corners).intersection(shapely.Polygon(other.corners))
    out = []
    for seg in getattr(shared, "geoms", [shared]):
        if not isinstance(seg, shapely.LineString) or seg.length <= EPS:
            continue
        zone = _sweep(me, other, seg)
        if zone is not None and _meets(me, other, seg, zone):
            out.append(Extension(k, j, zone))
    return out


def _meets(me: Roofline, other: Roofline, seg: shapely.LineString, zone: shapely.Polygon) -> bool:
    """Кровля me у общей линии где-то выше кровли other и уходит под неё в zone, не выше её конька:
    иначе она прошла бы соседа насквозь (эркер у торца щипца — под щипцом, а не под кровлей)."""
    return _rises_over(me, other, seg) and _top(me, seg) <= _ridge(other, zone) + EPS


def _ridge(line: Roofline, zone: shapely.Geometry) -> float:
    """Верх кровли line над zone."""
    return max((z for _, face in faces(line, zone) for _, _, z in face), default=line.eaves)


def _sweep(me: Roofline, other: Roofline, seg: shapely.LineString) -> shapely.Polygon | None:
    """Площадь над соседом, куда идёт кровля me через общую линию seg: полоса шириной seg по
    скату соседа, что поднимается от этой линии, до его конька — за коньком скат соседа опускается,
    и щипец вышел бы над ним снова. None — seg не торец щипца me (от этой стены или напротив идёт
    скат) или кровля соседа от seg не поднимается (торец его щипца, плоская)."""
    (x0, y0), y1 = seg.coords[0], seg.coords[-1][1]
    centre = shapely.Polygon(me.corners).centroid
    along_x = abs(y1 - y0) <= EPS  # общая линия вдоль x — кровля идёт по y
    n = (0.0, math.copysign(1.0, y0 - centre.y)) if along_x else (
        math.copysign(1.0, x0 - centre.x), 0.0)
    if any(abs(s.inward[0] * n[0] + s.inward[1] * n[1]) > EPS for s in me.slopes):
        return None
    return _up_to_ridge(other, seg, n)


def _up_to_ridge(other: Roofline, seg: shapely.LineString, n: Point) -> shapely.Polygon | None:
    """Полоса шириной seg (вдоль оси плана) в сторону n по скату other, что поднимается от seg,
    до его конька; такого ската нет — None."""
    (x0, y0), (x1, y1) = seg.coords[0], seg.coords[-1]
    rising = [face for s, face in faces(other, shapely.Polygon(other.corners))
              if math.dist(s.inward, n) <= EPS]
    if not rising:
        return None
    reach = [x * n[0] + y * n[1] for face in rising for x, y, _ in face]
    far = max(reach) * (n[0] + n[1])  # дальняя точка ската соседа по n — линия конька
    if abs(y1 - y0) <= EPS:  # линия вдоль x — полоса идёт по y
        return shapely.box(min(x0, x1), min(y0, far), max(x0, x1), max(y0, far))
    return shapely.box(min(x0, far), min(y0, y1), max(x0, far), max(y0, y1))


def _wall_gable(house: HouseRoof, g: WallGable) -> tuple[Roofline, int, shapely.Polygon] | None:
    """Щипец над карнизной стеной (`facade: Щипец над карнизной стеной`): скаты от линий x0 и x1
    поперёк стены, карниз и свес — части под серединой участка; площадь — полоса участка от стены
    по скату части до её конька. Вершина щипца не выше конька части — иначе его конёк прошёл бы
    крышу насквозь: уклон уменьшается до щипца «до конька» (у разметки конёк ядра по уклону и
    глубине из параметров бывает ниже, чем на листе). Скат части от стены не поднимается (торец) —
    None."""
    left, u, _ = axis(house.corners, g.side)
    at, mid = _walker(left, u), (g.x0_m + g.x1_m) / 2
    host = next(s.part for s in house.spans[g.side] if s.x0 - EPS <= mid <= s.x1 + EPS)
    base = house.parts[host]
    seg = shapely.LineString([at(g.x0_m), at(g.x1_m)])
    zone = _up_to_ridge(base, seg, (-u[1], u[0]))  # внутрь дома от стены
    if zone is None:
        return None
    rise = min(math.tan(math.radians(g.pitch_deg)),
               (_ridge(base, zone) - base.eaves) / (mid - g.x0_m))
    line = Roofline(list(shapely.Polygon(zone).exterior.coords)[:-1],
                    [Slope(at(g.x0_m), u), Slope(at(g.x1_m), (-u[0], -u[1]))], base.eaves,
                    rise, base.overhang)
    if not _meets(line, base, seg, zone):
        return None
    # свес части под щипцом прерывается, как карниз на листе: перед стеной видна кровля щипца
    eave = seg.buffer(base.overhang, cap_style="flat", single_sided=True)
    return line, host, zone.union(eave if eave.intersection(zone).area <= EPS else
                                  seg.buffer(-base.overhang, cap_style="flat", single_sided=True))


def _along(seg: shapely.LineString):
    """Точка отрезка seg по расстоянию x от его начала и длина отрезка."""
    (x0, y0), (x1, y1) = seg.coords[0], seg.coords[-1]
    u = ((x1 - x0) / seg.length, (y1 - y0) / seg.length)
    return (lambda x: (x0 + u[0] * x, y0 + u[1] * x)), seg.length


def _rises_over(me: Roofline, other: Roofline, seg: shapely.LineString) -> bool:
    """Кровля me над линией seg где-то выше кровли other — иначе она уходит под неё сама."""
    at, length = _along(seg)
    xs = set(_breaks(me, at, 0.0, length)) | set(_breaks(other, at, 0.0, length))
    return any(me.height(at(x)) > other.height(at(x)) + EPS for x in xs)


def _top(line: Roofline, seg: shapely.LineString) -> float:
    """Верх кровли line над отрезком seg — конёк щипца на торце."""
    at, length = _along(seg)
    return max(line.height(at(x)) for x in _breaks(line, at, 0.0, length))


def _surface(line: Roofline, zone: shapely.Geometry) -> list[tuple[shapely.Geometry, Plane]]:
    """Кровля line над zone плоскими кусками; у плоской крыши — карниз по всей zone."""
    if not line.slopes:
        return [(zone, Plane(0.0, 0.0, line.eaves))]
    return [(shapely.Polygon([(x, y) for x, y, _ in face]), _plane(line, s))
            for s, face in faces(line, zone)]


def _higher(pieces: list[tuple[shapely.Geometry, Plane]], plane: Plane) -> shapely.Geometry:
    """Где кровля из кусков pieces не ниже плоскости plane."""
    out = []
    for shape, q in pieces:
        n, c = (q.a - plane.a, q.b - plane.b), plane.c - q.c  # plane ≤ q ⇔ −n·p ≤ −c
        if math.hypot(*n) <= EPS:
            if q.c >= plane.c - EPS:
                out.append(shape)
            continue
        out.append(shape.intersection(_halfplane((-n[0], -n[1]), -c)))
    return shapely.union_all(out) if out else shapely.Polygon()


def _part_faces(house: HouseRoof, k: int) -> list[tuple[Slope, list[Point3]]]:
    """Скаты части k на её площади; где кровля продолжена над соседом (или сосед — над ней),
    остаётся только та из двух, что выше: так получаются ендовы поперечного щипца."""
    line = house.parts[k]
    found = faces(line, _area(house, k))
    rivals = [(e.zone, house.parts[e.into if e.part == k else e.part])
              for e in house.extensions if k in (e.part, e.into)]
    if not rivals:
        return found
    out = []
    for s, face in found:
        plane, shape = _plane(line, s), shapely.Polygon([(x, y) for x, y, _ in face])
        for zone, rival in rivals:
            shape = shape.difference(_higher(_surface(rival, zone), plane).intersection(zone))
        for piece in getattr(shape, "geoms", [shape]):
            if isinstance(piece, shapely.Polygon) and piece.area > EPS:
                out.append((s, [(x, y, plane.a * x + plane.b * y + plane.c)
                                for x, y in list(shapely.normalize(piece).exterior.coords)[:-1]]))
    return out


def house_above(house: HouseRoof, k: int, inset: float = 0.0) -> list[Polygon]:
    """Стена k выше карниза: по участку каждой части — фронтон или верх стены под односкатной.
    inset — линия сечения сдвинута от стены внутрь дома на inset метров (внутренняя грань
    стены толщиной inset): под односкатной крыша там ниже, чем над наружной гранью."""
    left, u, _ = axis(house.corners, k)
    left = (left[0] - u[1] * inset, left[1] + u[0] * inset)
    out = []
    for span in house.spans[k]:
        base = _above(house.parts[span.part], left, u, span.x0, span.x1)
        over = [o for e in house.extensions if e.into == span.part
                if (o := _above_zone(house.parts[e.part], e.zone, left, u, span)) is not None]
        if not over:
            out += [base] if base is not None else []
            continue
        top = shapely.box(span.x0, house.parts[span.part].eaves, span.x1, FAR)
        out += _polygons(shapely.union_all([shapely.Polygon(p) for p in [base, *over] if p])
                         .intersection(top))
    return out


def _above_zone(line: Roofline, zone: shapely.Polygon, left: Point, u: Point,
                span: Span) -> Polygon | None:
    """Щипец продолженной кровли line на участке стены span: там, где её площадь zone выходит на
    линию стены (поперечный щипец проходит соседа насквозь, gf#431)."""
    at = _walker(left, u)
    on = zone.intersection(shapely.LineString([at(span.x0), at(span.x1)]))
    if on.length <= EPS:
        return None
    xs = [(p[0] - left[0]) * u[0] + (p[1] - left[1]) * u[1] for p in on.coords]
    return _above(line, left, u, min(xs), max(xs))


def house_faces(house: HouseRoof) -> list[list[Point3]]:
    """Скаты всех частей в объёме."""
    if len(house.parts) == 1:
        return [face for _, face in faces(house.parts[0])]
    return [face for k in range(len(house.parts)) for _, face in _part_faces(house, k)]


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
    shown |= {e.part for e in house.extensions if e.into in shown}
    for p, line in ((p, line) for p, line in enumerate(house.parts) if p in shown):
        shape = _projected(_part_faces(house, p), left, u, thickness)
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
    """Примыкания: общая стена нижней и более высокой по карнизу частей — от нижней из двух кровель
    до верхней в каждой точке линии. Стена принадлежит той части, чья кровля выше; у разреза по
    ступени карниза (gf#422) кровля нижней по карнизу части может уйти выше верхней (щипец) —
    тогда это стена нижней части, и её примыкание идёт с обратной нормалью."""
    out = []
    through = {(e.part, e.into) for e in house.extensions}
    for n, low in enumerate(house.parts):
        for h, high in ((h, p) for h, p in enumerate(house.parts) if p.eaves > low.eaves + EPS):
            shared = shapely.Polygon(low.corners).intersection(shapely.Polygon(high.corners))
            for seg in getattr(shared, "geoms", [shared]):
                if isinstance(seg, shapely.LineString) and seg.length > EPS:
                    # кровля нижней продолжена над верхней — её стенки на этой линии нет
                    out += [j for j in _joint(low, high, h, list(seg.coords), n)
                            if j.high != n or (n, h) not in through]
    return out


def _crossings(low: Roofline, high: Roofline, at, xs: list[float]) -> list[float]:
    """Где между соседними изломами xs кровля нижней части пересекает кровлю верхней."""
    found = set(xs)
    for x0, x1 in zip(xs, xs[1:], strict=False):
        gap0 = high.height(at(x0)) - low.height(at(x0))
        gap1 = high.height(at(x1)) - low.height(at(x1))
        if gap0 * gap1 < -EPS and abs(gap1 - gap0) > EPS:
            found.add(x0 + gap0 / (gap0 - gap1) * (x1 - x0))
    return sorted(found)


def _joint(low: Roofline, high: Roofline, number: int, ends: list[Point],
           low_number: int) -> list[Joint]:
    (x0, y0), (x1, y1) = ends[0], ends[-1]
    length = math.dist(ends[0], ends[-1])
    u = ((x1 - x0) / length, (y1 - y0) / length)

    def at(x: float) -> Point:
        return x0 + u[0] * x, y0 + u[1] * x

    xs = sorted(set(_breaks(low, at, 0.0, length)) | set(_breaks(high, at, 0.0, length)))
    xs = _crossings(low, high, at, xs)
    mid = at(length / 2)
    centre = shapely.Polygon(high.corners).centroid
    normal = (u[1], -u[0])  # от верхней части к нижней
    if (mid[0] - centre.x) * normal[0] + (mid[1] - centre.y) * normal[1] < 0:
        normal = (-normal[0], -normal[1])
    by_owner: dict[bool, tuple[list, list]] = {True: ([], []), False: ([], [])}
    for a, b in zip(xs, xs[1:], strict=False):
        c = (a + b) / 2
        higher = high.height(at(c)) >= low.height(at(c))  # кровля чья выше: стена той части
        lo = [min(low.height(at(x)), high.height(at(x))) for x in (a, b)]
        up = [max(low.height(at(x)), high.height(at(x))) for x in (a, b)]
        if max(up[0] - lo[0], up[1] - lo[1]) <= EPS:
            continue
        walls, seam = by_owner[higher]
        walls.append([(*at(a), lo[0]), (*at(b), lo[1]), (*at(b), up[1]), (*at(a), up[0])])
        seam += [(*at(a), lo[0]), (*at(b), lo[1])]
    return [Joint(normal if higher else (-normal[0], -normal[1]), walls, seam,
                  number if higher else low_number)
            for higher, (walls, seam) in by_owner.items() if walls]


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


# ——— Запретная зона под крышей соседней нижней части (gf#412) ———


def covered(house: HouseRoof, k: int) -> list[ForbiddenZone]:
    """Участки стены k высокой части, закрытые кровлей соседней более низкой части: кровля нижней
    части (с вывесом) стоит перед стеной — по x от её края до края, по высоте от самой низкой точки
    кровли над участком (кромка вывеса) до самой высокой (у стены, у ската). Окно там на виде
    срезано кровлей. Участок стены — наружный, то есть только вывес за торцом нижней части:
    стена под самой нижней частью внутренняя и в сторону не входит."""
    left, u, _ = axis(house.corners, k)
    toward = (u[1], -u[0])
    found: list[ForbiddenZone] = []
    for span in house.spans[k]:
        high = house.parts[span.part]
        strip = shapely.box(span.x0, EPS, span.x1, FAR)  # впереди стены: x вдоль стены, d наружу
        zones: list[ForbiddenZone] = []
        for q, line in enumerate(house.parts):
            if line.eaves >= high.eaves - EPS:
                continue
            for _, face in _part_faces(house, q):
                zones += _under(face, line, left, u, toward, strip)
        found += _joined(zones)
    return found


def _under(face: list[Point3], line: Roofline, left: Point, u: Point, toward: Point,
           strip: shapely.Geometry) -> list[ForbiddenZone]:
    """Часть ската face перед стеной, в полосе strip: зона по x и высоте кровли над ней."""
    def at(p: Point) -> Point:  # точка плана → (x вдоль стены, d от стены наружу)
        return ((p[0] - left[0]) * u[0] + (p[1] - left[1]) * u[1],
                (p[0] - left[0]) * toward[0] + (p[1] - left[1]) * toward[1])

    piece = shapely.Polygon([at(p) for p in face]).buffer(0).intersection(strip)
    out = []
    for g in getattr(piece, "geoms", [piece]):
        if not isinstance(g, shapely.Polygon) or g.area <= EPS:
            continue
        heights = [line.height((left[0] + a * u[0] + d * toward[0],
                                left[1] + a * u[1] + d * toward[1])) for a, d in g.exterior.coords]
        x0, _, x1, _ = g.bounds
        out.append(ForbiddenZone(x0_m=x0, x1_m=x1, y0_m=min(heights), y1_m=max(heights)))
    return out


def _joined(zones: list[ForbiddenZone]) -> list[ForbiddenZone]:
    """Зоны, что пересекаются по x, — одной: рамка по x и высоте всех."""
    out: list[ForbiddenZone] = []
    for z in sorted(zones, key=lambda z: z.x0_m):
        if out and z.x0_m <= out[-1].x1_m + EPS:
            last = out[-1]
            out[-1] = ForbiddenZone(
                x0_m=last.x0_m, x1_m=max(last.x1_m, z.x1_m),
                y0_m=min(last.y0_m, z.y0_m), y1_m=max(last.y1_m, z.y1_m))
        else:
            out.append(z)
    return out


def with_covered(sheet: FacadeSheet) -> FacadeSheet:
    """Лист с запретными зонами под кровлей соседних нижних частей у стен (`covered`) — к зонам
    плана; прежние такие зоны заменяются. Дом без скатов или не из частей — как есть."""
    house = roofs(sheet)
    if house is None or len(house.parts) == 1:
        return sheet
    facades = []
    for k, f in enumerate(sheet.facades):
        plan = [z for z in f.side.forbidden if z.y0_m is None]
        facades.append(f.model_copy(update={"side": f.side.model_copy(update={
            "forbidden": [*plan, *covered(house, k)]})}))
    return sheet.model_copy(update={"facades": facades})
