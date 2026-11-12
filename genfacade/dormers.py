"""Слуховые окна (дормеры, gf#457, `facade: Слуховое окно`): геометрия для листа, 3D и IFC.

Дормер стоит на карнизном скате главной части (`roof.main_part`): вертикальное лицо шириной
`Dormer.width_m` в плоскости, параллельной карнизной стене, на `face_offset_m` внутрь от неё, окно
в лице, щёчки от лица до ската и крыша — двускатная (щипец над лицом, конёк поперёк конька дома)
или односкатная. Модель шага 4 дормеров не ставит и не видит: их строит код по `HouseSpec.dormers`.

Оси дормера — как у стены на листе: s вдоль карнизной стены слева направо снаружи (от неё же
отсчитывается `Dormer.at`), d — вглубь дома от плоскости стены, z — высота. Скат главной части —
z = карниз + рост · d, это низ кровли; кровля лежит выше на толщину листа. Лицо и щёчки стоят от
этой плоскости, верх кровли закрывает их низ на толщину, поэтому на листе стенка начинается над
кровлей (`view`), а в 3D и IFC уходит в её толщу.

Кровля дома под дормером вырезана (`cut`): скат режется по плану дормера — его лицу, щёчкам и
линии, где крыша дормера встречает скат дома; кусок ската вокруг выреза не имеет дыры, он собран из
выпуклых клеток. Крыша дормера идёт без свеса и толщины на листе (в 3D и IFC — плитой толщины
кровли дома).

Дормер не ставится, если скат положе `min_pitch_deg`, окно не помещается в лицо, вершина крыши
дормера выше конька дома минус `below_ridge_m`, лицо выходит за края стены или основание дормера
заходит на другой скат (у вальмовой крыши у торца).
"""

import dataclasses
import math
from dataclasses import dataclass
from enum import StrEnum

import shapely

from genfacade import roof
from genfacade.config import Config, DormerRules
from genfacade.schema import EPS, Dormer, DormerRoof, FacadeSheet, Facing, Point, Polygon

Point3 = roof.Point3
TOUCH_M = 0.02  # допуск касания кусков на виде, метры


class Part(StrEnum):
    """Из чего сделан кусок дормера: цвет на листе и в 3D."""

    ROOF = "roof"    # крыша дормера
    WALL = "wall"    # лицо, щипец, щёчка — стена цветом стены
    GLASS = "glass"  # окно


@dataclass(frozen=True)
class Frame:
    """Оси дормера (s, d, z) → плана и объёма: левый край карнизной стены главной части снаружи,
    единичные направления вдоль стены и вглубь дома."""

    left: Point
    u: Point
    inward: Point

    def plan(self, s: float, d: float) -> Point:
        return (self.left[0] + self.u[0] * s + self.inward[0] * d,
                self.left[1] + self.u[1] * s + self.inward[1] * d)

    def at(self, s: float, d: float, z: float) -> Point3:
        x, y = self.plan(s, d)
        return (x, y, z)


@dataclass(frozen=True)
class Profile:
    """Дормер в вертикальном сечении (d, z), общее для всех его сторон: лицо на глубине `d0` от
    низа кровли `zb` до верха `top`, вершина крыши на глубине `d_top` и высоте `z_top`; край
    крыши на уровне верха лица встречает скат дома на глубине `d_eave` (у односкатной — вершина)."""

    kind: DormerRoof
    d0: float
    zb: float
    top: float
    d_eave: float
    d_top: float
    z_top: float


@dataclass(frozen=True)
class Solid:
    """Плоский кусок дормера в объёме и куда он смотрит в плане (по нему видна ли его сторона)."""

    part: Part
    points: list[Point3]
    outward: Point


@dataclass(frozen=True)
class Built:
    """Построенный дормер: куски, вырез в плане, окно и всё, что нужно разрезать кровлю дома."""

    number: int
    dormer: Dormer
    side: int                 # сторона листа, на которой стоит его карнизная стена
    part: int                 # главная часть, на чьём скате он стоит
    frame: Frame
    line: roof.Roofline       # скаты главной части
    slope: roof.Slope         # скат, на котором он стоит
    profile: Profile
    s: tuple[float, float]    # края лица вдоль стены
    face_ring: list[Point]    # лицо в (s, z): прямоугольник, у двускатной — со щипцом
    window: tuple[float, float, float, float]  # s0, z0, s1, z1
    solids: list[Solid]

    def cheeks(self) -> list[Solid]:
        """Щёчки: куски стены после лица (порядок — `_solids`)."""
        return [s for s in self.solids if s.part is Part.WALL][1:]

    def rise_at(self, p: Point) -> float:
        """Низ кровли ската над точкой плана."""
        return self.line.eaves + self.line.rise * self.slope.depth(p)

    def hole(self) -> shapely.Polygon:
        """Основание дормера на скате в плане: лицо, щёчки и линия встречи крыши со скатом."""
        (s0, s1), p = self.s, self.profile
        mid = (s0 + s1) / 2
        ring = [(s0, p.d0), (s1, p.d0), (s1, p.d_eave), (s0, p.d_eave)]
        if p.kind is DormerRoof.GABLE:
            ring.insert(3, (mid, p.d_top))
        return shapely.Polygon([self.frame.plan(s, d) for s, d in ring])


def build(sheet: FacadeSheet, cfg: Config) -> list[Built]:
    """Дормеры листа, которые помещаются; не помещается — дормера нет (`Dormer` остаётся в
    параметрах дома, как у модели остаётся окно, не прошедшее валидатор)."""
    house = roof.roofs(sheet)
    if house is None or not sheet.spec.dormers:
        return []
    out: list[Built] = []
    for d in sheet.spec.dormers:
        found = _place(sheet, house, d, cfg)
        if found is not None:
            out.append(dataclasses.replace(found, number=len(out) + 1))
    return out


def _place(sheet: FacadeSheet, house: roof.HouseRoof, d: Dormer, cfg: Config) -> Built | None:
    """Дормер на скате главной части: куски и вырез, если он помещается."""
    main = roof.main_part(house)
    line, found = house.parts[main], _wall(house.parts[main], d.facing)
    side = _side(sheet, house, main, d.facing)
    if found is None or side is None:
        return None
    slope, frame, length = found
    s0, s1 = d.at * length - d.width_m / 2, d.at * length + d.width_m / 2
    profile = _profile(cfg.dormer, line, d, _ridge(line))
    if profile is None or s0 < -EPS or s1 > length + EPS:
        return None
    window = _window(cfg.dormer, profile, (s0, s1), cfg.sheet.roof.thickness_m)
    if window is None:
        return None
    ring = _face_ring(profile, s0, s1)
    built = Built(0, d, side, main, frame, line, slope, profile, (s0, s1), ring, window, [])
    return dataclasses.replace(built, solids=_solids(built)) if _on_own_slope(built) else None


def _side(sheet: FacadeSheet, house: roof.HouseRoof, main: int, facing: Facing) -> int | None:
    """Сторона листа, на которую смотрит скат: с участком главной части, а нет такой (стена главной
    части закрыта пристройкой, julie) — любая сторона с этой нормалью."""
    same = [k for k, f in enumerate(sheet.facades) if Facing.of(f.side.orientation) is facing]
    return next((k for k in same if any(s.part == main for s in house.spans[k])),
                same[0] if same else None)


def _wall(line: roof.Roofline, facing: Facing) -> tuple[roof.Slope, Frame, float] | None:
    """Скат главной части, спускающийся к стороне facing, оси его карнизной стены и её длина."""
    for slope in line.slopes:
        out = (-slope.inward[0], -slope.inward[1])
        if math.dist(out, facing.normal) > EPS:
            continue
        k = next(i for i, c in enumerate(line.corners) if math.dist(c, slope.at) <= EPS)
        left, u, length = roof.axis(line.corners, k)
        return slope, Frame(left, u, slope.inward), length
    return None


def _ridge(line: roof.Roofline) -> float:
    """Высота конька главной части: самая высокая вершина её скатов."""
    return max(z for _, face in roof.faces(line) for *_, z in face)


def _profile(r: DormerRules, line: roof.Roofline, d: Dormer, ridge: float) -> Profile | None:
    """Сечение дормера по правилам; не ложится на скат — None."""
    if math.degrees(math.atan(line.rise)) < r.min_pitch_deg - EPS:
        return None
    d0 = r.face_offset_m
    zb, top = line.eaves + line.rise * d0, line.eaves + r.face_top_m
    if top <= zb + EPS:
        return None
    if d.roof is DormerRoof.GABLE:
        peak = top + d.width_m / 2 * math.tan(math.radians(r.gable_pitch_deg))
        found = Profile(d.roof, d0, zb, top, (top - line.eaves) / line.rise,
                        (peak - line.eaves) / line.rise, peak)
    else:
        tilt = math.tan(math.radians(r.shed_pitch_deg))
        if line.rise <= tilt + EPS:
            return None
        meet = (top - tilt * d0 - line.eaves) / (line.rise - tilt)
        found = Profile(d.roof, d0, zb, top, meet, meet, line.eaves + line.rise * meet)
    return found if found.z_top <= ridge - r.below_ridge_m + EPS else None


def _window(r: DormerRules, p: Profile, s: tuple[float, float], thickness: float
            ) -> tuple[float, float, float, float] | None:
    """Окно лица: уже лица на `window_side_m` с каждой стороны, от `window_sill_m` над кровлей у
    лица до `window_head_m` под верхом лица; ниже `window_min_h_m` — окна нет."""
    lo, hi = p.zb + thickness + r.window_sill_m, p.top - r.window_head_m
    if hi - lo < r.window_min_h_m - EPS or s[1] - s[0] - 2 * r.window_side_m <= EPS:
        return None
    return (s[0] + r.window_side_m, lo, s[1] - r.window_side_m, hi)


def _face_ring(p: Profile, s0: float, s1: float) -> list[Point]:
    """Лицо в (s, z): прямоугольник от низа кровли до верха, у двускатной — со щипцом над ним."""
    ring = [(s0, p.zb), (s1, p.zb), (s1, p.top)]
    if p.kind is DormerRoof.GABLE:
        ring.append(((s0 + s1) / 2, p.z_top))
    return [*ring, (s0, p.top)]


def _on_own_slope(b: Built) -> bool:
    """Основание дормера лежит на его скате: над его углами и серединами сторон крыша главной части
    — этот скат, а не соседний (вальма у торца) или другой скат за коньком."""
    ring = list(b.hole().exterior.coords)
    points = ring[:-1] + [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
                          for p, q in zip(ring, ring[1:], strict=False)]
    return all(abs(b.line.height(p) - b.rise_at(p)) <= EPS for p in points)


def _solids(b: Built) -> list[Solid]:
    """Куски дормера: крыша, лицо со щипцом, щёчки, окно."""
    (s0, s1), p, f = b.s, b.profile, b.frame
    mid, out = (s0 + s1) / 2, (-f.inward[0], -f.inward[1])
    tip = (p.d_eave, p.top) if p.kind is DormerRoof.GABLE else (p.d_top, p.z_top)
    cheeks = [Solid(Part.WALL, [f.at(s, p.d0, p.zb), f.at(s, p.d0, p.top), f.at(s, *tip)],
                    (f.u[0] * sign, f.u[1] * sign)) for s, sign in ((s0, -1), (s1, 1))]
    face = Solid(Part.WALL, [f.at(s, p.d0, z) for s, z in b.face_ring], out)
    glass = Solid(Part.GLASS, [f.at(s, p.d0, z) for s, z in _corners(b.window)], out)
    return [*_roofs(b, mid, out), face, *cheeks, glass]


def _corners(box: tuple[float, float, float, float]) -> list[Point]:
    s0, z0, s1, z1 = box
    return [(s0, z0), (s1, z0), (s1, z1), (s0, z1)]


def _roofs(b: Built, mid: float, out: Point) -> list[Solid]:
    """Крыша дормера: два ската от конька до краёв лица или один от верха лица вглубь."""
    (s0, s1), p, f = b.s, b.profile, b.frame
    if p.kind is DormerRoof.SHED:
        ring = [f.at(s0, p.d0, p.top), f.at(s1, p.d0, p.top),
                f.at(s1, p.d_top, p.z_top), f.at(s0, p.d_top, p.z_top)]
        return [Solid(Part.ROOF, ring, out)]
    left = [f.at(s0, p.d0, p.top), f.at(mid, p.d0, p.z_top), f.at(mid, p.d_top, p.z_top),
            f.at(s0, p.d_eave, p.top)]
    right = [f.at(s1, p.d0, p.top), f.at(s1, p.d_eave, p.top), f.at(mid, p.d_top, p.z_top),
             f.at(mid, p.d0, p.z_top)]
    return [Solid(Part.ROOF, left, (-f.u[0], -f.u[1])), Solid(Part.ROOF, right, f.u)]


def on_eaves(sheet: FacadeSheet) -> FacadeSheet:
    """Лист с дормерами стаба шага 1 на карнизных скатах главной части по плану: стаб плана не
    видит, скаты у него — по умолчанию (`DormerStub.facings`); здесь — по одному на каждый скат,
    с местом, лицом и видом крыши первого дормера параметров."""
    house = roof.roofs(sheet)
    if house is None or not sheet.spec.dormers:
        return sheet
    line = house.parts[roof.main_part(house)]
    found = [sheet.spec.dormers[0].model_copy(update={"facing": Facing.of(
        (-s.inward[0], -s.inward[1]))}) for s in line.slopes]
    return sheet.model_copy(update={"spec": sheet.spec.model_copy(update={"dormers": found})})


def from_view(sheet: FacadeSheet, side: int, span: tuple[float, float], kind: DormerRoof
              ) -> Dormer | None:
    """Дормер по лицу на виде карнизной стены side — края лица span (метры, x вида, как у
    элементов): скат — к стороне стены, место — доля длины карнизной стены главной части от её
    левого края. Для разметки (`datasets/manual.py`): вид стены может быть любой части, на скате
    главной. Скат главной части к этой стороне не идёт или середина лица вне стены — None."""
    house = roof.roofs(sheet)
    if house is None:
        return None
    facing = Facing.of(sheet.facades[side].side.orientation)
    found = _wall(house.parts[roof.main_part(house)], facing)
    if found is None:
        return None
    left, u, _ = roof.axis(house.corners, side)
    mid = (span[0] + span[1]) / 2
    _, frame, length = found
    at = ((left[0] + u[0] * mid - frame.left[0]) * frame.u[0]
          + (left[1] + u[1] * mid - frame.left[1]) * frame.u[1]) / length
    if not -EPS <= at <= 1 + EPS:
        return None
    return Dormer(facing=facing, at=min(max(at, 0.0), 1.0), width_m=span[1] - span[0], roof=kind)


# ——— кровля дома под дормером ———

def cut(faces: list[list[Point3]], built: list[Built]) -> list[list[Point3]]:
    """Грани кровли дома без оснований дормеров."""
    for b in built:
        faces = [piece for face in faces for piece in _cut_face(face, b)]
    return faces


def _cut_face(face: list[Point3], b: Built) -> list[list[Point3]]:
    """Грань ската дормера без его основания: четыре клетки вокруг выреза, у каждой вершины на
    плоскости ската. Другая грань (другой скат, плита) и грань мимо выреза остаются как есть."""
    plan = shapely.Polygon([(x, y) for x, y, _ in face]).buffer(0)
    on_slope = all(abs(z - b.rise_at((x, y))) <= EPS for x, y, z in face)
    hole = b.hole()
    if not on_slope or plan.intersection(hole).area <= EPS:
        return [face]
    pieces = []
    for cell in _cells(b, hole):
        pieces += [[(x, y, b.rise_at((x, y))) for x, y in list(g.exterior.coords)[:-1]]
                   for g in getattr(plan.intersection(cell), "geoms", [plan.intersection(cell)])
                   if isinstance(g, shapely.Polygon) and g.area > EPS]
    return pieces


def _cells(b: Built, hole: shapely.Polygon) -> list[shapely.Geometry]:
    """Плоскость в плане без выреза: слева и справа от полосы дормера, перед лицом и за вырезом."""
    (s0, s1), far, d0 = b.s, roof.FAR, b.profile.d0

    def cell(a: float, c: float, lo: float, hi: float) -> shapely.Polygon:
        return shapely.Polygon([b.frame.plan(a, lo), b.frame.plan(c, lo), b.frame.plan(c, hi),
                                b.frame.plan(a, hi)])

    behind = cell(s0, s1, d0, far).difference(hole)
    return [cell(-far, s0, -far, far), cell(s1, far, -far, far), cell(s0, s1, -far, d0), behind]


# ——— лист и 3D ———

def view(built: list[Built], frame: tuple[Point, Point], thickness: float,
         seen: list[Polygon]) -> list[tuple[Part, Polygon]]:
    """Дормеры на виде стены (frame — начало и направление слева направо): куски, повёрнутые к
    зрителю, выше кровли дома — ниже неё они скрыты её толщей. seen — что на этом виде видно:
    кровля и стена над карнизом,  метрах вида; дормер рисуется только над ним (в полосе x каждого
    многоугольника, выше его низа) и обрезается по ней — иначе он висел бы за краем стены или над
    стеной, которой его кровли нет. x — вдоль стены, y — высота; порядок — крыша, стена, стекло."""
    (left, u), toward = frame, (frame[1][1], -frame[1][0])
    zone = shapely.union_all([shapely.box(min(x for x, _ in p), min(y for _, y in p),
                                          max(x for x, _ in p), roof.FAR) for p in seen]
                             or [shapely.Polygon()])
    shown = [(s.part, _above_cover(s.points, b, thickness)) for b in built for s in b.solids
             if s.outward[0] * toward[0] + s.outward[1] * toward[1] > EPS]
    shown.sort(key=lambda item: list(Part).index(item[0]))
    found = []
    for part, ring in shown:
        flat = [((p[0] - left[0]) * u[0] + (p[1] - left[1]) * u[1], p[2]) for p in ring]
        if len(flat) >= 3:
            found += [(part, shapely.Polygon(shape)) for shape in roof.polygons(
                shapely.Polygon(flat).buffer(0).intersection(zone))]
    return _attached(found, seen)


def _attached(found: list[tuple[Part, shapely.Polygon]], seen: list[Polygon]
              ) -> list[tuple[Part, Polygon]]:
    """Куски дормера, что стоят на видимой кровле или стене этого вида — касаются её или другого
    такого куска; остальные висели бы над ней в воздухе (кровли главной части на виде нет)."""
    ground = shapely.union_all([shapely.Polygon(p) for p in seen] or [shapely.Polygon()])
    kept, rest = [], list(found)
    reach = ground.buffer(TOUCH_M)
    while True:
        moved = [i for i in rest if i[1].intersects(reach)]
        if not moved:
            break
        kept += moved
        rest = [i for i in rest if i not in moved]
        reach = shapely.union_all([reach, *(i[1].buffer(TOUCH_M) for i in moved)])
    kept.sort(key=lambda item: list(Part).index(item[0]))
    return [(part, list(shape.exterior.coords)[:-1]) for part, shape in kept]


def _above_cover(ring: list[Point3], b: Built, thickness: float) -> list[Point3]:
    """Кусок дормера выше верха кровли дома (низ кровли у ската плюс толщина): отсекает
    плоскостью верха кровли — многоугольник выпуклый."""
    def over(p: Point3) -> float:
        return p[2] - b.rise_at((p[0], p[1])) - thickness

    out: list[Point3] = []
    for a, c in zip(ring, ring[1:] + ring[:1], strict=True):
        ga, gc = over(a), over(c)
        if ga >= 0:
            out.append(a)
        if (ga >= 0) != (gc >= 0):
            k = ga / (ga - gc)
            out.append(tuple(a[i] + k * (c[i] - a[i]) for i in range(3)))  # type: ignore[arg-type]
    return out


def solids(built: list[Built], out_m: float) -> dict[Part, list[list[Point3]]]:
    """Куски дормеров по материалу для 3D; стекло — чуть наружу от лица на `out_m`, чтобы не тонуть
    в нём."""
    found: dict[Part, list[list[Point3]]] = {part: [] for part in Part}
    for b in built:
        for s in b.solids:
            shift = out_m if s.part is Part.GLASS else 0.0
            found[s.part].append([(x + s.outward[0] * shift, y + s.outward[1] * shift, z)
                                  for x, y, z in s.points])
    return found
