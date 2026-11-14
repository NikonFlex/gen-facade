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
from itertools import combinations
from typing import NamedTuple

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
    стены на длину."""

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
    house = roof.roofs(sheet) if any(
        p.kind is PorchKind.MAIN for p in sheet.spec.porch_roofs) else None
    return [_awning(sheet, house, corners, p, cfg) for p in sheet.spec.porch_roofs]


def _awning(sheet: FacadeSheet, house: roof.HouseRoof | None, corners: list[Point], p: PorchRoof,
            cfg: Sheet) -> Awning:
    wall, u, _ = roof.axis(corners, p.side)
    n = (u[1], -u[0])
    frame = Frame((wall[0] + u[0] * p.x_m[0], wall[1] + u[1] * p.x_m[0]), u, n)
    if p.kind is PorchKind.MAIN:
        return _continued(sheet, house, frame, p, cfg)
    return _own(frame, p, cfg)


def _posts_at(p: PorchRoof, size: float) -> list[float]:
    """Положения столбов вдоль отрезка от левого края: равномерно, крайние вровень с краями."""
    half, length = size / 2, p.x_m[1] - p.x_m[0]
    if p.posts == 1:
        return [length / 2]
    return [half + i * (length - size) / (p.posts - 1) for i in range(p.posts)]


def _slab(bottom: list[Point], thick: float) -> list[Point]:
    """Профиль плиты: нижняя линия и она же, поднятая по вертикали на толщину кровли."""
    return bottom + [(s, z + thick) for s, z in reversed(bottom)]


def _own(frame: Frame, p: PorchRoof, cfg: Sheet) -> Awning:
    """Кровля своего вида: низ и верх — с вида (`bottom_m`, `top_m`), но не тоньше кровли дома."""
    thick, d, length = cfg.roof.thickness_m, p.depth_m, p.x_m[1] - p.x_m[0]
    lo, hi = p.bottom_m, max(p.top_m, p.bottom_m + thick)
    kind = RoofKind.GABLE if p.kind in (PorchKind.HIP, PorchKind.GABLE) else RoofKind(p.kind)
    gable = kind is RoofKind.GABLE
    if gable:
        bottom = [(0.0, lo), (length / 2, hi - thick), (length, lo)]
    elif kind is RoofKind.SHED:
        bottom = [(0.0, hi - thick), (d, lo)]
    else:
        bottom = [(0.0, lo), (d, lo)]
    flat = kind is RoofKind.FLAT
    profile = [(0.0, lo), (d, lo), (d, hi), (0.0, hi)] if flat else _slab(bottom, thick)

    def under(x: float) -> float:
        return lo + (hi - thick - lo) * (1 - abs(2 * x / length - 1)) if gable else lo
    return Awning(frame.left, frame.u, frame.n, length, d, profile,
                  _posts(frame, p, cfg, under), cfg.porch_roof.post_m, kind, gable)


def _posts(frame: Frame, p: PorchRoof, cfg: Sheet, under) -> list[Post]:
    """Столбы на наружном крае; высота каждого — `under(x)`, низ кровли над ним."""
    size = cfg.porch_roof.post_m
    return [Post(frame.at(x, p.depth_m - size / 2), under(x)) for x in _posts_at(p, size)]


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
    """Кровля у стены навеса: высота низа над точкой плана, скат идёт от этой стены, свес дома у
    этой стены, вид кровли дома."""

    height: Callable[[Point], float]
    sloped: bool
    reach: float
    kind: RoofKind


def _cover(sheet: FacadeSheet, line: roof.Roofline | None, frame: Frame) -> Cover:
    """Кровля у стены; плоской крыши нет — плита на уровне карниза со свесом из крыши дома."""
    if line is None:
        return Cover(lambda pt: sheet.spec.eaves_m, True, sheet.spec.roof.overhang_m,
                     RoofKind.FLAT)
    sloped = any(math.dist(s.inward, (-frame.n[0], -frame.n[1])) <= EPS for s in line.slopes)
    return Cover(line.height, sloped, line.overhang if sloped else line.gable_overhang,
                 sheet.spec.roof.kind)


def _continued(sheet: FacadeSheet, house: roof.HouseRoof | None, frame: Frame, p: PorchRoof,
               cfg: Sheet) -> Awning:
    """Навес — продолжение крыши. Скат от этой стены — карнизная стена: скат продолжается вниз
    за свес. Иначе щипцовая: сечение щипца выдавлено наружу."""
    line, size = _line(sheet, house, p), cfg.porch_roof.post_m
    cover = _cover(sheet, line, frame)
    reach, out = min(cover.reach, p.depth_m), p.depth_m - size / 2
    posts = [Post(frame.at(x, out), cover.height(frame.at(x, out if cover.sloped else 0.0)))
             for x in _posts_at(p, size)]
    return Awning(frame.left, frame.u, frame.n, p.x_m[1] - p.x_m[0], p.depth_m,
                  _continued_profile(line, frame, p, (cover, reach), cfg.roof.thickness_m), posts,
                  size, cover.kind, not cover.sloped, reach)


def _continued_profile(line: roof.Roofline | None, frame: Frame, p: PorchRoof,
                       over: tuple[Cover, float], thick: float) -> list[Point]:
    """Профиль продолжения: от свеса дома до выноса — скат вниз (профиль вынос–высота) или
    сечение щипца (вдоль стены от правого края–высота); вынос не больше свеса — кровли нет."""
    cover, reach = over
    length = p.x_m[1] - p.x_m[0]
    if p.depth_m - reach <= EPS:
        return []
    if cover.sloped:
        return _slab([(d, cover.height(frame.at(length / 2, d))) for d in (reach, p.depth_m)],
                     thick)
    xs = sorted(_breaks(line, frame, length), reverse=True)
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
    кромки стены навеса — одна у всех точек, вынос откладывается по знаку нормали вдоль x вида."""
    x = at(a.left)[0]
    out: list[tuple[Part, Polygon]] = []
    if a.posts:
        c = x + (a.depth - a.post_m / 2) * sign
        top = max(p.top for p in a.posts)
        out.append((Part.POST, _rect(c - a.post_m / 2, 0.0, c + a.post_m / 2, top)))
    if not a.profile:
        return out
    if a.outward:
        zs = [z for _, z in a.profile]
        xs = sorted((x + a.reach * sign, x + a.depth * sign))
        return out + [(Part.ROOF, _rect(xs[0], min(zs), xs[1], max(zs)))]
    return out + [(Part.ROOF, [(x + d * sign, z) for d, z in a.profile])]


def _rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
