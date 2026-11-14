"""Навес на столбах (gf#472, `facade: Навес на столбах`, `Кровля навеса`, `Столбы навеса`): кровля
и столбы над крыльцом или террасой. Считает код по параметрам дома (`HouseSpec.porch_roofs`);
модель шага 4 их не ставит и не видит. Лист, дом объёмом и IFC берут отсюда.

Кровля — призма вдоль стены: профиль в плоскости (расстояние от стены наружу, высота) выдавлен на
длину отрезка. Односкатная спускается от стены наружу; двускатная и вальмовая (вальма строится
как двускатная — ближайший вид, что строит модуль) — коньком вдоль стены посередине выноса;
плоская — плита. Столбы — квадратного сечения на наружном крае, от земли до низа кровли.
"""

from dataclasses import dataclass
from enum import StrEnum

from genfacade import roof
from genfacade.config import Sheet
from genfacade.schema import EPS, FacadeSheet, Point, Polygon, PorchRoof, RoofKind
from genfacade.unfold import plan_corners


class Part(StrEnum):
    """Что нарисовано на виде стены."""

    ROOF = "roof"
    POST = "post"


@dataclass(frozen=True)
class Awning:
    """Навес в плане: левый край отрезка на стене, направление вдоль стены слева направо, наружная
    нормаль, длина и вынос, профиль кровли (расстояние от стены, высота), центры столбов, сечение
    столба и высота столба, вид кровли с учётом вальмы."""

    left: Point
    u: Point
    n: Point
    length: float
    depth: float
    profile: list[Point]
    posts: list[Point]
    post_m: float
    post_top: float
    kind: RoofKind

    @property
    def footprint(self) -> list[Point]:
        """Четыре угла навеса в плане."""
        a = self.left
        b = (a[0] + self.u[0] * self.length, a[1] + self.u[1] * self.length)
        return [a, b, *((p[0] + self.n[0] * self.depth, p[1] + self.n[1] * self.depth)
                        for p in (b, a))]


def find(sheet: FacadeSheet, cfg: Sheet) -> list[Awning]:
    """Навесы дома; нет — пусто."""
    if not sheet.spec.porch_roofs:
        return []
    corners = plan_corners([f.side for f in sheet.facades])
    return [_awning(corners, p, cfg) for p in sheet.spec.porch_roofs]


def _awning(corners: list[Point], p: PorchRoof, cfg: Sheet) -> Awning:
    wall, u, _ = roof.axis(corners, p.side)
    n = (u[1], -u[0])
    x0, x1 = p.x_m
    left = (wall[0] + u[0] * x0, wall[1] + u[1] * x0)
    kind = RoofKind.GABLE if p.kind is RoofKind.HIP else p.kind
    return Awning(left, u, n, x1 - x0, p.depth_m, _profile(p, kind, cfg.roof.thickness_m),
                  _posts(p, left, u, n, cfg.porch_roof.post_m), cfg.porch_roof.post_m,
                  p.bottom_m, kind)


def _profile(p: PorchRoof, kind: RoofKind, thick: float) -> list[Point]:
    """Сечение кровли: низ — по `bottom_m`, верх — по `top_m`, но не тоньше кровли дома."""
    d, lo = p.depth_m, p.bottom_m
    hi = max(p.top_m, lo + thick)
    if kind is RoofKind.SHED:
        return [(0.0, hi - thick), (d, lo), (d, lo + thick), (0.0, hi)]
    if kind is RoofKind.FLAT:
        return [(0.0, lo), (d, lo), (d, hi), (0.0, hi)]
    mid = d / 2
    return [(0.0, lo), (mid, hi - thick), (d, lo), (d, lo + thick), (mid, hi), (0.0, lo + thick)]


def _posts(p: PorchRoof, left: Point, u: Point, n: Point, size: float) -> list[Point]:
    """Центры столбов: на наружном крае, равномерно; крайние вровень с краями отрезка."""
    half, length = size / 2, p.x_m[1] - p.x_m[0]
    if p.posts == 1:
        steps = [length / 2]
    else:
        steps = [half + i * (length - size) / (p.posts - 1) for i in range(p.posts)]
    out = p.depth_m - half
    return [(left[0] + u[0] * s + n[0] * out, left[1] + u[1] * s + n[1] * out) for s in steps]


# ——— на виде стены ———

def view(awnings: list[Awning], corners: list[Point], k: int) -> list[tuple[Part, Polygon]]:
    """Навесы на виде стены k (x вдоль стены слева направо, y — высота): у стены вида — кровля
    полосой и столбы спереди; у перпендикулярной — профиль; навес в задней половине дома и у
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
            out += _profile_view(a, at, a.n[0] * u[0] + a.n[1] * u[1])
    return out


def _front(a: Awning, at) -> list[tuple[Part, Polygon]]:
    """Спереди: полоса кровли между низом и верхом профиля и столбы от земли."""
    xs = [at(p)[0] for p in a.footprint]
    zs = [z for _, z in a.profile]
    out = [(Part.POST, _rect(x - a.post_m / 2, 0.0, x + a.post_m / 2, a.post_top))
           for x in (at(p)[0] for p in a.posts)]
    return out + [(Part.ROOF, _rect(min(xs), min(zs), max(xs), max(zs)))]


def _profile_view(a: Awning, at, sign: float) -> list[tuple[Part, Polygon]]:
    """Сбоку: профиль кровли и один столб (все стоят на одной линии вдоль взгляда); x кромки стены
    навеса — одна у всех точек, вынос откладывается по знаку нормали вдоль x вида."""
    x = at(a.left)[0]
    out: list[tuple[Part, Polygon]] = []
    if a.posts:
        c = x + (a.depth - a.post_m / 2) * sign
        out.append((Part.POST, _rect(c - a.post_m / 2, 0.0, c + a.post_m / 2, a.post_top)))
    return out + [(Part.ROOF, [(x + d * sign, z) for d, z in a.profile])]


def _rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
