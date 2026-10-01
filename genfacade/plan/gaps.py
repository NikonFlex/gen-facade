"""Разрывы между соосными стенами (plan-input.md, правило 5).

Разрыв — пустой промежуток между двумя стенами одной линии: окно, дверь или шов
векторизации. У правила GenPlan (`decorator.find_openings`) соосность — равенство
координат по другой оси, из-за чего противоположные стены равной длины дают ложный
проём поперёк дома, а перекрывающиеся соосные — разрыв отрицательной ширины (gf#36).
Здесь соосность — перекрытие полос толщины, а разрыв должен быть пустым.
"""

from dataclasses import dataclass

from genfacade.config import Gaps
from genfacade.plan.genplan_svg import TOL_PX, Box

X, Y = 0, 1  # ось, вдоль которой идут стены и лежит разрыв


@dataclass(frozen=True)
class Gap:
    box: Box
    axis: int

    @property
    def length_px(self) -> float:
        return _span(self.box, self.axis)[1] - _span(self.box, self.axis)[0]


@dataclass(frozen=True)
class Found:
    """Проём в пикселях: разрыв и что в нём."""

    kind: str  # window | door | entrance
    gap: Gap
    external: bool


def find_gaps(walls: list[Box], cfg: Gaps) -> list[Gap]:
    """Все разрывы, включая швы короче min_opening_px: они нужны, чтобы замкнуть контур."""
    gaps = []
    for axis in (X, Y):
        for a in walls:
            b = _nearest_collinear(a, walls, axis, cfg.min_band_overlap)
            if b is None:
                continue
            gap = Gap(_bridge(a, b, axis), axis)
            if _is_free(gap, walls) and gap not in gaps:
                gaps.append(gap)
    return gaps


def _span(box: Box, axis: int) -> tuple[float, float]:
    return (box.x0, box.x1) if axis == X else (box.y0, box.y1)


def _runs_along(box: Box, axis: int) -> bool:
    a0, a1 = _span(box, axis)
    b0, b1 = _span(box, 1 - axis)
    return a1 - a0 >= b1 - b0


def _band_overlap(a: Box, b: Box, axis: int) -> float:
    """Перекрытие полос толщины, в долях более тонкой стены."""
    (a0, a1), (b0, b1) = _span(a, 1 - axis), _span(b, 1 - axis)
    return (min(a1, b1) - max(a0, b0)) / min(a1 - a0, b1 - b0)


def _nearest_collinear(a: Box, walls: list[Box], axis: int, min_overlap: float) -> Box | None:
    """Ближайшая стена той же линии, начинающаяся дальше конца `a` по оси."""
    if not _runs_along(a, axis):
        return None
    end = _span(a, axis)[1]
    after = [
        b for b in walls
        if b is not a and _runs_along(b, axis) and _span(b, axis)[0] > end + TOL_PX
        and _band_overlap(a, b, axis) >= min_overlap
    ]
    return min(after, key=lambda b: _span(b, axis)[0], default=None)


def _bridge(a: Box, b: Box, axis: int) -> Box:
    """Промежуток от конца `a` до начала `b` в общей полосе толщины."""
    lo, hi = _span(a, axis)[1], _span(b, axis)[0]
    (a0, a1), (b0, b1) = _span(a, 1 - axis), _span(b, 1 - axis)
    t0, t1 = max(a0, b0), min(a1, b1)
    return Box(lo, t0, hi, t1) if axis == X else Box(t0, lo, t1, hi)


def _is_free(gap: Gap, walls: list[Box]) -> bool:
    """Промежуток не пересекает стена на всю толщину: иначе это стык, а не разрыв.

    Стена, которая только заходит в полосу толщины (внутренняя стена упирается в окно, —
    дефект GenPlan, plan-input.md «Открыто»), разрыв не закрывает.
    """
    along, across = _span(gap.box, gap.axis), _span(gap.box, 1 - gap.axis)
    for w in walls:
        (w0, w1), (c0, c1) = _span(w, gap.axis), _span(w, 1 - gap.axis)
        inside = min(along[1], w1) - max(along[0], w0) > TOL_PX
        if inside and c0 <= across[0] + TOL_PX and c1 >= across[1] - TOL_PX:
            return False
    return True
