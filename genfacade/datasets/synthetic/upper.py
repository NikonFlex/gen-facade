"""Окна верхних этажей: в плане их нет, место и ширину ставит правило, а не план.

Чаще стена повторяет окна нижнего этажа на тех же осях; иначе — свой ряд на тех же участках
стены, что у плана: между углами и примыканиями перегородок (запретными зонами), поэтому окно
верхнего этажа в запретную зону не попадает. Третий этаж повторяет второй.
"""

import random

from genfacade.config import Checks, Config, Synthetic
from genfacade.datasets.synthetic.plan import Span, bay_windows
from genfacade.schema import EPS, Opening, OpeningKind, Side


def rows(rng: random.Random, side: Side, floors: int, cfg: Config) -> list[list[Opening]]:
    """Окна каждого этажа стены, снизу вверх; первый — окна плана."""
    ground = [o for o in side.openings if o.kind is OpeningKind.WINDOW]
    if floors == 1 or not ground:  # глухая стена — глухая на всех этажах
        return [ground] * floors
    on_axes = rng.random() < cfg.synthetic.openings.upper_on_axes_p
    own = ground if on_axes else _own(rng, side, ground, cfg.synthetic)
    # Пустой ряд оставил бы этаж без окон, ряд почти на осях валидатор считает промахом.
    if not own or _near_axis(own, ground, cfg.checks):
        own = ground
    return [ground] + [own] * (floors - 1)


def _own(rng: random.Random, side: Side, ground: list[Opening], rules: Synthetic) -> list[Opening]:
    """Свой ряд: ширина — одна из ширин окон плана этой стены, число окон на участке — как в
    плане, по весам."""
    width = rng.choice(sorted({o.width_m for o in ground}))
    found = [o for bay in _bays(side, rules) for o in bay_windows(rng, bay, width, rules.openings)]
    return [Opening(kind=OpeningKind.WINDOW, x_m=o.at_m, width_m=o.width_m) for o in found]


def _near_axis(row: list[Opening], ground: list[Opening], checks: Checks) -> bool:
    """Граница предупреждения валидатора `axis_align`, с запасом на хвост float: 0,05000001 м
    после сетки токенов становится ровно 0,05 — и уже предупреждение."""
    return any(checks.eps_m < abs(_axis(a) - _axis(b)) <= checks.align_m + EPS
               for a in row for b in ground)


def _axis(o: Opening) -> float:
    return o.x_m + o.width_m / 2


def _bays(side: Side, rules: Synthetic) -> list[Span]:
    """Участки стены между углами и запретными зонами, с отступом corner_clear_m."""
    t, clear = rules.house.wall_m, rules.openings.corner_clear_m
    stops = [(0.0, t), *((z.x0_m, z.x1_m) for z in side.forbidden),
             (side.length_m - t, side.length_m)]
    return [(a[1] + clear, b[0] - clear) for a, b in zip(stops, stops[1:], strict=False)
            if b[0] - a[1] > 2 * clear]
