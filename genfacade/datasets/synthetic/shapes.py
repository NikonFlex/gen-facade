"""Контуры синтетических домов ступени 3: Г, Т, П, пристройка, эркер (`data: Ступени данных`).

Дом — объединение прямоугольных частей. Контур строится в своих осях (основной прямоугольник
в нуле, y вверх), обходится против часовой стрелки; затем весь дом поворачивается и, возможно,
отражается — случайно, своим потоком. Метры, на сетке шага house.grid_m.
"""

import random
from typing import NamedTuple

from genfacade.config import Contours
from genfacade.datasets.synthetic.scatter import Span
from genfacade.schema import ContourKind, Point

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1


class Layout(NamedTuple):
    """Контур и его части. wings — комнаты-крылья: между соседними стоит перегородка; alcoves —
    части контура без перегородки (эркер: комната продолжается в него)."""

    ring: list[Point]
    wings: list[Rect]
    alcoves: list[Rect]


def layout(kind: ContourKind, width: float, depth: float, cfg: Contours, step: float,
           rng: random.Random) -> Layout:
    """Контур вида kind (не rect) на основном прямоугольнике width × depth; он растёт, если вида
    не хватает места крыльям. Положение в плоскости — случайное, угол обхода — против часовой."""
    least = _least(kind, cfg)
    found = _BUILDERS[kind](max(width, least[0]), max(depth, least[1]), cfg, _Pick(rng, step))
    return _moved(found, rng.randrange(4), rng.random() < 0.5)


def _least(kind: ContourKind, cfg: Contours) -> Span:
    """Наименьшие ширина и глубина основного прямоугольника: на крылья и уступы хватает места."""
    w, a = cfg.wing_min_m, cfg.arm_min_m
    return {ContourKind.L: (2 * w, 2 * w), ContourKind.U: (3 * w, 2 * w),
            ContourKind.T: (w + 2 * a, w), ContourKind.ANNEX: (cfg.annex_width_m[0] + 2 * a, w),
            ContourKind.BAY: (cfg.bay_width_m[0] + 2 * a, w)}[kind]


class _Pick:
    """Значения на сетке из диапазонов — своим потоком контура."""

    def __init__(self, rng: random.Random, step: float):
        self.rng, self.step = rng, step

    def __call__(self, span: Span) -> float:
        low, high = round(span[0] / self.step), round(span[1] / self.step)
        return round(self.rng.randint(low, max(low, high)) * self.step, 3)

    def centred(self, whole: float, part: float) -> float:
        return round(round((whole - part) / 2 / self.step) * self.step, 3)


def _notch(width: float, depth: float, cfg: Contours, pick: _Pick) -> Layout:
    """Г: вырезан правый верхний угол nw × nd; перегородка продолжает нижнюю или боковую грань
    выреза."""
    w = cfg.wing_min_m
    nw, nd = pick((w, width - w)), pick((w, depth - w))
    ring = [(0, 0), (width, 0), (width, depth - nd), (width - nw, depth - nd),
            (width - nw, depth), (0, depth)]
    if pick.rng.random() < 0.5:
        wings = [(0, 0, width, depth - nd), (0, depth - nd, width - nw, depth)]
    else:
        wings = [(0, 0, width - nw, depth), (width - nw, 0, width, depth - nd)]
    return Layout(ring, wings, [])


def _courtyard(width: float, depth: float, cfg: Contours, pick: _Pick) -> Layout:
    """П: вырез nw × nd посередине верхней стороны, ножки по бокам."""
    w = cfg.wing_min_m
    nw, nd = pick((w, width - 2 * w)), pick((w, depth - w))
    x = pick((w, width - nw - w))
    ring = [(0, 0), (width, 0), (width, depth), (x + nw, depth), (x + nw, depth - nd),
            (x, depth - nd), (x, depth), (0, depth)]
    if pick.rng.random() < 0.5:
        wings = [(0, 0, width, depth - nd), (0, depth - nd, x, depth),
                 (x + nw, depth - nd, width, depth)]
    else:
        wings = [(0, 0, x, depth), (x, 0, x + nw, depth - nd), (x + nw, 0, width, depth)]
    return Layout(ring, wings, [])


def _stem(width: float, depth: float, box: tuple[float, float, float], alcove: bool) -> Layout:
    """Основной прямоугольник и выступ под ним: x, ширина и глубина выступа."""
    x, sw, sd = box
    ring = [(0, 0), (x, 0), (x, -sd), (x + sw, -sd), (x + sw, 0), (width, 0), (width, depth),
            (0, depth)]
    base, stem = (0, 0, width, depth), (x, -sd, x + sw, 0)
    return Layout(ring, [base] if alcove else [base, stem], [stem] if alcove else [])


def _tee(width: float, depth: float, cfg: Contours, pick: _Pick) -> Layout:
    sw = pick((cfg.wing_min_m, width - 2 * cfg.arm_min_m))
    return _stem(width, depth, (pick.centred(width, sw), sw, pick(cfg.stem_depth_m)), False)


def _annex(width: float, depth: float, cfg: Contours, pick: _Pick) -> Layout:
    return _off_centre(width, depth, (cfg.annex_width_m, cfg.annex_depth_m), cfg, pick, False)


def _bay(width: float, depth: float, cfg: Contours, pick: _Pick) -> Layout:
    return _off_centre(width, depth, (cfg.bay_width_m, cfg.bay_depth_m), cfg, pick, True)


def _off_centre(width: float, depth: float, size: tuple[Span, Span], cfg: Contours, pick: _Pick,
                alcove: bool) -> Layout:
    """Выступ не вровень с углами: от каждого угла основного объёма — не меньше arm_min_m."""
    arm = cfg.arm_min_m
    sw = pick((size[0][0], min(size[0][1], width - 2 * arm)))
    return _stem(width, depth, (pick((arm, width - sw - arm)), sw, pick(size[1])), alcove)


_BUILDERS = {ContourKind.L: _notch, ContourKind.U: _courtyard, ContourKind.T: _tee,
             ContourKind.ANNEX: _annex, ContourKind.BAY: _bay}


def _moved(found: Layout, turns: int, mirror: bool) -> Layout:
    """Поворот на turns четвертей и отражение; дом сдвинут: габарит начинается в нуле."""
    def point(p: Point) -> Point:
        x, y = (-p[0], p[1]) if mirror else p
        for _ in range(turns):
            x, y = -y, x
        return x, y

    def rect(r: Rect) -> Rect:
        (x0, y0), (x1, y1) = point(r[:2]), point(r[2:])
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    ring = [point(p) for p in found.ring]
    low = (min(x for x, _ in ring), min(y for _, y in ring))

    def shifted(r: Rect) -> Rect:
        return tuple(round(v - low[i % 2], 3) for i, v in enumerate(rect(r)))

    ring = [(round(x - low[0], 3), round(y - low[1], 3)) for x, y in ring]
    return Layout(ring[::-1] if mirror else ring, [shifted(r) for r in found.wings],
                  [shifted(r) for r in found.alcoves])
