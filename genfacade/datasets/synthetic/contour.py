"""План синтетического дома любого контура (`data: Ступени данных`, `data: Синтетика своим
генератором`): прямоугольник — ступень 1 (plan.py), Г, Т, П, пристройка, эркер — ступень 3.

Наружная стена — каждое ребро контура. У входящего угла перегородка продолжает стену выреза и
делит дом на прямоугольные крылья; в крыле — поперечные перегородки, а окна и вход ставятся теми же
правилами, что у прямоугольного дома (plan.py). Участки для окон считаются по каждому ребру: от
угла, от входящего угла и от перегородок, которые в него упираются.
"""

import random
from dataclasses import dataclass, replace

from genfacade.config import Synthetic
from genfacade.datasets.genplan_writer import PlanDraft, Run
from genfacade.datasets.synthetic import plan, shapes
from genfacade.datasets.synthetic.scatter import Span
from genfacade.datasets.synthetic.shapes import Layout, Rect
from genfacade.plan.gaps import Axis
from genfacade.schema import ContourKind, Point

EPS = 1e-6


def pick(seed: int, rules: Synthetic) -> ContourKind:
    """Вид контура по seed — своим потоком: доли видов не сдвигают остальные решения дома."""
    draw = random.Random(f"contour/{seed}")  # noqa: S311 — не криптография
    weights = rules.contours.weights
    return draw.choices(list(weights), list(weights.values()))[0]


def draft(seed: int, cfg: Synthetic) -> PlanDraft:
    """План дома по seed: вид контура — pick, остальное — как у прямоугольного."""
    kind = pick(seed, cfg)
    if kind is ContourKind.RECT:
        return plan.draft(seed, cfg)
    rng, cfg, widths, width, depth = plan.begin(seed, cfg)
    found = shapes.layout(kind, width, depth, cfg.contours, cfg.house.grid_m,
                          random.Random(f"shape/{seed}"))  # noqa: S311 — не криптография
    inner = _inner(found, rng, cfg)
    walls = _walls(found.ring, inner, cfg)
    runs = plan.with_windows(rng, walls, widths, cfg.openings)
    size = (max(x for x, _ in found.ring), max(y for _, y in found.ring))
    return PlanDraft(*size, cfg.house.wall_m, (*runs, *(_with_passage(r, rng, cfg) for r in inner)))


@dataclass(frozen=True)
class _Edge:
    """Ребро контура: линия поперёк оси, края вдоль неё и куда смотрит дом."""

    axis: Axis
    line: float
    span: Span
    inward: int  # +1 — дом в сторону растущей координаты поперёк оси
    reflex: tuple[bool, bool]  # входящий угол на нижнем и верхнем конце


def _edges(ring: list[Point]) -> list[_Edge]:
    """Рёбра контура, обход против часовой стрелки: дом слева от хода."""
    found, n = [], len(ring)
    for i, (a, b) in enumerate(zip(ring, ring[1:] + ring[:1], strict=True)):
        before, after = ring[i - 1], ring[(i + 2) % n]
        along = Axis.X if abs(a[1] - b[1]) < EPS else Axis.Y
        k = 0 if along is Axis.X else 1  # номер координаты вдоль оси
        step = b[k] - a[k]
        turn_a, turn_b = _turn(before, a, b), _turn(a, b, after)
        lo_first = step > 0
        found.append(_Edge(along, a[1 - k], (min(a[k], b[k]), max(a[k], b[k])),
                           _sign(step) if along is Axis.X else -_sign(step),
                           (turn_a < 0, turn_b < 0) if lo_first else (turn_b < 0, turn_a < 0)))
    return found


def _sign(value: float) -> int:
    return 1 if value > 0 else -1


def _turn(a: Point, b: Point, c: Point) -> float:
    """Поворот в b: больше нуля — налево (выпуклый угол при обходе против часовой), меньше —
    направо (входящий)."""
    (ux, uy), (vx, vy) = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
    return ux * vy - uy * vx


def _inner(found: Layout, rng: random.Random, cfg: Synthetic) -> list[Run]:
    """Перегородки без проходов: между крыльями и поперечные в каждом крыле."""
    edges, t = _edges(found.ring), cfg.house.wall_m
    parts = [_between(a, b, edges, t) for i, a in enumerate(found.wings)
             for b in found.wings[i + 1:]]
    runs = [r for r in parts if r is not None]
    for wing in found.wings:
        runs += _crosswise(rng, wing, edges, cfg)
    return runs


def _between(a: Rect, b: Rect, edges: list[_Edge], t: float) -> Run | None:
    """Перегородка по общей границе крыльев; None — общей границы нет. Полоса стоит с той же
    стороны линии, что и стена выреза, которую она продолжает."""
    for axis, k in ((Axis.Y, 0), (Axis.X, 1)):  # линия x = const — перегородка вдоль y
        for lo, hi in ((a, b), (b, a)):
            low, high = max(lo[1 - k], hi[1 - k]), min(lo[3 - k], hi[3 - k])
            if abs(lo[2 + k] - hi[k]) < EPS and high - low > EPS:
                line = lo[2 + k]
                side = _side(axis, line, (low, high), edges)
                return Run(axis, line if side > 0 else line - t, low, high)
    return None


def _collinear(axis: Axis, line: float, span: Span, edges: list[_Edge], tol: float
               ) -> _Edge | None:
    """Стена контура на линии line (с допуском tol), упирающаяся концом в перегородку span."""
    for e in edges:
        if e.axis is axis and abs(e.line - line) <= tol + EPS and any(
                e.span[0] - EPS <= end <= e.span[1] + EPS for end in span):
            return e
    return None


def _side(axis: Axis, line: float, span: Span, edges: list[_Edge]) -> int:
    """Куда смотрит дом у стены, лежащей на той же линии и упирающейся в перегородку; плюс — если
    такой стены нет."""
    found = _collinear(axis, line, span, edges, 0.0)
    return found.inward if found else 1


def _crosswise(rng: random.Random, wing: Rect, edges: list[_Edge], cfg: Synthetic) -> list[Run]:
    """Поперечные перегородки крыла — поперёк его длинной стороны, от одной границы до другой.
    Перегородка у линии стены выреза (ближе двух толщин) встаёт ровно на неё и в её полосу: рядом
    стена и перегородка оставляют между собой полосу, которую шаг 2 читает разрывом."""
    lengths = (wing[2] - wing[0], wing[3] - wing[1])
    k = 0 if lengths[0] >= lengths[1] else 1  # вдоль какой оси длинная сторона крыла
    across = Axis.Y if k == 0 else Axis.X
    short = (wing[1 - k], wing[3 - k])
    t = cfg.house.wall_m
    runs = []
    for c in plan.cuts(rng, lengths[k], cfg):
        line = round(wing[k] + c, 3)
        e = _collinear(across, line, short, edges, 2 * t)
        line = e.line if e else line
        inward = e.inward if e else 1
        runs.append(Run(across, line if inward > 0 else line - t, *short))
    return runs


def _with_passage(run: Run, rng: random.Random, cfg: Synthetic) -> Run:
    return replace(run, openings=(plan.passage(rng, (run.start_m, run.end_m), cfg),))


def _walls(ring: list[Point], inner: list[Run], cfg: Synthetic) -> list[plan.Wall]:
    """Наружные стены — по ребру контура. Стена у входящего угла заходит за него на толщину."""
    edges, t = _edges(ring), cfg.house.wall_m
    wide = Axis.X if max(x for x, _ in ring) >= max(y for _, y in ring) else Axis.Y
    walls = []
    for e in edges:
        lo, hi = e.span
        run = Run(e.axis, e.line if e.inward > 0 else e.line - t,
                  lo - (t if e.reflex[0] else 0.0), hi + (t if e.reflex[1] else 0.0))
        bays = _bays(e, inner, cfg)
        walls.append(plan.Wall(run, bays, e.axis is wide, e.span,
                               (bays[0][0], bays[-1][1]) if bays else e.span))
    return walls


def _bays(e: _Edge, inner: list[Run], cfg: Synthetic) -> tuple[Span, ...]:
    """Участки ребра для окон: между углами и упирающимися в ребро перегородками, не ближе
    corner_clear_m к ним и не ближе нормы к углам ребра (и к входящим тоже)."""
    t, clear = cfg.house.wall_m, cfg.openings.corner_clear_m
    lo, hi = e.span
    stops = [(lo, lo if e.reflex[0] else lo + t), *_stops(e, inner, t),
             (hi if e.reflex[1] else hi - t, hi)]
    free = [(a[1] + clear - lo, b[0] - clear - lo) for a, b in zip(stops, stops[1:], strict=False)]
    return tuple((round(a + lo, 3), round(b + lo, 3))
                 for a, b in plan.off_corners(free, hi - lo, cfg.openings.window_corner_m))


def _stops(e: _Edge, inner: list[Run], t: float) -> list[Span]:
    """Места, где перегородки упираются в ребро: полоса перегородки вдоль ребра. Перегородка от
    входящего угла полосой лежит за краем ребра — сюда не попадает."""
    found = []
    for r in inner:
        ends = (r.start_m, r.end_m)
        inside = e.span[0] - EPS <= r.across_m and r.across_m + t <= e.span[1] + EPS
        if r.axis is not e.axis and inside and any(abs(end - e.line) < EPS for end in ends):
            found.append((r.across_m, r.across_m + t))
    return sorted(found)
