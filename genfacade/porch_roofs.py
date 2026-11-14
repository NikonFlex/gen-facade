"""Навес на столбах (gf#472, `facade: Навес на столбах`, `Кровля навеса`, `Столбы навеса`): кровля
и столбы над крыльцом или террасой. Считает код по параметрам дома (`HouseSpec.porch_roofs`);
модель шага 4 их не ставит и не видит. Лист, дом объёмом и IFC берут отсюда.

Кровля — призма: профиль в вертикальной плоскости выдавлен вдоль оси. Односкатная и плоская —
профиль (вынос, высота) выдавлен вдоль стены; двускатная и вальмовая (вальма строится как
двускатная) — фронтоном наружу: профиль (вдоль стены, высота) — треугольник, выдавлен от стены
наружу, конёк поперёк стены посередине отрезка. Продолжение крыши дома (`main`) — кровля части
дома у этой стены за стену: у карнизной стены скат идёт вниз (профиль вынос–высота), у щипцовой
конёк и скаты идут дальше (сечение щипца, выдавленное наружу) — по `roof.Roofline.height`, второго
механизма кровли нет. Столбы — квадратного сечения на наружном крае, от земли до низа кровли.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations, pairwise
from typing import NamedTuple

import shapely

from genfacade import roof
from genfacade.config import Sheet
from genfacade.schema import (
    EPS,
    FacadeSheet,
    Point,
    Polygon,
    PorchKind,
    PorchRoof,
    RoofKind,
)
from genfacade.unfold import plan_corners


class Part(StrEnum):
    """Что нарисовано на виде стены."""

    ROOF = "roof"
    POST = "post"


class Post(NamedTuple):
    """Столб: центр в плане и высота — до низа кровли над ним."""

    at: Point
    top: float


@dataclass(frozen=True)
class Awning:
    """Навес в плане: левый край отрезка на стене, направление вдоль стены слева направо, наружная
    нормаль, длина и вынос, профиль кровли (пусто — кровля дома уже покрывает весь вынос), столбы,
    сечение столба, вид кровли с учётом вальмы. `outward` — профиль (вдоль стены от правого края,
    высота) выдавлен наружу от `reach` до выноса; иначе — профиль (вынос, высота) выдавлен вдоль
    стены на длину. `reach` и начало профиля вдоль выноса меньше нуля, если кровля продолжена за
    стену внутрь дома — до ската кровли дома (там она скрыта кровлей). `slab` — кровля плита
    постоянной толщины по вертикали, её скаты — плоские грани (`planes`)."""

    left: Point
    u: Point
    n: Point
    length: float
    depth: float
    profile: list[Point]
    posts: list[Post]
    post_m: float
    kind: RoofKind
    outward: bool = False
    reach: float = 0.0
    slab: bool = True

    @property
    def footprint(self) -> list[Point]:
        """Четыре угла навеса в плане."""
        a = self.left
        b = (a[0] + self.u[0] * self.length, a[1] + self.u[1] * self.length)
        return [a, b, *((p[0] + self.n[0] * self.depth, p[1] + self.n[1] * self.depth)
                        for p in (b, a))]

    @property
    def origin(self) -> Point:
        """Где начинается выдавливание профиля."""
        if not self.outward:
            return self.left
        return (self.left[0] + self.u[0] * self.length + self.n[0] * self.reach,
                self.left[1] + self.u[1] * self.length + self.n[1] * self.reach)

    @property
    def x_axis(self) -> Point:
        """Куда в плане направлена ось x профиля."""
        return (-self.u[0], -self.u[1]) if self.outward else self.n

    @property
    def sweep(self) -> tuple[Point, float]:
        """Направление выдавливания в плане и его длина."""
        return (self.n, self.depth - self.reach) if self.outward else (self.u, self.length)

    @property
    def planes(self) -> list[list[roof.Point3]]:
        """Низ плиты плоскими гранями (x, y плана, высота) — как скаты кровли дома: так 3D кладёт
        на них тот же рисунок кровли, и навес продолжает скат без шва. Не плита — пусто."""
        if not (self.slab and self.profile):
            return []
        (dx, dy), run = self.sweep
        (ox, oy), (ax, ay) = self.origin, self.x_axis
        bottom = self.profile[:len(self.profile) // 2]
        return [[(ox + ax * s + dx * run * k, oy + ay * s + dy * run * k, z)
                 for (s, z), k in ((a, 0), (b, 0), (b, 1), (a, 1))]
                for a, b in pairwise(bottom)]


class Frame(NamedTuple):
    """Отрезок стены: левый край, вдоль стены, наружу."""

    left: Point
    u: Point
    n: Point

    def at(self, x: float, d: float) -> Point:
        """Точка плана: x вдоль стены от левого края, d от стены наружу."""
        return (self.left[0] + self.u[0] * x + self.n[0] * d,
                self.left[1] + self.u[1] * x + self.n[1] * d)


def find(sheet: FacadeSheet, cfg: Sheet) -> list[Awning]:
    """Навесы дома; нет — пусто."""
    if not sheet.spec.porch_roofs:
        return []
    corners = plan_corners([f.side for f in sheet.facades])
    house = roof.roofs(sheet)
    return [_awning(sheet, house, corners, p, cfg) for p in sheet.spec.porch_roofs]


def _awning(sheet: FacadeSheet, house: roof.HouseRoof | None, corners: list[Point], p: PorchRoof,
            cfg: Sheet) -> Awning:
    wall, u, length = roof.axis(corners, p.side)
    n = (u[1], -u[0])
    frame = Frame((wall[0] + u[0] * p.x_m[0], wall[1] + u[1] * p.x_m[0]), u, n)
    flush = (p.x_m[0] <= EPS, p.x_m[1] >= length - EPS)  # отрезок доходит до края стены
    cover = _cover(sheet, _line(sheet, house, p), frame, flush)
    if p.kind is PorchKind.MAIN:
        return _continued(frame, p, cover, cfg)
    return _own(frame, p, cover, cfg)


def _inset(p: PorchRoof, cfg: Sheet) -> float:
    """Свес кровли за столбы: из настроек, но не больше трети выноса."""
    return min(cfg.porch_roof.overhang_m, p.depth_m / 3)


def _posts_at(p: PorchRoof, size: float, inset: float) -> list[float]:
    """Положения столбов вдоль отрезка от левого края: по разметке (`post_x_m`), иначе равномерно,
    крайние — на свес от краёв кровли."""
    length = p.x_m[1] - p.x_m[0]
    if p.post_x_m and p.posts:
        return [c - p.x_m[0] for c in p.post_x_m]
    lo = min(inset + size / 2, length / 2)
    if p.posts == 1:
        return [length / 2]
    return [lo + i * (length - 2 * lo) / (p.posts - 1) for i in range(p.posts)]


def _slab(bottom: list[Point], thick: float) -> list[Point]:
    """Профиль плиты: нижняя линия и она же, поднятая по вертикали на толщину кровли."""
    return bottom + [(s, z + thick) for s, z in reversed(bottom)]


def _tilt(p: PorchRoof, kind: RoofKind, cover: "Cover", cfg: Sheet) -> float:
    """Тангенс уклона ската навеса: как у кровли дома, если разметка (высоты верха и низа)
    расходится с ним не больше `pitch_tol_deg`; больше — по разметке («козырёк обычно параллелен
    крыше, либо явно видно, что нет»). Плоская — без уклона."""
    if kind is RoofKind.FLAT:
        return 0.0
    run = p.depth_m if kind is RoofKind.SHED else (p.x_m[1] - p.x_m[0]) / 2
    marked = max(p.top_m - cfg.roof.thickness_m - p.bottom_m, 0.0) / run
    gap = abs(math.degrees(math.atan(marked)) - math.degrees(math.atan(cover.rise)))
    return cover.rise if gap <= cfg.porch_roof.pitch_tol_deg else marked


def _inward(cover: "Cover", z_wall: float, rising: float) -> float:
    """Насколько (меньше нуля) продлить кровлю навеса за стену внутрь дома: верх у стены `z_wall`
    выше карниза — кровля идёт вверх к стене со скоростью `rising` и упирается в скат кровли дома
    (он у карнизной стены поднимается внутрь со скоростью `rise`). Ниже карниза, щипцовая стена,
    плоская крыша — кровля кончается на стене."""
    if not cover.sloped or cover.rise <= EPS or z_wall <= cover.eaves:
        return 0.0
    return -(z_wall - cover.eaves) / max(cover.rise - rising, cover.rise / 2)


def _own(frame: Frame, p: PorchRoof, cover: "Cover", cfg: Sheet) -> Awning:
    """Кровля своего вида: уклон — как у дома или по разметке (`_tilt`), край кровли на высоте низа
    с вида (`bottom_m`); верх у стены продлён до ската кровли дома (`_inward`), дыры между навесом
    и кровлей нет."""
    thick, d, length = cfg.roof.thickness_m, p.depth_m, p.x_m[1] - p.x_m[0]
    lo = p.bottom_m
    kind = RoofKind.GABLE if p.kind in (PorchKind.HIP, PorchKind.GABLE) else RoofKind(p.kind)
    tilt = _tilt(p, kind, cover, cfg)
    reach, slab = 0.0, kind is not RoofKind.FLAT
    if kind is RoofKind.GABLE:
        ridge = lo + tilt * length / 2
        reach = _inward(cover, ridge, 0.0)
        profile = _slab([(0.0, lo), (length / 2, ridge), (length, lo)], thick)
    elif kind is RoofKind.SHED:
        top = _inward(cover, lo + tilt * d, tilt)
        profile = _slab([(top, lo + tilt * (d - top)), (d, lo)], thick)
    else:
        top, hi = _inward(cover, lo, 0.0), lo + max(p.top_m - lo, thick)
        profile = [(top, lo), (d, lo), (d, hi), (top, hi)]

    def under(x: float, at: float) -> float:
        return lo + tilt * (min(x, length - x) if kind is RoofKind.GABLE else
                            d - at if kind is RoofKind.SHED else 0.0)
    return Awning(frame.left, frame.u, frame.n, length, d, profile,
                  _posts(frame, p, cfg, under), cfg.porch_roof.post_m, kind,
                  kind is RoofKind.GABLE, reach, slab)


def _posts(frame: Frame, p: PorchRoof, cfg: Sheet, under) -> list[Post]:
    """Столбы на свес внутрь от наружного края кровли; высота каждого — `under(x, d)`: низ кровли
    над ним."""
    size, inset = cfg.porch_roof.post_m, _inset(p, cfg)
    out = max(p.depth_m - inset - size / 2, size / 2)
    return [Post(frame.at(x, out), under(x, out)) for x in _posts_at(p, size, inset)]


# ——— продолжение крыши дома ———

def _line(sheet: FacadeSheet, house: roof.HouseRoof | None, p: PorchRoof) -> roof.Roofline | None:
    """Скаты части дома, к стене которой примыкает навес: часть — по участку стороны, что
    накрывает середину отрезка. Крыши нет (плоская) — None."""
    if house is None:
        return None
    mid = (p.x_m[0] + p.x_m[1]) / 2
    spans = house.spans[p.side]
    span = next((s for s in spans if s.x0 - EPS <= mid <= s.x1 + EPS), spans[0])
    return house.parts[span.part]


class Cover(NamedTuple):
    """Кровля у стены навеса: скаты части дома (нет — плоская), высота низа над точкой плана, скат
    идёт от этой стены, свес дома у этой стены и вдоль неё, вид кровли дома, карниз и рост высоты
    на метр глубины, на сколько кровля дома выступает за край стены вида на концах отрезка (слева,
    справа; нуль — конец отрезка не у края стены)."""

    line: roof.Roofline | None
    height: Callable[[Point], float]
    sloped: bool
    reach: float
    kind: RoofKind
    eaves: float
    rise: float
    pad: tuple[float, float]


def _cover(sheet: FacadeSheet, line: roof.Roofline | None, frame: Frame,
           flush: tuple[bool, bool]) -> Cover:
    """Кровля у стены; плоской крыши нет — плита на уровне карниза со свесом из крыши дома."""
    spec = sheet.spec
    if line is None:
        over = spec.roof.overhang_m
        return Cover(None, lambda pt: spec.eaves_m, True, over, RoofKind.FLAT, spec.eaves_m, 0.0,
                     (over if flush[0] else 0.0, over if flush[1] else 0.0))
    sloped = any(math.dist(s.inward, (-frame.n[0], -frame.n[1])) <= EPS for s in line.slopes)
    side = line.gable_overhang if sloped else line.overhang
    return Cover(line, line.height, sloped, line.overhang if sloped else line.gable_overhang,
                 spec.roof.kind, line.eaves, line.rise,
                 (side if flush[0] else 0.0, side if flush[1] else 0.0))


def _continued(frame: Frame, p: PorchRoof, cover: Cover, cfg: Sheet) -> Awning:
    """Навес — продолжение крыши. Скат от этой стены — карнизная стена: скат продолжается вниз
    за свес. Иначе щипцовая: сечение щипца выдавлено наружу. Кровля шире отрезка на свес дома там,
    где отрезок доходит до края стены, — как кровля дома."""
    size, inset = cfg.porch_roof.post_m, _inset(p, cfg)
    reach, out = min(cover.reach, p.depth_m), p.depth_m - inset - size / 2
    posts = [Post(frame.at(x, out), cover.height(frame.at(x, out if cover.sloped else 0.0)))
             for x in _posts_at(p, size, inset)]
    wide = Frame(frame.at(-cover.pad[0], 0.0), frame.u, frame.n)
    length = p.x_m[1] - p.x_m[0] + sum(cover.pad)
    profile = _continued_profile(cover, wide, (reach, p.depth_m, length), cfg.roof.thickness_m)
    return Awning(wide.left, wide.u, wide.n, length, p.depth_m, profile, posts, size, cover.kind,
                  not cover.sloped, reach)


def _continued_profile(cover: Cover, frame: Frame, size: tuple[float, float, float],
                       thick: float) -> list[Point]:
    """Профиль продолжения: от свеса дома до выноса — скат вниз (профиль вынос–высота) или
    сечение щипца (вдоль стены от правого края–высота); вынос не больше свеса — кровли нет.
    `size` — свес дома у стены, вынос навеса, длина кровли вдоль стены."""
    reach, depth, length = size
    if depth - reach <= EPS:
        return []
    if cover.sloped:
        return _slab([(d, cover.height(frame.at(length / 2, d))) for d in (reach, depth)], thick)
    xs = sorted(_breaks(cover.line, frame, length), reverse=True)
    return _slab([(length - x, cover.height(frame.at(x, 0.0))) for x in xs], thick)


def _breaks(line: roof.Roofline, frame: Frame, length: float) -> set[float]:
    """Где вдоль стены сечение щипца ломается: концы отрезка и места, где два ската равны по
    высоте (конёк)."""
    base = frame.at(0.0, 0.0)
    rate = [(s.depth(base), s.depth(frame.at(1.0, 0.0)) - s.depth(base)) for s in line.slopes]
    xs = {0.0, length}
    for (c1, k1), (c2, k2) in combinations(rate, 2):
        if abs(k1 - k2) > EPS and 0 < (x := (c2 - c1) / (k1 - k2)) < length:
            xs.add(x)
    return xs


# ——— на виде стены ———

def view(awnings: list[Awning], corners: list[Point], k: int) -> list[tuple[Part, Polygon]]:
    """Навесы на виде стены k (x вдоль стены слева направо, y — высота): у стены вида — кровля
    и столбы спереди; у перпендикулярной — профиль; навес в задней половине дома и у
    противоположной стены закрыт домом. Порядок — как рисовать."""
    at, toward, front = roof.view_frame(corners, k)
    u = roof.axis(corners, k)[1]
    out: list[tuple[Part, Polygon]] = []
    for a in awnings:
        if max(at(p)[1] for p in a.footprint) < front - EPS:
            continue
        along = a.n[0] * toward[0] + a.n[1] * toward[1]
        if along > 1 - EPS:
            out += _front(a, at)
        elif abs(along) <= EPS:
            out += _side(a, at, a.n[0] * u[0] + a.n[1] * u[1])
    return out


def _front(a: Awning, at) -> list[tuple[Part, Polygon]]:
    """Спереди: столбы от земли и кровля — сечение (фронтон) или полоса между низом и верхом."""
    out = [(Part.POST, _rect(x - a.post_m / 2, 0.0, x + a.post_m / 2, p.top))
           for p in a.posts for x in (at(p.at)[0],)]
    if not a.profile:
        return out
    if a.outward:
        x0 = at(a.origin)[0]
        sign = a.x_axis[0] * a.u[0] + a.x_axis[1] * a.u[1]
        return out + [(Part.ROOF, [(x0 + s * sign, z) for s, z in a.profile])]
    xs = [at(p)[0] for p in a.footprint]
    zs = [z for _, z in a.profile]
    return out + [(Part.ROOF, _rect(min(xs), min(zs), max(xs), max(zs)))]


def _side(a: Awning, at, sign: float) -> list[tuple[Part, Polygon]]:
    """Сбоку: кровля от стены до края и один столб (все стоят на одной линии вдоль взгляда); x
    кромки стены навеса — одна у всех точек, вынос откладывается по знаку нормали вдоль x вида.
    Кровля за стеной внутрь дома не рисуется — её скрывает кровля дома."""
    x = at(a.left)[0]
    out: list[tuple[Part, Polygon]] = []
    if a.posts:
        c = at(a.posts[0].at)[0]
        top = max(p.top for p in a.posts)
        out.append((Part.POST, _rect(c - a.post_m / 2, 0.0, c + a.post_m / 2, top)))
    if not a.profile:
        return out
    ends = sorted((x, x + a.depth * sign))
    if a.outward:
        zs = [z for _, z in a.profile]
        edge = sorted((x + max(a.reach, 0.0) * sign, x + a.depth * sign))
        return out + [(Part.ROOF, _rect(edge[0], min(zs), edge[1], max(zs)))]
    shape = shapely.Polygon([(x + d * sign, z) for d, z in a.profile]).intersection(
        shapely.box(ends[0], -roof.FAR, ends[1], roof.FAR))
    return out + [(Part.ROOF, q) for q in roof.polygons(shape)]


def _rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
