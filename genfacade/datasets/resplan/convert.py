"""План ResPlan → SVG в формате GenPlan, который читает препроцессор шага 2 (`plan-input`).

У ResPlan стены — многоугольники с разрывами, окна и двери — многоугольники в разрывах, в
пикселях холста 256 (README ResPlan). GenPlan рисует то же самое осевыми прямоугольниками:
стена — чёрный `<rect>`, окно — `<rect>` цвета окна в разрыве, дверь — пустой разрыв с открытой
створкой и дугой из петли (plan/genplan_svg.py). Поэтому:

- координаты почти осевых рёбер сводятся к общим линиям (шум векторизации ResPlan — доли
  пикселя), стены режутся по этим линиям на прямоугольники;
- окно и дверь — их охватывающий прямоугольник на тех же линиях;
- у двери рисуются створка внутрь дома и дуга, как у GenPlan.

Метров в выпуске нет: масштаб — из площади `area` (м², из листинга) и площади плана в пикселях
(статья ResPlan, «Metric-Scale Coordinates»). Ось y ResPlan — ось картинки, вниз, как в SVG.
"""

import math
from dataclasses import dataclass

import numpy
import shapely
from shapely.geometry.base import BaseGeometry

from genfacade.config import Canvas, Config, Gaps
from genfacade.plan.gaps import find_gaps
from genfacade.plan.genplan_svg import LEAF_PX, WALL_FILL, WINDOW_FILL, Box, PlanError
from genfacade.render.sheet_format import num
from genfacade.schema import Point

# Слои ResPlan, из которых собран дом. front_door — входная дверь, отдельно от прочих дверей.
WALL, WINDOW, DOOR, FRONT_DOOR, INNER = "wall", "window", "door", "front_door", "inner"


def m_per_px(plan: dict) -> float:
    """Метров на пиксель ResPlan: площадь листинга к площади плана по наружному контуру."""
    shape = shapely.union_all([plan[k] for k in (INNER, WALL, WINDOW, DOOR, FRONT_DOOR)
                               if plan.get(k) is not None])
    parts = shapely.get_parts(shape)
    filled = shapely.polygons(shapely.get_exterior_ring(parts[shapely.area(parts) > 0]))
    return math.sqrt(float(plan["area"]) / float(shapely.area(filled).sum()))


@dataclass(frozen=True)
class Frame:
    """Пиксели ResPlan → пиксели SVG: сдвиг к началу, масштаб холста GenPlan, поле."""

    x0: float
    y0: float
    k: float      # px SVG на px ResPlan
    pad: float    # поле холста, px SVG

    @classmethod
    def of(cls, plan: dict, canvas: Canvas) -> "Frame":
        x0, y0, _, _ = shapely.union_all([plan[WALL], plan[INNER]]).bounds
        return cls(x0, y0, m_per_px(plan) * canvas.px_per_m, canvas.margin_m * canvas.px_per_m)

    def __call__(self, geom: BaseGeometry) -> BaseGeometry:
        return shapely.transform(geom, lambda c: (c - (self.x0, self.y0)) * self.k + self.pad)


@dataclass(frozen=True)
class Drawing:
    """План в формате GenPlan и как он получен из ResPlan."""

    text: str
    frame: Frame
    height: float  # высота холста SVG, px: препроцессор переворачивает ось y по ней

    def in_plan_m(self, geom: BaseGeometry | None, m_per_svg_px: float) -> BaseGeometry:
        """Слой ResPlan в осях плана после препроцессора: метры, ось y вверх."""
        if geom is None:
            return shapely.GeometryCollection()
        k, h = m_per_svg_px, self.height
        return shapely.transform(self.frame(geom),
                                 lambda c: numpy.c_[c[:, 0] * k, (h - c[:, 1]) * k])


class Lines:
    """Общие линии по одной оси: близкие координаты (ближе tol) сводятся к их медиане."""

    def __init__(self, values: numpy.ndarray, tol: float):
        v = numpy.sort(values)
        starts = numpy.flatnonzero(numpy.diff(v, prepend=-numpy.inf) > tol)
        self.edges = v[starts]  # первая координата каждой группы
        self.centers = numpy.array([numpy.median(g) for g in numpy.split(v, starts[1:])])

    def __call__(self, values: numpy.ndarray) -> numpy.ndarray:
        return self.centers[numpy.searchsorted(self.edges, values, side="right") - 1]


def svg(plan: dict, cfg: Config) -> Drawing:
    """План ResPlan → текст SVG GenPlan; наклонные стены — PlanError с причиной."""
    canvas, rules = cfg.synthetic.canvas, cfg.data.resplan
    frame = Frame.of(plan, canvas)
    layers = {k: frame(_geom(plan, k)) for k in (WALL, WINDOW, DOOR, FRONT_DOOR, INNER)}
    coords = shapely.get_coordinates(shapely.union_all([layers[k] for k in (WALL, WINDOW, DOOR,
                                                                         FRONT_DOOR)]))
    tol = rules.snap_m * canvas.px_per_m
    xs, ys = Lines(coords[:, 0], tol), Lines(coords[:, 1], tol)

    def boxes(key: str) -> list[Box]:
        snapped = [_box(shapely.transform(g, lambda c: numpy.c_[xs(c[:, 0]), ys(c[:, 1])]))
                   for g in _parts(layers[key])]
        return [b for b in snapped if b.x1 > b.x0 and b.y1 > b.y0]  # сжался в линию — не проём

    walls = shapely.make_valid(shapely.transform(
        layers[WALL], lambda c: numpy.c_[xs(c[:, 0]), ys(c[:, 1])]))
    _check_axes(walls, rules.max_slant_m * canvas.px_per_m)
    doors, windows = boxes(DOOR) + boxes(FRONT_DOOR), boxes(WINDOW)
    spread = spaced(doors + windows)
    doors, windows = spread[:len(doors)], spread[len(doors):]
    pieces = cells(walls, xs.centers, ys.centers) + [s for b in doors + windows for s in stubs(b)]
    pieces += sealed(pieces, doors + windows, cfg.plan.gaps)
    body = ([_rect(b, WALL_FILL) for b in pieces]
            + [tag for b in doors for tag in _door(b, layers[INNER])]
            + [_rect(b, WINDOW_FILL) for b in windows])
    _, _, x1, y1 = shapely.union_all([walls, layers[INNER]]).bounds
    w, h = math.ceil(x1 + frame.pad), math.ceil(y1 + frame.pad)
    return Drawing(_document(w, h, body), frame, h)


def sealed(walls: list[Box], openings: list[Box], cfg: Gaps) -> list[Box]:
    """Разрывы между соосными стенами, где у ResPlan нет ни окна, ни двери, — стеной.

    Препроцессор считает проёмом любой разрыв (`plan-input: Проём только по разрыву`): у GenPlan
    других проёмов нет. У ResPlan проёмы заданы явно, а разрыв без них — устье выемки или двора,
    открытый проход между комнатами. Без заделки устье выемки стало бы на фасаде окном.
    Швы короче min_opening_px препроцессор и сам проёмом не считает — их не трогаем.
    """
    cover = shapely.union_all([shapely.box(b.x0, b.y0, b.x1, b.y1) for b in openings])
    return [g.box for g in find_gaps(walls, cfg) if g.length_px >= cfg.min_opening_px
            and not shapely.box(g.box.x0, g.box.y0, g.box.x1, g.box.y1).intersects(cover)]


def _geom(plan: dict, key: str) -> BaseGeometry:
    g = plan.get(key)
    return shapely.GeometryCollection() if g is None else g


def _parts(g: BaseGeometry) -> list[BaseGeometry]:
    return [p for p in shapely.get_parts(g) if not p.is_empty and p.area > 0]


def _box(g: BaseGeometry) -> Box:
    x0, y0, x1, y1 = g.bounds
    return Box(x0, y0, x1, y1)


def _check_axes(walls: BaseGeometry, max_slant: float) -> None:
    """После сведения к линиям рёбра стен осевые; наклонные длиннее max_slant — отказ."""
    slant = 0.0
    for ring in _rings(walls):
        d = numpy.abs(numpy.diff(shapely.get_coordinates(ring), axis=0))
        both = (d[:, 0] > 0) & (d[:, 1] > 0)
        slant += float(numpy.hypot(d[both, 0], d[both, 1]).sum())
    if slant > max_slant:
        raise PlanError(f"план не ортогональный: наклонных рёбер стен {slant:.0f} px")


def _rings(g: BaseGeometry) -> list[BaseGeometry]:
    polys = [p for p in shapely.get_parts(g) if isinstance(p, shapely.Polygon)]
    return [r for p in polys for r in (p.exterior, *p.interiors)]


def cells(shape: BaseGeometry, xs: numpy.ndarray, ys: numpy.ndarray) -> list[Box]:
    """Ортогональная фигура → прямоугольники по сетке линий: ряды клеток, затем слияние
    рядов с одинаковым пролётом. Стена вдоль x выходит одним прямоугольником на всю толщину."""
    cx, cy = (xs[:-1] + xs[1:]) / 2, (ys[:-1] + ys[1:]) / 2
    filled = shapely.contains_xy(shape, *numpy.meshgrid(cx, cy))
    rects, open_ = [], {}
    for j, row in enumerate(filled):
        spans = set(_runs(row))
        for span in [s for s in open_ if s not in spans]:
            rects.append(Box(xs[span[0]], ys[open_.pop(span)], xs[span[1]], ys[j]))
        for span in spans - open_.keys():
            open_[span] = j
    rects += [Box(xs[a], ys[j0], xs[b], ys[len(filled)]) for (a, b), j0 in open_.items()]
    return rects


def stubs(b: Box) -> list[Box]:
    """Квадраты стены толщиной проёма у обоих его концов, внахлёст с тем, что там есть.

    У GenPlan проём — разрыв между двумя стенами одной линии. У ResPlan дверь часто начинается
    прямо у поперечной стены угла: соосной стены по эту сторону нет, разрыв не находится, и
    контур уходит внутрь дома через проём. Квадрат на линии проёма даёт эту соосную стену;
    перекрытия стен препроцессор сливает (`plan-input`, «стены»).
    """
    if b.x1 - b.x0 >= b.y1 - b.y0:
        t = b.y1 - b.y0
        return [Box(b.x0 - t, b.y0, b.x0, b.y1), Box(b.x1, b.y0, b.x1 + t, b.y1)]
    t = b.x1 - b.x0
    return [Box(b.x0, b.y0 - t, b.x1, b.y0), Box(b.x0, b.y1, b.x1, b.y1 + t)]


def spaced(openings: list[Box]) -> list[Box]:
    """Проёмы одной линии ближе толщины стены друг к другу — укоротить так, чтобы между ними
    встал квадрат стены (его рисуют `stubs`). Иначе квадрат у конца одного проёма врезался бы
    в соседний и разрезал его, а без квадрата два проёма слились бы в один разрыв."""
    out = list(openings)
    for i, j in _neighbours(out):
        a, b = _span(out[i]), _span(out[j])
        t = _thickness(out[i])
        mid = (a[1] + b[0]) / 2
        out[i] = _with_span(out[i], (a[0], mid - t / 2))
        out[j] = _with_span(out[j], (mid + t / 2, b[1]))
    return [b for b in out if _span(b)[1] > _span(b)[0]]


def _neighbours(boxes: list[Box]) -> list[tuple[int, int]]:
    """Пары (i, j): проём j идёт вдоль той же линии сразу за i, ближе толщины стены."""
    pairs = []
    for i, a in enumerate(boxes):
        after = [(j, b) for j, b in enumerate(boxes) if j != i and _same_line(a, b)
                 and 0 <= _span(b)[0] - _span(a)[1] < _thickness(a)]
        if after:
            pairs.append((i, min(after, key=lambda jb: _span(jb[1])[0])[0]))
    return pairs


def _along_x(b: Box) -> bool:
    return b.x1 - b.x0 >= b.y1 - b.y0


def _span(b: Box) -> tuple[float, float]:
    return (b.x0, b.x1) if _along_x(b) else (b.y0, b.y1)


def _band(b: Box) -> tuple[float, float]:
    return (b.y0, b.y1) if _along_x(b) else (b.x0, b.x1)


def _thickness(b: Box) -> float:
    c0, c1 = _band(b)
    return c1 - c0


def _same_line(a: Box, b: Box) -> bool:
    (a0, a1), (b0, b1) = _band(a), _band(b)
    return _along_x(a) == _along_x(b) and min(a1, b1) - max(a0, b0) > (a1 - a0) / 2


def _with_span(b: Box, span: tuple[float, float]) -> Box:
    c0, c1 = _band(b)
    return Box(span[0], c0, span[1], c1) if _along_x(b) else Box(c0, span[0], c1, span[1])


def _runs(row: numpy.ndarray) -> list[tuple[int, int]]:
    """Отрезки подряд заполненных клеток ряда: (первая, за последней)."""
    edges = numpy.flatnonzero(numpy.diff(numpy.r_[0, row.astype(numpy.int8), 0]))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist(), strict=True))


def _door(b: Box, inner: BaseGeometry) -> list[str]:
    """Створка и дуга двери, как у GenPlan: петля — на грани стены у начала разрыва, створка
    открыта внутрь дома (туда, где помещение), дуга — от края разрыва до конца створки."""
    along_x = b.x1 - b.x0 >= b.y1 - b.y0
    a0, a1, c0, c1 = (b.x0, b.x1, b.y0, b.y1) if along_x else (b.y0, b.y1, b.x0, b.x1)

    def pt(a: float, c: float) -> Point:
        return (a, c) if along_x else (c, a)

    beyond = shapely.Point(pt((a0 + a1) / 2, c1 + (c1 - c0)))
    inward = 1 if inner.contains(beyond) else -1
    face = c1 if inward > 0 else c0
    tip = face + inward * (a1 - a0)
    (lx0, ly0), (lx1, ly1) = pt(a0, min(face, tip)), pt(a0 + LEAF_PX, max(face, tip))
    return [_rect(Box(lx0, ly0, lx1, ly1), WALL_FILL),
            _arc(pt(a0, face), pt(a1, face), pt(a0, tip))]


def _arc(hinge: Point, jamb: Point, tip: Point) -> str:
    r = math.dist(hinge, jamb)
    cross = (jamb[0] - hinge[0]) * (tip[1] - hinge[1]) - (jamb[1] - hinge[1]) * (tip[0] - hinge[0])
    return (f'<path d="M{num(jamb[0])},{num(jamb[1])} A{num(r)},{num(r)},0,0,{int(cross > 0)},'
            f'{num(tip[0])},{num(tip[1])}" stroke="{WALL_FILL}" fill="none" />')


def _rect(b: Box, fill: str) -> str:
    return (f'<rect x="{num(b.x0)}" y="{num(b.y0)}" width="{num(b.x1 - b.x0)}" '
            f'height="{num(b.y1 - b.y0)}" fill="{fill}" />')


def _document(w: int, h: int, body: list[str]) -> str:
    head = ('<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">')
    return "\n".join([head, *body, "</svg>"])
